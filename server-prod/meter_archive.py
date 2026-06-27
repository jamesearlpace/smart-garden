#!/usr/bin/env python3
"""Persistent index + reading store for the long-term cam frame archive.

The archive (dashboard.py `_archive_frame`) saves one JPEG per minute to
``METER_ARCHIVE_DIR`` and FIFO-evicts the oldest once it exceeds the disk cap.
This module keeps ONE ROW PER ARCHIVED IMAGE so the website can:

  * browse the full image history,
  * show + refresh the meter reading derived for each image (re-read with the
    LLM, or correct by hand, when something looks off), and
  * build ACCURATE historical water-consumption graphs from the corrected
    per-minute readings (monotonic positive deltas -> gallons).

Isolated like ``meter_audit.py`` / ``cnn_metrics.py``: its own sqlite DB so it
never contends with the live database. The baseline reading for each image is
the live meter lock at capture time (free); it can be refined on demand.
"""
import os
import sqlite3
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("METER_ARCHIVE_DB", os.path.join(HERE, "meter_archive.db"))

COUNTS_PER_CF = 1000.0
GAL_PER_CF = 7.48052
COUNTS_PER_GAL = COUNTS_PER_CF / GAL_PER_CF       # ~133.69
# Absolute plumbing flow ceiling (gal/min) used to reject garbled jumps when
# computing consumption — a single bad reading can't manufacture impossible use.
MAX_GPM = float(os.environ.get("METER_MAX_GPM", "20"))
# Keep lock-derived archive readings monotonic by default. If the live lock is
# temporarily stale and falls behind a recently corrected archive point, clamp
# the new lock row up to the previous archive reading.
LOCK_MONOTONIC = os.environ.get("METER_ARCHIVE_LOCK_MONOTONIC", "1") == "1"


def _conn():
    c = sqlite3.connect(DB_PATH, timeout=15)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    return c


def _is_trusted_anchor(source, confidence, reviewed):
    """Whether a row is strong enough to anchor interpolation."""
    if int(reviewed or 0) == 1:
        return True
    src = str(source or "").lower()
    conf = str(confidence or "").lower()
    if src in ("manual", "oracle"):
        return True
    if src == "cnn" and conf == "high":
        return True
    return False


def _max_forward_counts(elapsed_s):
    """Physical forward bound for one archive step."""
    e = max(1.0, float(elapsed_s or 1.0))
    return int((MAX_GPM / 60.0) * e * COUNTS_PER_GAL * 1.5 + 200)


def _auto_interpolate_to_anchor(c, right_ts):
    """Fill lock/prop rows between trusted anchors ending at right_ts.

    This keeps nearby history coherent automatically when the newest frame gets
    a trusted reading after several uncertain/stale lock-derived rows.
    """
    right = c.execute(
        "SELECT ts, reading, source, confidence, reviewed "
        "FROM archive_frame WHERE ts=? AND reading IS NOT NULL",
        (right_ts,)
    ).fetchone()
    if not right:
        return 0
    if not _is_trusted_anchor(
            right["source"], right["confidence"], right["reviewed"]):
        return 0

    left = None
    for r in c.execute(
            "SELECT ts, reading, source, confidence, reviewed "
            "FROM archive_frame WHERE ts<? AND reading IS NOT NULL "
            "ORDER BY ts DESC",
            (right_ts,)).fetchall():
        if _is_trusted_anchor(r["source"], r["confidence"], r["reviewed"]):
            left = r
            break
    if not left:
        return 0

    left_ts = left["ts"]
    left_val = int(left["reading"])
    right_val = int(right["reading"])
    if right_val < left_val:
        return 0

    left_ep = _epoch(left_ts)
    right_ep = _epoch(right_ts)
    if left_ep is None or right_ep is None or right_ep <= left_ep:
        return 0

    rows = c.execute(
        "SELECT ts, reading, source, confidence, reviewed "
        "FROM archive_frame WHERE ts>? AND ts<? AND reading IS NOT NULL "
        "ORDER BY ts",
        (left_ts, right_ts)
    ).fetchall()
    if not rows:
        return 0

    updated = 0
    now_s = datetime.now().isoformat(timespec="seconds")
    prev_val = left_val
    prev_ep = left_ep
    for r in rows:
        # Never rewrite human-reviewed or strong model/cnn rows.
        if int(r["reviewed"] or 0) == 1:
            prev_val = int(r["reading"])
            ep_r = _epoch(r["ts"])
            prev_ep = ep_r if ep_r is not None else prev_ep
            continue
        src = str(r["source"] or "").lower()
        if src not in ("lock", "propagated"):
            prev_val = int(r["reading"])
            ep_r = _epoch(r["ts"])
            prev_ep = ep_r if ep_r is not None else prev_ep
            continue

        ep = _epoch(r["ts"])
        if ep is None:
            continue
        frac = (ep - left_ep) / (right_ep - left_ep)
        frac = max(0.0, min(1.0, frac))
        est = int(round(left_val + (right_val - left_val) * frac))

        cap = _max_forward_counts(ep - prev_ep)
        lo = prev_val
        hi = min(right_val, prev_val + cap)
        new_val = min(max(est, lo), hi)

        old_val = int(r["reading"])
        old_conf = str(r["confidence"] or "")
        if old_val != new_val or src != "propagated" or old_conf != "inferred":
            c.execute(
                "UPDATE archive_frame SET reading=?, reading_cf=?, confidence=?, "
                "source=?, updated_ts=? WHERE ts=?",
                (new_val, new_val / COUNTS_PER_CF, "inferred",
                 "propagated", now_s, r["ts"])
            )
            updated += 1
        prev_val = new_val
        prev_ep = ep

    return updated


