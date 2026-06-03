"""Multi-year water usage + cost simulation for the Smart Garden system.

Walks the same ET₀ water-balance model (matches irrigation.py exactly) against
Open-Meteo historical archive for each year, then runs WD119 tiered rates
against the per-period totals.
"""
import urllib.request
import json
import yaml
from pathlib import Path
from datetime import date

CONFIG_PATH = Path(__file__).parent / "server-prod" / "config.yaml"
LAT = 47.7382
LON = -121.9856
YEARS = list(range(2015, 2026))  # 2015..2025 inclusive

# WD119 tiered rates (Nov 2025 schedule — used uniformly across all years for comparability)
GAL_PER_CCF = 748.6
SUMMER_TIERS   = [(7, 4.34), (14, 5.48), (28, 7.17), (float("inf"), 8.70)]
OFF_PEAK_TIERS = [(7, 2.90), (14, 3.65), (28, 4.79), (float("inf"), 5.81)]
BASELINE_CCF_PER_BILL = 10  # modest household, irrigation is marginal on top of this

def month_to_season_idx(m):
    if m in (3, 4, 5): return 0
    if m == 6:         return 1
    if m in (7, 8):    return 2
    if m in (9, 10):   return 3
    return -1

def fetch_weather(year):
    url = ("https://archive-api.open-meteo.com/v1/archive?"
           f"latitude={LAT}&longitude={LON}"
           f"&start_date={year}-04-01&end_date={year}-10-31"
           "&daily=et0_fao_evapotranspiration,precipitation_sum"
           "&timezone=America/Los_Angeles")
    with urllib.request.urlopen(url, timeout=30) as r:
        return json.load(r)

def tiered_cost(usage_ccf, tiers):
    cost = 0.0; prev = 0.0; remaining = usage_ccf
    for upper, price in tiers:
        slab = min(remaining, upper - prev)
        if slab <= 0: break
        cost += slab * price
        remaining -= slab; prev = upper
    return cost

def marginal_cost(baseline_ccf, irrig_ccf, tiers):
    return tiered_cost(baseline_ccf + irrig_ccf, tiers) - tiered_cost(baseline_ccf, tiers)

def simulate_year(year, cfg):
    soil_cfg = cfg.get("soil", {})
    awc = soil_cfg.get("awc_in_per_in", 0.15)
    default_root = soil_cfg.get("default_root_depth_in", 6)
    default_mad_pct = soil_cfg.get("default_mad_pct", 50)
    zones = [z for z in cfg["zones"] if z.get("installed") and z.get("auto_mode", True)]

    wx = fetch_weather(year)
    dates = wx["daily"]["time"]
    et0s  = wx["daily"]["et0_fao_evapotranspiration"]
    rains = wx["daily"]["precipitation_sum"]

    state = {}
    for z in zones:
        taw = z.get("root_depth_in", default_root) * awc * 25.4
        mad = taw * (z.get("mad_pct", default_mad_pct) / 100.0)
        state[z["id"]] = {
            "taw_mm": taw, "mad_mm": mad, "balance_mm": taw,
            "gpm": z.get("est_gpm", 0),
            "precip_iph": z.get("precip_rate_iph", 1.0),
            "max_runtime_min": z.get("max_runtime_min", 24),
            "kc": z["kc"],
            "cycle_soak": z.get("cycle_soak", False),
            "cycle_run_min": z.get("cycle_run_min", 8),
            "cycle_count": z.get("cycle_count", 3),
            "events": 0, "gallons": 0.0,
        }

    total_rain_mm = 0.0
    gal_by_month = {}
    for i, day_str in enumerate(dates):
        d = date.fromisoformat(day_str)
        season_idx = month_to_season_idx(d.month)
        if season_idx < 0:
            continue
        et0 = et0s[i] or 0.0
        rain = rains[i] or 0.0
        total_rain_mm += rain
        for zid, s in state.items():
            etc = et0 * s["kc"][season_idx]
            s["balance_mm"] = max(0, min(s["balance_mm"] - etc + rain, s["taw_mm"]))
            if s["balance_mm"] <= s["mad_mm"]:
                rt = (s["cycle_run_min"] * s["cycle_count"]) if s["cycle_soak"] else s["max_runtime_min"]
                rt = min(rt, s["max_runtime_min"])
                irrig_mm = (rt / 60.0) * s["precip_iph"] * 25.4
                gallons  = s["gpm"] * rt
                s["balance_mm"] = min(s["balance_mm"] + irrig_mm, s["taw_mm"])
                s["events"]  += 1
                s["gallons"] += gallons
                mkey = f"{d.year}-{d.month:02d}"
                gal_by_month[mkey] = gal_by_month.get(mkey, 0) + gallons

    total_events  = sum(s["events"]  for s in state.values())
    total_gallons = sum(s["gallons"] for s in state.values())

    # Compute marginal cost using bi-monthly billing windows
    periods = [
        ([f"{year}-04"],                "off_peak"),
        ([f"{year}-05", f"{year}-06"],  "summer"),
        ([f"{year}-07", f"{year}-08"],  "summer"),
        ([f"{year}-09", f"{year}-10"],  "summer"),
    ]
    cost = 0.0
    for months, season in periods:
        gal = sum(gal_by_month.get(m, 0) for m in months)
        ccf = gal / GAL_PER_CCF
        tiers = SUMMER_TIERS if season == "summer" else OFF_PEAK_TIERS
        cost += marginal_cost(BASELINE_CCF_PER_BILL, ccf, tiers)

    return {
        "year": year,
        "events": total_events,
        "gallons": total_gallons,
        "rain_in": total_rain_mm / 25.4,
        "cost_wd119": cost,
        "cost_duvall": cost * 1.25,
    }

