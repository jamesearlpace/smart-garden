#!/usr/bin/env python3
"""Cost of JUST sprinkler water in 2025 (current process applied to 2025 weather).

Uses the gallon totals from backtest_2025_gallons.py and the verified City of
Duvall 2026 inclining-block rate table (config.yaml billing).

Why marginal cost: water is billed per monthly cycle on inclining tiers, with
indoor use filling the cheap low tiers first. Sprinkler water sits ON TOP, so
its true cost = cost(indoor + sprinkler) - cost(indoor only), per month.

Sewer ($91.18) and storm ($32.17) are FLAT and don't change with sprinkler use
(irrigation doesn't add sewer), so sprinkler cost is purely the water-tier delta.
"""

GAL_PER_CF = 7.48052
INDOOR_CF_PER_MONTH = 400.0  # from the Feb-Mar winter bill (no irrigation): 400 cf

BASE_FEE = 34.26
TIERS = [
    (200, 0.0),
    (400, 5.10),
    (600, 6.56),
    (800, 8.03),
    (1000, 9.48),
    (999999, 10.97),
]

# Sprinkler gallons by month from the 2025 backtest (current process).
SPRINKLER_GAL_2025 = {
    "Apr": 1328, "May": 2119, "Jun": 4893,
    "Jul": 6840, "Aug": 3696, "Sep": 2529,
}


def water_cost(usage_cf):
    cost = BASE_FEE
    remaining = max(0.0, usage_cf)
    prev = 0
    for max_cf, rate in TIERS:
        if remaining <= 0:
            break
        band = max_cf - prev
        used = min(remaining, band)
        cost += used / 100.0 * rate
        remaining -= used
        prev = max_cf
    return cost


def main():
    base_indoor_cost = water_cost(INDOOR_CF_PER_MONTH)
    print(f"Indoor baseline: {INDOOR_CF_PER_MONTH:.0f} cf/mo -> water bill ${base_indoor_cost:.2f}/mo\n")

    print(f"{'Month':<6}{'Gallons':>9}{'cf':>8}{'Total bill':>12}{'Sprinkler $':>13}{'$/1000gal':>11}")
    print("-" * 59)
    total_gal = 0.0
    total_sprinkler_cost = 0.0
    summer_cost = 0.0
    for m, gal in SPRINKLER_GAL_2025.items():
        cf = gal / GAL_PER_CF
        full = water_cost(INDOOR_CF_PER_MONTH + cf)
        marginal = full - base_indoor_cost
        per_k = marginal / gal * 1000
        total_gal += gal
        total_sprinkler_cost += marginal
        if m in ("Jun", "Jul", "Aug"):
            summer_cost += marginal
        print(f"{m:<6}{gal:>9.0f}{cf:>8.0f}{full:>12.2f}{marginal:>13.2f}{per_k:>11.2f}")
    print("-" * 59)
    print(f"{'TOTAL':<6}{total_gal:>9.0f}{total_gal/GAL_PER_CF:>8.0f}{'':>12}{total_sprinkler_cost:>13.2f}")

    print(f"\n=== Cost of JUST sprinkler water, 2025 (current process) ===")
    print(f"  Jun-Aug sprinkler water:   ${summer_cost:,.2f}")
    print(f"  Full season (Apr-Sep):     ${total_sprinkler_cost:,.2f}")
    print(f"  Season sprinkler volume:   {total_gal:,.0f} gal "
          f"({total_gal/GAL_PER_CF:,.0f} cf / {total_gal/GAL_PER_CF/100:.1f} CCF)")
    blended = total_sprinkler_cost / (total_gal/GAL_PER_CF/100)
    print(f"  Blended marginal rate:     ${blended:.2f} per 100 cf "
          f"(${total_sprinkler_cost/total_gal*1000:.2f} per 1,000 gal)")


if __name__ == "__main__":
    main()
