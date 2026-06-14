#!/usr/bin/env python3
"""Backtest: how many gallons would the CURRENT watering process have used in 2025?

Replicates the moisture_sim.html FAO-56 checkbook backtest (the /moisture-sim
page with year=2025) server-side, then totals gallons per zone and per month.

Model (mirrors moisture_sim.html):
  bucketIn   = rootDepth(month) * awc   (awc = 0.15)
  ET drain   = et0 * kc(month) / bucketIn * 100   (% of bucket per day)
  rain credit= precip * 0.65 / bucketIn * 100      (effective rain)
  water when daily-min moisture < madPct (50%), 4-7AM window
  waterTarget= min(100, madPct + 20)
  minutes    = inches_needed / precipRate * 60, capped at max_runtime_min
  gallons    = est_gpm * minutes

Weather: Open-Meteo ERA5 archive, same lat/lon and date span as the page
(Mar 1 - Sep 30, 2025).
"""
import json
import urllib.request
from datetime import date, timedelta

LAT, LON = 47.7382, -121.9856
YEAR = 2025
AWC = 0.15

# Zones from config.yaml that water automatically.
# (id, name, precip_rate_iph, est_gpm, max_runtime_min, mad_pct, kc[spring,earlysummer,peak,fall])
ZONES = [
    (0, "Front Yard A",        1.5, 4.0, 24, 50, [0.85, 0.90, 0.95, 0.85]),
    (1, "Front Yard B",        1.5, 4.0, 24, 50, [0.85, 0.90, 0.95, 0.85]),
    (2, "Enclosed Backyard A", 1.3, 4.0, 24, 50, [0.85, 0.90, 0.95, 0.85]),
    (3, "Enclosed Backyard B", 1.3, 4.0, 24, 50, [0.85, 0.90, 0.95, 0.85]),
    (4, "Southeast",           1.3, 4.0, 24, 50, [0.85, 0.90, 0.95, 0.85]),
    (5, "South",               1.0, 3.0, 24, 50, [0.85, 0.90, 0.95, 0.85]),
    (6, "Southwest",           1.3, 4.0, 24, 50, [0.85, 0.90, 0.95, 0.85]),
    (8, "Grapes (drip)",       0.4, 0.5, 60, 60, [0.70, 0.90, 1.15, 0.80]),
]

ROOT_DEPTH_SCHEDULE = {3: 4, 4: 4, 5: 5, 6: 6, 7: 8, 8: 8, 9: 6, 10: 5}
# Drip uses deeper roots
ROOT_DEPTH_DRIP = {3: 8, 4: 8, 5: 10, 6: 11, 7: 12, 8: 12, 9: 11, 10: 10}

# Skip rules from config.yaml
SKIP_RAIN_IN = 8.0 / 25.4      # recent_rain_mm 8mm -> inches
SKIP_WIND_MPH = 15.0


def season_index(month):
    if 3 <= month <= 5:
        return 0
    if month == 6:
        return 1
    if 7 <= month <= 8:
        return 2
    if 9 <= month <= 10:
        return 3
    return -1


def fetch_weather():
    url = (
        "https://archive-api.open-meteo.com/v1/archive?"
        f"latitude={LAT}&longitude={LON}"
        f"&start_date={YEAR}-03-01&end_date={YEAR}-09-30"
        "&daily=et0_fao_evapotranspiration,precipitation_sum,"
        "temperature_2m_max,temperature_2m_min,wind_speed_10m_max"
        "&temperature_unit=fahrenheit&wind_speed_unit=mph"
        "&precipitation_unit=inch&timezone=America/Los_Angeles"
    )
    with urllib.request.urlopen(url, timeout=60) as r:
        return json.load(r)