def ensure_schema():
    c = _conn()
    try:
        c.execute(
            "CREATE TABLE IF NOT EXISTS archive_frame ("
            " ts TEXT PRIMARY KEY,"        # ISO capture time (sortable, unique)
            " filename TEXT NOT NULL,"     # basename in METER_ARCHIVE_DIR
            " reading INTEGER,"            # 9-digit counts; NULL if unknown
            " reading_cf REAL,"            # reading / 1000 (cubic feet)
            " confidence TEXT,"            # high|medium|low|lock|manual
            " source TEXT,"                # lock|oracle|manual
            " reviewed INTEGER DEFAULT 0," # 1 = a human confirmed/corrected it
            " updated_ts TEXT"
            ")")
        c.execute("CREATE INDEX IF NOT EXISTS ix_arc_ts ON archive_frame(ts)")
        # Convergence trend: one snapshot row per sample so the monitor can show
        # "perfectable remaining" trending toward zero over time (the single most
        # honest progress metric).
        c.execute(
            "CREATE TABLE IF NOT EXISTS convergence_snapshot ("
            " ts TEXT PRIMARY KEY,"            # ISO sample time
            " total INTEGER,"                  # all archive rows
            " authoritative INTEGER,"          # manual/oracle/reviewed rows
            " perfectable_remaining INTEGER,"  # uncertain rows still fixable
            " unrecoverable INTEGER,"          # evicted-image rows (no fix)
            " null_readings INTEGER,"          # rows with no reading at all
            " perfect_pct REAL"                # authoritative / total * 100
            ")")
        # Audit-the-monitor log: every blind re-read or human spot-check, so the
        # dashboard's "perfect" claim can itself be independently checked.
        c.execute(
            "CREATE TABLE IF NOT EXISTS audit_result ("
            " id INTEGER PRIMARY KEY AUTOINCREMENT,"
            " ts TEXT,"               # when the audit happened
            " frame_ts TEXT,"         # which archive row was audited
            " kind TEXT,"             # 'blind' (AI re-read) | 'human'
            " stored INTEGER,"        # value the system currently claims
            " checked INTEGER,"       # independent value (AI or human typed)
            " agree INTEGER,"         # 1 = matched, 0 = contradicted
            " source TEXT,"           # stored row's source at audit time
            " model TEXT,"            # blind re-read model (NULL for human)
            " note TEXT"
            ")")
        c.execute("CREATE INDEX IF NOT EXISTS ix_audit_ts ON audit_result(ts)")
        c.commit()
    finally:
        c.close()


