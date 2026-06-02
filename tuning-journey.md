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
| 19 | Depth stat shows "—"" (em-dash + quote) | ALL | Visual artifact when no watering data | `computeStats` returns `'—'` for depthIn, stat card HTML appends `"` for inches unit → displays as `—"` | Cosmetic — acceptable for now. Would fix by suppressing the unit when value is "—" |

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
The stats engine (`computeStats`) had 6 interacting bugs that produced garbage numbers. Each fix revealed the next bug because the underlying data has two pathological characteristics: (a) weeks of 0% moisture from when auto-watering was broken (bug #5), and (b) forecast predictions that generate synthetic future data.

### Root cause chain

```
Bug #5 (auto-watering broken)
  → Zones drain to 0% for weeks with no irrigation
  → Bug #6: historical data looks wrong (actually correct for broken system)
  → Bug #11: stats count those 0% weeks as stress
    → Fix: skip data before moisture > 10%
    → Bug #15: rain spike on May 16 briefly exceeds 10%, filter starts too early
      → Fix: raise to MAD (50%)

Bug #10 (add forecast watering prediction)
  → Forecast injects synthetic sprinkler bars into data[].sprinkler
  → Bug #12: real-data mode with 0 actual events falls to sim path, finds forecast sprinklers
    → Fix: gate on actualWaterings !== null
  → Bug #13: stress loop counts forecast predictions
    → Fix: skip isForecast points
  → Bug #16: curMoisture reads end of forecast (after predicted watering)
    → Fix: walk backward to last non-forecast point

Bug #14: 6-second valve test events
  → Relay toggle tests create watering_event rows with duration_sec = 1-6
  → Filter was > 5 seconds, allowing 6s events through
  → Creates phantom "cycles" that stress gets divided by
  → Fix: raise to > 60 seconds
```

### Lesson learned
The stats engine was designed for the brain simulation (which generates clean, self-consistent data with sprinkler events). When it was repurposed for real DB data, it inherited assumptions that don't hold:
- Real data has initialization artifacts (0% periods)
- Real data has test/accidental events (6-second relay toggles)
- Forecast predictions create synthetic future data that looks like real events
- The `data[]` array mixes historical truth with future predictions

**Defensive fix pattern applied:** Every loop in `computeStats` now has explicit guards:
- `if (data[j].isForecast) continue` — skip predictions
- `if (!pastInit && data[j].moisture > MAD) pastInit = true` — skip broken initialization
- `duration_sec <= 60` — skip test blips
- `curMoisture` walks backward to last real point

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
