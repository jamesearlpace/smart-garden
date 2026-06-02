# Smart Garden — Tuning & Scheduling Journey

**Status:** 🔧 Calibrating — precip rates likely too high for spread-out zones. Moisture sim deployed, tuning panel live.
**Last Updated:** 2026-06-02
**Goal:** Get each zone's moisture chart to reflect reality so automated scheduling decisions are correct.

**Parent doc:** [smart-garden-journey.md](smart-garden-journey.md) (system architecture, hardware, plumbing)

---

## Current System State

### Infrastructure
- **Server:** Acer Aspire at 192.168.0.109, port 5125, systemd `smart-garden-server.service`
- **Controller:** ESP32 at 192.168.0.150, 9 spray zones + drip
- **Dashboard:** https://sprinklers.savagepace.com (Google OAuth)
- **Moisture Sim:** https://sprinklers.savagepace.com/moisture-sim (deployed 2026-06-01)
- **Watering window:** 4:00–7:00 AM (spray), 8:00–10:00 PM (garden drip, zone 7)
- **Daily balance job:** 11:00 PM (calculates soil_balance from ET₀, rain, irrigation)
- **Forecast snapshot:** 3:55 AM (records predicted state before watering window)

### Zone Config (as of 2026-06-02)

| ID | Name | Type | Heads | GPM | Precip (iph) | Area (sq ft) | Root (in) | Status |
|----|------|------|-------|-----|-------------|-------------|-----------|--------|
| 0 | Front Yard A | spray | 4 | 4.0 | 1.5 | ~257 | 6 | ⚠️ needs area measurement |
| 1 | Front Yard B | spray | 4 | 4.0 | 1.5 | ~257 | 6 | ⚠️ needs area measurement |
| 2 | Enclosed Backyard A | spray | 4 | 4.0 | 1.3 | ~296 | 6 | ⚠️ needs area measurement |
| 3 | Enclosed Backyard B | spray | 4 | 4.0 | 1.3 | ~296 | 6 | ⚠️ needs area measurement |
| 4 | Southeast | spray | 4 | 4.0 | 1.3 | ~296 | 6 | ⚠️ closest heads, probably OK |
| 5 | South | spray | 3 | 3.0 | 1.0 | ~289 | 6 | ⚠️ needs area measurement |
| 6 | Southwest | spray | 4 | 4.0 | 1.3 | ~296 | 6 | ⚠️ needs area measurement |
| 7 | Garden | drip | 1 | 0.5 | 0.4 | — | 10 | needs Kc tuning |
| 8 | Grapes | drip | 1 | 0.5 | 0.4 | — | 12 | needs Kc tuning |
| 9 | Spare | spray | 0 | 0 | 0 | — | 6 | not installed |

**All nozzles:** 1 GPM pop-up spray heads.

**Area column:** Back-calculated from current precip rate (`96.25 × GPM ÷ precip_rate`). These are guesses — James needs to measure actual coverage.

### Known Issue: Precip Rates Probably Wrong

The current precip rates imply ~250-300 sq ft per zone. James says the east zones (0, 1, 4) have heads close together but the others are more spread out. If a zone actually covers 600+ sq ft, the precip rate should be half what it is, meaning the DB is recording 2x too much irrigation credit per minute of runtime. This makes the moisture chart peg to 100% after short runs.

**Fix:** Measure area per zone (or do catch-can test), enter in tuning panel, save.

---

## Tuning Panel (deployed 2026-06-02)

**Location:** Bottom of moisture sim page, click "⚙️ Zone Tuning" to expand.

**Knobs:**
1. **Heads** — number of sprinkler heads
2. **GPM per Head** — nozzle flow (1.0 for current nozzles)
3. **Area (sq ft)** — typing area auto-calculates precip rate
4. **Precip Rate (iph)** — master knob, can edit directly
5. **Root Depth (in)** — bucket size (6" spray, 10-12" drip)
6. **Kc per season** — shows for garden/grapes (Spring/Early Summer/Peak/Fall)

**Save** writes to `config.yaml` on server. Daily balance job (11 PM) uses new values going forward. Does NOT retroactively fix historical balance data.