def convergence_stats():
    """Current truth-coverage snapshot of the whole archive.

    * authoritative          = rows we claim are correct (manual/oracle/reviewed)
    * perfectable_remaining  = uncertain rows that still have a fixable path
    * unrecoverable          = rows whose image was evicted (can't re-read)
    * null_readings          = rows with no reading at all
    """
    c = _conn()
    try:
        total = int(c.execute(
            "SELECT COUNT(*) n FROM archive_frame").fetchone()["n"])
        authoritative = int(c.execute(
            "SELECT COUNT(*) n FROM archive_frame "
            "WHERE source IN ('manual','oracle') OR reviewed=1").fetchone()["n"])
        perfectable = int(c.execute(
            "SELECT COUNT(*) n FROM archive_frame "
            "WHERE reading IS NOT NULL AND reviewed=0 "
            "AND source NOT IN ('manual','oracle','evicted')").fetchone()["n"])
        unrecoverable = int(c.execute(
            "SELECT COUNT(*) n FROM archive_frame "
            "WHERE source='evicted'").fetchone()["n"])
        nulls = int(c.execute(
            "SELECT COUNT(*) n FROM archive_frame "
            "WHERE reading IS NULL").fetchone()["n"])
        pct = round((authoritative / total * 100.0), 2) if total else 0.0
        return {
            "total": total,
            "authoritative": authoritative,
            "perfectable_remaining": perfectable,
            "unrecoverable": unrecoverable,
            "null_readings": nulls,
            "perfect_pct": pct,
        }
    finally:
        c.close()


def record_convergence_snapshot():
    """Compute current convergence stats and persist a trend point."""
    s = convergence_stats()
    c = _conn()
    try:
        c.execute(
            "INSERT OR REPLACE INTO convergence_snapshot"
            "(ts,total,authoritative,perfectable_remaining,unrecoverable,"
            "null_readings,perfect_pct) VALUES(?,?,?,?,?,?,?)",
            (datetime.now().isoformat(timespec="seconds"),
             s["total"], s["authoritative"], s["perfectable_remaining"],
             s["unrecoverable"], s["null_readings"], s["perfect_pct"]))
        c.commit()
    finally:
        c.close()
    return s


def convergence_history(hours=24, limit=1000):
    """Snapshot trend over the last ``hours`` (oldest first)."""
    cutoff = (datetime.now() - timedelta(hours=max(1, int(hours)))
              ).isoformat(timespec="seconds")
    c = _conn()
    try:
        rows = c.execute(
            "SELECT * FROM convergence_snapshot WHERE ts>=? "
            "ORDER BY ts ASC LIMIT ?",
            (cutoff, int(limit))).fetchall()
        return [dict(r) for r in rows]
    finally:
        c.close()


def random_perfect_rows(limit=10):
    """Random sample of rows the system currently CLAIMS are correct
    (manual/oracle/reviewed). Used to audit those claims against the images."""
    c = _conn()
    try:
        rows = c.execute(
            "SELECT * FROM archive_frame "
            "WHERE reading IS NOT NULL "
            "AND (source IN ('manual','oracle') OR reviewed=1) "
            "ORDER BY RANDOM() LIMIT ?",
            (int(limit),)).fetchall()
        return [dict(r) for r in rows]
    finally:
        c.close()


def oldest_perfectable_rows(limit=5):
    """Oldest uncertain rows that still have a fixable path (not manual/oracle/
    evicted, not human-reviewed). The convergence drainer walks these into
    authoritative per-frame anchors so the WHOLE history converges over time."""
    c = _conn()
    try:
        rows = c.execute(
            "SELECT * FROM archive_frame "
            "WHERE reading IS NOT NULL AND reviewed=0 "
            "AND source NOT IN ('manual','oracle','evicted') "
            "ORDER BY ts ASC LIMIT ?",
            (int(limit),)).fetchall()
        return [dict(r) for r in rows]
    finally:
        c.close()


