# Smart Garden Irrigation Brain — Design Document

## Overview

This document describes the Tier-5 irrigation decision engine used in the Smart Garden system. The engine combines **FAO-56 soil water balance math** (the "algorithm") with **agronomic decision rules** (the "exceptions") to determine when, how much, and why to water each zone.

The system uses the same scientific foundation as commercial precision agriculture (Netafim, Lindsay FieldNET, Toro Lynx) but adapted for residential PNW cool-season grass without soil sensors.

---

## Part 1: The Algorithm (Soil Water Balance / Checkbook Method)

### Core equation (runs every 15 minutes)

```
moisture[t] = moisture[t-1] - ET_drain + rain + irrigation
```

Each variable is tracked as a **percentage of total available water (TAW)** in the root zone.

### 1.1 ET₀ Drain (evapotranspiration withdrawal)

**Source:** Open-Meteo `et0_fao_evapotranspiration` — daily Penman-Monteith reference ET₀ in inches.

**Prorated to 15-minute resolution** using a sine bell curve from 6 AM to 8 PM (56 steps):

```
drain = sin(phase) × dailyET_pct / (56 × 2/π)
```

Where:
- `phase` = position in the 6 AM–8 PM bell curve (peaks at ~1 PM)
- `dailyET_pct = (ET₀_inches / rootDepthInches) × 100 × Kc`
- Zero drain from 8 PM to 6 AM (ET₀ stops at night)

**Crop coefficient (Kc)** converts reference ET₀ to actual grass water use — varies by growth stage (see Part 2).

### 1.2 Rain (deposits)

**Source:** Open-Meteo hourly precipitation in inches.

Rain events are extracted from hourly data and spread across their duration in 15-minute steps. An **effectiveness factor of 75%** is applied — not all rain reaches the root zone (leaf interception, runoff, evaporation from wet surfaces).

```
effective_rain_pct = (depth / duration) × 100 × 0.75
```

### 1.3 Irrigation (deposits)

When the sprinkler is running:

```
sprinkler_pct = (precipRate / 4) × (100 / rootDepthInches)
```

For Zone 1 (Front Yard A): `(1.5 iph / 4) × (100 / 6") = 6.25% per 15-min step`

Each 15-minute step adds one quarter-hour's worth of the zone's calibrated precipitation rate, converted to root-zone moisture percentage.

### 1.4 Dynamic Thresholds

Two thresholds shift with **temperature** in real time:

**MAD (Management Allowable Depletion):** The moisture level where irrigation is needed.
```
MAD = seasonalMAD_base + (tempF - 70) / 10 × 3
```
- Clamped: 38% – 62%
- At 70°F: base value (50% in summer, 60% in spring)
- At 85°F: MAD rises to ~54.5% (grass needs more water when hot)
- At 55°F: MAD drops to ~45.5% (cooler = more tolerant)

**Wilt Point (Stress Limit):** Below this, permanent damage begins.
```
wilt = wiltBase + (tempF - 70) / 10 × 2
```
- Clamped: 22% – (MAD - 10%)
- Always stays at least 10% below MAD

### 1.5 Stress Tracking

Two types of stress are tracked cumulatively within each watering cycle:

- **Beneficial stress** (moisture between MAD and Wilt): `+0.25 hrs per 15-min step`
- **Damage stress** (moisture below Wilt): `+0.50 hrs per 15-min step` (counts double)

Both counters reset to zero after each watering event.

---

## Part 2: Seasonal Growth Stages

The system changes its entire irrigation personality based on the month. This mirrors what professional turf managers do — they don't use the same settings all year.

| Month | Stage | Kc | MAD Base | Recovery | Hardening? |
|-------|-------|-----|----------|----------|------------|
| Mar–Apr | Spring green-up | 0.40 | 60% | +12% | No |
| May | Active growth | 0.65 | 55% | +16% | No |
| Jun | Peak growth | 0.80 | 50% | +20% | Yes |
| Jul–Aug | Summer stress | 0.85 | 50% | +20% | Yes |
| Sep | Fall transition | 0.65 | 55% | +16% | No |
| Oct | Dormancy prep | 0.40 | 60% | +12% | No |

