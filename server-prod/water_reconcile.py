"""Independent meter-reading sanity check (the engine-vs-meter framework).

The irrigation engine logs which zones ran for how long (zone x runtime x gpm),
completely independently of the camera. So the meter MUST account for at least
that much water. Where the two disagree, a bug is hiding that no camera-only
check can catch — because a frozen/garbled reading is perfectly self-consistent:

  * meter << engine        -> the reading FROZE (sprinklers ran, meter missed it)
  * meter >> engine, no run -> household use, a leak, or a catch-up dump

This is the strongest single bug-catcher for the meter pipeline: it uses an
external signal the OCR does not control.
"""
import datetime as _dt

import database
import meter_ledger

NTFY_URL = "https://ntfy.sh/smart-garden-james"
FREEZE_MIN_EST_GAL = 50.0    # only judge days where sprinklers actually ran
FREEZE_RATIO = 0.5           # meter < 50% of the engine estimate = a freeze
HIGH_NORUN_GAL = 800.0       # no sprinklers but this much moved = worth a look
LOW_LEDGER_ROWS = 100        # very sparse for a canonical daily ledger


def _engine_by_day(conn):
    """date -> (estimated sprinkler gallons, # of auto runs)."""
    rows = conn.execute(
        "SELECT date(start_ts) d, SUM(est_gallons) est, COUNT(*) n "
        "FROM watering_event WHERE trigger_reason LIKE 'soil_dry%' "
        "GROUP BY date(start_ts)").fetchall()
    return {r["d"]: (r["est"] or 0.0, r["n"]) for r in rows}


def _verdict(est, meter, samples):
    if est > FREEZE_MIN_EST_GAL and meter < est * FREEZE_RATIO:
        return "freeze", (f"sprinklers ran ~{est:.0f} gal but the meter only "
                          f"moved {meter:.0f} gal — reading may have frozen")
    if est == 0 and meter == 0:
        return "idle", "no sprinklers and no meter movement (away or static)"
    if est == 0 and meter > HIGH_NORUN_GAL:
        return "high", (f"no sprinklers but the meter moved {meter:.0f} gal "
                        f"(heavy household use, a leak, or a catch-up dump)")
    if samples < LOW_LEDGER_ROWS:
        return "low_data", f"only {samples} ledger rows that day (capture gaps?)"
    return "ok", ""


def daily_table(days=14):
    """Per-day engine-estimated gallons vs the meter's actual movement."""
    conn = database.get_conn()
    try:
        eng = _engine_by_day(conn)
        out = []
        rows = meter_ledger.daily_usage_rows(days)
        for r in rows:
            day = r["date"]
            meter = round(r["gallons"] or 0.0, 1)
            samples = int(r["n_readings"] or 0)
            est, nruns = eng.get(day, (0.0, 0))
            est = round(est, 1)
            verdict, note = _verdict(est, meter, samples)
            out.append({"date": day, "engine_gal": est, "meter_gal": meter,
                        "runs": nruns, "diff_gal": round(meter - est, 1),
                        "samples": samples,
                        "image_backed": int(r["n_image_backed"] or 0),
                        "fresh_reads": int(r["n_fresh_reads"] or 0),
                        "method": r["method"],
                        "verdict": verdict, "note": note})
        return out
    finally:
        conn.close()


def reconcile_yesterday():
    y = (_dt.date.today() - _dt.timedelta(days=1)).isoformat()
    for row in daily_table(days=4):
        if row["date"] == y:
            return row
    return None


def check_and_alert():
    """Daily job: reconcile yesterday; push an ntfy alert if a freeze is seen."""
    row = reconcile_yesterday()
    if not row:
        return {"ok": True, "skipped": "no data for yesterday"}
    if row["verdict"] == "freeze":
        _notify("\U0001F4A7 Meter freeze suspected",
                f"{row['date']}: irrigation ran ~{row['engine_gal']:.0f} gal but "
                f"the meter only moved {row['meter_gal']:.0f} gal. The reading "
                f"may have frozen — check the /water-usage meter chart.")
    return {"ok": True, "row": row}


def _notify(title, message):
    try:
        import requests
        requests.post(NTFY_URL, data=message.encode("utf-8"),
                      headers={"Title": title.encode("utf-8"),
                               "Priority": "high", "Tags": "droplet"},
                      timeout=10)
    except Exception:
        pass
