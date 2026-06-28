"""
meter_ledger.py — the canonical, auditable water-meter data layer.

WHY THIS EXISTS
---------------
Meter data used to be spread across un-unified stores that drifted apart:
  * flow_sample   (smart-garden.db)   — the 15s lock snapshot; usage was built
                                         on it; only 30-day retention.
  * archive_frame (meter_archive.db)  — per-image reads; disk-capped.
  * the live lock / oracle / CNN      — transient, never persisted as facts.
None linked a usage number back to the image that proves it, the two stores
disagreed in the last digits, and nothing survived long-term. No number was
truly defensible.

This module is the SINGLE SOURCE OF TRUTH. Three cleanly separated layers:

  1. RAW OBSERVATION (immutable)   — what the OCR actually read from a given
                                     image, unconstrained. Write-once. The fact.
  2. VALIDATED READING (the truth) — the value we trust at each instant, with
                                     full provenance (read/corrected/propagated/
                                     held/anchored/interpolated). May be
                                     corrected over time; every change is logged.
  3. DERIVED METRICS (recomputable)— usage / daily / monthly, ALWAYS rebuilt
                                     FROM the validated layer, never the only
                                     copy, with a versioned method name so the
                                     computation itself is reproducible.

DEFENSIBILITY: every validated value is traceable end-to-end —
    chart  ->  usage_daily  ->  meter_reading  ->  raw read + the meter photo.
Corrections are append-only in meter_correction, so the full history of any
number can be replayed. The ledger is tiny (numbers + filenames) and is kept
FOREVER; only the JPEG evidence ages out.

SAFETY: this module owns its own DB (meter_ledger.db) and only READS the legacy
DBs during backfill. It does not touch the live capture pipeline. Backfill and
recompute are idempotent — safe to re-run.

CLI:
    python meter_ledger.py init
    python meter_ledger.py backfill          # archive (image-backed) + flow gaps
    python meter_ledger.py recompute         # rebuild usage_daily
    python meter_ledger.py stats
    python meter_ledger.py reconcile         # ledger usage vs legacy flow usage
    python meter_ledger.py lineage <ts>
"""
import os
import sqlite3
import sys
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("METER_LEDGER_DB", os.path.join(HERE, "meter_ledger.db"))
ARCHIVE_DB = os.environ.get(
    "METER_ARCHIVE_DB", os.path.join(HERE, "meter_archive.db"))
FLOW_DB = os.environ.get(
    "SMART_GARDEN_DB", os.path.join(HERE, "smart-garden.db"))

COUNTS_PER_CF = 1000.0      # 9-digit meter value / 1000 = cubic feet
GAL_PER_CF = 7.48052        # US gallons per cubic foot
USAGE_METHOD = "high_water_mark_v1"
GAP_FILL_WINDOW_S = 45      # a flow sample fills a gap only if no image-backed
                            # reading exists within +/- this many seconds


def _conn(path=DB_PATH):
    c = sqlite3.connect(path, timeout=30)
    c.row_factory = sqlite3.Row
    return c


