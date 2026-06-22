#!/usr/bin/env python3
"""Read-only accuracy audit for the water-meter lock.

WHY THIS EXISTS: the oracle now drives the displayed reading, so the oracle
cannot grade itself — "the oracle agrees with the lock" is circular when the
oracle SET the lock. The only non-circular truth available (short of reading
the meter by hand) is two independent models reading the SAME frame UNBIASED
(hint=None, so the lock can't bias them) and agreeing. This script samples the
latest frame on a timer and records, read-only:

  * lock_error  — how far the live lock is from that independent truth
  * lock_age_s  — staleness (is the display fresh or frozen?)
  * lock_delta  — change since last sample (negative = a self-correction DOWN)
  * agree       — did the two models agree on the whole cubic feet?

It NEVER writes the lock or touches cam/oracle state, and uses its OWN sqlite
DB (meter_audit.db) so it never contends with the live database.

Usage:
  python meter_audit.py            # one sample (run by the systemd timer)
  python meter_audit.py --report   # summarise the last 24h
  python meter_audit.py --report --hours=48
"""
import glob
import io
import json
import os
import sqlite3
import sys
import time
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import vision_oracle as vo  # noqa: E402  (reads the key from cam-env itself)

FRAME_DIR = os.environ.get("METER_FRAME_DIR", "/tmp/meter-frames")
STATE_PATH = os.environ.get("METER_STATE_PATH", "/tmp/meter_state.json")
DB_PATH = os.environ.get("METER_AUDIT_DB", os.path.join(HERE, "meter_audit.db"))
HEARTBEAT_MODEL = os.environ.get("ORACLE_MODEL", "gpt-4o-mini")
AUTHORITY_MODEL = os.environ.get("METER_ORACLE_AUTHORITY_MODEL", "gpt-4o")
# Mean luma below this = a dark/night frame the meter can't be read on; skip the
# (paid) model calls and just log staleness so we don't burn cost on black frames.
DARK_THRESHOLD = float(os.environ.get("METER_AUDIT_DARK", "35"))


def _conn():
    c = sqlite3.connect(DB_PATH, timeout=15)
    c.execute("PRAGMA journal_mode=WAL")
    return c


def ensure_schema():
    c = _conn()
    try:
        c.execute(
            "CREATE TABLE IF NOT EXISTS audit_eval ("
            " id INTEGER PRIMARY KEY AUTOINCREMENT,"
            " ts TEXT NOT NULL,"
            " lock_val INTEGER,"      # current displayed lock
            " lock_age_s REAL,"       # staleness: now - lock_ts
            " truth INTEGER,"         # independent ground truth (gpt-4o, unbiased)
            " mini_val INTEGER,"      # gpt-4o-mini unbiased read
            " gpt4o_val INTEGER,"     # gpt-4o unbiased read
            " agree INTEGER,"         # 1 if the two agree on whole cubic feet
            " lock_error INTEGER,"    # lock - truth (signed counts)
            " lock_delta INTEGER,"    # lock - previous lock (neg = down-correction)
            " mini_conf TEXT,"
            " gpt4o_conf TEXT,"
            " note TEXT"
            ")"
        )
        c.execute("CREATE INDEX IF NOT EXISTS ix_audit_ts ON audit_eval(ts)")
        c.commit()
    finally:
        c.close()


def _read_state():
    try:
        with open(STATE_PATH) as f:
            s = json.load(f)
        return int(s.get("last_good")), float(s.get("lock_ts") or 0)
    except Exception:
        return None, 0.0


def _latest_frame():
    frames = glob.glob(os.path.join(FRAME_DIR, "*.jpg"))
    return max(frames, key=os.path.getmtime) if frames else None


def _brightness(jpeg):
    try:
        from PIL import Image
        hist = Image.open(io.BytesIO(jpeg)).convert("L").histogram()
        total = sum(hist) or 1
        return sum(i * h for i, h in enumerate(hist)) / total
    except Exception:
        return 255.0


