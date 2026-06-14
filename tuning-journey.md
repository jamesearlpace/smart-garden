# Smart Garden — Tuning & Scheduling Journey

**Status:** ✅ Auto-watering operational (Bug #5 + dead sensor-gate both fixed 2026-06-02). 🔧 Still calibrating precip rates for spread-out zones.
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
| 2 | Zone 6 (SW) balance at 43% but no auto-watering | 6 | Server says "wait — outside window" but zone is below MAD | ✅ Bug #5 + dead sensor gate blocked all auto-watering; both fixed. Zone will water at next 4 AM window. | ✅ Resolved — monitor Jun 3 AM cycle |
| 3 | Zone 7 never auto-watered | 7 | No automatic watering events in DB for Garden drip | Bug #5 (TypeError) + dead sensor gate blocked all auto. Evening window 20:00-22:00 configured correctly. | ✅ Resolved — monitor tonight's 20:00 cycle |
| 3b | Zone 8 (Grapes) plumbing not installed | 8 | Zone in config but no physical valve/line | User confirmed not plumbed yet; should never turn on | ✅ Resolved 2026-06-02: `installed: false` in config.yaml. Backup at `~/smart-garden-server/config.yaml.bak-zone8fix` |
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
| 30 | Predicted sprinkler bar time changes when mouse moves | ALL | Hovering the precip chart shows a predicted sprinkler bar that jumps to different times as the mouse moves. Tooltip shows "Tue 5:00 PM" then "Wed 4:15 AM" etc. for the same predicted watering event. The time shown in the tooltip doesn't match the banner's "Wednesday Jun 3 ~4 AM". | Predicted watering was generated as 12 separate 15-min data points per event (one per step in the 4-7 AM window). Chart.js `mode: 'index'` tooltip snaps to the nearest x-axis point, so moving the mouse shows different 15-min slots. **Root cause:** the `forecastSprinklerBars` dataset mapped every `data[].sprinkler` point individually instead of aggregating per day. | ✅ Fixed: consolidated into ONE bar per watering day. All 15-min sprinkler values for a day are summed into a single bar positioned at 4 AM with the total predicted inches. Tooltip now shows stable "Wed Jun 3, 4:00 AM · Predicted Sprinkler 0.25"" regardless of mouse position. |
| 31 | Predicted sprinkler bar tooltip shows wrong date — "Tue Mar 3, 7:00 AM" instead of "Wed Jun 3, 4:00 AM" | ALL | Hovering the consolidated predicted sprinkler bar shows completely wrong date (March instead of June, wrong day of week, wrong time). | `toISOString().slice(0,10)` returns UTC date string. `new Date(dayKey + 'T04:00:00')` without timezone suffix is parsed as UTC 4 AM, which displays as 9 PM previous day in Pacific time. The month/day/time are all shifted. **Root cause:** UTC vs local timezone mismatch in date construction. | ✅ Fixed: use `p.t.getFullYear()/getMonth()/getDate()` for local-time day grouping, and `new Date(year, month, day, 4, 0, 0)` for local-time 4 AM bar position. |
| 32 | Tooltip shows "Sprinkler 0.00" (0 min)" and wrong date when hovering predicted bar | 6 (zones with valve test blips) | Hovering the predicted sprinkler bar shows two lines: "Sprinkler 0.00" (0 min)" from actual events AND "Predicted Sprinkler 0.20"" — with a wrong title date ("Tue Mar 3"). | **Two interacting causes:** (1) `actualBarData` included 1-second and 6-second valve test events (`duration_sec > 0` filter too loose). These create phantom zero-value bars that appear in the tooltip alongside the predicted bar. (2) Chart.js `mode: 'index'` tooltip title comes from the nearest data point across ALL datasets — the actual event's timestamp (May 27 or May 31) is different from the predicted bar's timestamp (Jun 3), causing the title to show the wrong date from whichever dataset resolves first in the nearest-point search. **Root cause:** the actual bar dataset had no minimum duration threshold, allowing test blips to pollute the chart and confuse the tooltip's date resolution. | ✅ Fixed: raised `actualBarData` filter from `duration_sec > 0` to `>= 60` seconds (same threshold used in stats). Zone 6's two test blips (1s, 6s) are now excluded. Without competing data points, the tooltip title correctly shows the predicted bar's date. |
| 33 | Precip tooltip title shows wrong date — "Tue Mar 3, 7:15 AM" instead of "Tue Jun 2, 2:18 PM" | ALL | Hovering any actual sprinkler bar shows a date months in the past (e.g. March 3 instead of June 2). The tooltip body label is correct ("💧 Sprinkler 0.03" (2 min)") but the title date is from a completely different time. Day-of-week happens to match (both are Tuesdays) making it less obvious. | **Root cause: `interaction.mode: 'index'` resolves tooltip items by ARRAY INDEX, not by timestamp.** The precip chart has 3-4 datasets with wildly different array lengths: Rain has hundreds of hourly data points (one per hour for the entire season), while Sprinkler has 1-2 actual events. When hovering a sprinkler bar, Chart.js finds the nearest point (sprinkler at array index 0), then fetches index 0 from ALL datasets. Rain dataset index 0 is the first hour of the season — e.g. March 3. The title callback `items[0].parsed.x` reads the FIRST item in the array, which comes from the Rain dataset (first in `precipDatasets`). Rain's index-0 timestamp → March 3. The label callback filters rain items with `y <= 0.001` so they don't show in the tooltip body, but the title callback runs on ALL items including invisible ones. **This is the same class of bug as #30-32** — `mode: 'index'` is fundamentally incompatible with time-scale scatter/bar charts that have datasets of different lengths. Previous fixes (#31 UTC, #32 test blips) masked this root cause for predicted bars by fixing adjacent issues. Now that actual sprinkler events exist in the DB, the true index-mismatch bug surfaced. **Fix:** Change the title callback to find the first tooltip item with a visible value (`parsed.y > 0.001`) and use THAT item's timestamp, matching the label filter logic. This ensures the title date always corresponds to the actual visible tooltip content. |
| 34 | Actual vs predicted sprinkler bars not visually to scale | 6 | Actual sprinkler bar (0.12", 6 min) appears tiny while predicted bar (0.20", ~9 min) appears massive — visual ratio far exceeds the 0.12:0.20 data ratio. | ~~Original RCA was wrong (blamed barThickness).~~ **Superseded by bug #35** — actual root cause is unit mismatch. |
| 35 | **ALL precip bars are in mixed units — actual sprinkler bars are raw inches, rain and predicted bars are moisture-fraction inches** | ALL | Bars on the same y-axis represent different physical quantities. Actual sprinkler: `precipRate × duration / 3600` = raw inches of water (0.13" for 6 min). Predicted sprinkler: `precipRate/4 × rd/100` per step, summed = moisture-equivalent fraction (0.20" label but actually means "the equivalent of 0.20" depth change in a 6" root zone"). Rain: also `× rd / 100`. The tooltip estimated runtime is also wrong — `0.20 / 1.3 × 60 = 9 min` but 0.20 isn't raw inches, so the real predicted runtime is ~150 min (2.5 hrs). **Root cause: the `actualBarData` builder (line ~1215) calculates `precipRate × duration_sec / 3600` (raw inches), while `rainBarData` (line ~1203) and `forecastSprinklerBars` (line ~1271) both multiply by `rd / 100` (root depth factor). These are different units on the same axis. The rain/forecast values are ~16× smaller than what they'd be in raw inches (factor = rd/100 = 6/100 = 0.06). This means actual sprinkler bars are 16× too tall relative to rain and predicted bars, OR rain/predicted bars are 16× too short relative to actual bars.** | ✅ Fixed: unified all three datasets to raw inches. `rainBarData` and `forecastSprinklerBars` now return raw `p.rain` and `p.sprinkler` values (no `× rd/100`). All bars on the precip chart are now in the same unit. |
| 36 | **Forecast predicts physically impossible watering runs (150 min, 3.25", +54.2% moisture in one cycle)** | ALL (any zone below MAD with low starting moisture) | Tooltip on predicted sprinkler bar shows "Predicted ~150 min · 3.25" · +54.2% moisture". Zone 7 starting at 0% triggers 10 consecutive 15-min watering steps from 4-6:30 AM until moisture reaches MAD+20 (70%). Each step adds `precipRate/4` = 0.325" raw. Total = 3.25" — more than the soil can hold (TAW for spray zones is ~0.9"). | **Root cause: the JS forecast loop (`generateBrainData`, line ~565 in `moisture_sim.html`) has no knowledge of the engine's `max_runtime_min` cap (config.yaml: 24 min for spray zones, 45 for drip, 60 for grapes) and no knowledge of the new same-day watering guard.** The JS code keeps watering each 15-min step while `moisture < madPct && isInFuture`. It only stops when moisture rises above MAD — which takes 9-10 steps when starting at 0%. The real Python engine: (1) runs ONE cycle of `max_runtime_min` minutes (= 0.52" for a 1.3 iph spray zone over 24 min), then (2) the same-day guard added in irrigation.py prevents any further runs that day. Real predicted gain ≈ 8.7% moisture, not 54%. | ✅ Fixed: added per-day per-zone runtime accumulator in forecast loop. Each step that triggers watering increments `minutesWateredToday` by 15 (or less if the cap is hit mid-step). Once `minutesWateredToday >= zone.max_runtime_min`, no more watering predictions for that day. The `sprinklerBar` value is also clamped to match the actual minutes added. This produces realistic single-cycle bars (~24 min, ~0.52", ~8.7% moisture). Tooltip "Predicted ~X min · Y" · +Z% moisture" now matches engine behavior. |
| 37 | **Whole-system audit: current watering strategy is wrong for a lawn AND broken for 4 of 10 zones** | 3, 6, 7, 8 (functional failures) + 0,1,2,4,5 (wrong strategy) | 30-day data audit revealed: **(a)** Drip zones 7 (Garden) and 8 (Grapes) have ZERO watering events in 30 days despite sitting at 0% balance (below MAD 19mm/23mm) — they should trigger every cycle. **(b)** Spray zones 3 (Enclosed Backyard B) and 6 (Southwest) got only 2 runs each in 30 days (≈3 min/run) while zones 0/1/2/4/5 got 6–18 runs — chronic per-zone starvation. **(c)** All spray zones have `cycle_soak: true, cycle_run_min: 8, cycle_count: 3` in config but the engine only honors `max_runtime_min` — cycle-and-soak is dead config (only referenced in `log_skip_event` gallons estimator at line 608). **(d)** Even when working, the strategy is shallow-frequent (24 min daily ≈ 0.36" net gain after same-day ET) instead of deep-infrequent (0.5–0.75"/cycle every 2–3 days, lawn best practice). Root depth assumption of 6" yields TAW = 0.9" — too small a reservoir to hold a proper deep soak, forcing daily refills. | **Four distinct root causes:** **(1) No zone serialization in `run_cycle`** (`irrigation.py` line 730–770): the loop calls `start_zone_watering(zid, ...)` on every dry zone in the same cycle pass. If the ESP32 / household water pressure can only handle 1 valve at a time, the unlucky zones never get water. There is no queue, round-robin, fairness counter, or "already watered N zones this cycle" guard. **(2) Drip-zone evening window suspect** — `evening_zones: [7, 8]` is in config but with zero observed runs, either the window check (`is_in_watering_window`) is rejecting them, or the valve open is silently failing, or the evaluation loop never reaches them. Needs log inspection. **(3) `cycle_soak` is documented behavior that doesn't exist** — `_evaluate_active_zone` only enforces `max_runtime_min × scale_pct`. Config values `cycle_soak`, `cycle_run_min`, `cycle_count` are read nowhere in the runtime path. Either implement them or remove from config and docs. **(4) Tuning defaults assume shallow turf** — `default_root_depth_in: 6` and `max_runtime_min: 24` jointly enforce a shallow-frequent watering pattern that's the opposite of healthy turf irrigation. For a 6" root zone at 0.15 AWC, TAW = 22.86 mm, MAD = 11.43 mm; daily peak ETc ≈ 5 mm refills to ~22 mm (clamped at TAW), so soil stays in 50–100% band perpetually. Even with proper serialization this is bad practice — trains roots shallow, half the water in the soil column unused, vicious cycle. | ⏳ **Not fixed.** Proposed remediation (in priority order): **(A) Diagnose drip zones first** — tail server.log during 8 PM evening window, confirm whether zones 7/8 are being evaluated and what decision returns. Likely a window/eval bug. **(B) Add zone serialization** — modify `run_cycle` to maintain a running "valves opened this cycle" set, defer remaining dry zones to next 5-min pass, OR explicitly serialize within the watering window using elapsed time. Prevents parallel-open starvation. **(C) Either implement or delete `cycle_soak`** — if hilly drainage makes cycle-and-soak unnecessary (already discussed for this property — SAM check valves drain anyway), remove the config keys and update README. If retained, wire into `_evaluate_active_zone` to inject soak gaps. **(D) Retune for deep-infrequent** — bump `default_root_depth_in` from 6 → 8 (TAW becomes 30 mm, MAD becomes 15 mm, allows ~2-day cycles), bump spray `max_runtime_min` from 24 → 35 (applies ~0.76" per cycle, refills 8" zone to field capacity). Net effect: zones water every 2–3 days for 35 min instead of daily for 24 min, soil cycles 50→100%, deeper roots over a season, less total water. **Do NOT apply (D) until (A)–(C) are fixed** — making the cycles longer while 4 zones still fail to water just deepens the asymmetry. | ✅ **Resolved 2026-06-02 18:00** — Root cause was Bug #5 (TypeError) + a separate dead "No valid soil sensor configured" gate that wrapped `evaluate_zone` in older builds. Both were patched out before 17:51 restart. Post-restart verification (`journalctl --since '4 hours ago'`): cycles now complete every 5 min with proper per-zone decisions. Zones 0/1/2/4/5 correctly skip (balance 18-21mm > MAD 11.43mm — well-watered from manual events). Zones 3/6 sit at 0% balance and will water at next 4 AM window (same-day guard releases at midnight). Zone 7 at 0% balance will water tonight 20:00-22:00 evening window. **Zone 8 (Grapes) flipped to `installed: false`** per user — not plumbed yet, will never turn on. Audit findings (a)/(b) are obsolete — they were symptoms of Bug #5. Finding (c) dead `cycle_soak` config stays open for cleanup. Finding (d) deep-infrequent retune deferred until after observing 2-3 days of healthy automated runs. |

#### Process Failure RCA: Why Bugs #30-35 Took All Day

**Pattern:** Six bugs, each "fixed" independently, each fix revealing the next. Classic symptom of treating symptoms instead of root causes.

**The fundamental mistake:** The precip chart was built by copying patterns from the moisture line chart without auditing unit consistency. Three different code paths build bar data using three different unit conversions:

```
rainBarData:           p.rain × rd / 100    (moisture-fraction)
forecastSprinklerBars: p.sprinkler × rd / 100  (moisture-fraction)  
actualBarData:         precipRate × sec/3600    (raw inches)
```

The rain and forecast code paths were written together (same developer session, same mental model). The `actualBarData` path was added later in a different session to show DB events — and it used a different formula without checking what the other datasets used. Once they were on the same chart, the visual mismatch was inevitable.

**Why it took 6 bugs to find:** Each bug appeared as a tooltip problem (#30 jumping time, #31 wrong month, #32 phantom items, #33 wrong title date, #34 wrong scale). The tooltip callbacks were patched 5 times. But the tooltip was never the problem — **the data was wrong.** The tooltip just made the data discrepancy visible. We kept "fixing" how the tooltip DISPLAYED bad data instead of asking "is the data correct?"

**Process fix for future:** When a bar chart shows unexpected values, verify the RAW DATA VALUES first (console.log the arrays) before touching tooltip callbacks. If two things on the same axis look wrong relative to each other, check units before checking rendering.

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

### 2026-06-02 evening — Audit follow-through: bug #5 + dead sensor-gate + zone 8 install flag

**User instruction:** "we don't have zones 8 and 9 set up they should never turn on. all the others are live and ready to start watering... feel free to begin fixing"

**Investigation chain:**
1. Pulled server's authoritative `irrigation.py` to `c:\MyCode\smart-garden\server-prod\` (heritage-vault rule: server is source of truth)
2. SQL audit showed 100% of 30-day watering events have `trigger_reason='manual'` — **zero auto-watering** for ANY zone, ever, in the audit window
3. Log inspection revealed two cascading dead-code bugs:
   - **Old soil-sensor gate** (`WARNING: Zone N is installed but has no valid soil sensor; skipping automatic watering decision` + `INFO: Zone N: skip — No valid soil sensor configured`) emitted on every cycle for every zone. Last seen in logs at 2026-06-01 17:06:08.
   - **`TypeError: list indices must be integers or slices, not NoneType`** at `irrigation.py:671` crashed the entire `run_cycle` job from the moment the new code deployed (Jun 1 ~17:00) through this morning at 4 AM. Per-zone log lines were absent because the cycle crashed at the `soil_readings` build step before reaching the eval loop.
4. Confirmed both fixes already on server: current `irrigation.py:690-695` has `if sensor_idx is None: continue` and the dead sensor-gate log calls are gone.
5. Verified post-restart cycle (17:51:15 → 17:51:37+): all 8 installed zones evaluated correctly. Zones 0/1/2/4/5 skip on balance > MAD; zones 3/6 skip on same-day guard (manual events earlier today); zone 7 waits for evening window.

**Changes deployed this session:**
- `config.yaml`: zone 8 (Grapes) flipped from `installed: true` → `installed: false` per user (not plumbed). Backup at `~/smart-garden-server/config.yaml.bak-zone8fix`.
- `smart-garden-server.service` restarted clean (PID 206597 then 210632) — all subsequent cycles run zones 0-7 only, skip zones 8 and 9.

**Current system state (verified 17:55):**
| Zone | Balance | MAD | Status |
|------|---------|-----|--------|
| 0 Front Yard A | 19.1 mm (84%) | 11.4 mm | ✅ Skip — well watered |
| 1 Front Yard B | 19.1 mm (84%) | 11.4 mm | ✅ Skip — well watered |
| 2 Backyard A | 19.4 mm (85%) | 11.4 mm | ✅ Skip — well watered |
| 3 Backyard B | 0.0 mm (0%) | 11.4 mm | ⏳ Will water 4 AM Jun 3 (same-day guard releases at midnight) |
| 4 Southeast | 21.3 mm (93%) | 11.4 mm | ✅ Skip — well watered |
| 5 South | 18.5 mm (81%) | 11.4 mm | ✅ Skip — well watered |
| 6 Southwest | 0.0 mm (0%) | 11.4 mm | ⏳ Will water 4 AM Jun 3 (same-day guard releases at midnight) |
| 7 Garden (drip) | 0.0 mm (0%) | 19.1 mm | ⏳ Will water 20:00 tonight (evening window) |
| 8 Grapes | n/a | n/a | 🚫 Not installed — engine skips |
| 9 Spare | n/a | n/a | 🚫 Not installed — engine skips |

**Validation plan:** Watch journalctl tonight at 20:00 (zone 7 should fire) and tomorrow at 04:00 (zones 3 and 6 should fire). If they do, Bug #37 is fully closed. If not, dig back in.

---

### 2026-06-02 evening — Strategic audit + Kc tune to FAO-56

User asked: "can you do an audit and tell me if the approach really is good" (the watering STRATEGY, not the bugs). Verdict: approach is sound — ET-based water balance (FAO-56), 50% MAD trigger, 4-7 AM morning window, deep cycles (~0.52 in applied = 58% of TAW), rain/wind/freeze skips, same-day guard. All match cool-season turfgrass best practices for PNW.

**Three tuning gaps identified:**
1. Kc values 15-30% too low (audit doc IRRIGATION-AUDIT.md flagged this; Open Bug #4)
2. Root depth 6" conservative for established lawn (8" supportable with deep-infrequent)
3. Precip rates are guesses, ±30% off until catch-can test

**Action taken: fixed #1 immediately.**

Spray zones 0-6 Kc updated from old [0.6, 0.75, 0.8, 0.65] (and [0.6, 0.7, 0.85, 0.6] for zones 2/3) to FAO-56 cool-season turf standard:

```yaml
kc:
  - 0.85   # Spring
  - 0.90   # Early Summer
  - 0.95   # Peak Summer
  - 0.85   # Fall
```

**Untouched:** zone 7 (garden drip, different crop), zone 8 (grapes, not installed), zone 9 (spare, not installed).

**Deploy steps:**
- Pulled server config to `C:\MyCode\smart-garden\server-prod\config.yaml` (heritage-vault rule).
- Edited Kc lines for zones 0-6.
- Validated YAML parse via python3 on server.
- Backed up at `~/smart-garden-server/config.yaml.bak-kc-fao56-20260602-1856`.
- Restarted `smart-garden-server.service` — clean start, scheduler running.

**Expected impact:** ET demand calculated from these Kc will be ~25-30% higher in peak summer. Engine will trigger watering ~25% more often (e.g., every 2.5 days instead of every 3.5 days at current weather), aligning with the 1-1.5 in/week PNW lawn requirement.

**Hold off on:**
- Root depth bump to 8" — wait 2-3 weeks until validated lawn health under new Kc.
- Catch-can test for precip rates — Saturday physical task.

Kc tune deployed without waiting for 3-day auto-watering validation per user direction ("do it").

---

## 2026-06-02 (Evening, second pass) — Forecast simulator AWC bug + chart audit

### Trigger
After deploying the Kc fix, user pushed back: Zone 6 chart still showed a *daily* watering forecast despite my claim of "every 2-3 days". I audited the forecast simulator code in [moisture_sim.html](server-prod/templates/moisture_sim.html) and found a real bug.

### Bug found: missing AWC in chart's forecast formulas

The forecast simulator (lines 548-588, the branch that runs when no DB balance exists for a forecast day) treated `rootDepth` (inches of soil) as the moisture bucket size, but the *plant-available* bucket is `rootDepth × AWC` (where AWC=0.15 for our sandy-loam default). This under-counted ET drain and irrigation credit by ~6.7×.

```js
// Before — bucket = full root depth (wrong, treats all soil water as available)
var etPctDay = (et0_in / rootDepth) * 100 * kc;
var rainPctDay = (fcstRainIn * 0.65 / rootDepth) * 100;
var waterPerStep = (zone.precipRate / 4) * (100 / rootDepth) * fracOfStep;

// After — bucket = plant-available water only (FAO-56 correct)
var awc = 0.15;
var bucketIn = rootDepth * awc;
var etPctDay = (et0_in * kc / bucketIn) * 100;
var rainPctDay = (fcstRainIn * 0.65 / bucketIn) * 100;
var waterPerStep = (zone.precipRate / 4) * (100 / bucketIn) * fracOfStep;
```

**Direction of error pre-fix:** chart was *under-predicting* both watering frequency AND cycle credit. After fix, both jump to match the real engine.

Backed up to `~/smart-garden-server/templates/moisture_sim.html.bak-awc-fix-20260602-192103`. Service restarted clean.

### Post-fix audit — chart vs reality math (Zone 6 / Southwest)

Verified the new chart against engine math + real DB + Open-Meteo forecast.

**Setup:**
- bucketIn = 6" root × 0.15 AWC = **0.9"** of plant-available water
- TAW = 22.86mm, MAD = 11.43mm (50%)
- precipRate 1.3 iph, max_runtime 24min → 0.52" per cycle
- Per-cycle credit as % = 0.52 / 0.9 = **57.8%**

**Open-Meteo forecast (verified imperial units do apply to ET₀ — chart's `precipitation_unit=inch` covers ET too):**

| Date | ET₀ (in) | Rain (in) |
|------|----------|-----------|
| Wed Jun 3 | 0.134 | 0.000 |
| Thu Jun 4 | 0.147 | 0.000 |
| Fri Jun 5 | 0.067 | 0.264 |
| Sat Jun 6 | 0.100 | 0.437 |
| Sun Jun 7 | 0.109 | 0.071 |
| Mon Jun 8 | 0.125 | 0.000 |

**Hand-calculated forecast trace (starting from real DB balance = 0% on Tue Jun 2):**

| Day | Start | Event | End |
|-----|-------|-------|-----|
| Wed | 0% | +57.8 cycle, −13.4 ET | ~44% |
| Thu | 44% | +25.6 cycle (capped at 70% target), −14.7 ET | ~55% |
| Fri | 55% | −6.7 ET, +19.1 rain (no cycle, above MAD) | ~67% |
| Sat | 67% | −10.0 ET, +31.6 rain (heavy storm) | ~89% |
| Sun | 89% | −10.9 ET, +5.1 rain | ~83% |
| Mon | 83% | −12.5 ET | ~71% |

**Chart visual reading (zone 6 / Southwest, 7d view, 19:25 PT):**

| Day | Chart shows | Math predicts | Match |
|-----|-------------|---------------|-------|
| Wed AM cycle | jump to ~55% | 57.8% | ✅ |
| Wed PM | dip into stress zone (~45%) | 44% | ✅ |
| Thu AM cycle | jump to ~70% | 70% (capped) | ✅ |
| Thu PM | drift down to ~55% | 55% | ✅ |
| Fri-Sat climb | climb to ~80% | 67% → 89% | ✅ |
| Sun peak | ~80% | 83% | ✅ |
| Mon drainage | drop to ~70% | 71% | ✅ |

**Verdict: chart is correct.** Every key behavior matches engine math within visual reading tolerance.

### Why it *looks* like daily watering on this view
The chart fires cycles **two days in a row** (Wed AM + Thu AM) because the system started at empty (0% balance). After Thu's cycle plus heavy weekend rain, watering stops — no cycles Fri-Mon. That's the every-2-3-days steady state I described earlier. The two consecutive cycles are the recovery from 0%, not the steady state.

### Other findings during audit (lower priority)

| # | Issue | Severity | Action |
|---|-------|----------|--------|
| 1 | Dropdown labels off-by-one — line 177 has `Zone {{ z.id + 1 }}`, so zone 6 displays as "Zone 7 — Southwest" | Cosmetic | Future fix |
| 2 | Sprinkler bar height reports full 15-min step even when MAD target cap short-circuits run early | Cosmetic | Future fix |
| 3 | Forecast simulator uses hardcoded `kc = 0.90` (or 0.40 winter) — works for spray (real 0.85-0.95) but over-predicts ET for drip zone 7 (real Kc 0.5-0.7) | Real for zone 7 only | Fix when auditing zone 7 |
| 4 | Two other `(100 / rootDepth)` patterns at lines ~643 + ~859 in different chart modes — should also use `bucketIn` | Unknown impact | Audit separately if needed |

### Files changed
- `server-prod/templates/moisture_sim.html` lines 548-588 (forecast simulator AWC fix)

### Validation pending
- Watch for first auto cycles tonight (zone 7 at 20:00) and tomorrow (zones 3 + 6 at 04:00).

---

## 2026-06-02 (Evening, third pass) — Dropdown label + per-zone Kc fix

After the AWC fix verified the chart matches reality, fixed two of the four side findings from that audit.

### Fix #1 — Dropdown off-by-one ❌ REVERTED
Initial change (line 177: `Zone {{ z.id + 1 }}` → `Zone {{ z.id }}`) was wrong. Reverted immediately. The whole rest of the dashboard (`index.html` lines 2368, 2991, 3834, 4882, 5288) uses `z.id + 1` — IDs are 0-indexed internally but **displayed as 1-indexed everywhere**. The "off-by-one" the audit flagged was actually the correct convention; the screenshot mis-read came from me, not the code.

### Fix #2 — Per-zone Kc in forecast simulator
Before: hardcoded `kc = (month >= 3 && month <= 11) ? 0.90 : 0.40` for *every* zone, including drip zone 7 (Garden, real Kc 0.5-0.7) and grapes zone 8 (0.7-1.15).

After: uses each zone's actual `kc[]` array from config.yaml with the engine's season mapping:

```js
// month → seasonIdx (matches weather.get_season_index() in engine)
// 3-5  = spring        → kc[0]
// 6    = early summer  → kc[1]
// 7-8  = peak          → kc[2]
// 9-10 = fall          → kc[3]
// else = dormant       → kc=0 (no ET drain)
var seasonIdx = (month >= 3 && month <= 5) ? 0 : (month === 6) ? 1 : (month >= 7 && month <= 8) ? 2 : (month >= 9 && month <= 10) ? 3 : -1;
var kc = seasonIdx >= 0 ? (zone.kc[seasonIdx] || 0.85) : 0;
```

`getZoneBrainConfig()` now passes through `z.kc` from the server-rendered ZONES array.

**Impact:** Zone 7 forecast ET was previously over-predicted by ~50% (used 0.90 instead of real 0.60 for June). Should now show watering recommendations every 3-4 days at current weather instead of every ~2 days. Zones 0-6 are unchanged (their real Kc happens to be ~0.90 in peak season).

### Skipped (not worth fixing)
- **Sprinkler bar overshoot when MAD-cap cuts cycle short** — cosmetic, doesn't affect decisions.
- **Two other `(100 / rootDepth)` patterns at lines ~643 + ~859** — inside `generateBrainData()`, only runs when user selects a historical year (2024/2025) from the year dropdown. Doesn't affect the live 2026 view.

### Files changed
- `server-prod/templates/moisture_sim.html` line 177 (dropdown), lines 337-346 (kc passthrough), lines 552-558 (per-zone Kc in forecast)
- Server backup: `~/smart-garden-server/templates/moisture_sim.html.bak-kc-zonelabel-20260602-193X`

---

## 2026-06-02 (Evening, fourth pass) — Chart audit + 6-bug fix

User noticed sprinkler bars and moisture-line jumps weren't aligned in time on the moisture-sim chart. Investigation revealed a family of related bugs all stemming from the same anti-pattern: the chart re-implements engine models in JS instead of consuming engine outputs.

### Bugs filed (8 total — #7 + adjacency audit)
| # | Severity | Title | Status |
|---|----------|-------|--------|
| [#7](https://github.com/jamesearlpace/smart-garden/issues/7) | High | Sprinkler bars vs moisture rise misaligned (8–18+ hr) | ✅ Closed |
| [#8](https://github.com/jamesearlpace/smart-garden/issues/8) | High | Brain sim hardcoded `KC_ACTIVE=0.90` | ✅ Closed |
| [#9](https://github.com/jamesearlpace/smart-garden/issues/9) | High | Two different season models in same chart | ✅ Closed |
| [#10](https://github.com/jamesearlpace/smart-garden/issues/10) | Med | Brain sim hardcoded 04-06AM, no evening_zones | ⏳ Open |
| [#11](https://github.com/jamesearlpace/smart-garden/issues/11) | Med | Rain credit dropped when hourly==0 | ✅ Closed |
| [#12](https://github.com/jamesearlpace/smart-garden/issues/12) | Low | `rootDepthSchedule` duplicated | ✅ Closed |
| [#13](https://github.com/jamesearlpace/smart-garden/issues/13) | Low | Rain runoff coefficients duplicated from `weather.py` | ⏳ Open |
| [#14](https://github.com/jamesearlpace/smart-garden/issues/14) | Low | ET sine overshoots 1.0 at h=20 m=15/30/45 | ✅ Closed |

### Root cause of #7 (the trigger)
`generateRealData2026()` had **two parallel sources of truth for irrigation**:
- **Sprinkler bars** built from `liveData.waterings` → bar `x` = actual `start_ts`
- **Moisture line** built from `soil_balance.irrigation_mm` (daily total) → splattered across hardcoded 04:00–06:00 window

For morning cycles the offset was ~46 min (line crested at 06:00, bar at 04:00). For evening cycles (zone 7 drip at 20:00) the offset was **wrong direction in time by ~14h** — the moisture jump showed at 06:00 of the same calendar day that the bar showed at 20:00.

### Fix (single PR, all 6 closed-issue fixes)
Extracted shared helpers at the top of `moisture_sim.html`:
```js
function getSeasonIndex(month) { ... }           // MIRRORS weather.py
function getSeasonalKc(zone, month) { ... }      // reads zone.kc[idx]
var ROOT_DEPTH_SCHEDULE = { 3:4, ... };
function getSeasonalRootDepth(zone, month) { ... }
function getEtFraction(h, m) { ... }             // CLAMPED to [0,1]
function parseLocalTs(ts) { ... }                // parses 'YYYY-MM-DDTHH:MM:SS' as LOCAL not UTC
```

Then:
- **#7 fix:** `generateRealData2026` now builds `actualIrrigByStep` from `watering_event` rows (same source as bars) and uses `irrigCumulative[step]` for the line. 4-6AM ramp retained only as fallback for the edge case where balance shows irrigation but no event rows exist.
- **#8, #9, #12, #14:** Both chart functions now call the shared helpers. No more `KC_ACTIVE`/`KC_DORMANT` constants, no more duplicated `rootDepthSchedule`, no more two season-mappings, no more `h <= 20` overshoot.
- **#11:** When `totalHourlyRain === 0 && rainDailyPct > 0`, line now spreads the daily rain credit across 08:00–20:00 instead of dropping it.

### Why these all shipped together
Every closed issue had the same architectural smell — chart JS owns its own copy of an engine model. Extracting the helpers fixed 5 of them as a side-effect of fixing #7. #10 (evening_zones support in historical brain sim) and #13 (runoff coefficients via API) require bigger surface changes and stay open.

### Prevention rules captured in issue bodies
1. Bars and line for the same physical event must share one source of truth.
2. Banned pattern: hardcoded hour windows in chart code (`h >= 4`, `// 4-6AM`, etc.).
3. Any model constant that exists in `config.yaml` must never appear as a literal in chart JS.
4. When fixing one of the two parallel chart functions, always check the sibling.
5. Closed-interval boundary checks (`<=`) on time windows produce off-by-one bugs — use half-open intervals consistently.
6. Models that exist in `weather.py`/`engine.py` must not be re-implemented in chart JS — share via API or extract into a documented helper that names the Python source.

### Validation
- Service restarted clean: `systemctl is-active smart-garden-server` → `active`
- Server template has 4 `getSeasonalKc` refs + 3 `actualIrrigByStep` refs — confirmed deployed
- No startup errors in journalctl
- Need user to verify by reloading `/moisture-sim` and confirming bar/line alignment for zone 4 around 2026-05-31 (the May 31 manual-flooding day was the clearest repro)

### Files changed
- `server-prod/templates/moisture_sim.html` — added helpers block (~lines 350-388), updated `generateRealData2026` (signature + per-event lookup + helper usage), updated `generateBrainData` (constants removed, helper usage, h<20 boundary), updated call site to pass `liveData.waterings`
- Local hash + server hash verified identical after deploy

---

## 2026-06-02 (Evening, fifth pass) — Deep RCA on bug #15 (regression introduced by #7 fix)

### TL;DR

Roughly 30 minutes after deploying the fix for [#7](https://github.com/jamesearlpace/smart-garden/issues/7), the user reloaded the chart and immediately spotted: tiny red sprinkler bars (manual 2-minute tests) were producing huge green moisture jumps. The "fix" introduced a per-event credit formula that overshot short events by 4–10x. Bug filed as [#15](https://github.com/jamesearlpace/smart-garden/issues/15), fixed and shipped within 10 minutes of report. The repair worked, but the more interesting question is **why I shipped the regression in the first place** — because I had just written six "prevention rules" that, if followed, would have caught this before it left my editor.

### Chronology

| Time | Event |
|------|-------|
| ~19:30 | Wrote 8 GitHub issues (#7–#14) documenting bugs found in chart audit. Each had a "Prevention Rules" section. |
| ~19:50 | User said "lets go" → I implemented helpers + per-event irrigation credit. |
| ~20:05 | Deployed. Service confirmed active. Smoke-checked the HTML returned `getSeasonalKc` and `actualIrrigByStep` — assumed correctness from presence. |
| ~20:15 | Updated journey doc proudly noting 6 bugs fixed with prevention rules. |
| ~20:20 | User loaded the chart, attached screenshot: *"the moisture % jumps disproportionately high with such little water from rain and sprinklers… look at it very carefully."* |
| ~20:25 | Investigated. Found the snapping bug. Filed #15. Fixed. Deployed. |

### The defect — exact code

The fix for #7 introduced this loop inside `generateRealData2026`:

```js
actualWaterings.forEach(function(w) {
  if (!w.start_ts || !w.duration_sec || w.duration_sec <= 0) return;
  var wStart = parseLocalTs(w.start_ts);
  var nSteps = Math.max(1, Math.round(w.duration_sec / 900));        // ← BUG
  var mmPerStep = (zone.precipRate * 25.4) / 4;                       // ← assumes full 15-min step
  for (var si = 0; si < nSteps; si++) {
    var stepTime = new Date(wStart.getTime() + si * 900000);
    // … credit pctPerStep to actualIrrigByStep[gKey]
  }
});
```

Three things are wrong on those two lines:

1. **`Math.round(duration_sec / 900)`** snaps any duration under 7.5 minutes to **0 steps**, and any duration between 7.5 and 22.5 minutes to **1 step**.
2. **`Math.max(1, …)`** forces the 0-step case up to **1 full step** — a 30-second test gets credited as if the sprinkler ran a full 15 minutes.
3. **`mmPerStep = precipRate × 25.4 / 4`** is *constant* per step. It assumes every step is full. There is no concept of "this step had only 30 seconds of water in it."

### Math, with real numbers

Zone 5 ("Southeast") config: `precip_rate_iph: 1.3`, root depth 6", AWC 0.15 → TAW = 22.86 mm.

A full 15-minute step at 1.3 in/hr applies `1.3 × 0.25 × 25.4 = 8.255 mm` = **36.1% of TAW per step**.

For each watering event in the visible 7-day window:

| Event | Real duration | Real water | My credit (broken) | Overshoot |
|-------|--------------|------------|-------------------|-----------|
| `88s`  | 1.5 min  | 0.83 mm (3.6% TAW)  | 36.1%  | **10×** |
| `127s` | 2.1 min  | 1.31 mm (5.7% TAW)  | 36.1%  | 6×      |
| `238s` | 4.0 min  | 2.18 mm (9.5% TAW)  | 36.1%  | 4×      |
| `1264s` | 21.1 min | 11.55 mm (50% TAW) | 36.1% (rounds to 1!) | **0.7×** (undershoots) |
| `1550s` | 25.8 min | 14.17 mm (62%)     | 72.2% (2 steps)      | 1.2×    |
| `3718s` | 62.0 min | 33.98 mm (149% → capped) | 144.4% (4 steps) | ~accurate |

Note the 1264s case: `round(1264/900) = round(1.4) = 1`, so 21 minutes of real watering gets credited as one 15-minute step. The bug isn't just "short events overshoot" — it's a step-quantization that breaks at multiple points on the duration axis.

### Visible discontinuity that triggered the user report

The engine's `database.get_daily_irrigation_mm()` is correct: `precipRate × total_sec / 3600 × 25.4`. So `soil_balance.irrigation_mm` and therefore `balance_mm` are accurate.

Each day in the chart loop starts from `startPct = prevBal.balance_mm / prevBal.taw_mm × 100` — the **engine's** end-of-day value. Mid-day, the chart's per-event credit inflates the line. At midnight the line snaps back to the engine truth.

That snap is exactly what the user circled in the screenshot: green moisture rockets to 100%, then the line plummets at the day boundary because the engine never agreed the soil was that wet.

### Why I shipped it

This is the embarrassing part. Bug #7's prevention rules explicitly said:

> *"Bars and line for the same physical event must share one source of truth."*

I read that as "use the same input data" and stopped there. The bars use `precipRate × duration_sec / 3600` (exact). My new line-credit code used `precipRate × nSteps × 0.25` (snapped). **Same data, different math — same class of bug as #7, just hidden behind a slightly different formula.** The prevention rule was correct but underspecified: data alone isn't enough; the *math applied to the data* has to match too.

Three other contributing factors:

1. **No sanity check.** The chart never asserts `sum(actualIrrigByStep for day) ≈ bal.irrigation_mm / bal.taw_mm × 100`. That single assertion would have failed on the first event I tested.
2. **Smoke test was theatre.** My deploy verification was `grep -c 'actualIrrigByStep' moisture_sim.html → 3` — confirms the *string* was deployed, not that the *math* was right. Counted as "✅ deployed" in my journey-doc update.
3. **No mental model of the input distribution.** I treated the events as "what does the engine produce when it autoruns?" — i.e. 8-minute cycles aligned to step boundaries. The real distribution includes lots of short manual pulses from user testing. `Math.max(1, round(x))` is a code smell that only matters when `x < 0.5`, which happens constantly in this workload.

### Pattern: chart-vs-engine math drift

This is now the **third** chart bug in the same general shape this session:
- **#7**: bars from event table, line from daily-total snapped to 4-6AM ramp → time offset.
- **#8/#9/#12**: chart constants drifted from engine constants → wrong magnitudes.
- **#15** (this one): bars use exact duration math, line uses step-quantized duration math → magnitude error on short events.

All three are variants of the same anti-pattern: **the chart re-derives a quantity that the engine already computed, and the two derivations disagree.** The fixes for #7 and #8 reduced surface area, but #15 shows that "shared data source" isn't a strong enough invariant. The strong invariant is **shared formula** or **shared computed output**.

### Prevention rules added (extends the #7 rules)

7. **For any per-event quantity (irrigation mm, irrigation %, rain mm), the chart's formula must be character-for-character the same as the engine's formula.** If it can't be (e.g. the engine returns daily totals only), the chart should consume the engine's output, not invent a new derivation.
8. **Banned pattern: `Math.max(1, Math.round(x / step))`** for any physical quantity. If `x` is duration in seconds and `step` is sub-event granularity, this corrupts short events. Use `Math.floor(start/step) → loop while stepStart < end → overlap = min(stepEnd, end) - max(stepStart, start)`.
9. **Day-boundary discontinuity is a smoke alarm.** If the moisture line jumps at midnight by more than ~5% (i.e. mid-day chart value disagrees with engine end-of-day), one of them is wrong. The engine is more trusted; the chart needs investigation.
10. **Deploy verification must check *math*, not *presence*.** "Grep finds the new function name" is not verification. The minimum bar is "open the page, look at the rendered chart, sanity-check at least one event."
11. **Subtle process rule: a prevention-rules section in a bug write-up is worth nothing if I don't audit my own fix against it before deploy.** The #7 prevention rule existed for ~20 minutes before I violated it in the fix for #7.

### Fix

```js
var firstStepStart = Math.floor(wStart.getTime() / 900000) * 900000;
for (var stepStartMs = firstStepStart; stepStartMs < wEndMs; stepStartMs += 900000) {
  var overlapSec = (Math.min(stepStartMs + 900000, wEndMs) - Math.max(stepStartMs, wStart.getTime())) / 1000;
  if (overlapSec <= 0) continue;
  var mmThisStep = zone.precipRate * (overlapSec / 3600) * 25.4;
  var pctThisStep = (mmThisStep / tawMm) * 100;
  // …
}
```

Step-overlap loop. A 30-second event hits one step with `overlapSec = 30` → credits 0.018 in × 25.4 = 0.45 mm = 2% TAW. A 2-minute event credits 5.7%. A 21-minute event hits two steps with 15 + 6 minutes → credits the correct total. Matches the engine's daily sum within rounding.

### Validation

- Deployed `c01b…` → new hash, restarted, service `active`.
- Chart visual not yet re-verified by user (waiting on reload).
- Should now satisfy invariant: `sum(actualIrrigByStep for day) === bal.irrigation_mm / bal.taw_mm × 100` (within float epsilon). **Should add this as a console.assert** in a future pass.

### Open follow-ups from this RCA

- **[#17](https://github.com/jamesearlpace/smart-garden/issues/17) filed** — Add a chart-vs-engine daily-total assertion. This is the single highest-leverage missing test. Would have caught #15 instantly. Recommended fix-order: do #17 FIRST so #16 can be validated against it.
- **[#16](https://github.com/jamesearlpace/smart-garden/issues/16) filed** — `generateBrainData` has 3 latent defects in the same code block:
  1. Same step-quantization bug as #15 (line 731)
  2. Timezone bug: `new Date(w.start_ts)` instead of `parseLocalTs()` (line 729)
  3. Physical-scale mismatch: divides by `rootDepth` (inches) instead of `rootDepth × AWC` (TAW) → understates moisture changes by 6.67× vs the engine and vs `generateRealData2026`
  
  Only affects historical-year dropdown (2024/2025). Not in user's hot path right now, but the function is structurally broken — three different physical bugs in 20 lines. Issue body recommends merging or deleting `generateBrainData` in favor of `generateRealData2026` output.
- Stop treating "string present in deployed HTML" as deploy verification. Need a real smoke test of the rendered chart. (Captured as rule #16 in issue #17.)

---

## 2026-06-02 (Sixth pass) — Implementing #17 + #16, and uncovering that defect 3 was a misdiagnosis

### TL;DR

Shipped #17 (chart-vs-engine assertion) cleanly. Shipped 2 of the 3 #16 defects (step-quantization, TZ) the same way. Defect 3 ("physical scale mismatch") turned out to be wrong: `generateBrainData` is **internally** self-consistent in a different scale than the engine, and changing only the irrigation overlay would have made the chart less coherent, not more. Filed [#18](https://github.com/jamesearlpace/smart-garden/issues/18) to track the architectural scale-unification work and closed #16 as partially fixed + redirected.

### #17 — assertion shipped

Added an IIFE `assertChartMatchesEngine()` in `generateRealData2026` right after `actualIrrigByStep` is built, before the day loop:

- Sums per-day step credits from the lookup.
- Compares to engine truth: `bal.irrigation_mm / bal.taw_mm × 100`.
- `console.warn`s when delta > 5% AND engine value > 0.5% (filters noise-floor days where both are ~0).
- Format: `[chart-engine drift] zone=N day=YYYY-MM-DD chart=X.X% engine=Y.Y% delta=Z.Z%`.

If the #15 bug had existed when this assertion was in place, it would have fired on page load instead of waiting for a user to spot a tall green bar in a screenshot.

### #16 defects 1+2 — shipped

`generateBrainData`'s `actualIrrigMap` loop now:
- Uses the same step-overlap math as `generateRealData2026` (no more `Math.max(1, Math.round(duration_sec/900))`).
- Uses `parseLocalTs(w.start_ts)` instead of `new Date(w.start_ts)`.

### #16 defect 3 — misdiagnosis, redirected to #18

When I went to fix the "scale mismatch" I read the whole function and realized: `generateBrainData` uses **"% of root depth in inches"** as its moisture scale **everywhere** — ET drain (line 867), rain credit (877), daily drain for arm threshold (889), expected-gain for rain skip (931), sprinkler credit (986), and the daily summary (1742–1743). All 7 sites divide by raw `rootDepth`. The function is **internally consistent**, just in a different scale than the engine (which uses % of TAW).

For Zone 5 (AWC=0.15), the two scales differ by `1/0.15 = 6.67×`. If I'd applied the originally-proposed fix to *only* the irrigation overlay (`actualIrrigMap`), the actual events would have credited ~6.67× more than the brain sim's own simulated rain and sprinkler events on the same chart. The overlay would have visually overwhelmed the baseline.

So `actualIrrigMap` now matches the brain's existing scale: `inchesThisStep / rootDepthIn × 100`. The deeper architectural choice — "should the whole brain function migrate to TAW, and what does that do to `madPct` and `wiltPct` interpretation?" — is tracked in **[#18](https://github.com/jamesearlpace/smart-garden/issues/18)**.

### What this teaches

The bug that *looks* local often isn't. I filed #16 expecting to make 3 surgical edits because I'd grepped for `(100 / rootDepth)` and found 2 sites and assumed they were defects. They aren't defects in isolation — they're the function's chosen scale. The actual issue is one level up: two functions on the same chart use two different physical scales, and **either** is internally fine; what's broken is the lack of a single canonical scale.

This is a different failure mode than #7/#15 (chart re-derives what engine already computed). Here both functions are correct in their own frame — the system bug is the absence of a shared frame.

### Other things noticed but left alone

Three more `new Date(w.start_ts)` TZ bugs in `moisture_sim.html` (lines 1035, 1179, 1317) for cycle clustering / daily marker / event filter. These don't visibly break anything because the deltas are in hours/days and the TZ offset is consistent. Noted in #16 close-out so the next person in this file sees them.

### Rules added (extends #15's #7–#11)

12. **Before "fixing" a numerical inconsistency between two functions, read both functions end-to-end.** A divisor that looks wrong in isolation may be the chosen scale of an internally-consistent function. Changing one site without changing the others is worse than not changing anything.
13. **"Scale mismatch" between modules is an architectural bug, not a line-edit.** Decide canonical scale first, migrate the loser, then change the line.
14. **An assertion's value is multiplicative with the deploy cadence.** #17 took 15 minutes to add and now runs on every page load. If it ever fires, it saves a screenshot-and-RCA cycle. This is what the time should be spent on after a regression like #15.

### Deploy

- md5 `77bf7f7a...` on Acer at `~/smart-garden-server/templates/moisture_sim.html`.
- Service `active`.
- Verification: `grep -c 'chart-engine drift'` → 1; `grep -c 'inchesThisStep'` → 2; `grep -c 'parseLocalTs(w.start_ts)'` → 2; `grep -c 'Math.max(1, Math.round(w.duration_sec'` → 0.
- User-side check: reload `/moisture-sim`, open browser console, switch to Zone 5. Either silence (assertion fine) or `[chart-engine drift]` warnings naming exact days (assertion firing on real drift → next bug).

### Status

- [#17](https://github.com/jamesearlpace/smart-garden/issues/17) — closed.
- [#16](https://github.com/jamesearlpace/smart-garden/issues/16) — closed (2 defects fixed, defect 3 reclassified).
- [#18](https://github.com/jamesearlpace/smart-garden/issues/18) — open: unify `generateBrainData` scale with engine.



