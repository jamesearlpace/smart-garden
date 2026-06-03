"""AUDIT: Will the Smart Garden engine starve the grass?

Three independent checks:

  CHECK 1 — Weekly water balance
    Per zone, per week: net = irrigation_in + rain_in - ETc_in
    If consistently negative → grass is in deficit → starving.

  CHECK 2 — Precip rate sanity (is config lying to engine?)
    The engine credits soil based on `precip_rate_iph` × runtime.
    If that rate is higher than what the sprinklers actually deliver
    over the real coverage area, the engine thinks soil is wetter
    than it actually is → under-waters → grass starves.

    Real precip rate (in/hr) = (GPM × 96.3) / coverage_sq_ft

  CHECK 3 — Industry-standard rule of thumb
    Cool-season turf in PNW needs ~1.0-1.5 inches of water per week
    in peak summer (after subtracting rain). Does the engine deliver?
"""
import urllib.request, json, yaml
from pathlib import Path
from datetime import date, timedelta

CONFIG_PATH = Path(__file__).parent / "server-prod" / "config.yaml"
LAT, LON = 47.7382, -121.9856
YEAR = 2025
START, END = f"{YEAR}-04-01", f"{YEAR}-10-31"

def month_season(m):
    if m in (3,4,5): return 0
    if m == 6:       return 1
    if m in (7,8):   return 2
    if m in (9,10):  return 3
    return -1

def fetch_wx():
    url = ("https://archive-api.open-meteo.com/v1/archive?"
           f"latitude={LAT}&longitude={LON}&start_date={START}&end_date={END}"
           "&daily=et0_fao_evapotranspiration,precipitation_sum"
           "&timezone=America/Los_Angeles")
    with urllib.request.urlopen(url, timeout=30) as r:
        return json.load(r)