**What each column means:**

- **Kc:** Multiplier on ET₀. Spring grass uses 40% of reference ET; midsummer grass uses 85%.
- **MAD Base:** How dry the soil can get before watering. Spring roots are shallow — can't handle deep deficit (60% = conservative). Summer roots are deep — can tolerate more (50%).
- **Recovery:** How far above MAD to refill. Spring: light +12% (frequent shallow cycles). Summer: deep +20% (infrequent deep cycles that encourage root growth).
- **Hardening:** Whether deliberate stress-skip cycles are allowed. Only in summer when roots are established enough to benefit.

---

## Part 3: Decision Rules (When NOT to Water)

The algorithm determines *when moisture reaches the trigger point*. The decision rules determine *what to do about it*. These rules run in a strict priority order at 4:00 AM each day (only when armed).

### 3.1 Arming

The system "arms" (becomes ready to water) when:

```
moisture ≤ MAD + (today's daily ET drain × 1.3)
```

This arms **one day ahead** — if moisture will cross MAD by this afternoon, water this morning before it happens.

**Pre-emptive arm:** If tomorrow's forecast high exceeds 85°F and moisture is within range, arm in the evening (6 PM+) so the next 4 AM window fires proactively.

### 3.2 Decision Cascade (4:00–6:00 AM)

When armed, the system runs these checks **in order**. The first one that matches wins. Only one decision per day.

#### Priority 1: Wind Skip 💨
```
IF today's forecast max wind > 10 mph:
  → SKIP (stay armed for tomorrow)
  → Reason: "Drift wastes 30-50% of water at high wind"
```

Uses the **daily max wind forecast**, not the 4 AM instantaneous reading (wind is always calm at 4 AM).

#### Priority 2: Rain Skip 🌧️
```
IF rain expected today OR tomorrow:
  IF moisture > MAD - 3%:
    → SKIP (stay armed, let nature water)
    → Record: skippedForRainDay = today, moistureAtSkip = current
  ELSE:
    → WATER DESPITE RAIN ⚠️ (too dry to gamble)
```