def _epoch(ts):
    try:
        return datetime.fromisoformat(ts).timestamp()
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------
def ensure_schema():
    c = _conn()
    try:
        # LAYER 1 + 2: one row per reading event. raw_* is the immutable
        # observation; committed_* is the validated truth (correctable).
        c.execute(
            "CREATE TABLE IF NOT EXISTS meter_reading ("
            " ts TEXT PRIMARY KEY,"          # capture instant (ISO, T-separated)
            " image_file TEXT,"              # evidence photo basename (NULL=none)
            # --- raw observation (write-once, immutable) ---
            " raw_reading INTEGER,"          # unconstrained OCR read of THIS image
            " raw_conf TEXT,"                # reader confidence for the raw read
            " reader TEXT,"                  # cnn | oracle | rapidocr | NULL
            # --- validated reading (the trusted value) ---
            " committed INTEGER,"            # validated value (9-digit counts)
            " committed_cf REAL,"            # committed / 1000 (cubic feet)
            " method TEXT,"                  # read|corrected|propagated|held|anchored|interpolated
            " confidence TEXT,"              # high|medium|low|inferred|manual|lock
            " reviewed INTEGER DEFAULT 0,"   # 1 = a human verified/corrected it
            # --- usage primitives (derived from committed) ---
            " state TEXT,"                   # idle | flow | gap | NULL
            " delta_cf REAL,"                # committed_cf - previous committed_cf
            # --- provenance of the row itself ---
            " origin TEXT,"                  # backfill:archive_frame|backfill:flow_sample|live
            " ingested_ts TEXT"              # when this row was written
            ")")
        c.execute("CREATE INDEX IF NOT EXISTS ix_mr_ts ON meter_reading(ts)")
        c.execute("CREATE INDEX IF NOT EXISTS ix_mr_img "
                  "ON meter_reading(image_file)")

        # AUDIT LOG: every change to a committed value, append-only. The
        # backbone of "defensible" — replay exactly how a value became what it is.
        c.execute(
            "CREATE TABLE IF NOT EXISTS meter_correction ("
            " id INTEGER PRIMARY KEY AUTOINCREMENT,"
            " ts TEXT,"                      # which reading (-> meter_reading.ts)
            " at TEXT,"                      # when the correction happened
            " old_committed INTEGER,"
            " new_committed INTEGER,"
            " method TEXT,"                  # corrected|propagated|anchored|reread
            " actor TEXT,"                   # human:james | system:propagate | ...
            " note TEXT"
            ")")
        c.execute("CREATE INDEX IF NOT EXISTS ix_mc_ts "
                  "ON meter_correction(ts)")

        # LAYER 3: recomputable daily rollup. NOT a source of truth — rebuilt
        # from meter_reading. Records the method + how much data backed it, so
        # the number is self-documenting and defensible.
        c.execute(
            "CREATE TABLE IF NOT EXISTS usage_daily ("
            " date TEXT PRIMARY KEY,"        # YYYY-MM-DD (local)
            " gallons REAL,"                 # water used that day
            " start_cf REAL,"               # committed at day start
            " end_cf REAL,"                 # committed at day end
            " n_readings INTEGER,"          # readings backing the day
            " n_image_backed INTEGER,"      # how many had a photo (auditable)
            " n_fresh_reads INTEGER,"       # how many were actual fresh OCR reads
            " method TEXT,"                 # versioned usage method
            " computed_ts TEXT"
            ")")
        c.commit()
    finally:
        c.close()


# ---------------------------------------------------------------------------
# Backfill (idempotent) — import history from the legacy stores
# ---------------------------------------------------------------------------
def _map_archive_method(source):
    return {
        "manual": "corrected",
        "oracle": "read",
        "cnn": "read",
        "propagated": "propagated",
        "lock": "held",
    }.get((source or "").lower(), (source or "held"))


def backfill_from_archive(since=None):
    """Image-backed readings (the auditable spine) from archive_frame."""
    if not os.path.exists(ARCHIVE_DB):
        return 0
    src = _conn(ARCHIVE_DB)
    try:
        cols = {r["name"] for r in src.execute(
            "PRAGMA table_info(archive_frame)")}
        has_raw = "raw_reading" in cols
        if since:
            rows = src.execute("SELECT * FROM archive_frame WHERE ts>? "
                               "ORDER BY ts", (since,)).fetchall()
        else:
            rows = src.execute(
                "SELECT * FROM archive_frame ORDER BY ts").fetchall()
    finally:
        src.close()
    now = datetime.now().isoformat(timespec="seconds")
    c = _conn()
    n = 0
    try:
        for r in rows:
            committed = r["reading"]
            committed_cf = (committed / COUNTS_PER_CF
                            if committed is not None else None)
            raw = r["raw_reading"] if has_raw else None
            raw_conf = r["raw_conf"] if has_raw else None
            reader = (r["raw_source"] if has_raw and r["raw_source"]
                      else None)
            c.execute(
                "INSERT OR IGNORE INTO meter_reading"
                "(ts,image_file,raw_reading,raw_conf,reader,committed,"
                " committed_cf,method,confidence,reviewed,state,delta_cf,"
                " origin,ingested_ts) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (r["ts"], r["filename"], raw, raw_conf, reader, committed,
                 committed_cf, _map_archive_method(r["source"]),
                 r["confidence"], r["reviewed"] or 0, None, None,
                 "backfill:archive_frame", now))
            n += c.total_changes and 1 or 0
        c.commit()
        # total_changes accounting above is unreliable per-row; report inserts
        return _count_origin("backfill:archive_frame")
    finally:
        c.close()