def main():
    cfg = yaml.safe_load(CONFIG_PATH.read_text())
    print(f"Simulating {len(YEARS)} years for Duvall, WA (47.74, -121.99)...")
    print("Using current config: 7 sprinkler zones, default sprinkler params.")
    print()
    results = []
    for y in YEARS:
        try:
            r = simulate_year(y, cfg)
            results.append(r)
            print(f"  {y}: {r['gallons']:>7,.0f} gal · {r['events']:>3} events · "
                  f"{r['rain_in']:>5.1f} in rain · ${r['cost_wd119']:>6.2f}")
        except Exception as e:
            print(f"  {y}: FAILED — {e}")

    print()
    print("=" * 88)
    print("MULTI-YEAR WATER USAGE + COST (Apr–Oct each year, 7 sprinkler zones)")
    print("=" * 88)
    print(f"{'Year':<6} {'Events':>7} {'Gallons':>10} {'Rain (in)':>10} "
          f"{'WD119 cost':>12} {'Duvall cost':>13}")
    print("-" * 88)
    for r in results:
        print(f"{r['year']:<6} {r['events']:>7} {r['gallons']:>10,.0f} "
              f"{r['rain_in']:>10.1f} ${r['cost_wd119']:>10,.2f} ${r['cost_duvall']:>11,.2f}")
    print("-" * 88)
    n = len(results)
    avg_g  = sum(r['gallons']     for r in results) / n
    avg_e  = sum(r['events']      for r in results) / n
    avg_r  = sum(r['rain_in']     for r in results) / n
    avg_c  = sum(r['cost_wd119']  for r in results) / n
    avg_cd = sum(r['cost_duvall'] for r in results) / n
    print(f"{'AVG':<6} {avg_e:>7.0f} {avg_g:>10,.0f} {avg_r:>10.1f} "
          f"${avg_c:>10,.2f} ${avg_cd:>11,.2f}")
    print()
    print("Driest year (most water used):")
    dry = max(results, key=lambda r: r["gallons"])
    print(f"  {dry['year']}: {dry['gallons']:,.0f} gal ({dry['rain_in']:.1f} in rain) → "
          f"${dry['cost_wd119']:,.2f} (WD119) / ${dry['cost_duvall']:,.2f} (Duvall)")
    wet = min(results, key=lambda r: r["gallons"])
    print(f"Wettest year (least water used):")
    print(f"  {wet['year']}: {wet['gallons']:,.0f} gal ({wet['rain_in']:.1f} in rain) → "
          f"${wet['cost_wd119']:,.2f} (WD119) / ${wet['cost_duvall']:,.2f} (Duvall)")
    print()
    print(f"NOTES: 'cost' = MARGINAL cost of irrigation on top of ${BASELINE_CCF_PER_BILL} CCF/bill")
    print("       baseline household use. WD119 rates as of Nov 2025 applied uniformly")
    print("       to all years (so this isolates weather variation, not rate inflation).")

if __name__ == "__main__":
    main()