def unaudited_rows(limit=5):
    """Rows that have NEVER had an independent blind audit (no audit_result row).
    Prioritises growing trust COVERAGE across the whole history. Random order so
    coverage spreads evenly rather than marching front-to-back. Manual rows are
    skipped (a human already vouched for them)."""
    c = _conn()
    try:
        rows = c.execute(
            "SELECT a.* FROM archive_frame a "
            "WHERE a.reading IS NOT NULL AND a.source!='manual' "
            "AND a.source!='evicted' "
            "AND NOT EXISTS (SELECT 1 FROM audit_result r WHERE r.frame_ts=a.ts) "
            "ORDER BY RANDOM() LIMIT ?",
            (int(limit),)).fetchall()
        return [dict(r) for r in rows]
    finally:
        c.close()


def audit_coverage():
    """How much of the history has been independently blind-checked at least
    once. Returns {total, audited, coverage_pct}."""
    c = _conn()
    try:
        total = int(c.execute(
            "SELECT COUNT(*) n FROM archive_frame "
            "WHERE reading IS NOT NULL AND source!='evicted'").fetchone()["n"])
        audited = int(c.execute(
            "SELECT COUNT(DISTINCT a.ts) n FROM archive_frame a "
            "WHERE a.reading IS NOT NULL "
            "AND EXISTS (SELECT 1 FROM audit_result r WHERE r.frame_ts=a.ts)"
        ).fetchone()["n"])
        pct = round((audited / total * 100.0), 2) if total else 0.0
        return {"total": total, "audited": audited, "coverage_pct": pct}
    finally:
        c.close()


def record_audit_result(frame_ts, stored, checked, agree, kind,
                        source=None, model=None, note=None):
    """Log one independent check of a stored value (blind AI or human)."""
    c = _conn()
    try:
        c.execute(
            "INSERT INTO audit_result"
            "(ts,frame_ts,kind,stored,checked,agree,source,model,note) "
            "VALUES(?,?,?,?,?,?,?,?,?)",
            (datetime.now().isoformat(timespec="seconds"),
             frame_ts, kind,
             int(stored) if stored is not None else None,
             int(checked) if checked is not None else None,
             1 if agree else 0, source, model, note))
        c.commit()
    finally:
        c.close()


def audit_summary(hours=168, limit_recent=40):
    """Agreement stats over recent audits, split by kind, plus recent rows.

    Agreement % = of values we claimed correct, how many an INDEPENDENT check
    confirmed. This is the metric that audits the monitor itself.
    """
    cutoff = (datetime.now() - timedelta(hours=max(1, int(hours)))
              ).isoformat(timespec="seconds")
    c = _conn()
    try:
        def _grade(kind):
            r = c.execute(
                "SELECT COUNT(*) n, SUM(agree) a FROM audit_result "
                "WHERE ts>=? AND kind=?",
                (cutoff, kind)).fetchone()
            n = int(r["n"] or 0)
            a = int(r["a"] or 0)
            return {"checked": n, "agreed": a, "disagreed": n - a,
                    "agreement_pct": round((a / n * 100.0), 1) if n else None}
        recent = [dict(r) for r in c.execute(
            "SELECT * FROM audit_result WHERE ts>=? "
            "ORDER BY ts DESC LIMIT ?",
            (cutoff, int(limit_recent))).fetchall()]
        return {
            "blind": _grade("blind"),
            "human": _grade("human"),
            "recent": recent,
        }
    finally:
        c.close()


def record(ts, filename, reading=None, confidence="lock", source="lock"):
    """Index a newly archived frame. INSERT OR IGNORE so a re-archive never
    clobbers a reading a human already refined for the same timestamp."""
    base_reading = int(reading) if reading is not None else None
    base_conf = confidence
    base_source = source
    c = _conn()
    try:
        if LOCK_MONOTONIC and base_source == "lock":
            prev = c.execute(
                "SELECT reading FROM archive_frame WHERE ts<? "
                "AND reading IS NOT NULL ORDER BY ts DESC LIMIT 1",
                (ts,)).fetchone()
            prev_val = int(prev["reading"]) if prev and prev["reading"] is not None else None
            if prev_val is not None:
                if base_reading is None:
                    base_reading = prev_val
                    base_conf = "propagated"
                    base_source = "propagated"
                elif base_reading < prev_val:
                    base_reading = prev_val
                    base_conf = "propagated"
                    base_source = "propagated"

        cf = (base_reading / COUNTS_PER_CF) if base_reading is not None else None
        c.execute(
            "INSERT OR IGNORE INTO archive_frame"
            "(ts,filename,reading,reading_cf,confidence,source,reviewed,updated_ts)"
            " VALUES(?,?,?,?,?,?,0,?)",
            (ts, filename, base_reading, cf, base_conf, base_source,
             datetime.now().isoformat(timespec="seconds")))

        # If this row is a trusted anchor, automatically smooth uncertain rows
        # between the previous trusted anchor and this one.
        if base_reading is not None and _is_trusted_anchor(base_source, base_conf, 0):
            _auto_interpolate_to_anchor(c, ts)

        c.commit()
    finally:
        c.close()