def backfill_from_flow_gaps(since=None):
    """Fill evidence-less gaps from flow_sample (the 15s lock) ONLY where no
    image-backed reading already covers that instant, so the image-backed spine
    stays primary and we don't double-count or re-introduce stream drift."""
    if not os.path.exists(FLOW_DB):
        return 0
    # Existing timestamps (sorted epochs) to test gap coverage fast. On an
    # incremental sync (since set) only the recent window is needed.
    c = _conn()
    try:
        if since:
            ex_rows = c.execute(
                "SELECT ts FROM meter_reading WHERE ts>=?", (since,)).fetchall()
        else:
            ex_rows = c.execute("SELECT ts FROM meter_reading").fetchall()
        existing = sorted(
            e for (e,) in ((_epoch(row["ts"]),) for row in ex_rows)
            if e is not None)
    finally:
        c.close()

    import bisect

    def covered(ep):
        if ep is None or not existing:
            return False
        i = bisect.bisect_left(existing, ep)
        for j in (i - 1, i):
            if 0 <= j < len(existing) and abs(existing[j] - ep) <= GAP_FILL_WINDOW_S:
                return True
        return False

    src = _conn(FLOW_DB)
    try:
        if since:
            rows = src.execute(
                "SELECT ts, reading_cf, state FROM flow_sample "
                "WHERE reading_cf IS NOT NULL AND ts>? ORDER BY ts",
                (since,)).fetchall()
        else:
            rows = src.execute(
                "SELECT ts, reading_cf, state FROM flow_sample "
                "WHERE reading_cf IS NOT NULL ORDER BY ts").fetchall()
    finally:
        src.close()
    now = datetime.now().isoformat(timespec="seconds")
    c = _conn()
    n = 0
    try:
        for r in rows:
            ep = _epoch(r["ts"])
            if covered(ep):
                continue
            cf = r["reading_cf"]
            committed = int(round(cf * COUNTS_PER_CF)) if cf is not None else None
            c.execute(
                "INSERT OR IGNORE INTO meter_reading"
                "(ts,image_file,raw_reading,raw_conf,reader,committed,"
                " committed_cf,method,confidence,reviewed,state,delta_cf,"
                " origin,ingested_ts) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (r["ts"], None, None, None, None, committed, cf,
                 "held", "lock", 0, r["state"], None,
                 "backfill:flow_sample", now))
            # keep the in-memory index current so the next gap test is correct
            bisect.insort(existing, ep)
            n += 1
        c.commit()
        return n
    finally:
        c.close()


def compute_deltas(only_null=False):
    """Fill delta_cf = committed_cf - previous committed_cf (a monotonic
    odometer; a negative delta is a misread/re-anchor). With only_null=True,
    process just the rows missing a delta (new arrivals) -- seeded from the row
    just before the first gap -- so the cost does not grow with ledger size."""
    c = _conn()
    try:
        if only_null:
            first = c.execute(
                "SELECT MIN(ts) m FROM meter_reading "
                "WHERE delta_cf IS NULL AND committed_cf IS NOT NULL"
            ).fetchone()["m"]
            if first is None:
                return 0
            pr = c.execute(
                "SELECT committed_cf FROM meter_reading "
                "WHERE ts<? AND committed_cf IS NOT NULL "
                "ORDER BY ts DESC LIMIT 1", (first,)).fetchone()
            prev = pr["committed_cf"] if pr else None
            rows = c.execute(
                "SELECT ts, committed_cf FROM meter_reading "
                "WHERE ts>=? AND committed_cf IS NOT NULL ORDER BY ts",
                (first,)).fetchall()
        else:
            prev = None
            rows = c.execute(
                "SELECT ts, committed_cf FROM meter_reading "
                "WHERE committed_cf IS NOT NULL ORDER BY ts").fetchall()
        for r in rows:
            # The very first reading has no predecessor -> 0.0 (NOT NULL), so a
            # NULL delta unambiguously means "new row, not yet computed" and the
            # incremental pass never re-scans the whole ledger.
            d = 0.0 if prev is None else round(r["committed_cf"] - prev, 3)
            c.execute("UPDATE meter_reading SET delta_cf=? WHERE ts=?",
                      (d, r["ts"]))
            prev = r["committed_cf"]
        c.commit()
        return len(rows)
    finally:
        c.close()


def backfill():
    ensure_schema()
    a = backfill_from_archive()
    f = backfill_from_flow_gaps()
    d = compute_deltas()
    return {"image_backed": a, "flow_gap_fill": f, "deltas": d,
            "total": _count_all()}


