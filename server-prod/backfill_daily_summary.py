"""One-shot backfill for daily_summary. Idempotent — safe to re-run.

Usage:
    python backfill_daily_summary.py [start_date]

Iterates every date that has watering, skip, or soil-balance data and
upserts a daily_summary row for it via BillingCalculator.update_daily_summary().
"""
import sys
import yaml

import database as db
from billing import BillingCalculator


def main():
    start_date = sys.argv[1] if len(sys.argv) > 1 else None

    with open("config.yaml") as f:
        config = yaml.safe_load(f)
    calc = BillingCalculator(config)

    conn = db.get_conn()
    try:
        rows = conn.execute(
            "SELECT d FROM ("
            "  SELECT DISTINCT DATE(start_ts) AS d FROM watering_event "
            "    WHERE end_ts IS NOT NULL "
            "  UNION SELECT DISTINCT DATE(ts) AS d FROM skip_event "
            "  UNION SELECT DISTINCT date AS d FROM soil_balance WHERE zone_id = 0 "
            ") WHERE d IS NOT NULL "
            + (f"AND d >= '{start_date}' " if start_date else "")
            + "ORDER BY d"
        ).fetchall()
    finally:
        conn.close()

    dates = [r["d"] for r in rows]
    if not dates:
        print("No dates found.")
        return

    print(f"Backfilling {len(dates)} days: {dates[0]} → {dates[-1]}")
    for d in dates:
        r = calc.update_daily_summary(d)
        print(f"  {d}: {r['total_gallons']:6.1f} gal  ${r['cost']:5.2f}  "
              f"(saved {r['gallons_saved']:5.1f} gal / ${r['cost_avoided']:4.2f})  "
              f"et0={r['et0_mm']}  rain={r['rain_mm']}  T={r['avg_temp_f']}")
    print(f"\nDone — {len(dates)} rows.")


if __name__ == "__main__":
    main()