def update_reading(ts, reading, confidence, source, reviewed=True):
    """Refine the reading for one archived image (re-read or manual correction)."""
    cf = (reading / COUNTS_PER_CF) if reading is not None else None
    c = _conn()
    try:
        cur = c.execute(
            "UPDATE archive_frame SET reading=?,reading_cf=?,confidence=?,"
            "source=?,reviewed=?,updated_ts=? WHERE ts=?",
            (reading, cf, confidence, source, 1 if reviewed else 0,
             datetime.now().isoformat(timespec="seconds"), ts))

        # A manual/oracle/cnn-high correction can close a gap; auto-fill the
        # in-between lock/prop rows immediately.
        if cur.rowcount > 0 and _is_trusted_anchor(source, confidence, reviewed):
            _auto_interpolate_to_anchor(c, ts)

        c.commit()
        return cur.rowcount > 0
    finally:
        c.close()


def reconcile_window(start_ts, end_ts):
    """Re-run trusted-anchor interpolation for a time window.

    Used by reconnect recovery: when the camera returns after a long gap,
    re-apply interpolation across rows in the affected window so stale/held
    lock rows are corrected automatically once trusted anchors exist.
    """
    c = _conn()
    try:
        rows = c.execute(
            "SELECT ts, source, confidence, reviewed "
            "FROM archive_frame WHERE ts>=? AND ts<=? AND reading IS NOT NULL "
            "ORDER BY ts ASC",
            (start_ts, end_ts),
        ).fetchall()
        anchors = [
            r["ts"] for r in rows
            if _is_trusted_anchor(r["source"], r["confidence"], r["reviewed"])
        ]
        updated = 0
        for ts in anchors:
            updated += int(_auto_interpolate_to_anchor(c, ts) or 0)
        c.commit()
        return {"anchors": len(anchors), "updated": int(updated)}
    finally:
        c.close()


def propagate_delta(anchor_ts, delta):
    """Shift subsequent unreviewed lock-derived rows by ``delta`` counts.

    Why: when a human corrects one recent frame, nearby lock-baseline rows often
    share the same offset. Propagating that offset forward keeps history coherent
    without touching already-reviewed anchors.

    Rules:
      * start strictly AFTER anchor_ts
      * update only rows with reviewed=0 and source in ('lock','propagated')
      * stop at the first reviewed row (manual/oracle anchor)
    Returns the number of rows updated.
    """
    try:
        delta = int(delta)
    except Exception:
        return 0
    if delta == 0:
        return 0
    c = _conn()
    try:
        rows = c.execute(
            "SELECT ts, reading, source, reviewed FROM archive_frame "
            "WHERE ts>? AND reading IS NOT NULL ORDER BY ts",
            (anchor_ts,)).fetchall()
        n = 0
        now = datetime.now().isoformat(timespec="seconds")
        for r in rows:
            src = (r["source"] or "")
            rev = int(r["reviewed"] or 0)
            if rev == 1:
                break
            if src not in ("lock", "propagated"):
                continue
            new_val = int(r["reading"]) + delta
            c.execute(
                "UPDATE archive_frame SET reading=?, reading_cf=?, confidence=?, "
                "source=?, updated_ts=? WHERE ts=?",
                (new_val, new_val / COUNTS_PER_CF, "propagated",
                 "propagated", now, r["ts"]))
            n += 1
        c.commit()
        return n
    finally:
        c.close()