def sync():
    """Keep the ledger current (for a timer): import new legacy rows,
    incrementally fill deltas, and rebuild the recent daily rollup. Idempotent.
    The legacy sources are bounded (flow_sample 30d retention, archive_frame
    disk-capped) and the delta/daily passes are incremental, so sync cost does
    not grow with ledger size."""
    ensure_schema()
    c = _conn()
    try:
        last = c.execute("SELECT MAX(ts) m FROM meter_reading").fetchone()["m"]
    finally:
        c.close()
    # Re-examine a 1-day overlap so late-arriving rows are not missed.
    since = None
    if last:
        try:
            since = (datetime.fromisoformat(last) - timedelta(days=1)
                     ).isoformat(timespec="seconds")
        except Exception:
            since = None
    backfill_from_archive(since)
    backfill_from_flow_gaps(since)
    nd = compute_deltas(only_null=True)
    days = recompute_daily(start=(since[:10] if since else None))
    return {"new_deltas": nd, "days_recomputed": days,
            "image_backed": _count_origin("backfill:archive_frame"),
            "flow_gap_fill": _count_origin("backfill:flow_sample"),
            "total": _count_all()}


# ---------------------------------------------------------------------------
# Derived metrics (recomputable) — the high-water-mark usage method
# ---------------------------------------------------------------------------
def recompute_daily(start=None, end=None):
    """Rebuild usage_daily from meter_reading via the high-water-mark method:
    the meter is a monotonic odometer, so water used = how far the running PEAK
    of committed_cf climbs. A dip is a re-anchor/misread (never reduces usage);
    re-climbing to a prior high is not double-counted. The peak carries across
    day boundaries; each new-high increment is attributed to the day it occurred.
    """
    c = _conn()
    try:
        q = ("SELECT ts, committed_cf, image_file, method FROM meter_reading "
             "WHERE committed_cf IS NOT NULL")
        args = []
        if start:
            q += " AND ts>=?"; args.append(start)
        if end:
            q += " AND ts<=?"; args.append(end)
        q += " ORDER BY ts"
        rows = c.execute(q, args).fetchall()

        days = {}            # date -> aggregate
        # Seed the running peak from BEFORE the (re)computed window so the
        # high-water-mark stays globally correct even on an incremental rebuild.
        peak = None
        if start:
            pr = c.execute(
                "SELECT MAX(committed_cf) m FROM meter_reading "
                "WHERE ts<? AND committed_cf IS NOT NULL", (start,)).fetchone()
            peak = pr["m"] if pr else None
        for r in rows:
            day = r["ts"][:10]
            d = days.get(day)
            if d is None:
                d = {"gallons": 0.0, "start_cf": r["committed_cf"],
                     "end_cf": r["committed_cf"], "n": 0,
                     "n_img": 0, "n_fresh": 0}
                days[day] = d
            cf = r["committed_cf"]
            if peak is None:
                peak = cf
            elif cf > peak:
                d["gallons"] += (cf - peak) * GAL_PER_CF
                peak = cf
            d["end_cf"] = cf
            d["n"] += 1
            if r["image_file"]:
                d["n_img"] += 1
            if r["method"] == "read":
                d["n_fresh"] += 1

        now = datetime.now().isoformat(timespec="seconds")
        for day, d in days.items():
            c.execute(
                "INSERT OR REPLACE INTO usage_daily"
                "(date,gallons,start_cf,end_cf,n_readings,n_image_backed,"
                " n_fresh_reads,method,computed_ts)"
                " VALUES(?,?,?,?,?,?,?,?,?)",
                (day, round(d["gallons"], 2), round(d["start_cf"], 3),
                 round(d["end_cf"], 3), d["n"], d["n_img"], d["n_fresh"],
                 USAGE_METHOD, now))
        c.commit()
        return len(days)
    finally:
        c.close()


# ---------------------------------------------------------------------------
# Auditability helpers
# ---------------------------------------------------------------------------
def lineage(ts):
    """Full drill-down for one reading: the validated value, the raw read, the
    image, and every correction ever applied to it."""
    c = _conn()
    try:
        r = c.execute("SELECT * FROM meter_reading WHERE ts=?", (ts,)).fetchone()
        if not r:
            return None
        corr = [dict(x) for x in c.execute(
            "SELECT * FROM meter_correction WHERE ts=? ORDER BY at", (ts,))]
        out = dict(r)
        out["corrections"] = corr
        return out
    finally:
        c.close()


def stats():
    c = _conn()
    try:
        total = c.execute("SELECT COUNT(*) n FROM meter_reading").fetchone()["n"]
        img = c.execute("SELECT COUNT(*) n FROM meter_reading "
                        "WHERE image_file IS NOT NULL").fetchone()["n"]
        raw = c.execute("SELECT COUNT(*) n FROM meter_reading "
                        "WHERE raw_reading IS NOT NULL").fetchone()["n"]
        rng = c.execute("SELECT MIN(ts) lo, MAX(ts) hi FROM meter_reading"
                        ).fetchone()
        by_method = {r["method"]: r["n"] for r in c.execute(
            "SELECT method, COUNT(*) n FROM meter_reading "
            "GROUP BY method ORDER BY n DESC")}
        by_origin = {r["origin"]: r["n"] for r in c.execute(
            "SELECT origin, COUNT(*) n FROM meter_reading GROUP BY origin")}
        days = c.execute("SELECT COUNT(*) n FROM usage_daily").fetchone()["n"]
        return {"total": total, "image_backed": img, "raw_reads": raw,
                "first": rng["lo"], "last": rng["hi"],
                "by_method": by_method, "by_origin": by_origin,
                "usage_days": days}
    finally:
        c.close()


