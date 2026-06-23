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
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("METER_ARCHIVE_DB", os.path.join(HERE, "meter_archive.db"))

COUNTS_PER_CF = 1000.0
GAL_PER_CF = 7.48052
COUNTS_PER_GAL = COUNTS_PER_CF / GAL_PER_CF       # ~133.69
# Absolute plumbing flow ceiling (gal/min) used to reject garbled jumps when
# computing consumption — a single bad reading can't manufacture impossible use.
MAX_GPM = float(os.environ.get("METER_MAX_GPM", "20"))


def _conn():
    c = sqlite3.connect(DB_PATH, timeout=15)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    return c


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
        c.commit()
    finally:
        c.close()


def record(ts, filename, reading=None, confidence="lock", source="lock"):
    """Index a newly archived frame. INSERT OR IGNORE so a re-archive never
    clobbers a reading a human already refined for the same timestamp."""
    cf = (reading / COUNTS_PER_CF) if reading is not None else None
    c = _conn()
    try:
        c.execute(
            "INSERT OR IGNORE INTO archive_frame"
            "(ts,filename,reading,reading_cf,confidence,source,reviewed,updated_ts)"
            " VALUES(?,?,?,?,?,?,0,?)",
            (ts, filename, reading, cf, confidence, source,
             datetime.now().isoformat(timespec="seconds")))
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
        c.commit()
        return cur.rowcount > 0
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
               only_unreviewed=False):
    q = "SELECT * FROM archive_frame"
    conds, args = [], []
    if start:
        conds.append("ts>=?"); args.append(start)
    if end:
        conds.append("ts<=?"); args.append(end)
    if only_unreviewed:
        conds.append("reviewed=0")
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


def count_range(start=None, end=None, only_unreviewed=False):
    q = "SELECT COUNT(*) n FROM archive_frame"
    conds, args = [], []
    if start:
        conds.append("ts>=?"); args.append(start)
    if end:
        conds.append("ts<=?"); args.append(end)
    if only_unreviewed:
        conds.append("reviewed=0")
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
    bucket_s = max(60, int(round((e1 - e0) / max(target_points, 1) / 60)) * 60)
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
    if bucket_s < 3600:
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
