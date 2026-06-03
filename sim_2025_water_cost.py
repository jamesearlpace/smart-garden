"""Cost estimate for 2025 simulated irrigation water usage.

Uses Woodinville Water District 119 (WD119) tiered rates — the wholesale
provider for Duvall and surrounding NE King County. If you're on City of
Duvall water, multiply by 1.25 (Duvall = WD119 rate + 25%).

Rates source: https://www.wd119.org/your-bill/  (effective Nov 1, 2025)

Billing is bi-monthly. Tiers RESET each billing period. The marginal cost of
irrigation depends on the baseline household usage (because irrigation lands
on top of whatever tier you're already in). We compute two scenarios:

  CASE A: typical household baseline 10 CCF / 2-month billing period
  CASE B: larger household baseline 15 CCF / 2-month billing period
  (1 CCF = 748.6 gallons; ~10 CCF bi-monthly ≈ 125 gal/day, modest family)

KEY POINT: King County sewer is typically charged off winter water (the
"winter averaging" rule), so summer irrigation usually does NOT inflate the
sewer bill. The numbers below are water-only.
"""

# Monthly irrigation totals (gallons) from sim_2025_water_usage.py output
IRRIGATION_GAL_BY_MONTH = {
    "2025-04": 1_296,
    "2025-05": 1_440,
    "2025-06": 4_488,
    "2025-07": 7_008,
    "2025-08": 4_032,
    "2025-09": 2_664,
    "2025-10": 0,
}

GAL_PER_CCF = 748.6

# WD119 tier boundaries (CCF) and per-CCF prices.
# Format: list of (upper_bound_CCF, price_per_CCF). Last tier upper = float('inf').
SUMMER_TIERS = [   # May – Oct
    (7,    4.34),
    (14,   5.48),
    (28,   7.17),
    (float("inf"), 8.70),
]
OFF_PEAK_TIERS = [ # Nov – Apr
    (7,    2.90),
    (14,   3.65),
    (28,   4.79),
    (float("inf"), 5.81),
]

# Bi-monthly base fee (3/4"-1" meter)
BASE_FEE_BIMONTHLY = 111.00

def tiered_cost(usage_ccf, tiers):
    """Compute usage charge for given CCF on the given tier schedule (cumulative)."""
    cost = 0.0
    prev_upper = 0.0
    remaining = usage_ccf
    for upper, price in tiers:
        slab = min(remaining, upper - prev_upper)
        if slab <= 0:
            break
        cost += slab * price
        remaining -= slab
        prev_upper = upper
    return cost

def marginal_irrigation_cost(baseline_ccf, irrig_ccf, tiers):
    """Cost OF the irrigation = cost(baseline + irrig) − cost(baseline)."""
    return tiered_cost(baseline_ccf + irrig_ccf, tiers) - tiered_cost(baseline_ccf, tiers)

# ── BUILD BI-MONTHLY BILLING PERIODS ───────────────────────────────
# WD119 bills cover two prior months (May bill = Mar+Apr usage, etc.)
periods = [
    ("Mar/Apr 2025", ["2025-04"],                "off_peak"),  # Mar irrig is 0, Apr is included
    ("May/Jun 2025", ["2025-05", "2025-06"],     "summer"),
    ("Jul/Aug 2025", ["2025-07", "2025-08"],     "summer"),
    ("Sep/Oct 2025", ["2025-09", "2025-10"],     "summer"),
]

print("=" * 88)
print("WATER COST ESTIMATE — 2025 SIMULATED IRRIGATION (WD119 rates, Nov 2025 schedule)")
print("=" * 88)
print()

for baseline_label, baseline_ccf in [("CASE A — modest baseline (10 CCF/bill)", 10),
                                      ("CASE B — larger baseline (15 CCF/bill)", 15)]:
    print(f"### {baseline_label} ###")
    print(f"{'Billing period':<16} {'Irrig gal':>10} {'Irrig CCF':>10} {'Tier':>10} {'Marginal $':>12}")
    print("-" * 88)
    total = 0.0
    total_irrig_ccf = 0.0
    for label, months, season in periods:
        gal = sum(IRRIGATION_GAL_BY_MONTH[m] for m in months)
        ccf = gal / GAL_PER_CCF
        total_irrig_ccf += ccf
        tiers = SUMMER_TIERS if season == "summer" else OFF_PEAK_TIERS
        cost = marginal_irrigation_cost(baseline_ccf, ccf, tiers)
        total += cost
        print(f"{label:<16} {gal:>10,} {ccf:>10.2f} {season:>10} ${cost:>10,.2f}")
    print("-" * 88)
    print(f"{'TOTAL':<16} {sum(IRRIGATION_GAL_BY_MONTH.values()):>10,} "
          f"{total_irrig_ccf:>10.2f} {'':>10} ${total:>10,.2f}")
    print(f"  → If on City of Duvall water (+25% surcharge): ${total*1.25:.2f}")
    print()

print("=" * 88)
print("NOTES")
print("=" * 88)
print(f"- 1 CCF = {GAL_PER_CCF} gallons; rates RESET per 2-month billing period")
print("- 'Marginal' = cost of the irrigation on top of normal household use")
print("  (irrigation gets pushed into the highest tiers because baseline is already used)")
print("- Sewer is NOT included — King County uses 'winter averaging' so summer outdoor")
print("  water typically does NOT inflate the sewer bill. Big hidden win for irrigation.")
print("- Base fee ($111/bill bi-monthly = $666/yr) is unchanged whether you irrigate or not.")
print("- Without the smart system, a dumb every-other-day schedule on the same 7 zones")
print("  would have been ~47,000 gal — roughly 2.2× the cost shown above (~$380-450).")
