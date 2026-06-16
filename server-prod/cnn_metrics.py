"""CNN metrics — the data layer for "is the model improving?" reporting.

Every time the oracle reads a frame it is, in effect, grading the CNN: the CNN
said X, the trusted oracle said Y. Logging those comparisons over time gives a
LIVE CNN-accuracy time-series per model version — the core improvement metric —
without any extra cost (the oracle was already reading those frames).

Also logs the daily reader split (how many frames the CNN handled for free vs
fell back to oracle) so the cost ramp-down is visible.

Isolated module, owns its own tables, never touches cam/oracle state.

Tables:
  cnn_eval   — one row per oracle verification (the ground-truth comparison)
  cnn_daily  — daily rollup (frames, cnn_used, fellback, oracle_calls, acc)
"""
import logging
from datetime import datetime

import database as db

log = logging.getLogger("smart-garden.cnn_metrics")


def ensure_schema():
    conn = db.get_conn()
    try:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS cnn_eval ("
            "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "  ts TEXT NOT NULL,"                 # ISO local
            "  model_version TEXT,"               # which CNN produced cnn_value
            "  cnn_value TEXT,"                   # CNN's 9-digit read (or '')
            "  cnn_min_conf REAL,"                # CNN's min per-digit confidence
            "  oracle_value TEXT NOT NULL,"       # trusted reader's 9-digit read
            "  cnn_correct INTEGER,"              # 1/0/NULL: cnn_value==oracle_value
            "  reader TEXT"                        # which reader was used live (cnn/rapidocr)
            ")"
        )
        conn.execute("CREATE INDEX IF NOT EXISTS ix_cnn_eval_ts ON cnn_eval(ts)")
        conn.execute(
            "CREATE TABLE IF NOT EXISTS cnn_daily ("
            "  date TEXT PRIMARY KEY,"            # YYYY-MM-DD local
            "  frames INTEGER DEFAULT 0,"        # total frames processed
            "  cnn_used INTEGER DEFAULT 0,"      # CNN confident -> free path
            "  cnn_fellback INTEGER DEFAULT 0,"  # CNN unsure -> fallback
            "  oracle_calls INTEGER DEFAULT 0,"  # paid oracle reads
            "  evals INTEGER DEFAULT 0,"         # oracle-vs-cnn comparisons
            "  cnn_correct INTEGER DEFAULT 0,"   # of those, CNN was right
            "  model_version TEXT"
            ")"
        )
        conn.commit()
    finally:
        conn.close()


def log_eval(cnn_value, cnn_min_conf, oracle_value, model_version, reader):
    """Record one oracle verification = one CNN accuracy sample."""
    if not oracle_value:
        return
    cnn_value = str(cnn_value or "")
    correct = None
    if len(cnn_value) == 9 and cnn_value.isdigit():
        correct = 1 if cnn_value == str(oracle_value) else 0
    now = datetime.now()
    today = now.strftime("%Y-%m-%d")
    conn = db.get_conn()
    try:
        conn.execute(
            "INSERT INTO cnn_eval (ts, model_version, cnn_value, cnn_min_conf, "
            "oracle_value, cnn_correct, reader) VALUES (?,?,?,?,?,?,?)",
            (now.isoformat(), model_version, cnn_value, cnn_min_conf,
             str(oracle_value), correct, reader))
        # roll into daily
        conn.execute(
            "INSERT INTO cnn_daily (date, evals, cnn_correct, model_version) "
            "VALUES (?, 1, ?, ?) ON CONFLICT(date) DO UPDATE SET "
            "evals = evals + 1, cnn_correct = cnn_correct + ?, "
            "model_version = excluded.model_version",
            (today, correct or 0, model_version, correct or 0))
        conn.commit()
    except Exception as e:
        log.debug("log_eval failed: %s", e)
    finally:
        conn.close()


def bump_daily(reader, used_cnn, fellback, oracle_call=False):
    """Increment the daily reader-split counters (called per processed frame)."""
    today = datetime.now().strftime("%Y-%m-%d")
    conn = db.get_conn()
    try:
        conn.execute(
            "INSERT INTO cnn_daily (date, frames, cnn_used, cnn_fellback, oracle_calls) "
            "VALUES (?, 1, ?, ?, ?) ON CONFLICT(date) DO UPDATE SET "
            "frames = frames + 1, cnn_used = cnn_used + ?, "
            "cnn_fellback = cnn_fellback + ?, oracle_calls = oracle_calls + ?",
            (today, int(used_cnn), int(fellback), int(oracle_call),
             int(used_cnn), int(fellback), int(oracle_call)))
        conn.commit()
    except Exception as e:
        log.debug("bump_daily failed: %s", e)
    finally:
        conn.close()


def report(days=30):
    """Return the improvement report: daily rows + overall accuracy by version."""
    conn = db.get_conn()
    try:
        daily = [dict(r) for r in conn.execute(
            "SELECT * FROM cnn_daily ORDER BY date DESC LIMIT ?", (days,))]
        by_ver = [dict(r) for r in conn.execute(
            "SELECT model_version, COUNT(*) AS evals, "
            "SUM(cnn_correct) AS correct, "
            "ROUND(100.0*SUM(cnn_correct)/COUNT(*),1) AS acc_pct "
            "FROM cnn_eval WHERE cnn_correct IS NOT NULL "
            "GROUP BY model_version ORDER BY model_version")]
        recent = [dict(r) for r in conn.execute(
            "SELECT ts, model_version, cnn_value, oracle_value, cnn_correct, "
            "cnn_min_conf FROM cnn_eval ORDER BY id DESC LIMIT 40")]
        return {"daily": daily, "by_version": by_ver, "recent": recent}
    finally:
        conn.close()