def max_reading_in(start, end):
    """Highest stored reading in [start, end] (or None). Used by the
    archive-to-lock self-heal to cheaply detect an impossible-high chain."""
    c = _conn()
    try:
        r = c.execute(
            "SELECT MAX(reading) m FROM archive_frame "
            "WHERE ts>=? AND ts<=? AND reading IS NOT NULL",
            (start, end)).fetchone()
        return int(r["m"]) if r and r["m"] is not None else None
    finally:
        c.close()


def suspect_rows(start, end, threshold, limit=50):
    """Rows in [start, end] that need a fresh PER-FRAME re-read because they no
    longer faithfully reflect their own image:
      * reading ABOVE ``threshold`` (impossible-high vs the trusted lock), OR
      * source ``reconciled`` (an earlier flat-to-lock heal that erased the real
        per-frame value — these read flat at the lock, so they're not "above" it
        but are still wrong for older timestamps).
    Never returns ``manual`` rows (human corrections are authoritative). NEWEST
    first so the visible/recent history (whose images still exist) is fixed
    before older rows that may have been evicted. Returns row dicts."""
    return reread_candidates(
        start, end, threshold, limit=limit, mode="suspect")


def reread_candidates(start, end, threshold, limit=50, mode="converge"):
    """Rows in [start, end] eligible for per-frame truth re-read.

    Modes:
      * "suspect": only impossible-high/reconciled rows (legacy behavior).
      * "converge": gradually replace uncertain lock/propagated/reconciled
        history with authoritative per-frame reads, while never touching manual
        or oracle anchors.
    """
    mode = str(mode or "converge").strip().lower()
    if mode not in ("suspect", "converge"):
        mode = "converge"
    c = _conn()
    try:
        if mode == "suspect":
            rows = c.execute(
                "SELECT * FROM archive_frame "
                "WHERE ts>=? AND ts<=? AND reading IS NOT NULL "
                "AND source!='manual' "
                "AND (reading>? OR source='reconciled') "
                "ORDER BY ts DESC LIMIT ?",
                (start, end, int(threshold), int(limit))).fetchall()
        else:
            rows = c.execute(
                "SELECT * FROM archive_frame "
                "WHERE ts>=? AND ts<=? AND reading IS NOT NULL "
                "AND reviewed=0 "
                "AND source NOT IN ('manual','oracle','evicted') "
                "AND (reading>? OR source IN ('reconciled','lock','propagated') "
                "     OR (source='cnn' AND confidence!='high')) "
                "ORDER BY ts DESC LIMIT ?",
                (start, end, int(threshold), int(limit))).fetchall()
        return [dict(r) for r in rows]
    finally:
        c.close()


def count_suspect(start, end, threshold):
    """Cheap count of rows needing a per-frame re-read (see suspect_rows)."""
    return count_reread_candidates(
        start, end, threshold, mode="suspect")


def count_reread_candidates(start, end, threshold, mode="converge"):
    """Count rows eligible for per-frame reread in the selected mode."""
    mode = str(mode or "converge").strip().lower()
    if mode not in ("suspect", "converge"):
        mode = "converge"
    c = _conn()
    try:
        if mode == "suspect":
            r = c.execute(
                "SELECT COUNT(*) n FROM archive_frame "
                "WHERE ts>=? AND ts<=? AND reading IS NOT NULL "
                "AND source!='manual' AND (reading>? OR source='reconciled')",
                (start, end, int(threshold))).fetchone()
        else:
            r = c.execute(
                "SELECT COUNT(*) n FROM archive_frame "
                "WHERE ts>=? AND ts<=? AND reading IS NOT NULL "
                "AND reviewed=0 "
                "AND source NOT IN ('manual','oracle','evicted') "
                "AND (reading>? OR source IN ('reconciled','lock','propagated') "
                "     OR (source='cnn' AND confidence!='high'))",
                (start, end, int(threshold))).fetchone()
        return int(r["n"]) if r else 0
    finally:
        c.close()