def reconcile():
    """Prove the ledger is correct: compare ledger high-water-mark usage to the
    legacy flow_sample net movement over the overlapping window. They should
    agree to within last-digit noise."""
    out = {"ledger_gal": None, "legacy_net_gal": None, "diff_gal": None}
    c = _conn()
    try:
        led = c.execute(
            "SELECT SUM(gallons) g, MIN(date) lo, MAX(date) hi "
            "FROM usage_daily").fetchone()
        out["ledger_gal"] = round(led["g"] or 0.0, 1)
        out["window"] = f"{led['lo']}..{led['hi']}"
    finally:
        c.close()
    if os.path.exists(FLOW_DB) and out.get("window"):
        lo = out["window"].split("..")[0]
        src = _conn(FLOW_DB)
        try:
            r = src.execute(
                "SELECT MIN(reading_cf) lo, MAX(reading_cf) hi FROM flow_sample "
                "WHERE reading_cf IS NOT NULL AND ts>=?", (lo + "T00:00:00",)
            ).fetchone()
            if r and r["lo"] is not None:
                out["legacy_net_gal"] = round((r["hi"] - r["lo"]) * GAL_PER_CF, 1)
                out["diff_gal"] = round(
                    out["ledger_gal"] - out["legacy_net_gal"], 1)
        finally:
            src.close()
    return out


# ---------------------------------------------------------------------------
# Query helpers (for charts / the API)
# ---------------------------------------------------------------------------
def readings_range(start=None, end=None, limit=4000, image_only=False,
                   order="desc"):
    """Readings in [start, end] straight from the canonical ledger -- the same
    rows the photos come from, so a plotted point and its image can only
    disagree because of OCR."""
    c = _conn()
    try:
        q = ("SELECT ts, image_file, raw_reading, raw_conf, reader, committed,"
             " committed_cf, method, confidence, reviewed, state, delta_cf "
             "FROM meter_reading WHERE committed_cf IS NOT NULL")
        args = []
        if start:
            q += " AND ts>=?"; args.append(start)
        if end:
            q += " AND ts<=?"; args.append(end)
        if image_only:
            q += " AND image_file IS NOT NULL"
        q += " ORDER BY ts " + ("ASC" if order == "asc" else "DESC")
        q += " LIMIT ?"; args.append(int(limit))
        return [dict(r) for r in c.execute(q, args).fetchall()]
    finally:
        c.close()


def count_readings(start=None, end=None, image_only=False):
    c = _conn()
    try:
        q = ("SELECT COUNT(*) n FROM meter_reading "
             "WHERE committed_cf IS NOT NULL")
        args = []
        if start:
            q += " AND ts>=?"; args.append(start)
        if end:
            q += " AND ts<=?"; args.append(end)
        if image_only:
            q += " AND image_file IS NOT NULL"
        return int(c.execute(q, args).fetchone()["n"])
    finally:
        c.close()


# ---------------------------------------------------------------------------
# small internals
# ---------------------------------------------------------------------------
def _count_all():
    c = _conn()
    try:
        return c.execute("SELECT COUNT(*) n FROM meter_reading").fetchone()["n"]
    finally:
        c.close()


def _count_origin(origin):
    c = _conn()
    try:
        return c.execute("SELECT COUNT(*) n FROM meter_reading WHERE origin=?",
                         (origin,)).fetchone()["n"]
    finally:
        c.close()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "stats"
    if cmd == "init":
        ensure_schema()
        print("schema ready at", DB_PATH)
    elif cmd == "backfill":
        print(backfill())
    elif cmd == "sync":
        print(sync())
    elif cmd == "recompute":
        print("usage_daily rows:", recompute_daily())
    elif cmd == "stats":
        import json
        print(json.dumps(stats(), indent=2))
    elif cmd == "reconcile":
        import json
        print(json.dumps(reconcile(), indent=2))
    elif cmd == "lineage":
        import json
        print(json.dumps(lineage(sys.argv[2]), indent=2, default=str))
    else:
        print("commands: init backfill recompute stats reconcile lineage <ts>")