Rain is "expected" if:
- Yesterday's weather flagged `rainTomorrow = true`
- Today has measurable precipitation (>0.05")
- Any rain event scheduled for today or tomorrow in the data

#### Priority 3: Rain Catch-Up 💧
```
IF we skipped for rain within the last 2 days:
  Calculate actual rain received since skip
  IF effective rain < 3% moisture gain:
    → WATER (catch-up: "Rain was a bust, compensating")
  ELSE:
    → Rain covered it, no action needed
```

This is the "trust but verify" rule. The system trusts the rain forecast to skip, but checks within 2 days whether the rain actually delivered. If not, it compensates immediately.

#### Priority 4: Hardening Skip 🌿
```
IF summer month (Jun-Aug)
AND NOT in hardening mode already
AND ≥21 days since last hardening
AND moisture near MAD (within +5%)
AND moisture safely above wilt (+8%):
  → ENTER HARDENING MODE (skip this watering)
  → Reason: "Regulated deficit irrigation — forcing root growth"

IF in hardening mode AND moisture drops to wilt + 5%:
  → EXIT HARDENING, water deeply (MAD + 22%)
  → Reason: "End hardening — approaching damage zone"
```

Every 3 weeks during summer, the system deliberately skips one watering cycle to force the grass roots deeper. This is what vineyards and professional turf programs call **regulated deficit irrigation (RDI)**. The system monitors continuously during hardening and aborts if moisture gets too close to the damage zone.

#### Priority 5: Normal Watering 💧
```
IF none of the above triggered:
  → WATER
  → Target = MAD + seasonalRecover + heatBonus
  → heatBonus = max(0, avg3dayHigh - 70) × 0.04
  → Capped at 80%
```

Recovery depth adapts to both **season** and **current heat**:
- Cool May day: target = 55% + 16% = 71%
- Hot July day (avg 85°F): target = 50% + 20% + (85-70)×0.04 = 70.6%
- Cool September: target = 55% + 16% = 71%

### 3.3 Emergency Override 🚨

Runs **every 15 minutes, any hour** (not just 4 AM):

```
IF moisture ≤ wiltPoint + 2%:
  → WATER IMMEDIATELY (bypass time window)
  → Target = MAD + 15%
  → Reason: "Prevents permanent cell damage"
```

This is the safety net. If a heat wave, forecast error, or system downtime lets moisture crash to the damage zone, the emergency override fires regardless of time of day, wind, or rain forecast.

---

## Part 4: Data Sources

| Source | What it provides | Update frequency |
|--------|-----------------|------------------|
| Open-Meteo Archive API | Historical hourly: temp, wind, precip. Daily: ET₀, max/min temp, max wind. | Per request (free, no key) |
| Open-Meteo Forecast API | 7-day forecast: same fields | Every 30 min (server caches) |
| Zone Configuration | Precip rate (iph), Kc schedule, root depth (in), MAD, soil type | Manual (Settings page) |
| FAO-56 Reference | Penman-Monteith ET₀ calculation, MAD guidelines, Kc curves | Built into Open-Meteo |

---

## Part 5: Visualization

The dashboard shows two stacked charts:

**Top chart:** Precipitation bars (inverted, hanging from top)
- Blue bars = rain (in inches, right axis)
- Green bars = sprinkler (in inches)

**Bottom chart:** Soil moisture line
- Green line = estimated moisture %
- Orange dashed line = MAD threshold (shifts with temperature)
- Red dashed line = Stress Limit / Wilt Point
- Orange temp line = temperature (right axis, °F)
- Amber shading = beneficial stress zone (between MAD and Wilt)
- Red shading = damage stress zone (below Wilt)

**Decision markers on the moisture line:**
| Symbol | Color | Meaning |
|--------|-------|---------|
| ● circle | green | Watered |
| ▲ triangle | blue | Rain skip |
| ◆ diamond | gray | Wind skip |
| ■ square | amber | Stress delay |
| ★ star | orange | Pre-emptive arm |
| ▲ triangle | purple | Hardening skip |
| ✕ cross | red | Emergency |

**Checkbook tooltip:** Hover any point to see the full balance sheet — ET loss, rain/sprinkler gains, temperature, wind, MAD, and stress state.

**Decision log:** Below the chart, a timestamped list of every decision with the reasoning.

---

## Part 6: Stats Cards

| Metric | Green | Yellow | Red | What it means |
|--------|-------|--------|-----|---------------|
| Avg Cycle Length | 2–4 days | >4 days | — | How often the system waters |
| Stress / Cycle | 2–8 hrs | 8–12 hrs | >12 hrs | Beneficial stress per watering cycle |
| Deep Stress / Cycle | 0 hrs | 0–1 hrs | >1 hr | Time below wilt point (should be zero) |
| Depth Per Cycle | 0.5–0.75" | 0.4–0.8" | >1" | Inches of water applied per cycle |

---

## Part 7: What a Dumb Timer Does vs. What This System Does

| Situation | Timer | This System |
|-----------|-------|-------------|
| It rained yesterday | Waters anyway | Skips — rain already refilled |
| 90°F forecast tomorrow | Same schedule | Pre-waters tonight to build buffer |
| Windy morning | Waters, loses 40% to drift | Skips, tries tomorrow |
| Forecast said rain but it didn't come | Skipped, lawn dries out | Catches up within 2 days |
| July dry spell | Same as May | Deeper watering, longer cycles, hardening |
| Cool September | Same as July | Lighter watering, higher MAD, no hardening |
| Moisture approaching damage zone at 2 PM | Waits until scheduled time | Emergency override — waters immediately |
| Grass hasn't been stressed in 3 weeks | Doesn't know | Deliberately skips one cycle for root growth |