def retire_missing(ts):
    """Retire one unrecoverable row from future reread queues.

    Used when the archived image file has already been evicted by the disk cap.
    This prevents a permanent tail of non-actionable candidates from keeping the
    convergence queue non-zero forever.
    """
    c = _conn()
    try:
        cur = c.execute(
            "UPDATE archive_frame SET source='evicted', confidence='missing_image', "
            "updated_ts=? WHERE ts=? AND reviewed=0 "
            "AND source NOT IN ('manual','oracle')",
            (datetime.now().isoformat(timespec="seconds"), ts))
        c.commit()
        return (cur.rowcount or 0) > 0
    finally:
        c.close()


def reconcile_above(threshold, new_value, start, end):
    """Self-heal: collapse provably-impossible-high archive rows onto the
    trusted live lock value.

    A water meter is monotonic, so the current oracle-trusted lock is the
    highest value the register has EVER reached. Any archive row reading ABOVE
    that (beyond a small physical-lead tolerance) is therefore impossible — it's
    a drifted CNN/lock chain, not real history. This rewrites every such row in
    [start, end] to ``new_value`` (the trusted lock).

    SHARPENING (the reason this is its own function): it deliberately OVERRIDES
    rows previously marked as trusted anchors (``cnn``-high, ``oracle``, ``lock``,
    ``propagated``) — those are exactly the wrong rows that block the existing
    interpolation helpers. It NEVER touches ``manual`` rows (a human correction
    is authoritative and is left alone). Returns the number of rows rewritten.
    """
    try:
        threshold = int(threshold)
        new_value = int(new_value)
    except (TypeError, ValueError):
        return 0
    cf = new_value / COUNTS_PER_CF
    now = datetime.now().isoformat(timespec="seconds")
    c = _conn()
    try:
        cur = c.execute(
            "UPDATE archive_frame SET reading=?, reading_cf=?, "
            "confidence='reconciled', source='reconciled', updated_ts=? "
            "WHERE ts>=? AND ts<=? AND reading IS NOT NULL AND reading>? "
            "AND source!='manual'",
            (new_value, cf, now, start, end, threshold))
        c.commit()
        return int(cur.rowcount or 0)
    finally:
        c.close()


def delete_by_filename(filename):
    """Drop the row for an image the disk-cap evicted (keep DB in sync)."""
    c = _conn()
    try:
        c.execute("DELETE FROM archive_frame WHERE filename=?", (filename,))
        c.commit()
    finally:
        c.close()


def get(ts):
    c = _conn()
    try:
        r = c.execute("SELECT * FROM archive_frame WHERE ts=?", (ts,)).fetchone()
        return dict(r) if r else None
    finally:
        c.close()


def neighbor_reading(ts):
    """Most recent known reading at or before ``ts`` (context for a re-read)."""
    c = _conn()
    try:
        r = c.execute(
            "SELECT reading FROM archive_frame WHERE ts<=? AND reading IS NOT NULL"
            " ORDER BY ts DESC LIMIT 1", (ts,)).fetchone()
        return int(r["reading"]) if r and r["reading"] is not None else None
    finally:
        c.close()


def bounds():
    """(min_ts, max_ts, total_rows) across the whole archive index."""
    c = _conn()
    try:
        r = c.execute(
            "SELECT MIN(ts) a, MAX(ts) b, COUNT(*) n FROM archive_frame"
        ).fetchone()
        return (r["a"], r["b"], r["n"]) if r else (None, None, 0)
    finally:
        c.close()


def list_range(start=None, end=None, limit=200, offset=0, order="desc",
               only_unreviewed=False, include_propagated=True):
    q = "SELECT * FROM archive_frame"
    conds, args = [], []
    if start:
        conds.append("ts>=?"); args.append(start)
    if end:
        conds.append("ts<=?"); args.append(end)
    if only_unreviewed:
        conds.append("reviewed=0")
    if not include_propagated:
        conds.append("source!='propagated'")
    if conds:
        q += " WHERE " + " AND ".join(conds)
    q += " ORDER BY ts " + ("ASC" if order == "asc" else "DESC")
    q += " LIMIT ? OFFSET ?"
    args += [int(limit), int(offset)]
    c = _conn()
    try:
        return [dict(r) for r in c.execute(q, args).fetchall()]
    finally:
        c.close()