def run_once():
    ensure_schema()
    now = time.time()
    lock_val, lock_ts = _read_state()
    lock_age = (now - lock_ts) if lock_ts else None
    frame = _latest_frame()
    mini_val = g4_val = truth = agree = lock_error = None
    mini_conf = g4_conf = None
    note = ""
    if frame is None:
        note = "no-frame"
    else:
        data = open(frame, "rb").read()
        if _brightness(data) < DARK_THRESHOLD:
            note = "dark-skip"
        else:
            rm = vo.read_meter(data, rotate180=True, hint=None,
                               model=HEARTBEAT_MODEL)
            rg = vo.read_meter(data, rotate180=True, hint=None,
                               model=AUTHORITY_MODEL)
            mini_val, mini_conf = rm.get("value"), rm.get("confidence")
            g4_val, g4_conf = rg.get("value"), rg.get("confidence")
            if g4_val is not None and rg.get("ok"):
                truth = g4_val            # gpt-4o is the better reader
            if mini_val is not None and g4_val is not None:
                agree = 1 if (mini_val // 1000) == (g4_val // 1000) else 0
            if truth is not None and lock_val is not None:
                lock_error = lock_val - truth

    c = _conn()
    try:
        prev = c.execute("SELECT lock_val FROM audit_eval WHERE lock_val IS NOT "
                         "NULL ORDER BY id DESC LIMIT 1").fetchone()
        lock_delta = (lock_val - prev[0]) if (prev and lock_val is not None) else None
        c.execute(
            "INSERT INTO audit_eval(ts,lock_val,lock_age_s,truth,mini_val,"
            "gpt4o_val,agree,lock_error,lock_delta,mini_conf,gpt4o_conf,note) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (datetime.now().isoformat(timespec="seconds"), lock_val, lock_age,
             truth, mini_val, g4_val, agree, lock_error, lock_delta,
             mini_conf, g4_conf, note))
        c.commit()
    finally:
        c.close()
    print(f"[audit] lock={lock_val} age={lock_age and round(lock_age)}s "
          f"truth={truth} mini={mini_val} gpt4o={g4_val} agree={agree} "
          f"err={lock_error} delta={lock_delta} {note}".rstrip())


def _median(xs):
    s = sorted(xs)
    return s[len(s) // 2] if s else None


def report(hours=24):
    ensure_schema()
    since = datetime.fromtimestamp(time.time() - hours * 3600).isoformat()
    c = _conn()
    rows = c.execute(
        "SELECT ts,lock_val,lock_age_s,truth,mini_val,gpt4o_val,agree,"
        "lock_error,lock_delta,note FROM audit_eval WHERE ts>=? ORDER BY id",
        (since,)).fetchall()
    c.close()
    graded = [r for r in rows if r[7] is not None]
    errs = [abs(r[7]) for r in graded]
    ages = [r[2] for r in rows if r[2] is not None]
    agrees = [r[6] for r in rows if r[6] is not None]
    downs = [r[8] for r in graded if r[8] is not None and r[8] < 0]
    print(f"=== Meter lock audit — last {hours}h ===")
    print(f"samples: {len(rows)}   graded (error vs independent truth): {len(graded)}")
    if errs:
        pct = lambda k: 100 * sum(1 for e in errs if e <= k) / len(errs)
        print(f"lock error |counts|: median={_median(errs)}  max={max(errs)}  "
              f"| within 10={pct(10):.0f}%  within 100={pct(100):.0f}%  "
              f"whole-cf exact (<1000)={pct(1000):.0f}%")
    if ages:
        print(f"staleness (s): median={_median(ages):.0f}  max={max(ages):.0f}")
    if agrees:
        print(f"two-model agreement (whole-cf): "
              f"{100*sum(agrees)/len(agrees):.0f}%  ({len(agrees)} pairs)")
    print(f"down-corrections observed: {len(downs)}"
          + (f"  (recovered {-sum(downs)} counts total)" if downs else ""))
    skips = sum(1 for r in rows if r[9] == "dark-skip")
    if skips:
        print(f"dark frames skipped: {skips}")


if __name__ == "__main__":
    if "--report" in sys.argv:
        h = 24
        for a in sys.argv:
            if a.startswith("--hours="):
                h = int(a.split("=", 1)[1])
        report(h)
    else:
        run_once()
