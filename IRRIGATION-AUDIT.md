# Irrigation Brain Audit — FAO-56 vs. Current Implementation

## Summary

The irrigation brain is architecturally sound — the checkbook method, decision rules, and visualization are all correct in concept. However, several **parameter values are wrong** based on FAO-56 and PNW turfgrass science. These would cause the real system to under-water in some periods and over-water in others.

---

## Issue 1: Kc Values Are Too Low ⚠️ CRITICAL

**FAO-56 Table 12 says** for cool-season turf grass (bluegrass, ryegrass, fescue):
- Kc ini = **0.90**
- Kc mid = **0.95** 
- Kc end = **0.95**
- "Where careful water management is practiced, Kc's can be reduced by 0.10" → minimum **0.85**

**Current implementation:**
| Month | Current Kc | FAO-56 says |
|-------|-----------|-------------|
| Mar-Apr | 0.40 | 0.85-0.90 |
| May | 0.65 | 0.90-0.95 |
| Jun | 0.80 | 0.95 |
| Jul-Aug | 0.85 | 0.95 |
| Sep | 0.65 | 0.90-0.95 |
| Oct | 0.40 | 0.85-0.90 |

**Impact:** The system calculates ET crop at roughly **half** the actual rate in spring and fall, and 10-15% low in summer. This means it thinks the soil is wetter than it actually is. The grass would be stressed before the system realizes it needs water.

**Why this happened:** I treated turf grass like an annual crop with growth stages. But turf grass is a **perennial** — it maintains near-full ground cover year-round (except brief winter dormancy in PNW). FAO-56 explicitly notes turf grass Kc is nearly constant because the canopy stays dense.

**Fix:** Use Kc = 0.90 year-round (0.85 with deficit management). The seasonal variation should come from ET₀ itself (which naturally drops in spring/fall due to shorter days, lower temps), not from artificially lowering Kc.

**Exception:** During actual winter dormancy (Dec-Feb in PNW when grass is brown), Kc should drop to ~0.40. But May-September the grass is fully active.

---

## Issue 2: MAD Values May Be Too Aggressive

**FAO-56 Table 22** recommends MAD for turf grass:
- Well-maintained turf: **MAD = 40%** (i.e., water when 40% of available water is depleted)
- Stress-tolerant turf / deficit management: **MAD = 50-60%**

**Current implementation:** MAD = 50% base (summer), 55-60% (spring/fall)

**Assessment:** The summer MAD of 50% is within range for deficit irrigation of cool-season grass. The spring/fall values of 55-60% are aggressive for shallow-rooted spring grass — but this is intentional (we want to let spring grass develop before demanding deep roots).

**Verdict:** Acceptable. The 50% MAD for summer is standard for deficit management. For a homeowner who wants a pristine lawn, 40% would be better. For water conservation + root development, 50% is defensible.

---

## Issue 3: Root Depth of 6" May Be Shallow

**PNW Extension (WSU/OSU) recommendations** for cool-season grass root depth:
- New/establishing lawn: 3-4 inches
- Established lawn: 6-8 inches
- Well-managed, deep-watered lawn: 8-12 inches

**Current implementation:** Fixed at 6 inches year-round.

**Impact:** Root depth determines how the soil "bucket" converts between inches of water and moisture %. At 6" roots, 0.18" ET₀/day = ~3% daily drain. At 8" roots, same ET₀ = ~2.25% daily drain. Underestimating root depth means the system thinks the bucket is smaller than it is, leading to more frequent (but shallower) watering.

**Recommendation:** Consider 8" for summer (established, deep-watered turf) and 4-6" for spring. This would naturally create the seasonal watering pattern we want — without needing to hack Kc.

---

## Issue 4: Seasonal Kc Schedule Concept Is Wrong

**The real seasonal variation comes from:**
1. **ET₀ itself** — Open-Meteo already calculates lower ET₀ in spring/fall (shorter days, lower solar radiation, cooler temps). A May day has ET₀ = 0.12" vs July = 0.18". With Kc = 0.90, ET crop adjusts automatically.
2. **Root depth** — The only real plant-side variable that changes seasonally. Shallower roots in spring = smaller effective bucket = more frequent light watering. Deeper roots in summer = bigger bucket = less frequent deep watering.