def count_range(start=None, end=None, only_unreviewed=False,
                include_propagated=True):
    q = "SELECT COUNT(*) n FROM archive_frame"
    conds, args = [], []
    if start:
        conds.append("ts>=?"); args.append(start)
    if end:
        conds.append("ts<=?"); args.append(end)
    if only_unreviewed:
        conds.append("reviewed=0")
    if not include_propagated:
        conds.append("source!='propagated'")
    if conds:
        q += " WHERE " + " AND ".join(conds)
    c = _conn()
    try:
        return int(c.execute(q, args).fetchone()["n"])
    finally:
        c.close()


def _epoch(ts):
    try:
        return datetime.fromisoformat(ts).timestamp()
    except Exception:
        return None


def usage_series(start, end, target_points=60):
    """Accurate historical consumption from the corrected per-minute readings.

    Pull every known reading in [start, end] sorted ascending, walk consecutive
    pairs, and count only MONOTONIC, PHYSICALLY-PLAUSIBLE forward deltas as
    water used (a down-step is a re-anchor/misread; an impossible spike above the
    plumbing ceiling is a garble — both are skipped, so a single bad image can't
    fabricate usage). Sum into evenly-sized time buckets.

    Returns {bucket_s, bucket_label, usage:[{t,gallons}], line:[{t,gal}],
    total_gal, points, readings}.
    """
    c = _conn()
    try:
        rows = c.execute(
            "SELECT ts, reading FROM archive_frame WHERE reading IS NOT NULL"
            " AND ts>=? AND ts<=? ORDER BY ts", (start, end)).fetchall()
    finally:
        c.close()
    e0, e1 = _epoch(start), _epoch(end)
    if e0 is None or e1 is None or e1 <= e0:
        return {"bucket_s": 0, "bucket_label": "—", "usage": [], "line": [],
                "total_gal": 0.0, "points": 0, "readings": len(rows)}
    # Bucket size auto-scales to ~target_points across the window. Allow FINE
    # (down to 5s) buckets for short spans so flow events show their true ~5s
    # detail; longer spans still coarsen to whole minutes/hours.
    raw = (e1 - e0) / max(target_points, 1)
    if raw <= 55:
        bucket_s = max(5, int(round(raw / 5)) * 5)
    else:
        bucket_s = int(round(raw / 60)) * 60
    buckets, order = {}, []
    line = []
    cum = 0.0
    prev_ep = prev_val = None
    for r in rows:
        ep = _epoch(r["ts"])
        val = int(r["reading"])
        if ep is None:
            continue
        if prev_ep is not None:
            elapsed = ep - prev_ep
            d = val - prev_val
            cap = (MAX_GPM / 60.0) * max(elapsed, 1) * COUNTS_PER_GAL * 1.5 + 200
            if 0 < d <= cap:
                gal = d / COUNTS_PER_GAL
                cum += gal
                key = int(ep // bucket_s)
                b = buckets.get(key)
                if b is None:
                    b = {"ts": r["ts"], "gal": 0.0}
                    buckets[key] = b
                    order.append(key)
                b["gal"] += gal
                line.append({"t": r["ts"], "gal": round(cum, 2)})
        prev_ep, prev_val = ep, val
    usage = [{"t": buckets[k]["ts"], "gallons": round(buckets[k]["gal"], 2),
              "start_ms": int(k * bucket_s * 1000),
              "end_ms": int((k + 1) * bucket_s * 1000)} for k in order]
    if bucket_s < 60:
        blabel = f"{bucket_s} sec"
    elif bucket_s < 3600:
        blabel = f"{bucket_s // 60} min"
    elif bucket_s < 86400:
        blabel = f"{bucket_s // 3600} hr"
    else:
        blabel = f"{bucket_s // 86400} day"
    return {"bucket_s": bucket_s, "bucket_label": blabel, "usage": usage,
            "line": line, "total_gal": round(cum, 2), "points": len(usage),
            "readings": len(rows)}


if __name__ == "__main__":
    import sys
    ensure_schema()
    if "--bounds" in sys.argv:
        print("bounds:", bounds())
    else:
        a, b, n = bounds()
        print(f"archive index: {n} rows  ({a} .. {b})  db={DB_PATH}")