def simulate_zone(zone, wx):
    zid, name, precip_rate, est_gpm, max_rt, mad, kc = zone
    is_drip = "drip" in name.lower()
    days = wx["daily"]["time"]
    et0 = wx["daily"]["et0_fao_evapotranspiration"]
    rain = wx["daily"]["precipitation_sum"]
    wind = wx["daily"]["wind_speed_10m_max"]

    moisture = 80.0  # start near field capacity
    monthly_gal = {}
    monthly_min = {}
    monthly_events = {}
    total_gal = 0.0
    total_events = 0

    for i, d in enumerate(days):
        month = int(d[5:7])
        sidx = season_index(month)
        if sidx < 0:
            continue
        rd = (ROOT_DEPTH_DRIP if is_drip else ROOT_DEPTH_SCHEDULE).get(month, 6)
        bucket_in = rd * AWC
        kc_m = kc[sidx]

        e = et0[i] if et0[i] is not None else 0.0
        p = rain[i] if rain[i] is not None else 0.0
        w = wind[i] if wind[i] is not None else 0.0

        # ET drain
        moisture -= (e * kc_m / bucket_in) * 100.0
        # Rain credit (effective 65%)
        moisture += (p * 0.65 / bucket_in) * 100.0
        moisture = max(0.0, min(100.0, moisture))

        # Watering decision (early AM). Skip on significant rain or high wind.
        skip = (p >= SKIP_RAIN_IN) or (w >= SKIP_WIND_MPH)
        if (not skip) and moisture < mad:
            target = min(100.0, mad + 20.0)
            need_pct = target - moisture
            need_in = need_pct / 100.0 * bucket_in
            minutes = need_in / precip_rate * 60.0
            minutes = min(minutes, max_rt)
            applied_in = precip_rate * minutes / 60.0
            moisture += applied_in / bucket_in * 100.0
            moisture = min(100.0, moisture)
            gal = est_gpm * minutes
            total_gal += gal
            total_events += 1
            monthly_gal[month] = monthly_gal.get(month, 0.0) + gal
            monthly_min[month] = monthly_min.get(month, 0.0) + minutes
            monthly_events[month] = monthly_events.get(month, 0) + 1

    return {
        "id": zid, "name": name, "total_gal": total_gal,
        "events": total_events, "monthly_gal": monthly_gal,
        "monthly_events": monthly_events,
    }


def main():
    print(f"Fetching {YEAR} ERA5 archive weather for Duvall ({LAT},{LON})...")
    wx = fetch_weather()
    n = len(wx["daily"]["time"])
    print(f"Got {n} days ({wx['daily']['time'][0]} to {wx['daily']['time'][-1]})\n")

    results = [simulate_zone(z, wx) for z in ZONES]

    months = [4, 5, 6, 7, 8, 9]
    mname = {4: "Apr", 5: "May", 6: "Jun", 7: "Jul", 8: "Aug", 9: "Sep"}

    # Per-zone table
    header = f"{'Zone':<22}" + "".join(f"{mname[m]:>8}" for m in months) + f"{'TOTAL':>10}"
    print(header)
    print("-" * len(header))
    month_totals = {m: 0.0 for m in months}
    grand = 0.0
    for r in results:
        row = f"{r['name']:<22}"
        for m in months:
            g = r["monthly_gal"].get(m, 0.0)
            month_totals[m] += g
            row += f"{g:>8.0f}"
        row += f"{r['total_gal']:>10.0f}"
        grand += r["total_gal"]
        print(row)
    print("-" * len(header))
    foot = f"{'ALL ZONES (gal)':<22}"
    for m in months:
        foot += f"{month_totals[m]:>8.0f}"
    foot += f"{grand:>10.0f}"
    print(foot)

    # Summer focus
    summer = month_totals[6] + month_totals[7] + month_totals[8]
    print("\n=== Summary (irrigation only, current process applied to 2025 weather) ===")
    for m in months:
        print(f"  {mname[m]} 2025: {month_totals[m]:>8.0f} gal  ({month_totals[m]/100:.1f} units / {month_totals[m]/748:.1f} CCF)")
    print(f"\n  Jun-Aug 2025 total: {summer:>8.0f} gal  ({summer/748:.1f} CCF)")
    print(f"  Mar-Sep season:     {grand:>8.0f} gal  ({grand/748:.1f} CCF)")
    # Add indoor baseline for context
    print(f"\n  (Indoor baseline ~400 cf/mo = ~3,000 gal/mo is separate, not included above.)")


if __name__ == "__main__":
    main()
