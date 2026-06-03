"""Simulate 2025 summer water usage if the Smart Garden system had been running.

Mirrors irrigation.py:
  - TAW_mm = root_depth_in * awc * 25.4
  - MAD_mm = TAW_mm * mad_pct
  - Daily: balance -= et0 * kc; balance += rain_mm; balance += irrigation_mm; clamp[0, TAW]
  - Water when balance <= MAD (using PREVIOUS day's closing balance for the morning decision)
  - Event: cycle_soak 8min x 3 = 24 min; gallons = est_gpm * 24

Pulls ET0 + precip from Open-Meteo historical archive (same source as engine).
"""
import urllib.request
import json
import yaml
from pathlib import Path
from datetime import date

CONFIG_PATH = Path(__file__).parent / "server-prod" / "config.yaml"
LAT = 47.7382
LON = -121.9856
START = "2025-04-01"   # spring start (engine treats Mar-May as spring)
END   = "2025-10-31"   # fall end (Sep-Oct = fall, Nov+ = dormant)

def fetch_weather():
    url = ("https://archive-api.open-meteo.com/v1/archive?"
           f"latitude={LAT}&longitude={LON}"
           f"&start_date={START}&end_date={END}"
           "&daily=et0_fao_evapotranspiration,precipitation_sum"
           "&timezone=America/Los_Angeles")
    print(f"Fetching: {url}")
    with urllib.request.urlopen(url, timeout=30) as r:
        return json.load(r)

def month_to_season_idx(month: int) -> int:
    # 0=spring(3-5), 1=early_summer(6), 2=peak(7-8), 3=fall(9-10), -1=dormant
    if month in (3, 4, 5): return 0
    if month == 6:         return 1
    if month in (7, 8):    return 2
    if month in (9, 10):   return 3
    return -1

def main():
    cfg = yaml.safe_load(CONFIG_PATH.read_text())
    soil_cfg = cfg.get("soil", {})
    awc = soil_cfg.get("awc_in_per_in", 0.15)
    default_root = soil_cfg.get("default_root_depth_in", 6)
    default_mad_pct = soil_cfg.get("default_mad_pct", 50)

    # Only installed + auto_mode sprinkler zones (drip zones 8&9 are manual)
    zones = [z for z in cfg["zones"]
             if z.get("installed") and z.get("auto_mode", True)]

    print(f"Simulating {len(zones)} zones: {[z['name'] for z in zones]}")

    wx = fetch_weather()
    dates = wx["daily"]["time"]
    et0s  = wx["daily"]["et0_fao_evapotranspiration"]   # mm
    rains = wx["daily"]["precipitation_sum"]            # mm
    print(f"Got {len(dates)} days of weather: {dates[0]} to {dates[-1]}")

    # Per-zone state: balance starts at TAW (field capacity), as the engine does
    state = {}
    for z in zones:
        root = z.get("root_depth_in", default_root)
        taw  = root * awc * 25.4
        mad  = taw * (z.get("mad_pct", default_mad_pct) / 100.0)
        state[z["id"]] = {
            "name": z["name"],
            "taw_mm": taw,
            "mad_mm": mad,
            "balance_mm": taw,        # start at field capacity
            "gpm": z.get("est_gpm", 0),
            "precip_iph": z.get("precip_rate_iph", 1.0),
            "max_runtime_min": z.get("max_runtime_min", 24),
            "kc": z["kc"],
            "cycle_soak": z.get("cycle_soak", False),
            "cycle_run_min": z.get("cycle_run_min", 8),
            "cycle_count": z.get("cycle_count", 3),
            "events": 0,
            "gallons": 0.0,
            "events_by_month": {},
            "gallons_by_month": {},
        }

    total_rain_mm = 0.0
    days_skipped_dormant = 0

    for i, day_str in enumerate(dates):
        d = date.fromisoformat(day_str)
        season_idx = month_to_season_idx(d.month)
        if season_idx < 0:
            days_skipped_dormant += 1
            continue
        et0 = et0s[i] or 0.0
        rain = rains[i] or 0.0
        total_rain_mm += rain

        for zid, s in state.items():
            kc = s["kc"][season_idx]
            etc = et0 * kc

            # Apply yesterday's net: ET demand, rain credit
            s["balance_mm"] = s["balance_mm"] - etc + rain
            s["balance_mm"] = max(0, min(s["balance_mm"], s["taw_mm"]))

            # Morning decision: water if balance <= MAD
            if s["balance_mm"] <= s["mad_mm"]:
                # Standard event: cycle 8 min x 3 = 24 min (or max_runtime_min)
                if s["cycle_soak"]:
                    runtime_min = s["cycle_run_min"] * s["cycle_count"]
                else:
                    runtime_min = s["max_runtime_min"]
                runtime_min = min(runtime_min, s["max_runtime_min"])
                irrig_mm = (runtime_min / 60.0) * s["precip_iph"] * 25.4
                gallons  = s["gpm"] * runtime_min

                s["balance_mm"] = min(s["balance_mm"] + irrig_mm, s["taw_mm"])
                s["events"]  += 1
                s["gallons"] += gallons
                mkey = f"{d.year}-{d.month:02d}"
                s["events_by_month"][mkey]  = s["events_by_month"].get(mkey, 0) + 1
                s["gallons_by_month"][mkey] = s["gallons_by_month"].get(mkey, 0) + gallons

    # ── REPORT ─────────────────────────────────────────────────
    print()
    print("=" * 78)
    print(f"SIMULATED 2025 SUMMER WATER USAGE — {START} to {END}")
    print(f"Location: lat={LAT}, lon={LON} (Duvall, WA)")
    print(f"Source:   Open-Meteo historical archive (ERA5/ECMWF)")
    print("=" * 78)
    print(f"Active growing days:  {len(dates) - days_skipped_dormant}")
    print(f"Dormant days (skipped): {days_skipped_dormant}")
    print(f"Total rainfall:       {total_rain_mm:.0f} mm  ({total_rain_mm/25.4:.1f} in)")
    print()
    print(f"{'Zone':<22} {'Events':>7} {'Gallons':>10} {'Avg gal/event':>14}")
    print("-" * 78)
    total_events  = 0
    total_gallons = 0.0
    for zid, s in state.items():
        avg = s["gallons"] / s["events"] if s["events"] else 0
        print(f"{s['name']:<22} {s['events']:>7} {s['gallons']:>10,.0f} {avg:>14,.0f}")
        total_events  += s["events"]
        total_gallons += s["gallons"]
    print("-" * 78)
    print(f"{'TOTAL':<22} {total_events:>7} {total_gallons:>10,.0f}")
    print()

    # Monthly breakdown
    months = sorted({m for s in state.values() for m in s["gallons_by_month"]})
    print(f"{'Month':<10} {'Events':>7} {'Gallons':>10}")
    print("-" * 35)
    for m in months:
        ev  = sum(s["events_by_month"].get(m, 0)  for s in state.values())
        gal = sum(s["gallons_by_month"].get(m, 0) for s in state.values())
        print(f"{m:<10} {ev:>7} {gal:>10,.0f}")
    print()

    # Headline
    print("=" * 78)
    print(f"HEADLINE: ~{total_gallons:,.0f} gallons across 7 sprinkler zones")
    print(f"          = ~{total_gallons/748:,.0f} CCF (1 CCF = 748 gal, water bill unit)")
    print("=" * 78)

if __name__ == "__main__":
    main()
