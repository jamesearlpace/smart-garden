#!/usr/bin/env python3
"""Recalibrated 2025 sprinkler cost — anchored to the REAL meter, not est_gpm.

The first backtest priced gallons off config `est_gpm`, which implies an
irrigated area far smaller than reality. The real meter proves it: the May 2026
bill shows ~2,100 cf (~15,700 gal) of irrigation in one month.

Fix: derive the true irrigated AREA from the real May meter + that month's
ET/rain, then price every month by ET-physics (net irrigation = cropET - eff.
rain) using actual archive weather. Marginal tier cost (sits on top of indoor).
"""
import json
import urllib.request

LAT, LON = 47.7382, -121.9856
GAL_PER_CF = 7.48052
RAIN_EFF = 0.65          # effective fraction of rain that counts
INDOOR_CF = 400.0        # winter bill baseline
KC = {3: 0.85, 4: 0.85, 5: 0.90, 6: 0.90, 7: 0.95, 8: 0.95, 9: 0.85}

# Real meter anchor: Apr 27 -> May 27 2026 bill = 2,500 cf whole-house.
REAL_MAY_IRRIG_CF = 2500.0 - INDOOR_CF   # ~2,100 cf irrigation

BASE_FEE = 34.26
TIERS = [(200, 0.0), (400, 5.10), (600, 6.56), (800, 8.03), (1000, 9.48), (999999, 10.97)]


def water_cost(cf):
    cost, rem, prev = BASE_FEE, max(0.0, cf), 0
    for mx, rate in TIERS:
        if rem <= 0:
            break
        used = min(rem, mx - prev)
        cost += used / 100.0 * rate
        rem -= used
        prev = mx
    return cost


def fetch(start, end):
    url = ("https://archive-api.open-meteo.com/v1/archive?"
           f"latitude={LAT}&longitude={LON}&start_date={start}&end_date={end}"
           "&daily=et0_fao_evapotranspiration,precipitation_sum"
           "&precipitation_unit=inch&timezone=America/Los_Angeles")
    with urllib.request.urlopen(url, timeout=60) as r:
        return json.load(r)


def net_irrigation_inches(wx):
    """Sum of daily max(0, cropET - effective_rain), grouped by month."""
    days = wx["daily"]["time"]
    et0 = wx["daily"]["et0_fao_evapotranspiration"]
    rain = wx["daily"]["precipitation_sum"]
    by_month = {}
    for i, d in enumerate(days):
        m = int(d[5:7])
        e = (et0[i] or 0.0) * KC.get(m, 0.85)
        r = (rain[i] or 0.0) * RAIN_EFF
        by_month[m] = by_month.get(m, 0.0) + max(0.0, e - r)
    return by_month


def main():
    # 1) Derive irrigated area from the real May 2026 meter.
    print("Deriving irrigated area from real May 2026 meter...")
    may26 = fetch("2026-04-27", "2026-05-27")
    may_net_in = net_irrigation_inches(may26).get(5, 0) + net_irrigation_inches(may26).get(4, 0)
    real_may_gal = REAL_MAY_IRRIG_CF * GAL_PER_CF
    # gallons = net_in * area_sqft * 0.623  ->  area = gal / (net_in * 0.623)
    area_sqft = real_may_gal / (may_net_in * 0.623)
    print(f"  Real May irrigation: {REAL_MAY_IRRIG_CF:.0f} cf = {real_may_gal:,.0f} gal")
    print(f"  May net ET-rain:     {may_net_in:.2f} in")
    print(f"  => Irrigated area:   {area_sqft:,.0f} sqft\n")

    # 2) Apply that area to 2025 weather, month by month.
    wx25 = fetch("2025-03-01", "2025-09-30")
    net25 = net_irrigation_inches(wx25)

    mname = {4: "Apr", 5: "May", 6: "Jun", 7: "Jul", 8: "Aug", 9: "Sep"}
    base_cost = water_cost(INDOOR_CF)
    print(f"{'Month':<6}{'Net in':>8}{'Gallons':>10}{'cf':>8}{'Sprinkler $':>13}")
    print("-" * 45)
    tot_gal = tot_cost = summer = 0.0
    for m in [4, 5, 6, 7, 8, 9]:
        net_in = net25.get(m, 0.0)
        gal = net_in * area_sqft * 0.623
        cf = gal / GAL_PER_CF
        marg = water_cost(INDOOR_CF + cf) - base_cost
        tot_gal += gal
        tot_cost += marg
        if m in (6, 7, 8):
            summer += marg
        print(f"{mname[m]:<6}{net_in:>8.2f}{gal:>10,.0f}{cf:>8.0f}{marg:>13.2f}")
    print("-" * 45)
    print(f"{'TOTAL':<6}{'':>8}{tot_gal:>10,.0f}{tot_gal/GAL_PER_CF:>8.0f}{tot_cost:>13.2f}")
    print(f"\n=== Recalibrated 2025 sprinkler water (anchored to real meter) ===")
    print(f"  Jun-Aug sprinkler water cost:  ${summer:,.0f}")
    print(f"  Full season (Apr-Sep):         ${tot_cost:,.0f}")
    print(f"  Season volume:                 {tot_gal:,.0f} gal ({tot_gal/GAL_PER_CF/100:.0f} CCF)")


if __name__ == "__main__":
    main()