**What the current system does:** Uses artificially low Kc values (0.40-0.65) in spring/fall to simulate lower water demand. This is double-counting — ET₀ is already low in those months. The result is the system barely waters at all in May-June, right when the grass is actively growing and needs consistent moisture.

**Fix:** Set Kc = 0.90 constant. Vary root depth by season if desired (4" spring → 8" summer → 6" fall). Let ET₀ do the heavy lifting for seasonal variation.

---

## Issue 5: Hardening Cycle Timing

**Current:** Every 21 days in Jun-Aug.

**Agronomic science says:** Regulated deficit irrigation (RDI) for cool-season turf is well-documented but the literature recommends:
- **2-3 week intervals** between RDI cycles ✅ (matches our 21 days)
- **Only during active growth, not during heat stress** — don't harden during a heat wave, only during mild periods
- **Duration of 3-5 days** maximum stress before recovery

**Current gap:** The system allows hardening even during heat waves (it just checks month, not temperature). A hardening cycle during a 90°F stretch would push cool-season grass into dormancy, not root development.

**Fix:** Add temperature guard: only enter hardening if the forecast 5-day average high is below 80°F. Above that, heat stress is doing the hardening for you — no need to add moisture stress on top.

---

## Issue 6: Rain Effectiveness Factor

**Current:** 75% of all rain reaches roots.

**USDA-NRCS guidance** for effective rainfall:
- Light rain (<0.2"): **30-50%** effective (most evaporates off leaves)
- Medium rain (0.2-0.5"): **60-75%** effective
- Heavy rain (>0.5"): **75-90%** effective (runoff increases on heavy clay, not an issue for Duvall loam)

**Recommendation:** Use a sliding scale based on rain intensity rather than flat 75%. Light PNW drizzle (<0.1") should count much less than a 0.3" shower.

---

## Issue 7: Wind Threshold

**Current:** Skip if daily max wind > 10 mph.

**Irrigation industry standard:**
- Spray heads: skip above **10 mph** ✅
- Rotary heads: skip above **15 mph**
- Drip: wind doesn't matter

**Assessment:** 10 mph is correct for spray heads, which is what the Orbit 57861 system uses. No change needed.

---

## Issue 8: The 4 AM-Only Window Is Fine

**Industry recommendation:** Water between 4-10 AM. Earlier is better (less wind, less evaporation, blades dry by afternoon).

**Current:** 4-6 AM.

**Assessment:** Perfect. No change needed.

---

## Recommended Changes (Priority Order)

| Priority | Change | Impact |
|----------|--------|--------|
| 1 | **Fix Kc to 0.90 constant** (0.85 with deficit mgmt) | Prevents chronic under-estimation of water demand |
| 2 | **Remove seasonal Kc schedule** — let ET₀ handle seasonality | Simpler, more correct |
| 3 | **Add seasonal root depth** (4" spring → 8" summer → 6" fall) | Better bucket sizing, natural seasonal pattern |
| 4 | **Guard hardening against heat** (no hardening if 5-day avg > 80°F) | Prevents dormancy-inducing stress |
| 5 | **Sliding rain effectiveness** (30-90% based on intensity) | More accurate rain credit |
| 6 | **Consider 8" root depth for summer** instead of 6" | More realistic for established PNW turf |

## What's Working Well

- ✅ FAO-56 Penman-Monteith ET₀ from Open-Meteo
- ✅ Checkbook method with 15-minute resolution
- ✅ Dynamic MAD shifting with temperature
- ✅ Wind skip using daily max forecast
- ✅ Rain skip with catch-up verification
- ✅ Pre-emptive arming for heat events
- ✅ Emergency override at wilt point
- ✅ Decision logging with full reasoning
- ✅ 4-6 AM watering window
- ✅ Visualization with auditable checkbook tooltip
