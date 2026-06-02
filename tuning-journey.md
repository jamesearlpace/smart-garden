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
| 7 | May 26 phantom jump from 0% to 100% | 6 and others | Balance jumps from 0.0mm to 22.9mm (TAW) with 0 rain and 0 irrigation | `update_daily_balances` has `balance = taw_mm` fallback when it can't find yesterday's record. A server restart or missed day triggers this — the code assumes "first entry = field capacity" | Add guard: only reset to TAW if balance history has <3 entries (true first run), otherwise carry forward last known balance |
| 8 | Legend shows sim-only decision types in real-data mode | — | Rain Skip, Wind Skip, Hardening, Pre-emptive, Emergency, etc. in legend for 2026 | Legend is static HTML, doesn't change between real-data and brain-sim modes | Conditionally hide sim legend row when `selectedYear === '2026'` |
| 9 | "Actual Run (DB)" in legend with no data | 6,7,8 | Legend shows "Actual Run" marker for zones that have never been watered | Static legend item always shown regardless of data | Only show if actualWaterings.length > 0, or hide entirely in 2026 mode (bars are labeled "Sprinkler") |
| 10 | Forecast line shows only ET decay, no predicted watering | ALL | After "Now" the moisture line just drops — doesn't show when auto-watering would fire and refill | `generateRealData2026` forecast path only subtracts ET, never adds irrigation | Add logic: if forecast moisture drops below MAD during 4-7AM window, inject predicted watering and show recovery |
| 11 | Stats contaminated by bogus 0% initialization period | ALL | "56.4 hrs Deep Stress / Cycle" — computed from the weeks the system was broken | `computeStats` counts all data points including the bogus 0% period before first real watering | Filter stats to only include data after first watering event, or after the May 26 reset |

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