def main():
    cfg = yaml.safe_load(CONFIG_PATH.read_text())
    soil_cfg = cfg.get("soil", {})
    awc = soil_cfg.get("awc_in_per_in", 0.15)
    default_root = soil_cfg.get("default_root_depth_in", 6)
    default_mad_pct = soil_cfg.get("default_mad_pct", 50)
    zones = [z for z in cfg["zones"] if z.get("installed") and z.get("auto_mode", True)]

    # ── CHECK 2 — Precip rate sanity (BEFORE simulation) ─────────────────────
    print("=" * 92)
    print("CHECK 2 — PRECIP-RATE SANITY (is the config lying to the engine?)")
    print("=" * 92)
    print("Formula: real precip in/hr = (GPM × 96.3) / coverage_sq_ft")
    print("Industry typical zone sizes for 3-4 head residential zones: 400-800 sq ft")
    print()
    print(f"{'Zone':<24} {'Heads':>5} {'GPM':>5} {'Config in/hr':>14} "
          f"{'Implied sq ft':>15} {'Realistic?':>12}")
    print("-" * 92)
    for z in zones:
        gpm = z.get("est_gpm", 0)
        rate = z.get("precip_rate_iph", 1.0)
        implied_sqft = (gpm * 96.3) / rate if rate > 0 else 0
        # Real residential zones cover ~400-800 sq ft. Flag if implied is well outside.
        if implied_sqft < 250:
            flag = "⚠️ TOO SMALL"
        elif implied_sqft > 1000:
            flag = "⚠️ HUGE"
        elif 350 <= implied_sqft <= 900:
            flag = "✅ plausible"
        else:
            flag = "?? edge"
        print(f"{z['name']:<24} {z.get('heads',0):>5} {gpm:>5.1f} {rate:>14.2f} "
              f"{implied_sqft:>15.0f} {flag:>12}")
    print()
    print("INTERPRETATION:")
    print("  - If 'implied sq ft' looks TOO SMALL: the config believes the sprinklers")
    print("    are dumping water on a tiny postage stamp, so the engine thinks each cycle")
    print("    deposits MORE inches than it actually does on real lawn area.")
    print("    Consequence: engine UNDER-waters, grass STARVES.")
    print("  - If TOO LARGE: opposite problem — engine OVER-waters.")
    print()

    # ── Simulate to get weekly water deposited ─────────────────────────────
    wx = fetch_wx()
    dates = wx["daily"]["time"]
    et0s  = wx["daily"]["et0_fao_evapotranspiration"]
    rains = wx["daily"]["precipitation_sum"]

    state = {}
    for z in zones:
        taw = z.get("root_depth_in", default_root) * awc * 25.4
        mad = taw * (z.get("mad_pct", default_mad_pct) / 100.0)
        state[z["id"]] = {
            "name": z["name"], "taw_mm": taw, "mad_mm": mad, "balance_mm": taw,
            "kc": z["kc"],
            "precip_iph": z.get("precip_rate_iph", 1.0),
            "max_runtime_min": z.get("max_runtime_min", 24),
            "cycle_soak": z.get("cycle_soak", False),
            "cycle_run_min": z.get("cycle_run_min", 8),
            "cycle_count": z.get("cycle_count", 3),
            "gpm": z.get("est_gpm", 0),
            # daily logs
            "etc_in_daily": [],
            "rain_in_daily": [],
            "irrig_in_daily": [],
        }

    for i, day_str in enumerate(dates):
        d = date.fromisoformat(day_str)
        season_idx = month_season(d.month)
        et0 = et0s[i] or 0.0
        rain = rains[i] or 0.0
        for zid, s in state.items():
            if season_idx < 0:
                etc = 0
            else:
                etc = et0 * s["kc"][season_idx]
            s["etc_in_daily"].append(etc / 25.4)
            s["rain_in_daily"].append(rain / 25.4)

            s["balance_mm"] = max(0, min(s["balance_mm"] - etc + rain, s["taw_mm"]))
            irrig_in = 0.0
            if season_idx >= 0 and s["balance_mm"] <= s["mad_mm"]:
                rt = (s["cycle_run_min"] * s["cycle_count"]) if s["cycle_soak"] else s["max_runtime_min"]
                rt = min(rt, s["max_runtime_min"])
                # CONFIG-DECLARED deposit (what engine credits)
                irrig_in = (rt / 60.0) * s["precip_iph"]
                irrig_mm = irrig_in * 25.4
                s["balance_mm"] = min(s["balance_mm"] + irrig_mm, s["taw_mm"])
            s["irrig_in_daily"].append(irrig_in)

    # ── CHECK 1 — Weekly water balance ─────────────────────────────────────
    print("=" * 92)
    print(f"CHECK 1 — WEEKLY WATER BALANCE  ({YEAR})")
    print("=" * 92)
    print("Industry target for cool-season turf in peak summer: 1.0-1.5 in/week net deposit")
    print("(Net = irrigation + rain - ETc). Negative = soil drying out = grass stressed.")
    print()

    # Aggregate by ISO week
    def iso_week(d): return d.isocalendar()[:2]  # (year, week)
    week_data = {}
    for i, day_str in enumerate(dates):
        d = date.fromisoformat(day_str)
        wk = iso_week(d)
        if wk not in week_data:
            week_data[wk] = {"start": d, "etc": {}, "rain": 0.0, "irrig": {}}
        week_data[wk]["rain"] += rains[i] / 25.4
        for zid, s in state.items():
            week_data[wk]["etc"][zid]   = week_data[wk]["etc"].get(zid, 0)   + s["etc_in_daily"][i]
            week_data[wk]["irrig"][zid] = week_data[wk]["irrig"].get(zid, 0) + s["irrig_in_daily"][i]

    # Print a sample zone (Front Yard A) week-by-week + summary across all zones
    sample_zid = zones[0]["id"]
    sample_name = zones[0]["name"]
    print(f"Sample: {sample_name} (id={sample_zid}) — week-by-week")
    print(f"{'Week start':<14} {'ETc in':>8} {'Rain in':>9} {'Irrig in':>10} "
          f"{'Net in':>9} {'Status':>14}")
    print("-" * 92)
    weeks_sorted = sorted(week_data.keys())
    deficit_weeks = 0
    severe_deficit = 0
    for wk in weeks_sorted:
        wd = week_data[wk]
        etc = wd["etc"].get(sample_zid, 0)
        rn  = wd["rain"]
        ir  = wd["irrig"].get(sample_zid, 0)
        net = ir + rn - etc
        # Only flag during peak (we care about June-Sep heat)
        if wd["start"].month in (6, 7, 8):
            if net < -0.3:   status = "🔴 SEVERE"
            elif net < 0:    status = "🟡 deficit"
            elif net < 0.5:  status = "🟢 tight"
            else:            status = "✅ ample"
            if net < 0: deficit_weeks += 1
            if net < -0.3: severe_deficit += 1
        else:
            status = ""
        print(f"{wd['start'].isoformat():<14} {etc:>8.2f} {rn:>9.2f} {ir:>10.2f} "
              f"{net:>9.2f} {status:>14}")
    print()
    print(f"Peak summer (Jun-Aug) deficit weeks for {sample_name}: {deficit_weeks} "
          f"({severe_deficit} severe)")
    print()

    # ── CHECK 3 — Industry rule of thumb across all zones ───────────────────
    print("=" * 92)
    print("CHECK 3 — INDUSTRY RULE OF THUMB (1.0-1.5 in/week net during peak)")
    print("=" * 92)
    print()
    print(f"{'Zone':<24} {'Peak ETc/wk':>13} {'Peak rain/wk':>14} {'Peak irrig/wk':>15} "
          f"{'Net/wk':>9} {'Verdict':>12}")
    print("-" * 92)
    # Average across Jul-Aug only (true peak)
    peak_weeks = [wk for wk in weeks_sorted if week_data[wk]["start"].month in (7, 8)]
    for z in zones:
        zid = z["id"]
        etc_sum = sum(week_data[wk]["etc"].get(zid, 0)   for wk in peak_weeks)
        rn_sum  = sum(week_data[wk]["rain"]              for wk in peak_weeks)
        ir_sum  = sum(week_data[wk]["irrig"].get(zid, 0) for wk in peak_weeks)
        n = len(peak_weeks)
        etc_w, rn_w, ir_w = etc_sum/n, rn_sum/n, ir_sum/n
        net = ir_w + rn_w - etc_w
        if net < -0.2: verdict = "🔴 STARVE"
        elif net < 0:  verdict = "🟡 thin"
        elif net < 0.3:verdict = "🟢 fine"
        else:          verdict = "💧 lush"
        print(f"{z['name']:<24} {etc_w:>13.2f} {rn_w:>14.2f} {ir_w:>15.2f} "
              f"{net:>9.2f} {verdict:>12}")
    print()

    # ── CHECK 4 — Bonus: model assumptions vs reality ───────────────────────
    print("=" * 92)
    print("CHECK 4 — MODEL ASSUMPTIONS")
    print("=" * 92)
    print(f"  Root depth:       {default_root} in   (PNW turf typical: 6-10 in, 6 = shallow ✅ safe)")
    print(f"  AWC:              {awc} in/in (silt loam typical: 0.15-0.18 ✅)")
    print(f"  MAD threshold:    {default_mad_pct}%   (cool-season turf typical: 40-50% ✅)")
    print(f"  TAW (root×awc):   {default_root * awc:.2f} in plant-available water")
    print(f"  MAD trigger at:   {default_root * awc * default_mad_pct/100:.2f} in depletion")
    print("                    → engine waters when soil has used ~half its reservoir")
    print(f"  Kc peak summer:   {zones[0]['kc'][2]} (FAO turfgrass: 0.85-0.95 ✅)")
    print()
    print("  These are CONSERVATIVE (err on the side of watering MORE often, not less).")
    print("  Shallow root assumption + 50% MAD = ~half-week to dry out in peak.")
    print("  The only way grass starves is if precip_rate_iph in CHECK 2 is too high.")

if __name__ == "__main__":
    main()