**API:** `POST /api/zone-config` with JSON body `{ zone_id, precip_rate_iph, heads, est_gpm, area_sqft, root_depth_in, kc }`.

---

## Bugs & Issues

### Open

| # | Issue | Zone(s) | Symptom | Likely Cause | Fix |
|---|-------|---------|---------|-------------|-----|
| 1 | Moisture pegs 100% after short runs | 0,1,2,4,5 | 5-min run shows 100% for days | Precip rate too high (area too small) | Measure area, update tuning panel |
| 2 | Zone 6 (SW) balance at 43% but no auto-watering | 6 | Server says "wait — outside window" but zone is below MAD | ✅ Bug #5 blocked all auto-watering; now fixed. Zone will water at next 4 AM window. | Resolved by bug #5 fix — monitor Jun 3 AM |
| 3 | Zone 7/8 never watered | 7,8 | No watering events in DB for garden/grapes | Evening window (8-10 PM) for zone 7 only; zone 8 not in any window | Add zone 8 to evening window or create separate schedule |
| 4 | Kc values in config are old seasonal schedule | all spray | Config has `kc: [0.6, 0.75, 0.8, 0.65]` per zone | Pre-audit values — should be 0.90 constant for active turf | Update via tuning panel or bulk config update |
| 5 | `irrigation.py:671` TypeError on run_cycle | ALL | No auto-watering ever fires, all events are manual | `pass` instead of `continue` — sensor_idx=None falls through to array indexing | ✅ Fixed 2026-06-02: `pass` → `continue` |
| 6 | Bogus 0% moisture for weeks in early data | ALL | Moisture shows 0% for 12-18 days per zone in Apr-May | Balance initialized at field capacity but drained to 0 with no irrigation (bug #5 meant no auto-watering to refill, no manual watering until late May) | Historical data is correct given bug #5 — system was broken. No retroactive fix needed. |
| 7 | May 26 phantom jump from 0% to 100% | 6 and others | Balance jumps from 0.0mm to 22.9mm (TAW) with 0 rain and 0 irrigation | `update_daily_balances` has `balance = taw_mm` fallback when it can't find yesterday's record | ✅ Fixed: carry forward today's existing balance instead of resetting to TAW. Only use TAW on true first entry. |
| 8 | Legend shows sim-only decision types in real-data mode | — | Rain Skip, Wind Skip, Hardening, Pre-emptive, Emergency, etc. in legend for 2026 | Legend is static HTML | ✅ Fixed: sim legend row hidden when year=2026 |
| 9 | "Actual Run (DB)" in legend with no data | 6,7,8 | Legend shows "Actual Run" marker for zones that have never been watered | Static legend item always shown | ✅ Fixed: removed from static legend, bars self-label via Chart.js tooltips |
| 10 | Forecast line shows only ET decay, no predicted watering | ALL | After "Now" the moisture line just drops | Forecast path only subtracts ET | ✅ Fixed: forecast now predicts watering when moisture crosses MAD during 4-7AM window, shows recovery + sprinkler bars + rain credit |
| 11 | Stats contaminated by bogus 0% initialization period | ALL | "56.4 hrs Deep Stress / Cycle" from weeks of broken data | Stats include bogus 0% period | ✅ Fixed: stats skip data until moisture first exceeds 10% |
| 12 | Stats use sim sprinkler counting in real-data mode | 6,7,8 (0 actual events) | "177 hrs Stress/Cycle" — zone never watered shows huge stress | `actualWaterings.length > 0` is false for unwatered zones → falls through to sim path → finds forecast predicted sprinklers → divides stress by 1-2 phantom cycles | ✅ Fixed: real-data mode uses `actualWaterings !== null` gate, never falls through to sim path |
| 13 | Stats include forecast data in stress count | ALL | Stress hours inflated by forecast predictions | Stress loop counts all data points including `isForecast=true` | ✅ Fixed: `if (data[j].isForecast) continue` in stress loop |
| 14 | 6-second valve tests create phantom watering cycles | 6 | Stats show "0.8 days" cycle length for zone with no real watering | `computeStats` filtered events at `> 5` seconds; 6-second manual relay test blips passed the filter and created 2 phantom "cycles" | ✅ Fixed: raised minimum to 60 seconds |
| 15 | Init period filter at 10% starts too early | 6 | "275.8 hrs Deep Stress" — PNW rain briefly pushed moisture above 10% mid-May, filter started counting, moisture fell back to 0% for 9 more days | Threshold too low — rain spike on May 16 pushed moisture above 10% but the system was still broken (no auto-watering). All subsequent 0% days counted as deep stress. | ✅ Fixed: raised threshold from 10% to MAD (50%) — system wasn't real until moisture exceeded the watering trigger |
| 16 | Current moisture badge reads end of forecast | ALL | Badge shows 76.9% when actual moisture is ~36% | `curMoisture` in `computeStats` used `data[data.length - 1]` which is the last point of the 7-day forecast after predicted watering cycles have been applied, not the actual current moisture | ✅ Fixed: walks backward from end to find last non-forecast point |
| 17 | No "Next Watering" banner when moisture already below MAD | 6 | Zone at 43% (below MAD 50%), server logging "will water at next window", but no banner shown | `updateNextWateringBanner` had `if (lastMoisture > madPct)` — only showed banner when moisture was ABOVE MAD (estimating future crossing). When already below MAD, the condition was false and banner was hidden. | ✅ Fixed: added `if (lastMoisture <= madPct)` branch that shows "needs water now — next 4 AM window" |
| 18 | Stress stats misleading when 0 watering cycles | 6,7,8 | Shows "0.0 hrs Stress/Cycle" even though zone has real stress | `stressHours / cycles.length` — with 0 cycles, the ternary returned `'0.0'`. There IS stress (zone is below MAD for days), it just can't be expressed per-cycle because there are no cycles. | ✅ Fixed: when cycles=0, shows total stress hours instead of per-cycle (e.g. "142 total") or "—" if no stress at all |
| 19 | Depth stat shows "—"" (em-dash + quote) | ALL | Visual artifact when no watering data | `computeStats` returns `'—'` for depthIn, stat card HTML unconditionally appends `"` for inches unit → displays as `—"` | ✅ Fixed: suppress `"` when value is "—" |
| 20 | Next Watering banner not showing (attempt 1) | 6 (below MAD) | Zone at 43.2% < MAD 50%, banner not visible | Below-MAD check was nested inside `if (forecast.length > 0)` — if forecast_7day was empty, banner was hidden | ✅ Fixed: moved below-MAD check outside forecast gate |
| 21 | 30d range includes forecast, shortens visible history | ALL | "30d" shows May 10–Jun 8 instead of May 3–Jun 2 | `tMin = tMax - 30 days` where `tMax` = end of forecast | ✅ Fixed: calculate `tMin` from `Date.now()` not end of data |
| 22 | Next Watering banner STILL not showing after fix #20 | 6 (below MAD) | 3 fix attempts failed | JS was always correct — banner was rendering above the viewport | ✅ Root cause was #24 (positioning) |
| 23 | Next Watering banner STILL not showing after fixes #17, #20, #22 | 6 (below MAD) | Inlined logic, added try/catch — still invisible | Same as #22 — the code worked, the element was above the scroll position | ✅ Root cause was #24 (positioning) |
| 24 | Banner renders above viewport — user never sees it | ALL | Banner div was outside the card, above the fold. Page auto-scrolled to card on load. | Banner HTML was between nav and card divs. On page load, the card filled the viewport and the banner was above it. Every fix from #17-#23 was correct JS that set `display:flex` successfully — but the element was scrolled out of view. | ✅ Fixed: moved banner inside the card, after the subtitle |
| 25 | Forecast predicted sprinkler bars not shown in precip chart | ALL | Predicted watering shows in moisture line (recovery bumps) but no green bars in precip chart | `buildChart` had `if (!isReal)` gate on sprinkler bar dataset — real-data mode filtered out ALL sprinkler bars including forecast predictions. Forecast bars were generated in `data[].sprinkler` but never rendered. | ✅ Fixed: added separate dataset for forecast sprinkler bars (faded green, 35% opacity) |
| 26 | Forecast watering fires every day — way too aggressive | ALL | Predicted sprinkler bars appear daily in 7-day forecast, moisture oscillates 45-55% | Forecast recalculated `moisture = lastBalPct - etSoFar` from scratch at every 15-min step. Watering at 4 AM raised moisture to 70%, but the next step recalculated from the same `lastBalPct` (43%), discarding the watering. By end of day, moisture was back to ~43% because ET was subtracted from the un-watered base. Next day: same 43% start → water again. **Root cause:** No running accumulator — each step was stateless. | ✅ Fixed: switched to running balance that carries forward across steps. Watering, ET drain, and rain all accumulate. `lastBalPct` only sets the initial value at step 0 of each forecast day. |
| 27 | May 26 phantom spike to 100% visible on chart | 6 (all zones affected) | Moisture jumps from 0% to 100% on May 26 with no rain or irrigation bars to explain it | Historical DB data corruption from bug #7 (phantom TAW reset). See full RCA below. | ✅ Fixed: corrected May 26 DB rows + recalculated full downstream chain (May 27–Jun 1) for all zones using checkbook math: `balance = max(0, min(taw, prev - etc + rain + irrig))`. Zones with heavy manual irrigation (0,2,4,5) recover quickly; zones never watered (3,6,7,8) correctly show ~0%. |
| 29 | Predicted watering appears before "Now" line | ALL | Moisture line rises above MAD before the "Now" marker, implying watering happened that hasn't occurred | Forecast code predicts watering at 4 AM for any day without a DB balance row. Today (Jun 2) has no row yet (11 PM job hasn't run), so it enters the forecast path. At 4 AM today (which is in the past), it predicts watering → moisture jumps to ~50%. But it's now 1 PM and that watering never happened. The chart shows a false recovery before "Now." **Root cause:** forecast predicted watering for past time slots on the current day. **Adjacent issue:** today's data uses the forecast code path (no `bal` record) but is NOT marked `isForecast` (weather data is real from archive API). This means today's simulated balance is rendered as historical data (no forecast shading, counted in stats). This is mostly cosmetic — the moisture line is a reasonable estimate using real weather, just not DB-verified. | ✅ Fixed: added `isInFuture = stepTime > Date.now()` check — only predict watering for future time slots. Past hours on today show continued decay from last known balance. |

### Verified Correct (not bugs)

| Item | Value Shown | Why It's Correct |
|------|-------------|-----------------|
| Badge 43.2% | Zone 6 balance 9.87mm / 22.86mm TAW | = 43.2%. Reads last non-forecast data point. ✅ |
| "— days" cycle length | No watering cycles | Zone has 0 real watering events > 60s. Only two 1s and 6s valve test blips. ✅ |
| "10 total hrs" stress | Below MAD since Jun 1 afternoon | ~1.5 days × ~7 daytime hrs ≈ 10 hrs beneficial stress. Filter correctly starts from May 26 (first time > MAD). ✅ |
| "0 total hrs" deep stress | Never below 35% since May 26 | Moisture dropped from 100% → 43.2% but stress limit is 35%. Never reached. ✅ |
| Forecast predicted watering | Green bars + moisture recovery | Zone at 43% < MAD 50% → predicts watering at next 4 AM window, then daily ET decay + periodic re-watering. ✅ |

### Resolved

| # | Issue | Resolution | Date |
|---|-------|-----------|------|
| — | Rain getting 6x too much credit in sim | Fixed: `rain / rootDepth` scaling in `generateBrainData` | 2026-06-01 |
| — | 30/60/90d buttons showed start of season not recent | Fixed: simulate full season, zoom to last N days | 2026-06-01 |
| — | Sim sprinkler bars showing for zones that never ran | Fixed: 2026 uses real DB data only, no brain simulation | 2026-06-01 |
| — | Fabricated rain-skip decisions in 2026 view | Fixed: removed all decision fabrication from real-data mode | 2026-06-02 |

---

## RCA: Auto-Watering Completely Broken (Bug #5)

**Severity:** Critical — system was non-functional for auto-watering since code deployment.

### Summary
Every `run_cycle()` call (every 5 min, 24/7) crashed with `TypeError: list indices must be integers or slices, not NoneType` at line 671. The decision loop never reached zone evaluation. All 128 watering events in the DB were manual.

### Root cause
```python
# BROKEN (deployed Jun 1 ~17:00):
if sensor_idx is None:
    pass                                          # ← no-op, falls through
soil_readings[zone["id"]] = soil_list[None]["pct"]  # ← CRASH

# PREVIOUS WORKING CODE (≤ May 27):
if sensor_idx is None:
    invalid_sensor_zones.add(zone["id"])
    log.warning("Zone %d has no sensor; skipping", zone["id"])
    continue                                      # ← skips to next zone
```

The refactor intended to enable water-balance mode for sensorless zones. The old 6-line block (warning + skip) was replaced with a 2-line comment + `pass`. But `pass` doesn't skip the next line — `soil_list[None]` still executes.

### Timeline
- **≤ May 27**: Working code — sensorless zones safely skipped with `continue` (but never auto-watered)
- **Jun 1 17:06**: Refactored code deployed — `continue` replaced with `pass`
- **Jun 1 17:07**: First crash. 213 consecutive crashes over 17.75 hours.
- **Jun 2 10:39**: Fixed — `pass` → `continue`. First successful cycle immediately.

### Why it wasn't caught
1. No monitoring on `run_cycle` completion — APScheduler logged exceptions but no alert fired
2. Manual watering still worked (bypasses `run_cycle`)
3. Crash tracebacks buried in 17K-line log file
4. No "last successful cycle" health metric

### Preventive measures (implemented below)
1. ✅ Added `=== Decision cycle complete ===` log line (was already there but unreachable due to crash)
2. ✅ Added ntfy alert if run_cycle hasn't succeeded in >15 minutes
3. ✅ Added `last_successful_cycle_ts` to system health

---

## RCA: Stats Engine Cascade Failure (Bugs #11-16)

**Severity:** Medium — misleading data, no operational impact.

### Summary
The stats engine (`computeStats`) had 6 interacting bugs that produced garbage numbers (177 hrs, 275 hrs, 0.8 days for a zone with zero real watering). Each fix revealed the next bug in the chain. The root cause was reusing a stats engine designed for clean simulated data to process messy real-world data that contains initialization artifacts, test blips, and forecast predictions.

### Root cause: two pathological data characteristics

The real DB data has two properties the stats engine was never designed for:

1. **Initialization garbage**: Auto-watering was broken (bug #5) for the system's entire life, so zones drained from field capacity to 0% with no irrigation. This created weeks of 0% data that looks like catastrophic deep stress but is actually just "the system wasn't running yet."

2. **Forecast pollution**: Bug #10's fix (add predicted watering to forecast) injected synthetic `data[].sprinkler` values and created moisture oscillations in the future portion of the data array. Stats couldn't distinguish these predictions from historical reality.

### The cascade (each fix unmasked the next)

```
Bug #5 fix (auto-watering crash)
  └→ Exposed bug #6: weeks of 0% moisture in DB (correct — system was broken)
     └→ Bug #11: stats counted 0% weeks as stress → "56 hrs Deep Stress"
        └→ Fix: skip data before moisture > 10%
           └→ Bug #15: rain spike May 16 briefly exceeded 10%, filter started too early
              └→ Fix: skip data before moisture > MAD (50%)

Bug #10 fix (forecast predicted watering)
  └→ Injected data[].sprinkler values into forecast portion
     ├→ Bug #12: real-data mode with 0 actual events fell to sim path
     │  (actualWaterings.length > 0 was false → else branch → counted forecast sprinklers)
     │  └→ Fix: gate on actualWaterings !== null (not .length)
     ├→ Bug #13: stress loop counted forecast data points
     │  └→ Fix: skip isForecast in stress loop
     └→ Bug #16: curMoisture read end of forecast (77%) instead of current (43%)
        └→ Fix: walk backward to last non-forecast point

Manual valve test artifacts
  └→ Bug #14: 6-second relay tests created watering_event rows
     └→ Filter at > 5s let 6s events through → phantom "cycles"
        └→ Fix: raise to > 60 seconds
```

### Key lesson
**Never reuse simulation-era code for real data without auditing every assumption.** The sim engine generates clean self-consistent arrays where every sprinkler entry is intentional. Real data has: initialization artifacts, test blips, manual overrides, server restarts causing balance resets, and forecast predictions mixed in. Every loop, filter, and division needs explicit guards for these cases.

### Guards now in place
- `if (data[j].isForecast) continue` in stress loop
- `if (!pastInit && data[j].moisture > MAD) pastInit = true` to skip broken init period
- `duration_sec <= 60` to skip relay test blips
- `isRealMode = actualWaterings !== null` (not `.length > 0`) to prevent fallthrough to sim path
- `curMoisture` walks backward from end to find last non-forecast point
- Stats show "X total" instead of "0.0 per cycle" when no real cycles exist

---

## RCA: Next Watering Banner Missing (Bug #17)

**Severity:** Medium — key user-facing prediction not shown when most needed.

### Root cause
`updateNextWateringBanner` had the condition `if (forecast.length > 0 && lastMoisture > madPct)`. This only shows the banner when moisture is **above** MAD — meaning "you don't need water yet, here's when you will." When moisture is **already below** MAD (the zone needs water NOW), the condition is false and the banner disappears.

Additionally, `lastMoisture` was reading `data[data.length - 1]` — the end of the 7-day forecast, not the current actual moisture. So even when the banner did show, it used the wrong moisture value.

### Why this happened
The banner was written for the happy-path case (zone is fine, estimate when it won't be). The unhappy-path case (zone already needs water) was never considered because:
1. During development, the mockup used simulated data where zones always get watered before crossing MAD
2. Bug #5 (auto-watering broken) meant real zones frequently crossed below MAD — a condition the banner code never anticipated

### Fix
Two branches:
- `lastMoisture <= madPct`: "Needs water now — next 4 AM window" with amber color
- `lastMoisture > madPct`: Walk forward through ET forecast to find crossing day (original logic, fixed moisture source)

---

## RCA: May 26 Phantom 100% Spike (Bug #27)

**Severity:** Low (cosmetic — historical data only, prevents future occurrence via bug #7 fix)

### Summary
On May 26, all zones' soil balance jumped from 0% to 100% (TAW) in the DB with zero rain, zero irrigation, zero ET₀, and zero Kc. This creates a visually jarring spike on the moisture chart with no corresponding rain or sprinkler bar to explain it.

### Evidence

**DB data for Zone 6:**
```
Date        bal   rain  irrig  et0   kc
2026-05-25  0.0   1.4   0.0    2.38  0.6   ← correct: nearly empty
2026-05-26  22.9  0.0   0.0    0.0   0.0   ← WRONG: all zeros except balance=TAW
2026-05-27  20.1  0.0   0.0    4.6   0.6   ← correct: normal ET drain from 22.9
```

**All 10 zones** show the same pattern on May 26: `balance = TAW`, all other fields = 0.

**Server log on May 26:**
- 23:00:00 — `update_daily_balances` runs normally → Zone 6 = **0.3mm** (with real ET₀=2.04, rain=1.5)
- 23:13:34 — server restart #1
- 23:17:02 — server restart #2
- 23:23:24 — server restart #3
- ... (13 total restarts between 23:13 and 00:35)

### Root cause

The 11 PM balance job ran correctly and wrote 0.3mm. Then **13 server restarts** in 80 minutes triggered `update_daily_balances` again via APScheduler. On one of these restarts:

1. `prev = db.get_soil_balance(zid)` → found today's row (May 26, balance=0.3mm)
2. `prev["date"] == today` → entered the "already updated today" branch
3. `db.get_soil_balance_history(zid, days=2)` → returned **empty** (DB contention during WAL checkpoint or restart race condition)
4. `yprev = None` → **fallback: `balance = taw_mm`** (22.9mm for spray zones)
5. `upsert_soil_balance(... balance=22.9, et0=0, kc=0, etc=0, rain=0, irrig=0)` → **overwrote** the correct 0.3mm

The weather cache was cold after restart, so `et0 = 0` and `rain = 0`. The upsert wrote all zeros plus TAW balance.

### Why all zones were affected
The `update_daily_balances` loop processes ALL zones in a single call. When the DB query returned empty for one zone, it returned empty for all zones (same DB connection issue during the restart).

### Prevention
- **Bug #7 fix** (deployed Jun 2): The `yprev = None` fallback now carries forward `prev["balance_mm"]` instead of resetting to `taw_mm`. If this scenario recurs, the balance would stay at its current value (0.3mm), not jump to 100%.
- **Historical data remains corrupt**: The May 26 row still has the bad 22.9mm value. This is a one-time artifact that will scroll off the chart as time passes.

### Options to fix the historical data
1. **Manual DB correction**: Set May 26 balance to 0.3mm for all spray zones (what the job calculated) — changes the chart retroactively
2. **Leave it**: The spike will scroll off the 30d/60d views within weeks. Full Season view will always show it as a reminder of the system's early instability
3. **Chart-side filter**: Detect and suppress spikes where `balance_mm == taw_mm AND et0_mm == 0 AND rain_mm == 0 AND irrigation_mm == 0` — marks as "initialization artifact" and interpolates

## Calibration TODO

- [ ] **Measure zone areas** — pace off or use Google Earth for each zone's coverage area
- [ ] **Enter areas in tuning panel** — precip rates will auto-calculate
- [ ] **Catch-can test** (optional, gold standard) — 4-5 cups per zone, run 15 min, measure depth
- [ ] **USDA Web Soil Survey** — look up Duvall address for soil type and AWC (available water capacity)
- [ ] **Update Kc to 0.90** for all spray zones (FAO-56 audit said current 0.6-0.8 values are too low)
- [ ] **Tune garden Kc** — depends on what's planted, probably 0.8-1.1
- [ ] **Tune grape Kc** — young vines 0.3-0.5, established 0.5-0.7
- [ ] **Verify auto-watering fires** — has the server ever run a non-manual cycle? Check watering_event trigger_reason

---

## Key Files

| File | Location | Purpose |
|------|----------|---------|
| `config.yaml` | `~/smart-garden-server/` on Acer | Zone config (tuning panel writes here) |
| `irrigation.py` | `~/smart-garden-server/` on Acer | Decision engine — `run_cycle()`, `update_daily_balances()` |
| `dashboard.py` | `~/smart-garden-server/` on Acer | Flask routes including `/api/zone-config`, `/api/moisture-data` |
| `moisture_sim.html` | `~/smart-garden-server/templates/` | Chart page + tuning panel |
| `database.py` | `~/smart-garden-server/` on Acer | `soil_balance`, `watering_event`, `forecast_snapshot` tables |
| `weather.py` | `~/smart-garden-server/` on Acer | Open-Meteo client, 30-min cache |
| `moisture-sim-preview.html` | `C:\MyCode\smart-garden\` | Standalone mockup for backtesting 2021-2025 (brain sim only) |
| `IRRIGATION-BRAIN.md` | `C:\MyCode\smart-garden\` | Brain algorithm design doc |
| `IRRIGATION-AUDIT.md` | `C:\MyCode\smart-garden\` | FAO-56 compliance audit |

---

## Deployment Checklist

```bash
# Deploy code changes (template + Python)
scp dashboard.py jamesearlpace@192.168.0.109:~/smart-garden-server/
scp templates/moisture_sim.html jamesearlpace@192.168.0.109:~/smart-garden-server/templates/

# Restart only if Python files changed (templates auto-reload)
ssh jamesearlpace@192.168.0.109 "sudo systemctl restart smart-garden-server"

# Verify
ssh jamesearlpace@192.168.0.109 "systemctl is-active smart-garden-server"
```

---

## Session Log

### 2026-06-01 — Moisture Sim Deployment

Built and deployed the moisture simulation chart page:
- Two-chart layout (precip bars + moisture line) with Open-Meteo weather
- 2026 uses real DB data (soil_balance + watering_event), 2021-2025 uses brain sim
- Fixed rain scaling bug (was 6x too high), date range buttons, decision fabrication
- Added nav links from dashboard and forecast pages
- Integrated actual watering events into moisture calculation

### 2026-06-02 — Tuning Panel + Real Data Cleanup

- Removed all brain simulation from 2026 view — pure DB data
- Added per-zone tuning panel with precip rate, heads, area, root depth, Kc
- API endpoint `POST /api/zone-config` saves changes to `config.yaml`
- Discovered precip rates likely too high for spread-out zones (moisture pegs 100%)
- All nozzles confirmed as 1 GPM pop-up spray heads
- Next: James measures zone coverage areas, enters in tuning panel
