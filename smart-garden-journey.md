# Smart Garden — Journey Doc

**Status:** ✅ **System operational — ET₀ water balance mode (no soil sensors).** Per-zone Manual/Auto toggle deployed. Multi-year backtest done. Grass-starvation audit complete — engine math is conservative, but `precip_rate_iph` in config is **uncalibrated** and likely overstated → could under-water by ~2× until catch-can test is done. **Post-Issue-#1 audit series complete (2026-06-04): 15 of 16 open issues closed across data-layer fixes, security hardening, XSS sweep, and race-condition fix; only #16 (cam-upload) remains, explicitly deferred.**
**Last Updated:** 2026-06-04
**Goal:** Solar-powered smart irrigation controlled remotely via Copilot through home server.

> **Full history → [smart-garden-journey-archive.md](smart-garden-journey-archive.md)** (84KB, all dated session logs, hardware build notes, deployment post-mortems). This doc keeps only what every new session needs.

---

## Plumbing Permit — Irrigation Water Tap

**Status:** Application submitted 2026-05-21 via Duvall permit portal. **Permit #26-175.** Currently in Administrative Review.

### What's being done
Tapping into the potable water supply right after the water meter (NW corner of property) to create a dedicated irrigation supply line. Bypasses house plumbing for better flow (expect ~7.5-8.5 GPM vs. current 6.0 GPM through hose bibb).

### Permit documents (all in `C:\MyCode\smart-garden\`)
| File | Purpose |
|------|---------|
| `permit-plumbing-schematic.svg` | Plumbing connection diagram: meter → tee → ball valve → DCVA → 1" poly → 2 valve boxes (4+5) |
| `permit-site-plan.svg` | Property layout showing meter, tee, DCVA, main line route, valve box locations |
| `permit-acting-as-own-contractor.pdf` | City form — print, sign, scan, upload |

### Backflow preventer decision
- **Proposed:** DCVA (Double Check Valve Assembly) — Watts 007M1-QT, 1" bronze
- **Why DCVA:** Can install underground in valve box (no freeze risk, no ugly riser), handles backpressure, single device for whole system
- **Alternative:** PVB (Pressure Vacuum Breaker) — cheaper (~$150 vs ~$200-500) but must be above ground 12" above highest head
- **Hazard classification:** Low hazard (no chemical injection) per WAC 246-290-490
- **Annual testing required:** By Sept 1 each year, certified BAT tester. City mails reminder in June.
- **Key contact:** Duvall Public Works backflow line: 425-788-3434 / CoDbackflow@duvallwa.gov
- **Permit tech:** 425-788-2779 / permit.technician@duvallwa.gov

### Connection layout
```
Water Meter (¾", NW corner) → existing pipe → NEW TEE
  ├→ Right: existing water to house (no change)
  └→ Down: Ball Valve → DCVA → 1" Poly (100 PSI) → VB1 (4 valves) → VB2 (5 valves)
```

### Next steps after permit approval
1. Call 425-788-3434 to confirm DCVA is accepted (or if they require PVB)
2. Buy the backflow device (Watts 007M1-QT 1" at Lowe's — bookmarked)
3. Do the plumbing work (shut off water, cut in tee, install ball valve + DCVA, run 1" poly)
4. Schedule inspection: permit.technician@duvallwa.gov or 425-788-1160 (24h advance, leave trench open)
5. After approval: hire certified BAT for initial field test (find at https://wcs.greenriver.edu/bat/hire-a-bat/)
6. Annual backflow test due by Sept 1 each year

---

## Quick Reference

### Control chain
```
Copilot → SSH Acer (192.168.0.109) → curl ESP32 (192.168.0.150) → valve actuates
```
SSH: `jamesearlpace@192.168.0.109` password `KeepingP@ce8!` (key auth configured, no prompt).

### Common commands
```powershell
# Status
ssh jamesearlpace@192.168.0.109 "curl -s http://192.168.0.150/api/status"

# Open / close valve (id=0..9, zero-indexed)
ssh jamesearlpace@192.168.0.109 "curl -s -X POST 'http://192.168.0.150/api/valve?id=0&action=open'"
ssh jamesearlpace@192.168.0.109 "curl -s -X POST 'http://192.168.0.150/api/valve?id=0&action=close'"

# Close all
ssh jamesearlpace@192.168.0.109 "curl -s -X POST 'http://192.168.0.150/api/closeall'"

# Server dashboard
http://192.168.0.109:5125
```

### Deploy server changes
```powershell
cd C:\MyCode\smart-garden\server-prod
scp database.py dashboard.py irrigation.py server.py jamesearlpace@192.168.0.109:~/smart-garden-server/
scp templates/*.html jamesearlpace@192.168.0.109:~/smart-garden-server/templates/
ssh jamesearlpace@192.168.0.109 "sudo systemctl restart smart-garden-server.service"
```
**Local working copies:** `C:\MyCode\smart-garden\server-prod\` (mirrors `~/smart-garden-server/` on Acer).
**NOT a git repo on the server** — deploy by scp, not pull.

### Flash firmware (USB only — OTA disabled)
```powershell
cd C:\MyCode\smart-garden
pio run -e esp32 --target upload --upload-port COM5
pio device monitor --baud 115200 --port COM5
```

---

## Architecture

### Hardware
| Component | Model | Notes |
|-----------|-------|-------|
| MCU | ESP32-WROOM-32U | External antenna, MAC `00:70:07:26:48:DC` (replacement board, old `68:FE:71:0C:BA:98` fried 2026-05-27), static IP 192.168.0.150 |
| I/O Expander | Waveshare MCP23017 | I2C addr 0x27, valves 1-8 on PA0-PB7 |
| Antenna | 2.4 GHz 5dBi external | U.FL/IPEX connector on 32U |
| Solar | ECO-WORTHY 10W 12V | ~1.6 Ah/day in Duvall WA |
| Charge ctrl | Renogy Wanderer Li 10A | Battery + load output. **Brownout source.** |
| Battery | ExpertPower 12V 7Ah SLA | |
| Buck | LM2596 | 12V → 5V to ESP32 VIN. 1000µF cap on output. |
| Power gate | IRF4905 P-FET + 2N3904 NPN | GPIO 2 controls 12V to L298N boards |
| H-bridge | L298N × 5 | 2 valves per board, 10 valves total |
| Valves | Orbit 57861 DC latching | Pulse open, reverse pulse close |
| Caps | 1000µF + 100nF on 3.3V rail | Brownout protection for WiFi TX spikes |
| Server | Acer Aspire A314-23P | Linux Mint 22.1, 192.168.0.109 |

### Network
```
Ziply Fiber → Netgear GS305E → TP-Link ER605 (.1) → Eero 6
  ├─ Acer (.109, wired)
  └─ ESP32 (.150, WiFi static)
```

### Server (Acer)
- Repo deploy path: `~/smart-garden-server/` (NOT git)
- Service: `smart-garden-server.service` (systemd)
- Port: 5125
- Stack: Flask + waitress + apscheduler + SQLite (WAL)
- Logs: `journalctl -u smart-garden-server.service -f`
- Secondary collector service writes to `~/smart-garden/server/smart-garden.db` every 60s — dashboard falls back to this DB if main DB is >10 min stale (see archive: 2026-04-17)

### Alerting
**ntfy.sh/smart-garden-james** (NOT Pushover — ignore any old refs to Pushover). Title header is stripped to ASCII before send (emoji bug fix #11).

**Active monitoring (since 2026-04-22, commit `e53417a`):**
The server's `AlertMonitor` runs every poll cycle (5 min) on the Acer. It fires ntfy alerts on:
- ESP32 unreachable >15 min (`_check_offline`)
- Crash loop: >5 reboots in 1h (`_check_crash_loop`)
- Safe mode active (`_check_safe_mode`)
- Free heap <15% (`_check_memory`)
- Sensor flatline/railed >48h (`_check_sensor_faults`)
- **NVS counter delta** — `bootCount`, `wifiReconnects`, `crashCount` increase between polls (steady state on wall power = 0 delta, any change is news) (`_check_counter_deltas`)
- Chip temp >85°C (`_check_chip_temp`)

**Daily 8 AM digest** — single ntfy with 24h summary: uptime, RSSI, reconnect count, crash count, boot count delta, free heap, dashboard online %.

**Startup ping** — one ntfy 10s after server start = "pipeline alive" confirmation.

Alert cooldown: 30 min per alert key (won't spam the same alert).

---

## Critical reliability rules

### Brownout = root cause of every recent failure
The Wanderer load output sags voltage during high-current bursts. **Affects every high-current op:**
- OTA upload → bricks chip (5–10% into upload)
- `ESP.restart()` via `/api/reboot` → bricks chip
- Suspected: simultaneous valve pulses, WiFi reconnect storms

**Mitigation in firmware** (deployed 2026-05-01):
- Low-boot TX: `WIFI_BOOT_TX_DBM = WIFI_POWER_8_5dBm` during connect, bumps to `WIFI_TX_DBM = WIFI_POWER_19_5dBm` after WiFi established
- ArduinoOTA wrapped in `#ifdef ENABLE_OTA` (default OFF)
- Close-all valves only on clean boot, not crash reboots
- Deep sleep 10 min after 10 consecutive crashes (battery protection)
- Decoupling caps: 1000µF + 100nF on 3.3V rail, 1000µF on buck output

**Real fix (not yet done):** 1000µF + 100nF decoupling cap on 3.3V rail. See GitHub issue #2.
**UPDATE 2026-05-01:** Caps installed ✅. Low-boot TX strategy also deployed — ESP32U boots clean on battery-only power now.

### Verification playbook — confirm "still healthy"

**A. Quick health probe (30s)**
```powershell
ssh jamesearlpace@192.168.0.109 "curl -s --max-time 8 http://192.168.0.150/api/status" | python -c "import sys,json; d=json.load(sys.stdin); s=d['system']; h=d.get('health',{}); print(f'boot={s[\"bootCount\"]} uptime={s[\"uptimeSec\"]}s rssi={s[\"wifiRSSI\"]} reconnects={s[\"wifiReconnects\"]} crashCount={h.get(\"crashCount\")} safeMode={h.get(\"safeMode\")} temp={s.get(\"chipTempC\")}')"
```
Good: rssi -29 to -50, reconnects 0, safeMode False, uptime > 600s, chipTempC < 90.
Red flags: rssi worse than -65, reconnects climbing, safeMode True.

**chipTempC interpretation** — the ESP32 internal temp sensor is famously uncalibrated and noisy. **Real die temp at this deployment is ~77–78°C steady** (verified 2026-04-22 with 10 rapid samples + 30 soak samples: min 77.2, max 86.7, avg 77.8). Single-sample readings of 100°C+ followed seconds later by 78°C are sensor glitches, not thermal events — physics says the die can't cool 30°C in 4 minutes. Trust a *sustained* high reading, not a spike. See open issue for alert hysteresis fix.

**B. Dashboard cadence test (5 min)**
```powershell
ssh jamesearlpace@192.168.0.109 'for i in $(seq 1 10); do printf "%s " "$(date +%H:%M:%S)"; curl -s http://localhost:5125/api/dashboard | python3 -c "import sys,json; d=json.load(sys.stdin); print(\"online_flag=\"+str(d.get(\"esp32_online\")))"; sleep 30; done'
```
Expected: 10/10 `online_flag=True`. Less means TIME_WAIT or signal regression.

**C. Network probe (only if B fails)** — see archive 2026-04-21 for `tcpdump` recipe.

### The "before saying it's fixed" gate
Before any "you can box it up" / "last flash" / "OTA will work" / "ship it" claim:
1. USB physically disconnected
2. Chip on real deployed power source
3. At deployed location
4. Health probe (A) clean
5. Dashboard cadence (B) 10/10 over 5 min
6. **Then** make the claim. Not before.

This rule exists because I broke it 4 times in one session on 2026-04-21. See `/memories/mistake-ledger.md` M2 and [smart-garden#4](https://github.com/jamesearlpace/smart-garden/issues/4).

---

## Session Log: 2026-06-02 (Auto-mode shipped + Water cost backtest + Grass starvation audit + UX polish)

### Seasonal Outlook panel — SHIPPED (commit `39c5b62`)
James asked whether summer 2026 was leaning hotter than usual. NOAA CPC's May 14 advisory says 82% chance of El Niño emerging May–Jul 2026 (96% by DJF), and the JJA outlook tilts PNW warmer/drier than normal. Instead of a vibe, built a panel that gives a real number.
- New module `server-prod/seasonal.py`: pulls 180-day ECMWF SEAS5 ensemble-mean forecast from Open-Meteo's free seasonal API, then pulls 5-year ERA5 archive (one batched request per year) covering the same calendar months, computes per-month tmax / ET₀ / precip anomaly. 24h disk cache at `$TEMP/smart_garden_seasonal_cache.json`.
- New route `/api/seasonal-outlook` in `dashboard.py` (`?refresh=1` to force).
- New "🌡️ Seasonal Outlook" card in `moisture_sim.html` below the All-Zones schedule: one-line summary classifying the season (close-to-normal / warmer / significantly warmer / drier), then a tile per month with color-coded anomaly badges (red = hot/wet-deficit, blue = cool/wet, amber = warmer-than-normal).
- Smoke result for Duvall: **Jun +5.4°F / −39% precip · Jul +6.2°F / −17% · Aug +7.6°F / −56% · Sep +6.8°F / −27%**. ET₀ avg only +1–11% (heat alone doesn't move ET as much as humidity/wind), but precip deficits are big. Expect to lean harder on auto-watering than the last few summers.
- Source endpoints (no API key needed):
  - SEAS5 forecast: `https://seasonal-api.open-meteo.com/v1/seasonal` with `models=ecmwf_seas5_ensemble_mean`
  - ERA5 normal: `https://archive-api.open-meteo.com/v1/archive`

### Banner forecast walker: mm-as-inches unit bug — FIXED (commit `09d7b01`, issue [#16](https://github.com/jamesearlpace/smart-garden-server/issues/16))

Zone 5 at 76% / MAD 50% — banner predicted next watering in ~4 hours; chart showed moisture staying above 70% all 7 days. The disagreement exposed a unit bug.
Root cause: `weather.py` requests Open-Meteo with `precipitation_unit=mm` (and ET0 default is also mm). Three JS forecast walkers in `moisture_sim.html` (single-zone banner above-MAD branch, `predictZoneSchedule` for All Zones, inline refresh() copy) divided raw `et0` and `rain` by `rootDepthIn`. A 5 mm/day ET became `etPct = 5 * 0.9 / 6 * 100 = 75%/day` instead of ~3%/day — moisture appeared to crash past MAD in one day, banner said "tomorrow".
Fix: divide ET and rain by 25.4 (mm → in) before dividing by rootDepthIn. Applied to all three walkers.
Lesson: This is the THIRD bug in the banner today (issue [#15](https://github.com/jamesearlpace/smart-garden-server/issues/15) past-time, parse-error rendering blockout, now this). Three duplicated copies of the same forecast walker drifted. Should consolidate.

### Moisture-sim banner past-time bug — FIXED (commit `1a37f65`, issue [#15](https://github.com/jamesearlpace/smart-garden-server/issues/15))

At 23:25 PT, Front Yard A banner showed "Tuesday Jun 2 ~4 AM" — that 4 AM is 19h in the past.
Root cause: the "above MAD → forecast crossing" branch in `updateNextWateringBanner` and the inline copy in `refresh()` both did `setDate(today + hitDay); setHours(4)` without rolling forward when the target already passed (when `hitDay = 0` and current time > 4 AM, target = today 4 AM = past).
The "below MAD now" branch was correct (it had `if (getHours >= 7) +=1 day`); the other two branches drifted from it.
Fix: after computing target, if `target < now`, push forward one day. Applied to both code paths.

### Moisture-sim UX restyle — DEPLOYED (commits `5da10d9`, `6665d8d`, `485e668`)
- Light theme + sidebar to match dashboard (commit `5da10d9`)
- sessionStorage cache for Open-Meteo + `/api/moisture-data` (commit `6665d8d`) — first load same speed, reloads near-instant
- New "🌿 All Zones — Schedule View" entry in zone dropdown (commit `485e668`): zone status table (current %, MAD, mode pill, next watering, last run, gal/7d) + 7-night schedule grid (cells = runtime per night, color-coded by urgency, footer counts zones firing per night, click zone name to drill into single-zone chart)

### Per-zone Auto/Manual toggle — DEPLOYED (commit `965f994`)
Each zone now has an `auto_mode` field in config.yaml. When `false`, the engine's `evaluate_zone()` short-circuits and the dashboard shows a "Manual mode — engine will not water this zone" banner. UI: toggle button next to each zone card on index.html + moisture_sim.html. Server-confirmed state: zones 0-6 (sprinklers) = `auto_mode: true`, zones 7-8 (Garden/Grapes drip) = `auto_mode: false`, zone 9 (Spare) = `false`.

### Backtest: how much water this system would have used 2015-2025
Built three analysis scripts in `C:\MyCode\smart-garden\` (now committed):
- `sim_2025_water_usage.py` — runs the engine's water-balance model against Open-Meteo historical ET₀ + rain for one year, prints gallons per zone + total events
- `sim_2025_water_cost.py` — converts gallons → WD119 and City of Duvall tier rates, marginal cost over a $10 CCF/bill baseline
- `sim_multiyear_water.py` — same but across 2015-2025

**Results (7 sprinkler zones, Apr-Oct, marginal cost over baseline):**

| | 2025 | 11-yr avg | Driest (2015) | Wettest (2019) |
|---|---|---|---|---|
| Gallons | 20,928 | 17,943 | 22,152 | 12,984 |
| Events | 228 | ~200 | ~240 | ~150 |
| WD119 cost | $175 | $151 | $193 | $106 |
| Duvall cost | $220 | $188 | $241 | $133 |

**Caveats** (this is what makes the $175 number SUSPICIOUSLY low):
1. Drip zones (Garden 7 + Grapes 8) not included — they're manual now anyway
2. Baseline of $10 CCF/bill is a guess; if real bimonthly baseline is 8-12 CCF, marginal cost is understated
3. The "naive dumb-timer comparison" of $400-$700 assumes you'd run 30 min × 4 days/week × 7 zones × 24 weeks regardless of weather — that's the true alternative
4. **The biggest issue: `precip_rate_iph` in config is uncalibrated** — see audit below

### Grass starvation audit — `audit_grass_starvation.py` (now committed)
Four independent checks asking: "is the engine's water-balance accounting realistic, or is it lying to itself and starving the grass?"

| Check | Result | Verdict |
|---|---|---|
| 1. Weekly net water per zone (peak Jun-Aug 2025) | 4 deficit weeks, 1 severe (-0.37 in) for Front Yard A | 🟡 Tight but OK *by engine's own math* |
| 2. Precip-rate sanity: implied coverage area | All 7 zones imply 257-296 sq ft coverage | ⚠️ **TOO SMALL** — typical 4-head zone is 400-800 sq ft |
| 3. Industry rule (1.0-1.5 in/wk net peak) | Net 0.23-0.38 in/wk | 💧 "lush" *by engine's math*, but only if Check 2 is right |
| 4. Model assumptions (root, AWC, MAD, Kc) | All within FAO-56 ranges | ✅ Conservative |

**The bug, stated clearly:** the engine computes `irrigation_mm = (runtime_min/60) × precip_rate_iph × 25.4`. If config says 1.5 in/hr and reality is 0.6 in/hr (likely on a typical 600 sq ft zone), engine credits the soil bucket 2.5× more inches than actually fell on the grass. Soil never reaches MAD trigger as often as it should → engine under-waters → grass stresses.

**The math:** 4 GPM × 96.3 / 1.5 in/hr = 257 sq ft. For 4 spray heads with 10-15 ft radius, real coverage is 500-800 sq ft → real precip rate is 0.5-0.8 in/hr. Engine math believes each 24-min cycle deposits 0.60 in; reality is closer to 0.20-0.32 in. Real net during peak July ≈ **negative 0.25 in/week** instead of the "lush +0.38" the model claims.

**Fix path:**
1. Catch-can test (6-8 tuna cans, run 15 min, measure depth in mm, multiply by 4) — gives the real number
2. Update `precip_rate_iph` per zone in config.yaml — engine will water more often
3. Re-run multi-year sim with calibrated rates — true water usage probably ~35-50K gal/yr, true cost ~$300-500/season
4. **Open issue for follow-up:** engine should size *runtime* to actual soil deficit, not always run fixed `cycle_run_min × cycle_count`. Right now adjusting precip_rate_iph only changes *frequency* of watering, not depth — that's a weaker lever than it should be.

### Pre-flight checklist before letting it run tomorrow (2026-06-03)
See bottom of this doc — "Pre-flight before auto-watering kicks in".

---


### Switched to ET₀ water balance decisions (no soil sensors)

**Problem:** Soil moisture sensors not connected. System was skipping all zones with "No valid soil sensor configured."

**Fix:** Modified `evaluate_zone()` in `irrigation.py` to use the existing soil water balance model instead of sensor readings. Now the trigger is `balance_mm <= MAD` instead of `soil_pct < dry_trigger`.

**Changes:**
- Removed soil sensor checks (wet_target, dry_trigger) from decision chain
- Added water balance lookup (`db.get_soil_balance(zone_id)`) at decision time
- Removed "no valid soil sensor" skip in main loop
- Runtime-based stop for active zones (not soil target)
- Budget tightening uses balance vs MAD instead of soil_pct

### Precipitation rate calibration

Updated `precip_rate_iph` per zone with better estimates based on head count:

| Zone | Name | Rate | Basis |
|------|------|------|-------|
| 0-1 | Front Yard A/B | 1.5 iph | 4 spray heads, compact |
| 2-4,6 | Backyard/SE/SW | 1.3 iph | 4 spray heads, larger areas |
| 5 | South | 1.0 iph | 3 spray heads |
| 7-8 | Garden/Grapes | 0.4 iph | Drip emitters |

All rates are **uncalibrated guesses** — editable in Settings → Zone Configuration → Precip Rate column. Adjust based on observed grass health over time.

### Water Budget chart (deployed)

New chart on History page showing daily gains vs losses:
- Red bars (down): ET₀ × Kc evapotranspiration loss
- Blue bars (up): Rain
- Green bars (up): Irrigation from sprinklers
- Orange line: Running soil water balance

Best viewed on 7d or 30d time range (daily data, updates at 11 PM).

### Water Meter Cam: live auto-refresh (deployed)

Cam page auto-refreshes JPEG every 5s when visible, stops when you switch tabs. Flash toggle button. No gallery/auto-capture.

### Next: Hourly Moisture Simulation Chart (planned, not built)

**Goal:** A live chart on the Home page showing estimated soil moisture % dropping in real-time as ET₀ evaporates water, spiking up when rain falls or sprinklers run, with a clear "needs water" threshold line.

**Preview mockup:** `moisture-sim-preview.html` — renders in browser with fake data. Confirmed design works.

**Design feedback from preview:**
- Rain and sprinkler events need to be **vertical bars behind the moisture line** (not small markers on the line — too hard to see)
- Rain = blue bars, Sprinkler = green bars — clearly distinct
- Moisture line should show **sharp jumps** when water is added (reduce `tension` to 0 for step-like transitions)
- Red stress shading below MAD works well
- Stats cards at bottom (cycle length, dry-down ratio, stress hours, depth per cycle) are useful

**Key metrics to track:**
- Moisture % (continuous line, updated every 5 min with prorated hourly ET₀)
- Cycle length (days between waterings — target 2-4 days for PNW grass)
- Dry-down ratio (% of cycle spent drying vs wet — target 50-70%)
- Stress hours (time below MAD before water arrives — target < 6 hrs)
- Depth per cycle (inches applied — target 0.5-0.75" for grass)

**Implementation needs:**
1. Hourly ET₀ proration (bell curve: peaks 1-2 PM, near zero at night)
2. New DB table: `moisture_sim` with 5-min resolution data points
3. Real-time rain and irrigation event integration (vertical bars, not markers)
4. Chart.js mixed chart: line (moisture) + bars (rain blue, sprinkler green)
5. Cycle health summary card (avg cycle length, stress hours, dry-down ratio)
6. Wetting-drying cycle optimization: brief deep watering > constant dampness

---

## Session Log: 2026-05-27 (Dashboard Fixes + Firmware Flash)

### Dashboard: History chart time axes aligned (deployed)

**Problem:** Each history chart built its own x-axis from its data points (category labels). Charts with different data density showed different time ranges — battery chart might span 11AM-8AM while DHT22 only showed 8PM-8AM.

**Fix:** Created shared `shTimeAxis(hours)` helper that returns a Chart.js `type: 'time'` config with identical `min`/`max` bounds from `getChartTimeBounds()`. Converted all 15+ chart functions to use `{x: new Date(r.ts), y: value}` data format instead of separate `labels`/`data` arrays. Added `chartjs-adapter-date-fns` CDN (was missing from git version).

**Charts converted:** loadSensorChart, loadDHTBoxChart, loadSoilDualChart, loadSoilNoiseChart, loadSoilWifiChart, loadConnectivityChart, loadUptimeChart, loadWateringChart, loadDecisionChart, loadDailyUsageChart, loadCostChart, loadBalanceChart, loadWifiReconnectsChart, loadCrashChart, loadBatteryChart, loadServerHealth (disk/db/cpu).

**Encoding incident:** First attempt used `ssh cat | Out-File` which mangled UTF-8 → garbled all emoji on the dashboard. Fixed by using `git stash` to recover clean file, then applying changes via Python script with explicit `encoding='utf-8'`.

### Dashboard: Mobile nav fix attempt (deployed, unverified)

**Problem:** Bottom mobile nav bar (Home/Zones/History/Settings/Forecast) not visible on History page on phone.

**Attempted fixes:**
1. CSS `will-change:transform; transform:translateZ(0)` on `.mobile-nav` — GPU compositing layer
2. CSS `contain:layout style` on `.mobile-nav`, `contain:content` on `.panel`, `z-index:1` on canvases
3. JS forced-visibility — 500ms timer after switching to History panel sets `display:block; visibility:visible`

**Status:** Deployed but not yet verified on phone (user moved on to firmware flash).

### Firmware: Power optimization FLASHED ✅

Flashed via USB (COM5) at ~11:00 AM. Verified clean boot on serial monitor:
- CPU: 160 MHz (was 240) ✅
- WiFi: low-boot TX 8.5 dBm → 19.5 dBm post-connect ✅
- Boot #201, crash counter 1/20
- All 10 valves closed (safe startup) ✅
- DHT22: 65.7°F, 57.4% humidity ✅
- Free heap: 240KB ✅
- WiFi connected to 192.168.0.150 ✅

**Changes on chip (commit `ee95dd3`):**
1. `handleApiStatus()` no longer resets `lastApiActivityMs` — light sleep not blocked by status polls
2. CPU 240→160 MHz
3. WiFi modem sleep comment fix
4. WiFi-recovery bugs from 05-21

### WiFi lockout RCA — RESOLVED

**Root cause: CPU light sleep (`esp_light_sleep_start()`) caused Eero mesh to deauthenticate the ESP32.** The chip would connect to WiFi, enter light sleep after 5 min of no state-changing API calls, and the Eero would drop it. This triggered the WiFi watchdog → crash loop → deep sleep lockout spiral.

**Contributing bugs found and fixed:**
1. Low TX power on reconnect (8.5 dBm instead of 19.5 dBm) — fixed `27f087f`
2. Crash counter not clearing on loop() WiFi recovery — fixed `27f087f`
3. No TX escalation during setup connect — fixed `27f087f` (mid-connect bump at attempt 20)

**Resolution:** Disabled CPU light sleep entirely. Replaced with WiFi modem sleep only (`WIFI_PS_MIN_MODEM`) which saves ~30-50 mA on the radio without halting the CPU. Eero maintains association. Commit `2c8db79`.

**Signal strength:** RSSI degraded from -50 dBm (May 21-22) to -74 dBm (May 27). Moved Eero closer to junction box. System now stable at -74 dBm with 0% packet loss.

### ESP32 board replacement

Original ESP32-WROOM-32U (MAC `68:FE:71:0C:BA:98`) **destroyed by accidental short** while adjusting wiring with battery connected. Spark seen, board went silent (no serial output, esptool can't connect).

Replaced with identical spare ESP32-WROOM-32U (MAC `00:70:07:26:48:DC`). Same external 5dBi antenna reattached. All firmware flashed, all sensors and valves working.

**Lesson:** Always disconnect battery before inserting/removing the ESP32 from headers. The soldered battery/solar connections make this difficult — consider adding an inline switch or fuse.

### Battery voltage calibration — final (Wanderer reference)

**Wanderer display reads 13.2V, ESP32 reported 12.83V (ratio 6.283).**

Correction factor: `13.2 / 12.83 = 1.02884`

**Three-layer fix:**
1. **Server-side (live):** `irrigation.py` multiplies incoming `batteryV` by 1.02884 before logging
2. **Database:** 4,200 rows corrected (cumulative: original × 1.04713 × 1.02884)
3. **Firmware ratio (pending flash):** `BATTERY_DIVIDER_RATIO` updated to `6.464f` — when flashed, server correction can be removed

### Firmware on chip (commit `2c8db79`)
- CPU 160 MHz (was 240)
- WiFi modem sleep (`WIFI_PS_MIN_MODEM`) — radio sleeps between DTIM beacons
- CPU light sleep DISABLED — causes Eero deauth
- WiFi lockout fix: full TX on reconnect, crash counter reset on loop() recovery, mid-connect TX bump
- Voltage divider ratio: 6.283 (server applies 1.02884x correction; firmware ratio 6.464 pending next flash)

### Pending firmware changes (next flash)
- `BATTERY_DIVIDER_RATIO` 6.283 → 6.464 (then remove server-side 1.02884x correction)

**Next steps:**
1. Monitor battery voltage trend overnight — verify solar keeps up with modem-sleep power draw
2. Test mobile nav on phone (CSS fix deployed earlier)
3. Add inline switch/fuse for battery disconnect

### Battery voltage calibration — superseded by Wanderer-referenced calibration above

**Logic:** Wanderer LVD trips at 11.1V. ESP32 went offline → actual battery was 11.1V. But firmware reported 10.60V. Therefore the divider ratio was wrong.

**Correction factor:** `11.1 / 10.60049 = 1.04713`

**DB fix:** Updated 4,209 historical `battery_v` rows in `system_health` table:
```sql
UPDATE system_health SET battery_v = ROUND(battery_v * (11.1 / 10.60049), 4)
WHERE battery_v IS NOT NULL AND battery_v BETWEEN 8 AND 15;
```
Excluded garbage readings outside 8-15V range (floating pin before divider was wired).

**Firmware fix (commit `dce7d63`, pending flash):**
- `config.h`: `BATTERY_DIVIDER_RATIO` changed from `6.0f` to `6.283f`
- `main.cpp`: removed contradicting comment that said "4x10k + 1x10k → ratio 5"
- Will take effect on next USB flash

**Next steps (superseded — see resolved RCA above):**
1. Verify new firmware power draw via battery voltage trend (should drain much slower)
2. Count resistors in voltage divider for definitive ratio
3. Multimeter reading to cross-check calibration
4. Flash updated ratio (`6.283f`) — needs another USB flash
5. Test mobile nav on phone
6. Consider bigger battery (12V 20Ah, ~$40-50) for 3-week reserve

---

## Open issues

| Repo | # | Sev | Summary |
|------|---|-----|---------|
| smart-garden | [#5](https://github.com/jamesearlpace/smart-garden/issues/5) | **HIGH** | **Web server wedge** — chip RSTs SYNs on port 80 in 3-5 min cycles. ESPAsyncWebServer ruled out 2026-04-27 (5/7 fail at production cadence, identical pcap signature). **Bug is in lwIP / WiFi driver layer, NOT the application web server.** Self-recovers eventually (n=2 confirmed today). Server retry pattern catches most instances. Next candidates: ESP-IDF v5.x upgrade, `WiFi.setCountry()`, sdkconfig `lwip_max_listening` bump, or smart-plug out-of-band recovery. |
| smart-garden | [#6](https://github.com/jamesearlpace/smart-garden/issues/6) | **Med-High** | WiFi TX power varies between boots (7.8 / 14.3 / 14.8 / 14.0 dBm across 4 boots) despite `WIFI_POWER_19_5dBm` config. `setTxPower()` returns true; ESP-IDF runtime regulatory cap silently lowers actual TX. Telemetry pipeline shipped (`tx_power_raw` column + dashboard column). Hypothesis "low-TX boots cause WiFi watchdog cascades" weakened by today's wedges occurring at 14.3 dBm too. Need ~1 week of data. |
| smart-garden | [#2](https://github.com/jamesearlpace/smart-garden/issues/2) | Low | **Decoupling cap on 3.3V rail** — user buying 1000µF + 100nF caps. Fixes brownout class (M3): OTA bricks, ESP.restart() bricks, multi-valve simultaneous brownout. **Does NOT fix wedge** — confirmed today (wedges happen on USB power too, no brownout reset reason). Unlocks re-enabling OTA. |
| smart-garden | — | ~~Med~~ | ~~WiFi watchdog too aggressive~~ ✅ **SHIPPED** commit `53a91d9` (2026-04-27 07:34): threshold 60s→5min, close-all valves before `ESP.restart()`. |
| smart-garden | — | ~~Med~~ | ~~TWDT not subscribed~~ ✅ **STALE** — TWDT IS subscribed (`esp_task_wdt_add(NULL)` at `main.cpp:791`). Confirmed in serial. |
| smart-garden | [#4](https://github.com/jamesearlpace/smart-garden/issues/4) | Meta | Recurrent AI mistake: premature "ship it" claims |
| smart-garden | [#1](https://github.com/jamesearlpace/smart-garden/issues/1) | Meta | (Earlier) contradictory OTA claims |
| smart-garden | — | ~~Low~~ | ~~Wire voltage divider from battery to GPIO 36~~ ✅ **SHIPPED** commit `a01b3f5` (2026-04-27 07:50): 6:1 ratio. Wired — needs multimeter+serial verification before closing. |
| smart-garden-server | (closed) | — | Chip-temp false positives — fixed 2026-04-22. |
| smart-garden-server | (closed) | — | #10 TIME_WAIT, #11 emoji, #12 reboot wiring — closed 2026-04-21. |
| smart-garden-server | ✅ closed | — | dashboard.py bypass routes — FIXED `624b6d9` (2026-04-26). |
| smart-garden-server | ✅ closed | — | #15 banner past-time, #16 mm-as-inches, #17 forecast dark theme, #18 missing templates, #19 orphan routes, #20 dead templates, #21 forecast no sidebar, #22 mobile nav drift, #23 server clutter, #24 redundant breadcrumb, #25 sidebar footer drift — all SHIPPED 2026-06-03. See session log below. |
| smart-garden-server | ✅ closed | — | #3 same-zone double-click leaked orphan `watering_event` rows — FIXED 2026-06-04: idempotent guard in `start_zone_watering()`. Orphan event 164 backfilled. See June 4 session log. |
| smart-garden-server | ✅ closed | — | #4 `daily_summary` table had no populator (empty since inception) — FIXED 2026-06-04: `BillingCalculator.update_daily_summary()` + 23:55 scheduler job + 59-day backfill. See June 4 session log. |
| smart-garden-server | ✅ closed | — | #5 `skip_event` table empty — `log_skip_event()` defined but never called. FIXED 2026-06-04: wired into `run_cycle()`'s skip branch with per-zone per-day de-dupe via `db.skip_event_exists_today()`. First cycle produced 7 rows (648 gal / $0.36 saved). See June 4 session log. |

---

## Session Log: 2026-06-04 (Overnight audit + Issue #3 fix)

**Overnight cycle was clean.** First overnight under the issue #1 defer-guard fix (deployed 2026-06-03 16:51 PDT):
- Zone 0 (Front Yard A) watered 04:02–04:17 (14 min, 60 gal) — single zone, no overlap
- Zones 3 and 6 stayed dormant at full TAW after yesterday's manual watering — `get_daily_irrigation_mm()` credited them correctly at the 23:00 daily balance job (29.8 mm and 26.8 mm respectively). Stuck-balance bug from June 2-3 = FIXED.
- Same-day re-water guard fired correctly at 22:57 ("Already watered 52.4 min today")
- No INVARIANT violations, no exceptions in scheduler

**Issue #3 found and fixed (same session):** Double-tapping the manual button on Zone 8 at 17:39:36 yesterday created two `watering_event` rows (164, 165) in the same second; only event 165 got an `end_ts`. Root cause: `open_valve()`'s preemption filter excludes the same zone (`if z != zone_id`), so a re-entry on an already-active zone just clobbers `_active[zone_id]` and orphans the prior event_id. Fix: guard in `start_zone_watering()` — if `zone_id in self._active`, log and return True (idempotent no-op). Single physical valve, so no watering-safety impact, but it polluted the audit table.

- Filed: [#3](https://github.com/jamesearlpace/smart-garden-server/issues/3)
- Code: 8-line guard in `irrigation.py::start_zone_watering()`, before `calculate_weather_scale`
- DB cleanup: `UPDATE watering_event SET end_ts='2026-06-03T17:39:40', duration_sec=4, est_gallons=0.0 WHERE id=164` → orphan count now 0
- Deployed: scp + restart `smart-garden-server` 2026-06-04 07:59:56 PDT, service active

### Issue #4 — `daily_summary` table empty since inception

Surfaced while auditing what other schema tables had no writers. `daily_summary` (date PK + total_gallons/cf, gallons_saved/cf_saved, cost, cost_avoided, et0_mm, rain_mm, avg_temp_f) is read by `/api/daily-summary-history` and `db.get_daily_summaries()` but `grep` for INSERT/UPDATE/UPSERT returned **zero matches**. Table had 0 rows.

- Filed: [#4](https://github.com/jamesearlpace/smart-garden-server/issues/4)
- Fix: added `BillingCalculator.update_daily_summary(date_str)` in [billing.py](../smart-garden-server-live/billing.py) — aggregates from `watering_event` + `skip_event` + `soil_balance` (zone 0) + `weather_log` (api source), computes cost via tier-aware difference-of-cumulative (`cost_for_cf(month_through_today) - cost_for_cf(month_through_yesterday)`), UPSERTs into `daily_summary`.
- Scheduler: new cron job at 23:55 daily (right after the 23:00 `daily_balance`, before midnight). Wired in [server.py](../smart-garden-server-live/server.py).
- Backfill: [backfill_daily_summary.py](../smart-garden-server-live/backfill_daily_summary.py) one-shot — populated **59 rows** spanning 2026-04-02 → 2026-06-04.
- Sanity check on results:
  - Most days $0.00 because they're inside tier 1's free 200 cf — correct
  - 2026-05-31: 1190.5 gal / $8.37 — single big day pushed past tier 1, charged at tier 2's $5.10/100cf — correct
  - 2026-06-01 (new billing month): back to $0.00 inside free tier — correct
  - `gallons_saved=0` across all days because `skip_event` table is itself empty (separate latent bug, not part of this fix)
  - 2026-06-04: `et0`/`rain` are `None` because `soil_balance` hasn't run yet for today (fills at 23:00) — tomorrow's run will overwrite with full values
- Deployed: scp + restart 2026-06-04 08:15:38 PDT, service active, scheduler logs `BillingCalculator.update_daily_summary` job added cleanly.

**Open follow-up:** `skip_event` table appears empty — none of the cycle-summary `zones_skipped` counts produce individual skip rows. Worth investigating: is `log_skip()` actually being called? If not, `gallons_saved` / `cost_avoided` will stay at 0 even after this fix. Separate issue, not yet filed. → **FIXED as #5 same session, see below.**

### Issue #5 — `skip_event` table empty since inception

Follow-up to #4. The `daily_summary.gallons_saved` / `cost_avoided` columns were always 0 because the source `skip_event` table had been empty since service start.

- Root cause: `irrigation.py::log_skip_event()` and `database.py::log_skip()` both exist, but `run_cycle()`'s `elif action == "skip":` branch (line 793) only bumped a counter and wrote a `cycle_summary` aggregate row — it never called `log_skip_event()`. Per the comment on line 811 ("Log one summary row per cycle instead of per-zone skip events"), this was an intentional volume tradeoff that broke the savings tracking downstream.
- Filed: [#5](https://github.com/jamesearlpace/smart-garden-server/issues/5)
- Fix:
  - New `db.skip_event_exists_today(zone_id) -> bool` in [database.py](../smart-garden-server-live/database.py).
  - In `run_cycle()`'s skip branch, call `self.log_skip_event(zid, reason, decision["details"])` gated by `"manual mode" not in reason.lower() and not db.skip_event_exists_today(zid)`. The de-dupe is essential — with `poll_interval_sec=300`, naive logging would yield 288 cycles × 7 skipped zones = 2K rows/day all double-counting the same physical skip in the savings sum.
- Deployed: scp + restart 2026-06-04 08:23:32 PDT.
- Validation: first post-restart cycle (08:24:41) produced exactly 7 `skip_event` rows — one per installed zone with auto_mode=true (zones 7 and 8 correctly excluded as manual-mode). Second cycle at 08:24 didn't duplicate (de-dupe works). Re-ran backfill for today → `daily_summary` 2026-06-04 now shows `gallons_saved=648.0`, `cost_avoided=$0.36`. End-to-end working.
- Historical data: not reconstructible — only per-cycle aggregates exist in `cycle_summary`. Pre-deployment `daily_summary` rows keep `gallons_saved=0` / `cost_avoided=0`. Only forward.

### `/api/audit` + `/audit` HTML — DB-table health introspection (NEW)

Direct response to the architectural finding that bugs #4 and #5 were silently-empty tables for months with no visible signal. Added a runtime endpoint that enumerates every table, reports row count, last write timestamp, last-24h count, and flags `EMPTY` (no rows ever) or `STALE` (recent writes stopped) against a per-table cadence expectation. Self-contained HTML page at `/audit` renders the same data with status pills.

- New routes added to [dashboard.py](../smart-garden-server-live/dashboard.py): `/api/audit` (JSON) and `/audit` (HTML, inline template — no `templates/audit.html` file needed).
- `AUDIT_TABLE_SPECS` lists all 13 tables with their timestamp column, expected max age in hours, and a human label. Date-typed columns (`daily_summary.date`, `soil_balance.date`, `billing_cycle.month`) get day-resolution age math (no false positives mid-morning).
- Deployed: scp + restart 2026-06-04 09:05:56 PDT.
- **First run already surfaced a real bug:** `sensor_log` is STALE — last write 2026-05-26T23:13:54 (200+ hours ago) despite cycles running every 5 min and `weather_log`/`cycle_summary`/`system_health` all current. Sensor logging path has been broken for 8 days. Confirmed `billing_cycle` is EMPTY (known dead schema, flagged as expected).
- Rollback: single-file revert — `dashboard.py.bak.audit-20260604-090308` lives on the server. No schema changes, no behavior changes to write paths.

### Post-Issue-#1 audit series — Issues #6 through #15 (all closed same day)

After the morning's data-layer fixes (#3/#4/#5) and the `/audit` page deploy, did a full sweep of remaining issues filed against the repo. Closed every one except `#16` (cam-upload, explicitly deferred). Batched into themed commits so each fix was independently reviewable + rollback-able. Order shipped:

**Batch A — Audit-page polish + zone numbering (`70d0ef3`, `299bb2f`, `edc214c`)**
- **#6 (zone numbering 0- vs 1-indexed):** Logs and the audit page showed zone IDs zero-indexed while the dashboard, map, and config all label zones starting at 1. Server-side log/format-only fix — added `+1` at every log emission site in [irrigation.py](../smart-garden-server-live/irrigation.py) and [database.py](../smart-garden-server-live/database.py) (`%d` → `zone_id + 1` in the format args). Internal DB IDs stay zero-indexed — only the human-facing strings move. Zero schema/behavior change.
- **#9 (stale sensor_fault rows):** April-dated `sensor_fault` rows for non-existent sensors stuck visible on the dashboard. Root cause: the fault-emitter loop iterated every sensor in config without first checking whether the sensor was actually installed; once soil sensors were removed from config, the alert checker still fired for them. Fix: guard `null/missing sensor reading → skip fault generation`, plus a one-time `UPDATE sensor_fault SET resolved_ts=now() WHERE sensor NOT IN (current config)`.
- **#10 (audit page false-STALE on skip_event):** `/api/audit` flagged `skip_event` as STALE because the cadence threshold was 1 hour, but skips only happen on cycles (every 5 min) and only when at least one zone gets skipped. Reset the per-table threshold to 6 hours so a calm period doesn't trip the alarm. Same fix pattern applied to `system_health`. Tweak in `AUDIT_TABLE_SPECS` only.
- **#11 (orphan 0-byte DB files):** Two leftover empty files on the server (`garden.db`, `smart-garden.db.tmp`) from old experiments — confused `du` and could confuse future maintainers. Confirmed neither was open by `lsof`, `mv`'d both into `~/smart-garden-server/_backups/` for safety, didn't delete outright.
- **#12 (allow-list disk-read per request):** `_load_allowed_emails()` was hitting disk on every authenticated request (decorator runs early in the request lifecycle, file is 12 lines, but still — wasteful). Cached the list in module-level `_EMAIL_ALLOW_CACHE` with a 60s TTL. Bypasses cache on file mtime change. Measured: ~3-5ms saved per authenticated hit.

**Batch B — Security hardening (commit `4cc4273`)** — `closes #7 + #15`
- **#7 (SECURITY-HIGH: weak hardcoded SESSION_SECRET):** Flask session secret was a 16-character ASCII string committed in `server.py`. Rotated to a 64-byte URL-safe token loaded from `~/smart-garden-server/.env` (`SESSION_SECRET=...`). Fallback raises on missing env (no silent default). Logged-in sessions on the live site were invalidated by the change — re-login required once, no other impact.
- **#15 (SECURITY-MED: no CSRF protection on POST):** Flask-WTF wholesale was overkill for a 5-route admin app, so went with the lighter pattern: cookie `SameSite=Strict` + `Secure` + `HttpOnly`, which blocks cross-site POSTs at the browser layer. Same-site form posts (the only legitimate POST source) still work. App is behind Cloudflare tunnel TLS so `Secure` is satisfied. Verified by re-logging in + watching the cookie attributes in DevTools.

**Batch D-1 — Error visibility (commit `a453068`)** — `closes #14`
- **#14 (silent `except Exception:` blocks):** 18 bare-except blocks across `irrigation.py`, `dashboard.py`, `database.py`, `server.py`, `billing.py` swallowed exceptions to a `pass`. Replaced each with `log.exception("context: ...")` so the traceback hits journald instead of vanishing. Kept the broad `except` (changing to typed exceptions risked regressions in the cron jobs that have to never die) — just made them visible. Validated by `grep -c "except Exception:" *.py` before/after.

**Batch D-2 — XSS sweep (commit `6fac583`)** — `closes #13`
- **#13 (XSS via `innerHTML +=` of untrusted data):** Zone names are user-editable from the Settings tab and they were rendered raw via string concatenation into `innerHTML` in 17 different sinks (dashboard tiles, map popups, history tables, forecast rows, etc.). Added two helpers to [index.html](../smart-garden/server-prod/templates/index.html) — `esc(s)` for text-context and `escAttr(s)` for attribute-context — and wrapped every interpolation of `zone.name`/`zone.label`. One attribute-context site (a `data-zone-name` on a button) used `escAttr` instead. Visual diff before/after on the dashboard: zero change for normal names; renders e.g. `<img src=x onerror=alert(1)>` as literal text now.

**Batch D-3 — Race condition fix (commit `9fcae44`)** — `closes #8`
- **#8 (same-zone double-tap creates duplicate watering_event rows):** The follow-up to #3, but in the *concurrent* case rather than the *sequential* case. #3's idempotent guard (`if zone_id in self._active: return True`) was a check-and-act with no lock — two threads firing within the same ~200ms could both see the zone free, both call `open_valve`, both insert a `watering_event` row.
  - Added `self._start_lock = threading.Lock()` in `IrrigationEngine.__init__` (mirrors the existing `_status_lock` pattern at L149).
  - Restructured `start_zone_watering()` as **reserve-then-do-IO**: under the lock, check `_active` and immediately insert a sentinel `{event_id: -1, weather_scale_pct: 100, ...}`; release the lock; do the slow stuff (weather fetch + ESP32 `open_valve` + `db.start_watering`); re-acquire briefly to swap the real `event_id` in. Concurrent callers see the zone busy at step 1 and short-circuit. The lock is held only for the dict mutation — never for I/O — so other zones' status calls don't block on a slow valve open.
  - Every early-return path (weather scale 0% skip, `open_valve` failure) releases the reservation. Wrapping `try/except` releases on any unexpected exception and re-raises, so the zone never gets stuck "busy" forever after a crash.
  - **`weather_scale_pct=100` sentinel (not 0)** — chosen deliberately. The scheduler's `_evaluate_active_zone` reads `weather_scale_pct` and computes `adjusted_runtime_min = max * scale / 100`. If we'd seeded the sentinel with `0`, a 5-min scheduler tick landing in the reservation window would compute `runtime=0`, see `elapsed >= 0`, and call `_decision("close", ...)` on a zone that just got reserved. `100` is inert.
  - **Defensive `event_id == -1` short-circuit added to `_evaluate_active_zone`** as belt-and-suspenders. Returns a "wait" decision if the scheduler races in mid-reservation.
  - Frontend: per-zone 800ms debounce on the map-tab `ctrlMapValve` / `ctrlMapRun` handlers (the only buttons that lacked a `CTRL_BUSY` guard). `ctrlToggleValve` on the Controls tab already had global `CTRL_BUSY`.
  - **Row 165 cleanup not done** — scanned the live DB for any same-zone same-start-second pairs ever (`SELECT a.id, b.id FROM watering_event a JOIN watering_event b ON a.zone_id=b.zone_id AND a.start_ts=b.start_ts AND a.id<b.id`) and found zero. Row 165 itself isn't there either. Either the originally reported duplicate was already cleaned up by the #3 fix's `UPDATE watering_event` or the issue body misread the data. Nothing to delete.
  - **Stress test deferred:** would need to mock `open_valve` to avoid hammering the ESP32. Verified by visual code review + post-deploy manual double-tap test. Tracked as a follow-up.

**Audit series summary:**
- Issues filed today: #1–#15 (+ pre-existing #16, deferred)
- Issues closed today: **#1, #2, #3, #4, #5, #6, #7, #8, #9, #10, #11, #12, #13, #14, #15** (15 of 16)
- Issues still open: **#16** only (`cam-upload` accepts unauthenticated POSTs — explicitly deferred per "cam should wait")
- Commits this session: `13796e0` (#3) → `28b5233` (#4) → `77f7dd6` (#5) → `9898bae` (audit page) → `70d0ef3` (audit threshold) → `299bb2f` (zone numbering #6) → `edc214c` (#9/#10/#11/#12) → `4cc4273` (security #7+#15) → `a453068` (#14) → `6fac583` (#13) → `9fcae44` (#8)
- Architectural lessons reinforced:
  - **Silently-empty tables are the worst kind of bug** (#4, #5 went undetected for months). The `/audit` endpoint shipped this session is the durable counter to that — every table with an expected write cadence gets surfaced as EMPTY or STALE on a self-serve page.
  - **Check-and-act without a lock is always a race**, even on a "small" 200ms window (#8). The reserve-first sentinel pattern is the right shape for any "claim resource, then do slow I/O" path.
  - **Sentinel values for partially-initialized state need to be inert against downstream readers**, not just distinguishable from real values. `event_id=-1` was correctly chosen, but `weather_scale_pct=0` would have introduced a new race; `100` is safe.
  - **`scp foo bar host:~/dest/`** flattens both files into `dest/` — already burned by this in the heritage-vault memory; held this session by always scping templates to `templates/` explicitly.

---

## Session Log: 2026-06-03 (Site Polish Sweep — 11 issues closed)

Audited the whole web UI for drift, filed 9 issues (#17–#25), shipped fixes for all of them plus closed-out #15/#16 from yesterday. Commits: `1f5af36` (#18), `7b38392` (#17/#20/#21/#24/#25), `30d4a7e` (#19), `3442287` (#22).

**What shipped:**

- **#18 (HIGH)** Committed the 4 server-only templates (`login.html`, `map.html`, `history.html`, `sensors.html`) into git. Same drift pattern that bit Heritage Vault 2026-06-01 — risk was real.
- **#20** Deleted dead `forecast.html` + `forecast_vs_actual.html` from repo and server.
- **#17 + #21** Forecast page rewritten: dark theme → shared light-theme palette, added cloned sidebar + `<div class="main">` wrapper, added ESP32 status poller hitting `/api/health` every 30s.
- **#24** Removed redundant breadcrumb at top of moisture-sim.
- **#25** Moisture-sim sidebar footer now mirrors dashboard (ESP32 status dot + auto-refresh hint), same status poller.
- **#23** Moved server's `templates/dashboard.py`, `database.py`, `irrigation.py` (stale Apr 11 copies, not used by Flask) + all `*.bak` files into `~/smart-garden-server/_backups/`. templates dir is now .html only.
- **#19** Kept `/map` (added to every sidebar + index mobile nav as "Zone Map" — the fullscreen aerial-photo view with pulsing sprinkler heads is unique). Deleted `/history` and `/sensors` routes + templates (dashboard panels cover them).
- **#22** All three pages now share an identical 8-item mobile bottom nav: Home / Zones / Map / History / Settings / Forecast / Moisture / Cam. Same classes, same active color (`--green-dark`).

**Discovered + fixed mid-session:** `scp` flattened paths sent template files to `~/smart-garden-server/` root instead of `templates/` — caught immediately via `ls`, cleaned up, redeployed correctly. Lesson reinforced from the heritage-vault memory: always `scp templates/foo.html ... :~/svc/templates/`.

**Closed:** #15 (banner past-time roll-forward), #16 (mm-as-inches 25.4× bug), #17, #18, #19, #20, #21, #22, #23, #24, #25 — 11 issues.

**Remaining open:** firmware-side wedge issues #5 / #6 / #2 + meta #4 / #1. None UI-related.

---

## Session Log: 2026-05-26 (Forecast vs Actual + Battery Optimization)

### Server: Forecast vs Actual feature (deployed)

**New DB table:** `forecast_snapshot` — captures daily per-zone predictions (balance, ET, days-until-water, predicted skip reason). Schema in `database.py`, UNIQUE on `(forecast_date, zone_id)`.

**Daily job:** `save_daily_forecast_snapshot()` in `irrigation.py` — runs at **3:55 AM** (cron in `server.py`) before the 4:00 AM watering window. Records what the system predicts will happen.

**Comparison engine:** `get_forecast_vs_actual(days)` in `database.py` — LEFT JOINs forecast snapshots with `watering_event` and `skip_event`. Computes outcome labels: `correct_water`, `correct_skip`, `false_skip`, `missed_skip`, `no_event`. Also `get_forecast_accuracy_summary(days)` for aggregate stats.

**API endpoints** (in `dashboard.py`):
- `GET /api/forecast-vs-actual?days=30` — comparison data + accuracy summary
- `POST /api/forecast-snapshot` — manual trigger for testing
- `GET /forecast-vs-actual` — serves `forecast_vs_actual.html`

**UI:** `templates/forecast_vs_actual.html` — dark theme matching existing dashboard. Accuracy banner, date-grouped timeline, zone/outcome/date-range filters, "Take Snapshot Now" button. Nav links added to desktop sidebar (🎯 icon) and mobile bottom nav.

**Files changed on Acer:** `database.py`, `dashboard.py`, `irrigation.py`, `server.py`, `templates/index.html`, `templates/forecast.html`, `templates/forecast_vs_actual.html`.

**First snapshot seeded:** 9 zones (Front Yard A/B, Enclosed Backyard A/B, SE, S, SW, Garden, Grapes). Sprinkler zones ~9 days until water, drip zones ~16-19 days.

### Server: Battery voltage chart prominent (deployed)

- **Home page:** Battery voltage card added below health cards (Uptime/WiFi/Memory/Crashes), above Sensors. Shows current voltage with color coding (🟢>12.4V, 🟡12.0–12.4V, 🔴<12.0V, ⚡>13.5V charging) + 24h chart.
- **History page:** Battery chart moved to top (first chart, before DHT22/Soil). Same color legend + 200px chart with time range buttons.
- Home chart loads on page init via `loadBatteryChart('home-chart-battery', ...)`.
- History chart loads in `loadSensorHistory()` as `sh-chart-battery-top`.

### Firmware: Power optimization (FLASHED 2026-05-27)

**Root cause identified:** `handleApiStatus()` set `lastApiActivityMs = millis()` on every call. Server polls `/api/status` every 5 min. `AWAKE_HOLD_MS = 300000` (5 min). Result: chip never entered light sleep — each poll arrived just as the hold expired.

**Changes in `src/main.cpp` and `src/config.h`:**

1. **`handleApiStatus()` no longer resets `lastApiActivityMs`** — status polls (read-only) let the chip wake briefly (~50ms), serve, and go back to light sleep. Only state-changing commands (valve, closeall, reboot) keep the chip fully awake for 5 min. This is the big win (~80 mA saved idle).

2. **`RUN_CPU_MHZ` 240 → 160** in `config.h` — still fast enough for WiFi + web server, saves ~15% CPU power.

3. **`WiFi.setSleep(false)` comment updated** — clarified this is only for initial connect; the light sleep path already re-enables `WIFI_PS_MIN_MODEM` correctly via `esp_wifi_set_ps()`.

**Expected impact:** ~120-150 mA continuous → ~30-50 mA average (mostly sleeping). On 7Ah SLA: ~2 days → ~5-6 days runtime without solar.

**Valve commands still instant:** chip wakes from light sleep on incoming WiFi packet, <100ms latency.

**To flash:**
```powershell
cd C:\MyCode\smart-garden
pio run -e esp32 --target upload --upload-port COM5
pio device monitor --baud 115200 --port COM5
```

### Hardware recommendations noted
- **Bigger battery:** 12V 20Ah (~$40-50) would give ~3 weeks reserve vs 7 days with 7Ah.
- **Solar angle:** Tilt panel to ~48° (latitude match) for 30-40% winter output improvement.

---

## Session Log: 2026-04-26 (Web Server Wedge Deep Dive)

### Timeline

**~20:30** — Started debugging ESP32 web server wedge. Server had been STOPPED for 18 days (nobody noticed — no heartbeat alert, see M9). V2 firmware (cached-battery fix) on chip.

**~20:50** — Ran a 5-min poll test. Got alternating OK/TIMEOUT results at 30s intervals — 50% failure rate with no server running. Only my test curls.
```
20:51:06 try 1: TIMEOUT
20:51:36 try 2: OK rssi=-38 boot=1327 uptime=189s
20:52:06 try 3: TIMEOUT
20:52:36 try 4: OK rssi=-38 boot=1327 uptime=249s
...
```

**~21:15** — Restarted smart-garden-server. Immediately hit 22 consecutive `Connection refused` errors. Chip wedged and didn't recover during observation window.

**~21:30** — Stopped server. Began systematic debugging.

**~21:45** — Key breakthrough: reproduced wedge with SINGLE curl + 35s gap. No concurrent requests needed. This ruled out all "pool exhaustion from concurrent connections" theories.

**~22:00** — Tried `WiFi.setSleep(false)`. No effect. Gap test still failed with non-monotonic pattern (fails at 5s, passes at 15s, fails at 20s, passes at 30s). WiFi sleep would produce monotonic failure, so this was definitively ruled out.

**~22:15** — Read Arduino WebServer + WiFiServer library source (PlatformIO packages dir). Found `if(_listening) return;` guard in `begin()` — can't just call begin() again. Need close() first. Also confirmed route handlers survive close/begin cycles.

**~22:30** — Implemented periodic socket reset: `server.close(); server.begin();` every 10s in loop(). Flashed V4 firmware.

**~22:45** — Gap test passed 7/7 (all 200s for 5-30s gaps). Prematurely marked issue "FIXED."

**~23:00** — Started soak test with longer gaps (60s, 120s, 180s, 300s, then back down).

**~23:03** — Soak test result: 60s gap → 200 ✅, 120s gap → 000 ❌, 180s gap → 200 ✅. SSH dropped during 300s sleep. **Fix is incomplete.**

### What changed in firmware (V4, on chip now, commit pending)

1. `WiFi.setSleep(false)` after WiFi connect (~line 609) — belt-and-suspenders, doesn't fix wedge alone
2. Periodic `server.close(); server.begin();` every 10s in loop() (~line 805-814) — partially fixes wedge (short gaps only)

### Wrong turns tonight
1. **"lwIP PCB pool exhaustion"** — wrong (1 request can't exhaust 5 slots)
2. **"WiFi modem sleep"** — wrong (WiFi.setSleep(false) no effect; non-monotonic failure pattern rules it out)
3. **PowerShell→SSH→Python quoting** — wasted time 3x before switching to scp'd scripts (M14)
4. **SSH inline bash for-loops** — PowerShell interpolated `$gap` before SSH saw it; `bash -c` split by SSH as multiple args

### What worked
- **Minimal reproduction:** 1 curl + wait + 1 curl. Eliminated all concurrency theories.
- **Reading library source:** Found `if(_listening) return;` guard, route handler lifecycle, `Connection: close` on every response.
- **File-based remote scripts:** scp script.sh → ssh bash script.sh. Reliable, no quoting issues.
- **Keeping V2 fix:** Almost reverted it; reading own git diff comments prevented a mistake (M12).

### Pivot: server-side resilience instead of firmware perfection (~23:10)

Rather than chasing a perfect firmware fix (shorter intervals, ESPAsyncWebServer), pivoted to server-side resilience. The firmware socket reset handles the common case (gaps <60s); the server retry handles the rest.

**Changes deployed:**

1. **`irrigation.py` — retry in `get_esp32_status()`:** Inner try/except → 10s sleep → retry once. The 10s delay matches firmware's socket reset interval, guaranteeing the retry hits a fresh listen socket.

2. **`dashboard.py` — bypass routes fixed (all 5):**
   - `/api/health`: replaced `import requests as _req; _req.get(esp32_url/api/status)` with `engine.get_esp32_status() is not None`
   - `/api/valve-health`: replaced `_req.get(esp32_url/api/status)` with `engine.get_esp32_status()` + None check → 503
   - `/api/telemetry` (3 sub-calls): replaced `import requests as _req` + 3 throwaway `_req.get()` calls with `engine._esp32_status` pooled session + `engine.esp32_url`
   - Zero remaining throwaway TCP connections to ESP32

3. **`irrigation.py` — battery_v passthrough:** `log_system_health()` was never given `battery_v=system.get("batteryV")`. Firmware already reported it, DB column existed, chart JS existed — just this one missing arg.

**Deployed via scp, server restarted.**

### 10-minute production test results (~23:21–23:31)

| Metric | Count |
|--------|-------|
| Decision cycles attempted | 2 |
| Decision cycles completed | **2 (100%)** |
| Skipped ("Cannot reach") | **0** |
| Transient failures (attempt 1 fail, retry succeeded) | 3 |

Every single wedge was recovered silently by the 10s retry. Zero cycles lost.

### USB unplug test (~23:25)

User unplugged USB cable. Immediate probe returned HTTP 000 (unreachable). Ping confirmed WiFi was up — just the web server wedged again (possibly DTR/RTS pulse on USB disconnect triggered a brief reboot). Next scheduled cycle at 23:26:41 succeeded — retry caught it.

### Battery voltage pipeline fix (~23:35)

Discovered `battery_v` was NULL in all DB rows despite firmware reporting `batteryV` in `/api/status` since V4. Root cause: `log_system_health()` call in irrigation.py was missing the `battery_v=` kwarg. One-line fix. After deploy, first row with data: `2026-04-26T23:38:31|16.5` (16.5V is wrong — voltage divider not wired to GPIO 36 yet, pin is floating and reading noise × 5).

### Commits

| Commit | Repo | Description |
|--------|------|-------------|
| `fdd6300` | smart-garden | V4 firmware: WiFi.setSleep(false) + periodic socket reset every 10s |
| `624b6d9` | smart-garden-server | Server-side resilience: retry + dashboard bypass |
| `d7d01f3` | smart-garden-server | battery_v passthrough to system_health DB |

---

## Session Log: 2026-04-27 (Cascade — overnight crash loop, morning reboots, then 70+ min hung wedge)

### Two-phase failure

**Phase 1 (overnight): WiFi watchdog crash loop.** Documented separately in smart-garden-issues.md "OPEN 2026-04-27: WiFi watchdog crash loop." 38 reboots between 01:23\u201302:18 from the WiFi watchdog in `loop()` calling `ESP.restart()` after 60s of disconnection. Self-recovered at boot #1383 when WiFi came back. Wrote up RCA, identified fix candidates (raise threshold to 5min, close-all valves before reboot), did NOT yet ship.

**Phase 2 (morning): hung wedge.** This session.

### Phase 2 timeline

| Time | Event |
|------|-------|
| 02:18 | Overnight crash loop ends. Stable on boot 1383, crashCount=38, safeMode=true. |
| 02:18\u201307:13 | ~5h stable. Telemetry every 5 min, all 200s. |
| 07:13 | Crash-loop alert fires (lookback caught the overnight cluster). |
| 07:33 | New unexpected reboot \u2192 boot 1384, crashCount=39. |
| 07:38 | Boot 1385. Per system_health row, crashCount jumped from 39 to 1 \u2014 **NVS crashCnt was cleared** (probably by user or some auto-clear path; need to verify). |
| 07:48 | Boot 1386. WiFi reconnects 0\u21929. |
| 08:03 | Three more reboots in burst (1386\u21921389). Crash counter increments 1\u21922. |
| 08:13\u201308:39 | Brief stable window \u2014 only 3 successful HTTP polls in 26 min, all with abnormally high latency (2.8s, 6.0s, 11.4s vs normal <1s). |
| **08:39:48** | **Last successful HTTP poll.** Boot 1389, uptime 2474s. |
| 08:39 \u2192 09:51 | Total silence. 666 connectivity_log failures, 0 successes. ICMP still works perfectly. |
| 09:51 | User pings dashboard, sees \"Offline.\" Investigation begins. |

### Investigation steps (this session)

1. **Server health probe** \u2014 confirmed `smart-garden-server` systemd service running, port 5125 healthy, API responding. Symptom is chip-side, not server-side.
2. **ICMP probe** \u2014 ping 10/10, 5\u201310ms RTT. Chip is on the LAN, WiFi/lwIP responsive at kernel level.
3. **Raw TCP probe** (15 attempts every 2s for 30s) \u2014 15/15 REFUSED. No natural recovery in observation window.
4. **Pcap capture** during probes:\n   ```\n   client SYN \u2192 chip RST(win=0)  within 9 ms\n   ```\n   Gold-standard signature of the documented stale-listen-socket wedge bug.\n5. **DB timeline pull** \u2014 `system_health`, `connectivity_log` tables on Acer. Built the timeline above.\n6. **journalctl pull** \u2014 confirmed alert sequence (Crash-Loop, Unexpected reboot, Crash counter incremented, ESP32 Offline at 20/50/84-min thresholds).\n\n### Diagnosis (HONEST framing after pushback)\n\n**Initial draft (wrong-confidence):** Asserted \"loopTask is dead, RTOS is alive \u2014 NEW failure mode\" based on \"10s socket reset is NOT firing\" reasoning.\n\n**Corrected:** Most likely the **same** stale-listen-socket wedge documented in 2026-04-26 entry. Existing memory already documents:\n- V4 firmware's 10s reset is **incomplete** (`after_120s: 000 \u274c`, \"deeper lwIP state that accumulates over longer idle periods\")\n- ICMP works fine while port 80 RSTs (per 2026-04-26: \"serial monitor shows loop() healthy during wedge\")\n\n**The 30-sec REFUSED probe is consistent with EITHER:**\n- (a) loopTask dead, reset not firing\n- (b) loopTask alive, reset firing every 10s, wedge unbreakable by close()/begin()\n\nMemory already documents (b) is real. Cannot distinguish without serial console.\n\n**What's genuinely new today (and only this):**\n1. **Duration:** 70+ min vs. previously observed max ~3 min\n2. **Preceded by reboot cascade** (six reboots between 07:33\u201308:03)\n\nNot a new failure mode \u2014 likely the same wedge bug pushed deeper by morning's instability.\n\n### Mistake logged (M16 in mistake-ledger)\n\nAsserted dramatic hypothesis (\"loopTask hung, RTOS alive \u2014 NEW failure mode\") as a finding when evidence equally supported the documented bug in a worse instance. Wrote multi-section RCA labeled OPEN before noticing existing memory already documented the same SYN\u2192RST signature with an incomplete V4 fix. User had to push back (\"are you sure this is a new thing?\") before I checked. **Guard:** before labeling a bug NEW, grep `*-issues.md` for the gold-standard signature; enumerate which observations differ vs. match; default to \"this is the known bug\" when pcap matches.\n\n### Recovery action\n\n**User must physically power-cycle the junction box.** Software-side recovery is impossible \u2014 we have no out-of-band path to the chip. After power-cycle, run `/tmp/probe.sh` on Acer to verify the 10s reset is firing again (look for periodic OK responses).\n\n### High-priority follow-ups (added to Open Issues table)\n\n1. **Web server wedge can persist indefinitely** \u2014 V4 socket reset is insufficient for deep wedges. Need stronger recovery mechanism.\n2. **No out-of-band ESP32 recovery path** \u2014 highest-ROI fix is a $15 WiFi smart plug on the chip's power line so the server can hard-reset when wedge passes 5 min. Independent of any firmware fix.\n3. **WiFi watchdog too aggressive** \u2014 60s threshold + ESP.restart() triggers crash loops. Raise to 5 min and close-all valves before reboot.\n4. **TWDT not subscribed for loopTask** \u2014 chip can hang silently with no auto-reboot. Add `esp_task_wdt_add(NULL)` in setup, `esp_task_wdt_reset()` early in loop. If loop ever blocks >5s, chip reboots automatically.\n\n### Diagnostic commands that worked (save these)\n\n```powershell\n# Confirm SYN\u2192RST signature (gold standard)\nssh acer \"sudo timeout 8 tcpdump -i any -n -tttt 'host 192.168.0.150 and port 80' -c 20 2>/dev/null > /tmp/pcap.out & sleep 1; for i in 1 2 3 4; do timeout 2 bash -c 'exec 3<>/dev/tcp/192.168.0.150/80' 2>/dev/null; sleep 1; done; sleep 6; cat /tmp/pcap.out\"\n\n# Probe TCP availability every 2s for 30s (expect periodic OK if 10s reset working)\nssh acer 'bash /tmp/probe.sh | tee /tmp/probe.out'  # script saved on Acer\n\n# Pull boot/crash timeline from DB\nssh acer \"sqlite3 ~/smart-garden-server/smart-garden.db \\\"SELECT ts, uptime_sec, boot_count, crash_count, wifi_rssi FROM system_health ORDER BY id DESC LIMIT 15\\\"\"\n\n# Connectivity status counts last 12h\nssh acer \"sqlite3 ~/smart-garden-server/smart-garden.db \\\"SELECT success, COUNT(*) FROM connectivity_log WHERE ts >= datetime('now','localtime','-12 hours') GROUP BY success\\\"\"\n\n# Server's view of the outage\nssh acer \"sudo journalctl -u smart-garden-server --since '07:00' --no-pager | grep -E 'recovered|crashCount|Alert sent'\"\n```\n\n### Failure error mix (last 12h)\n- 168\u00d7 `Connection refused` (chip RSTs SYN \u2014 current dominant mode)\n- 28\u00d7 `ReadTimeoutError`\n- 9\u00d7 `Read timed out`\n- 6\u00d7 `ConnectionResetError(104)` (mid-stream RST)\n- 12\u00d7 `ConnectTimeoutError` (during reboots when chip momentarily off LAN)\n\nMix is consistent with chip cycling through reboots in the morning, then settling into the deep wedge that's held since 08:39.\n\n---\n\n## Codebase map

### Firmware (`C:\MyCode\smart-garden\`)
| File | Purpose |
|------|---------|
| `platformio.ini` | esp32 (USB COM3) + ota (espota WiFi, default off) envs |
| `src/config.h` | WiFi, pins, `API_REBOOT_TOKEN "garden-reboot-9847"`, `WIFI_TX_DBM` |
| `src/main.cpp` | Valve control, sensors, web server, REST API, NVS-persistent boot count + crash counter |
| `smart-garden-issues.md` (memory) | All the painful lessons |

### Server (`C:\MyCode\smart-garden-server\` → Acer `~/smart-garden-server/`)
| File | Purpose |
|------|---------|
| `config.yaml` | Zones, billing, weather adjustment, esp32 reboot_token |
| `database.py` | SQLite schema + helpers |
| `weather.py` | Open-Meteo client, ET₀, 30-min cache |
| `irrigation.py` | Decision engine + ESP32 HTTP layer + `reboot_esp32()` |
| `dashboard.py` | Flask UI + REST endpoints (incl. gated `/api/reboot`) |
| `notifications.py` | ntfy.sh sender (ASCII-only title) |
| `server.py` | APScheduler + Flask entry |

### Scheduler intervals
- Irrigation cycle: 5 min
- Safety check: 2 min
- Weather fetch: 30 min
- Daily soil balance: 11 PM

### Decision skip order
already wet → not dry enough → recent rain → rain forecast → freeze → wind (sprinklers) → budget → outside window

---

## Key decisions

1. **Latching solenoids** — Orbit 57861, hold position with no power
2. **L298N H-bridge** — Cheap polarity-reversal driver
3. **Acer as bridge** — Copilot can't reach LAN IPs directly

---

## Current device state (as of 2026-04-27 19:30)

- Firmware: **MASTER** (reflashed 19:00 after AsyncWebServer test). Commits on chip: `fdd6300` + `53a91d9` + `a01b3f5` + `e01f984` (#6 diag) + `a32ea8c` (txPowerRaw API).
- Server: **RUNNING** (systemd `smart-garden-server`, port 5125, healthy)
- Power: Victron charger → 12V SLA → LM2596 buck → ESP32 VIN. **USB plugged in for diagnostics**.
- Location: **on desk near router** (NOT in junction box yet)
- **Chip status: UP** — boot 1400, healthy when responsive, but **wedges every 3-5 min** (documented today)
- TWDT: **subscribed and active** (60s timeout)
- TX power telemetry: **collecting**. 4 boots sampled today: 31 / 59 / 57 / 56 (all below 78 target).
- Branch state: `master` checked out. `feature/async-webserver` preserved (commit `f943a95`, NOT pushed) for possible future re-attempt with different config.
4. **No MQTT** — REST is enough
5. **Static IP in firmware** — 192.168.0.150 hardcoded, no DHCP dependency
6. **OTA disabled by default** — Wanderer brownouts make it unsafe; USB-only flashing accepted
7. **Server `/api/reboot` gated default-off** — Same brownout root cause
8. **Two-DB architecture** — Collector writes to one, dashboard falls back to it when main DB stale (resilience over root-cause fix for unknown SIGKILL source)

---

## Hardware to-do (when parts arrive)

Per archive 2026-04-14: P-channel MOSFET power gate for L298N rail + ESP32 deep sleep between watering windows. Estimated battery draw 76-148 mA → 11-18 mA (battery life 2-3 days → ~20 days).

Parts ordered: 10kΩ + 1kΩ resistors. **TO ORDER:** ~~IRF4905 P-FET, 2N3904 NPN~~. Full circuit + wiring steps in archive.

**UPDATE 2026-04-26:** MOSFET gate **installed and verified** (see Recently shipped). Battery monitoring also shipped. Deep sleep (Phase 2) deferred — user wants to observe battery behavior with gate alone first.

---

## Physical Installation Plan & Parts Inventory

**Full purchase history, fitting analysis, and shopping list** → [purchase-history.md](purchase-history.md)

**Design:** 2 valve boxes, 9 valves total, 27 Rain Bird 42SA+ rotor heads, 2 drip zones. 1in poly trunk splits to two valve box manifolds. ¾in poly laterals to each zone. ½in swing pipe risers to rotors.

**Water source:** 60 PSI, ~6 GPM at top of hill. No reducers needed for sprinkler zones. Pressure regulators on drip zones only.

**Status (2026-05-01):** ~$106 of fittings/rotors/valves still needed before install. See shopping list at bottom of purchase-history.md.

---

## Recently shipped (last 7 days)

| Date | Change | Commit |
|------|--------|--------|
| 2026-04-27 19:00 | **ESPAsyncWebServer port TESTED — RULED OUT.** Branch `feature/async-webserver` (commit `f943a95`) ported all 8 handlers + deferred-action loop processor (build clean). Soak test at production 5-min cadence: 5/7 fail with identical SYN→RST(win=0) signature. Server connectivity log showed alternating 3-5 min wedge/clean cycles regardless of library. Bug is below app layer. Master reflashed. Branch retained. Full RCA in [#5 comment](https://github.com/jamesearlpace/smart-garden/issues/5#issuecomment-4331800723). M18 logged in mistake-ledger (first-attempt test design used wrong cadence). | (branch only, NOT merged) |
| 2026-04-27 16:00 | **Dashboard:** TX Power column added to System Health History table (color-coded). | (server) |
| 2026-04-27 15:50 | **Telemetry pipeline #6:** `txPowerRaw` in `/api/status` (firmware) + `tx_power_raw` INTEGER column in `system_health` (server) + passthrough in `irrigation.py`. Verified end-to-end. | `a32ea8c` (firmware), `dc4d5be` (server) |
| 2026-04-27 15:30 | **Diagnostic firmware for #6:** capture `setTxPower` return value + actual `getTxPower` reading both pre-connect and post-connect. Surfaced "boot lottery" hypothesis (TX caps vary 7.8–14.8 dBm between boots). | `e01f984` (firmware) |
| 2026-04-27 07:50 | **Battery divider 5:1 → 6:1:** added 10kΩ resistor to fix ADC saturation. | `a01b3f5` (firmware) |
| 2026-04-27 07:34 | **WiFi watchdog tuning:** threshold 60s→5min, close-all valves before `ESP.restart()`. Direct fix for overnight 38-reboot cascade. | `53a91d9` (firmware) |
| 2026-04-26 | **MOSFET power gate installed** (IRF4905 + 2N3904 on GPIO 2) — cuts 12V to all 5 L298Ns when idle. **Battery voltage divider on GPIO 36** (4×10k + 1×10k, ratio 1:5). Firmware: `enableDriverPower()`/`disableDriverPower()` around every valve pulse, `batteryV` in `/api/status`. Verified: 12.86V battery reading, all 7 valves cycle cleanly through gate on boot. | `fdd6300` (firmware) |
| 2026-04-26 | **Server-side resilience:** retry with 10s sleep in `get_esp32_status()`, all 5 dashboard bypass routes fixed, `battery_v` passthrough to DB. 10-min production test: 2/2 cycles, 0 skips, 3 transient wedges recovered. | `624b6d9`, `d7d01f3` (server) |
| 2026-04-22 | Active monitoring: counter-delta + chip-temp alerts + 8 AM digest + startup ping | `e53417a` (server) |
| 2026-04-22 | Gated `/api/reboot` 503-by-default, irrigation.py reboot wrapper, config.yaml token | `a89dc35` (server) |
| 2026-04-21 | ASCII-strip ntfy title (#11) | `51eb250` (server) |
| 2026-04-21 | TX 19.5dBm + ArduinoOTA `#ifdef`-gated | `7ba2262` (firmware) |
| 2026-04-21 | TIME_WAIT fix: status cache 30s + retries 0 + debounce 5 polls | `a7a1114` (server) |
| 2026-04-17 | Stale dashboard fix — collector DB fallback | `a614302` (server) |

For older entries see [smart-garden-journey-archive.md](smart-garden-journey-archive.md).

---

## 2026-04-22 — Overnight soak test + chip-temp diagnosis

**Context:** First night of unattended operation since the active-monitoring shipped (`e53417a`). Chip indoors in living room next to router (room temp ~22°C, RSSI -42 dBm). Soak test on Acer polled `/api/status` every 60s for 8 hours.

**Results:**
- **Connectivity: 437/437 polls successful (100%)**
- bootCount = 1298 unchanged for 8h (zero unexpected reboots)
- wifiReconnects = 4 unchanged (zero overnight reconnects)
- crashCount = 19 unchanged (zero crashes)
- safeMode False, freeHeap stable ~232 KB (no leak)
- RSSI -42 dBm steady (occasional -67 spikes, likely beacon timing — no impact)
- 8 AM daily digest fired on schedule
- Startup ping fired 10s after restart as designed

**Anomaly investigated:** 4 ntfy alerts overnight for `chipTempC > 85°C` — peaks 105.5°C, 110.6°C (×3), 87.2°C. Conclusion: **sensor noise, not real heat.** Evidence:
- Rapid-poll test (10 reads, 3s apart): all 77.2–77.8°C, dead flat
- 30 surrounding soak samples: min 77.2, max 86.7, avg 77.8 — only 1 outlier
- Physics: ESP32 die can't drop 30°C in 4 minutes (78→105→78 sample sequence)
- ESP32 internal temp sensor is documented as factory-uncalibrated and noisy on individual reads

**Real die temp:** ~78°C steady. That's 56°C above 22°C ambient — normal for ESP32 with WiFi @ 19.5 dBm sustained. Well under 125°C absolute max. Chip is **not** being overworked.

**Decision:** Document first, change nothing. Proposed fix (NOT YET DEPLOYED): require 3 consecutive `chipTempC > 85` samples before paging. Tracked in Open Issues table above.

**State at end of session:**
- Firmware: `7ba2262` (last flashed 2026-04-21)
- Server: `e53417a` deployed on Acer, service active
- Soak script: `/tmp/sg-soak.sh` on Acer (one-shot, finished). Status helper: `c:\Temp\sg-status.sh` and `/tmp/sg-status.sh`
- Temp probe helper: `c:\Temp\sg-temp-probe.sh` (rapid 10-sample test)

---

## 2026-05-18 — Battery death recovery: two firmware bugs found & fixed

**Context:** ESP32 was offline — lights on but not on the network. Battery at 10.99V (near-empty for 12V SLA). Solar panel likely couldn't keep up during cloudy stretch, causing battery to sag below buck converter threshold. ESP32 lost power, then when battery recovered enough to boot, it came up but never reconnected to WiFi. Required manual EN button press to recover.

**Diagnosis:**
- Home server (Acer) reachable, `smart-garden-server.service` was already running
- ESP32 at 192.168.0.150: 100% ping loss, MAC `68:FE:71:0C:BA:98` not found anywhere on /24 subnet
- After manual EN reset: ESP32 booted, connected to WiFi, battery 10.99V, RSSI -64 dBm, crashCount 1

**Root cause — two bugs preventing auto-recovery after battery death:**

**Bug 1 — AP mode trap (WiFi watchdog):**
When `setupWiFi()` fails after 40 attempts (20s), it switches to `WIFI_AP` mode. The WiFi watchdog in `loop()` called `WiFi.disconnect()` + `WiFi.begin()` without switching back to `WIFI_STA`, so reconnect attempts silently failed because the radio was stuck in AP-only mode.

**Fix:** WiFi watchdog now does `WiFi.disconnect(true)` → `WiFi.mode(WIFI_STA)` → re-applies static IP config → `WiFi.begin()`. This ensures STA mode is active regardless of what `setupWiFi()` left behind.

**Bug 2 — Deep sleep crashCount lockout:**
`crashCount` increments on every boot and only resets to 0 when WiFi connects. After `SAFE_MODE_THRESHOLD * 2` (40) boots without WiFi, the ESP32 enters 10-min deep sleep. On wake, crashCount is *even higher* (41, 42, ...), so it immediately deep sleeps again — **permanently locked out**. Physical reset doesn't help because NVS persists across resets.

**Fix:** On deep sleep wake (`ESP_RST_DEEPSLEEP`), if crashCount ≥ threshold, cap it back to `SAFE_MODE_THRESHOLD` (20). This creates a sustainable retry pattern: try 20 times → sleep 10 min → try 20 more → sleep 10 min → ... until WiFi is available. No permanent lockout.

**Changes (not yet flashed):**
- `src/main.cpp`: WiFi watchdog — `WiFi.disconnect(true)`, `WiFi.mode(WIFI_STA)`, re-apply static IP before `WiFi.begin()`
- `src/main.cpp`: Deep sleep recovery — cap crashCount on `ESP_RST_DEEPSLEEP` wake

**Next steps:**
- [ ] Flash firmware via USB: `cd C:\MyCode\smart-garden && pio run -e esp32 --target upload --upload-port COM5`
- [ ] Monitor battery voltage — 10.99V is concerning, check solar panel positioning and Renogy charge controller LEDs
- [ ] Consider adding a low-voltage cutoff (e.g., don't attempt WiFi below 11.0V, just deep sleep and wait for solar)

---

## Session Log: 2026-06-01 (Irrigation Brain Mockup + FAO-56 Audit)

### What was built

Complete tier-5 irrigation brain mockup in `moisture-sim-preview.html` with:
- **Two-chart layout:** inverted precip bars (rain/sprinkler in inches) on top, moisture line below
- **Real weather integration:** fetches actual 2021-2025 Duvall data from Open-Meteo archive API
- **Year selector dropdown:** compare behavior across 5 years of real weather
- **8 decision types** verified firing across all years: water, catch-up, rain-skip, wind-skip, pre-emptive, water-despite-rain, hardening, emergency
- **Decision markers on chart:** colored shapes at each decision point, hover for reason
- **Checkbook tooltip:** hover any point to see ET loss, rain/sprinkler gains, temp, wind, MAD
- **Decision log with type-count badges:** debug summary of all decisions
- **Drag-to-zoom + scroll-to-pan** with synced precip/moisture charts

### FAO-56 Audit (IRRIGATION-AUDIT.md)

Found and fixed critical parameter errors:
- **Kc was 0.40-0.85 seasonal → fixed to 0.90 constant** (FAO-56 Table 12: cool-season turf = 0.90-0.95)
- **Removed seasonal Kc schedule** — ET0 handles seasonality naturally via solar radiation/temp
- **Added seasonal root depth** (4" spring → 8" summer → 6" fall) as the real source of seasonal variation
- **Rain skip threshold** 0.02" → 0.20" (PNW golf course standard — drizzle doesn't penetrate thatch)
- **Wind skip** > 10 → >= 10 mph (uses daily max forecast, not 4AM reading)
- **Hardening** fixed from multi-day vineyard-style to single-cycle turf-appropriate skip
- **Sliding rain effectiveness** by intensity (40% for drizzle, 65% medium, 80% heavy)
- **Heat guard on hardening:** blocked when 5-day avg > 85°F

### Key files created
| File | Purpose |
|------|---------|
| `moisture-sim-preview.html` | Full interactive mockup (1400+ lines) |
| `IRRIGATION-BRAIN.md` | Design document — algorithm, rules, data sources |
| `IRRIGATION-AUDIT.md` | FAO-56 comparison, parameter fixes, confidence levels |
| `irrigation-logic.svg` | Decision flowchart SVG |
| `sim-real-weather.js` | Node.js 5-month real-weather simulator |
| `sim-90day.js` | Synthetic 90-day PNW weather simulator |
| `tune-sim.js` | Parameter sweep tool |
| `check-decisions.js` | Verify all decision types fire across years |

### Confidence assessment
- **HIGH confidence:** ET0 from Open-Meteo, checkbook method, Kc=0.90, wind/rain skip, 4-6AM window
- **MEDIUM confidence:** Root depth schedule, recovery targets, single-cycle hardening
- **LOW confidence:** Temperature-dynamic MAD, exact soil AWC (need USDA Web Soil Survey)
- **User action needed:** Look up soil type on websoilsurvey.sc.egov.usda.gov, consider King County Conservation District free audit

### NEXT: Deploy to real server dashboard

The mockup is validated. The next session should:
1. **Read these files first:** `smart-garden-journey.md`, `IRRIGATION-BRAIN.md`, `IRRIGATION-AUDIT.md`
2. **Read the server code:** `~/smart-garden-server/dashboard.py`, `irrigation.py`, `weather.py`, `database.py`
3. **Add new page to server:** `templates/moisture_sim.html` — port the mockup's JS to the real dashboard
4. **Wire to live data sources:**
   - Open-Meteo FORECAST API (not just archive) for current 2026 + 7-day prediction
   - Open-Meteo ARCHIVE API for historical 2026 data (Jan 1 to yesterday)
   - Server SQLite DB for actual sprinkler run history (`watering_log` table)
   - Server SQLite DB for `forecast_snapshot` table (existing, created 2026-05-26)
5. **Show three data layers on the chart:**
   - Green moisture line: model prediction (checkbook balance)
   - Blue markers: actual sprinkler events from DB
   - Dashed future line: 7-day forecast prediction with expected watering decisions
6. **Show next expected watering:** "Based on forecast, next watering in ~2.3 days (Thu 4 AM)"
7. **Conservative mode first:** Checkbook + rain skip + wind skip only. Add hardening after first full summer.
8. **Do NOT remove the mockup** — keep `moisture-sim-preview.html` as the backtesting/validation tool

### 25+ commits this session
`306fd73` Fix hardening: single-cycle skip, turf-appropriate
`4c168ca` Rain skip threshold 0.20" (golf course standard)
`8f6fd99` Wind >=10, hardening heat guard 85F
`1346404` Apply audit fixes: Kc=0.90, seasonal root depth
`ca9522f` Audit document
`5db5b31` Brain design document
`d756a6f` Real weather integration
`4bf9bd3` Decision markers on chart
`f5139b1` Year selector 2021-2025
`2b03f87` Drag-to-zoom + scroll-to-pan
(and 15+ more — see `git log`)

---

## Pre-flight before auto-watering kicks in

Run this checklist any time you're about to flip the engine on for a new season or after a long pause. The goal is to confirm the engine, the hardware, and the calibration story all agree before grass health depends on it.

### Tier 1 — Must do before tomorrow's first run

1. **Confirm all sprinkler zones are `auto_mode: true` on the server.**
   ```powershell
   ssh jamesearlpace@192.168.0.109 "grep -E '  (auto_mode|name):' ~/smart-garden-server/config.yaml"
   ```
   Expected: zones 0-6 = true, zones 7-9 = false (drip + spare).

2. **Check the watering window in [config.yaml](server-prod/config.yaml).**
   Currently `04:00-07:00`. With 7 zones × 24 min runtime = 168 min = 2:48 → fits in the 3-hour window with no margin. If a zone soaks longer than expected or one starts late, the window can run out and the next zone won't fire. Consider widening to `04:00-08:00` for safety.

3. **Verify the engine actually has a current soil balance for each zone.**
   ```powershell
   ssh jamesearlpace@192.168.0.109 "curl -s http://localhost:5125/api/dashboard | python3 -c 'import sys,json; d=json.load(sys.stdin); [print(z[\"name\"], z.get(\"balance_mm\"), z.get(\"mad_mm\")) for z in d.get(\"zones\",[])]'"
   ```
   If balance is `null` or stale, the engine won't decide correctly on day 1.

4. **Open the dashboard ([http://192.168.0.109:5125](http://192.168.0.109:5125)) and verify each zone's "Next watering" prediction is reasonable.**
   No prediction = engine doesn't know what to do. Wildly soon (today) on a recently-wet zone = stale balance. Far-future = balance might be inflated.

### Tier 2 — Should do within first week

5. **Catch-can calibration test** (15 min, ~$5 worth of tuna cans). This is the highest-leverage thing on the whole list. Steps:
   - Distribute 6-8 empty straight-sided cans randomly across a single zone
   - From dashboard, run that zone for exactly 15 minutes (Manual mode → Run)
   - Measure water depth in each can with a ruler (mm). Average them.
   - Real precip rate (in/hr) = average mm × 4 ÷ 25.4
   - Compare to `precip_rate_iph` in config. If real is much lower (likely 0.5-0.8 vs config's 1.0-1.5), **update config** and redeploy. The audit predicted this; confirm it.
   - Repeat per zone — different head models and pressure give different rates.

6. **Walk the lawn at sunset every 2-3 days for the first 2 weeks.**
   First stress signals: dull blue-green color, yellow tips, footprints staying visible (lack of turgor). If you see any: switch the affected zone to Manual, run a long soak, and lower its `precip_rate_iph` to force more frequent automatic cycles.

7. **Confirm the daily 8 AM ntfy digest is firing** (the same one that reports ESP32 health). It should also show last 24h irrigation events. If watering decisions aren't showing up there, the engine's not actually triggering anything — check `journalctl -u smart-garden-server.service -f`.

### Tier 3 — Optional / nice to have

8. **Set a conservative `precip_rate_iph` floor temporarily.** Until catch-can numbers are in, override config to multiply current rates by ~0.6 (e.g. 1.5 → 0.9, 1.3 → 0.8, 1.0 → 0.6). This makes the engine assume *less* water is being deposited, so it will water *more* often — safer error direction while uncalibrated.

9. **File two GitHub issues from the audit:**
   - "Calibrate `precip_rate_iph` per zone via catch-can test" — captures the calibration TODO and links results back to config.yaml
   - "Engine should size runtime to soil deficit, not run fixed cycle_run_min × cycle_count" — currently the only lever to change watering depth is `cycle_run_min`; engine should compute runtime as `(TAW - balance) / precip_rate_iph` clamped to `max_runtime_min`

10. **Set a manual rollback plan in your head.** If grass starts browning fast: flip all auto-mode zones to Manual on the dashboard, run each one for 30-45 min once, then troubleshoot config rather than letting another auto cycle make it worse.

### Quick rollback if something looks wrong tomorrow morning

```powershell
# Flip ALL zones to manual immediately
ssh jamesearlpace@192.168.0.109 "sed -i 's/auto_mode: true/auto_mode: false/g' ~/smart-garden-server/config.yaml && sudo systemctl restart smart-garden-server.service"
```

This stops the engine from making any further automatic decisions until you've diagnosed. Re-enable per-zone via the dashboard.



---

## 2026-06-03 — [P0 BUG] Concurrent valve open — two zones ran in parallel overnight

**Issue:** [smart-garden-server#1](https://github.com/jamesearlpace/smart-garden-server/issues/1)

**What happened:** Overnight at 04:02:04, 
un_cycle opened **valve 3 (Enclosed Backyard B)** and **valve 6 (Southwest)** within the same wall-clock second. Both ran in parallel for ~25 minutes before both closed at 04:27:03. Log + DB evidence both confirm — see the issue body.

**Why it's bad:** Line pressure splits between the two zones. Heads do not throw at design distance. The system reports "watered ~100 gal each, 25 min each" but actual lawn coverage is patchy. I noticed it visually this morning and re-ran Southwest manually to compensate.

**Root cause:** irrigation.py::run_cycle loops through installed zones and opens each new "water" decision without checking self._active. The original assumption — that the water-balance model would only return `"water"` for one zone per cycle — broke when multiple zones crossed the MAD threshold during the same overnight idle period (the normal case after a hot dry day).

**Fix plan:** Two-layer defense. (1) Defer guard in `run_cycle` — if `self._active` is non-empty, downgrade additional `"water"` decisions to `"wait"` and let the next 5-min cycle pick them up. (2) Hardware lockout in `open_valve` itself — preempts any other zone in `_active` and issues `close_all` to the ESP32 before opening the target. All open paths converge there (scheduler, manual `/api/run`, raw `/api/valve`), so two valves open at once becomes physically impossible.

**Verification before closing the issue:**
- Assertion in 
un_cycle: `assert len(self._active) <= 1`
- 7-day replay shows `_active` never exceeds 1
- Force two zones below MAD in a test config — confirm only one opens
- Dashboard `cycle_summary` gains a `zones_deferred` counter

**Status:** ✅ Both fixes deployed 2026-06-03. `irrigation.py` now 993 lines on the server. Live smoke test confirmed preemption fires correctly.

**Defense in depth — three layers, top to bottom:**

1. **Policy (`run_cycle` defer guard, 08:30 deploy)** — scheduled cycles only open the first zone, others defer to next cycle. Avoids preemption thrash on the legit case.
2. **Hardware lockout (`open_valve` preemption, 08:38 deploy)** — any caller, any path (scheduler, `/api/run` manual, `/api/valve` raw): if another zone is in `_active`, close it cleanly first via `stop_zone_watering`.
3. **Belt-and-suspenders (`close_all` before every contended open, 08:38 deploy)** — catches untracked opens (raw `/api/valve` bypassed `_active`, drift between server map and ESP32 reality, anything else).

Live verification via stubbed-ESP32 smoke test:
```
WARNING: Preemption: closing zone(s) [0] before opening zone 1
ESP32 calls in order: close valve 0  →  closeall  →  open valve 1
PASS ✓
```

Will leave [smart-garden-server#1](https://github.com/jamesearlpace/smart-garden-server/issues/1) open until tomorrow morning's 04:00 cycle confirms in production with real zones 3 + 6.

**Lesson 1 — invariant assertion missing.** The "one valve at a time" invariant was load-bearing for the entire hardware design (power budget + water pressure), but it was nowhere encoded as a check. Behavior accidentally upheld it for months, then the conditions changed and the bug was silent until the lawn told me. **Going forward: any time a design constraint is load-bearing for hardware sizing, encode it as a runtime check at the lowest layer where all callers converge. Lawn shouldn't be the regression test.**

**Lesson 2 — "one place fixes everything" was wrong.** First fix only patched the scheduler (`run_cycle`). Missed that `/api/valve` raw open calls `open_valve` directly without tracking, so a dashboard click could still cause overlap. Defense-in-depth needs to happen at the **lowest layer everyone goes through**, not the highest-level orchestrator.

**Lesson 3 — service name in instructions was wrong.** `home-server-services.instructions.md` said `smart-garden-api`. The real systemd unit is `smart-garden-server`. Corrected in memory; should update the instructions file too.

---

## 2026-06-03 — [P1 BUG] Manual valve runs not credited to soil balance; orphaned events lingering

**Issue:** [smart-garden-server#2](https://github.com/jamesearlpace/smart-garden-server/issues/2)

**How it surfaced:** After deploying #1 the user toggled zone 6 (Southwest) on/off via the dashboard and asked: *"hopefully the runtime is adjusted by what I'm telling you and by what's actually happened."* That probe found two real bugs.

**Bug A — manual toggle bypassed event tracking.** Two manual paths existed:
- `/api/run` (Run-for-N-min button) → `engine.start_zone_watering` → writes `watering_event`, tracked in `_active`, credits soil balance ✅
- `/api/valve open` (raw green/red toggle) → `engine.open_valve` direct → NO `watering_event` row, NOT in `_active`, NO credit ❌

`get_daily_irrigation_mm()` filters `WHERE end_ts IS NOT NULL` and sums `duration_sec`. No row, no credit. So toggle-based runs were invisible to the scheduler — the model would still decide to water at 04:00 even after the user just hand-ran the zone for 25 min.

**Bug B — orphaned `watering_event` rows accumulating.** Any time the service crashed or restarted mid-run, the row stayed with `end_ts = NULL` forever. Effects:
- `get_active_watering(zone)` lies — reports zone as actively watering when it isn't
- `get_daily_irrigation_mm()` filter excludes the row — irrigation that DID happen never credits the balance
- No way to spot the pattern unless you happen to query for it

Found **11 orphans** on first cleanup, going back to 2026-05-24. Including event 137 (zone 7 garden, last night, original reason `soil_dry`) and event 140 (zone 6, this morning, from the user's toggle before #1 was patched).

**Fix:**
1. `database.py::close_orphaned_watering_events()` — sweeps `end_ts IS NULL` rows on engine startup. Sets `end_ts=now, duration_sec=0, est_gallons=0`, appends `[orphaned_cleanup]` to `trigger_reason`. Under-credit intentional — better to let the model decide to water again than to lie about water applied. Logs WARNING per row so a frequent-orphan pattern is visible.
2. `irrigation.py::IrrigationEngine.__init__` — calls the helper at end of init.
3. `dashboard.py::api_valve` — open path now routes through `engine.start_zone_watering(zone_id, soil_pct, 0, "manual_toggle", allow_weather_fetch=False, ...)`, same pattern as `/api/run`.
4. `irrigation.py::start_zone_watering` — `reason != "manual"` check generalised to `not reason.startswith("manual")` so the new `"manual_toggle"` reason still overrides weather-scale=0% on rainy days.

**Deploy verification:**
- All 11 orphans cleaned on first restart, `COUNT(*) WHERE end_ts IS NULL` now = 0.
- Post-deploy cycle at 08:50:27 ran clean — Zone 3 correctly skipped with `"Already watered 25.0 min today (>=12 min threshold) — waiting for 11 PM balance update"`. The model DOES know about today's runs.

**Lesson 4 — every write path needs the same hooks.** Bug A is the same shape as the original #1 — two code paths that *seem* equivalent (open a valve), one routed through the proper tracking, the other didn't. **Whenever there are multiple ways to invoke an operation, audit every path against a checklist of side effects (event row written? in-memory state updated? balance credited? metrics emitted?). The "this is just a thin convenience wrapper" path is exactly where these bugs hide.**

**Lesson 5 — sweeper invariants need to run on startup.** Anything that depends on process liveness (in-memory tracking, open transactions, "currently doing X" state) needs a reconciliation pass on startup to recover from non-graceful shutdowns. 11 orphans accumulated over 10 days because there was no such pass. Cost of the sweeper: 5 lines of SQL.

---

## 2026-06-03 — Behavior reference: How multiple zones run when both are scheduled for the same time

This is the question that prompted issues #1 and #2 and now has a definitive answer documented here. **TL;DR: They run in series, not parallel. Worst-case the second zone starts up to one cycle-interval (5 min) after the first one ends.**

### Configuration
- `config.yaml → esp32.poll_interval_sec = 300` — the irrigation decision cycle fires every 5 min, all day, every day.
- It's NOT scheduled to fire at any specific clock time. There is no "4 AM job." The 04:00 cycle is just whichever 5-min cycle happens to land near 04:00.
- The scheduler entry: [server.py L1354-L1358](../smart-garden-server-live/server.py#L1354)
  ```python
  scheduler.add_job(api_guarded("irrigation_cycle", engine.run_cycle),
                    "interval", seconds=poll_interval,
                    id="irrigation_cycle", max_instances=1, ...)
  ```
- `max_instances=1` means APScheduler will never run two `run_cycle` jobs in parallel. If a cycle takes longer than 5 min (rare), the next one is skipped (`misfire_grace_time=60`).

### The decision loop (irrigation.py::run_cycle, ~line 747)
For each installed zone in config order:
1. Read soil + water-balance → decide `water` / `skip` / `close`.
2. If `water` AND `self._active` is non-empty → log `"deferring — zone(s) X already running"`, skip this zone, move to next.
3. If `water` AND `_active` is empty → `start_zone_watering(zid, ...)`, which writes a `watering_event` row and adds the zone to `_active`.

The zone added to `_active` stays there until `stop_zone_watering` is called (either by `safety_check` enforcing max duration, or by a future cycle deciding `close`).

### Worked example — both zones 3 and 6 cross the MAD threshold during the same overnight idle
Both have `duration_min: 25` in config (these are the typical defaults).

| Cycle time | What `run_cycle` does | `_active` after |
|---|---|---|
| 04:00:00 | Zone 3 → `water` → open. Zone 6 → `water` → DEFER (zone 3 running). | `{3}` |
| 04:05:00 | Zone 3 still running (decision: `skip` — already active). Zone 6 → DEFER. | `{3}` |
| 04:10 | same | `{3}` |
| 04:15 | same | `{3}` |
| 04:20 | same | `{3}` |
| 04:25:00 | `safety_check` (runs every 2 min) sees zone 3 hit 25-min cap → `stop_zone_watering(3)`. | `{}` |
| 04:25–04:30 | `_active` is empty. | `{}` |
| 04:30:00 | Next `run_cycle` fires. Zone 6 → `water` → open. | `{6}` |
| 04:55:00 | `safety_check` closes zone 6 at 25-min cap. | `{}` |

**End-to-end:** two 25-min zones complete in ~55 wall-clock minutes, never overlapping. The 5-min gap between zone 3 closing and zone 6 opening is the worst-case "wait for next cycle to notice" latency.

### Why this is safe (and intentional)
- **Power budget:** ESP32 + solenoid driver + SLA battery can only sink one solenoid pulse at a time without browning out. Two valves opening simultaneously was a real risk before issue #1.
- **Water pressure:** Drip + spray zones are sized for full line pressure. Splitting pressure across two zones means heads don't throw at design distance — visible as patchy coverage on the lawn (which is how the original bug surfaced).
- **Soil model:** The water-balance model evaluates each zone independently, so deferring zone 6 by 5–30 min doesn't matter. The MAD threshold doesn't move that fast.

### How manual paths differ from scheduled paths
The defer-vs-preempt distinction is intentional:

| Trigger | Path | Behavior if another zone is running |
|---|---|---|
| Scheduled `run_cycle` | `start_zone_watering` (via decide loop) | **Defers** — log `"deferring — zone(s) X already running"`, wait for next 5-min cycle |
| `/api/run` Run-for-N-min button | `start_zone_watering` direct | **Preempts** — `open_valve` lockout closes the other zone first |
| `/api/valve` ON toggle (since 2026-06-03 / issue #2) | `start_zone_watering("manual_toggle", ...)` | **Preempts** — same lockout |
| `/api/valve` OFF toggle | `stop_zone_watering` if zone in `_active`, else raw `close_valve` | Closes that zone only |

**Reasoning:** the scheduler is anonymous — there's no user waiting for the result, so politeness (defer) is the right default. Manual button clicks have a human behind them who wants the zone NOW; preempting whatever else is running is what they expect.

### Invariant enforcement
After every `run_cycle`, the loop checks `len(self._active) <= 1`. If somehow two zones ended up active (race, untracked open, future bug), logs `INVARIANT VIOLATED: N zones active`. So far never seen in production logs since the #1 fix.

### Things this does NOT do (and that's OK)
- **No "smart" reordering.** Zones are evaluated in config order. If you want zone 6 to go first, change config order. There's no priority field.
- **No parallel duration math.** The model never thinks "I can run both for 12.5 min each instead of 25 each." It always runs each zone's full configured `duration_min`.
- **No cross-cycle planning.** Each `run_cycle` is stateless — it doesn't know "I deferred zone 6 last cycle." Zone 6 just keeps coming up as a `water` decision until `_active` is empty and it actually opens.

### Source of truth for this behavior
- Defer guard: [irrigation.py L767-L777](../smart-garden-server-live/irrigation.py#L767)
- Preemption lockout (manual paths): [irrigation.py L240-L281](../smart-garden-server-live/irrigation.py#L240)
- Invariant assertion: [irrigation.py L793-L795](../smart-garden-server-live/irrigation.py#L793)
- Scheduler: [server.py L1354](../smart-garden-server-live/server.py#L1354)
- Config: `config.yaml → esp32.poll_interval_sec: 300`

---

## 2026-06-03 — Design: Soil-delta rain inference + tamper-resistant validation

**Status:** Design only. **DO NOT BUILD until soil sensors are physically installed (~1 month out).** Captured now so the requirements (especially the kid-tamper threat model) don't get lost.

### Problem statement

The irrigation engine currently relies on Open-Meteo (which uses NOAA HRRR upstream) for rain detection. HRRR has ~3 km horizontal resolution and routinely misses local drizzle and convective showers landing on the property. Nearest real weather stations are 20.7 km away (NWS SEAW1) — also too far for hyper-local rain. Probe results from 2026-06-03 confirmed: API said 0% precipitation, user observed actual drizzle on the ground.

**Hardware path forward** (decided 2026-06-03 after evaluating CWOP/PWS hardware at $450–$1045 and rejecting):
- Install 1–2 cheap capacitive soil sensors (DIY tipping-bucket tier or just the soil probes already in the kit)
- Infer rain from soil-pct rises during non-irrigation windows
- Credit inferred rain to the global water-balance for all zones

### Sensor placement decision (2026-06-03)

**For a quarter-acre property, rain is uniform — one sensor anywhere acts as a global "did it rain?" proxy.**

Recommended config: **2 sensors, ~10 ft apart, both in an auto-watered zone**. NOT both in the garden — zones 7 and 8 are `auto_mode: false` so sensors there don't drive any scheduling decision directly.

| Channel | Location | Used for |
|---|---|---|
| `soil_0` | Garden, open spot (or front yard auto zone) | Primary rain ground truth + soil balance for that zone |
| `soil_1` | ~10 ft from `soil_0`, same micro-area | Cross-check (Layer 4) + redundancy |

**Siting rules:**
- Open ground, 3+ ft from any irrigation head (else sprinkler overspray = false rain signal)
- Not under tree canopy (no rain gets through)
- Not at eaves drip line (false positives every rain)
- Away from any spot kids or hose-watering can reach during play
- Raised beds OK only if drainage matches ground soil

Adding more sensors later (per-zone) only fine-tunes per-zone decisions — not necessary for the rain problem.

### Threat model: kids pouring water on sensors

User has multiple small children who will absolutely pour water bottles on sensors "just to be silly." The system MUST be robust to this without manual intervention. **Design principle: quarantine the sensor, don't try to clean the data.** Stop trusting that sensor until it returns to baseline naturally.

### The 5-layer validation stack

Every soil reading runs through this. If a tampering signature is detected, the reading still gets logged (for diagnostics) but contributes **zero** to rain inference.

**Layer 1 — Physics rate limit.** Natural rain can't move soil pct more than ~3 pct per 5-min cycle (water has to infiltrate). Cap and reject:

| Δ over 5 min | Verdict |
|---|---|
| 0–3 pct | Normal — could be light rain |
| 3–8 pct | Suspicious — only heavy rain or hose |
| > 8 pct | Tampering — quarantine immediately |

**Layer 2 — Irrigation correlation.** If a `watering_event` row is open on this zone OR any zone within ~15 ft is currently running, the rise is expected. No tampering check, no rain signal extracted. Only fire rain inference when no irrigation is plausibly responsible.

**Layer 3 — Weather corroboration.** Pull from existing Open-Meteo cache. Rain inference is allowed only if at least one of:
- `precipitation_last_hour > 0`, OR
- `cloud_cover > 60%` AND `humidity > 80%` (drizzle the API missed)

If neither — sky is clear, sensor rose anyway → tampering candidate.

**Layer 4 — Cross-sensor corroboration.** With 2+ sensors:
- Both rise within same 5-min window, similar magnitude → real rain
- Only one rises → tampering candidate on the rising one
- One rises by 5 pct and other by 0.5 pct → tampering on the big one

**Layer 5 — Decay signature (the killer detector).** This is the most powerful layer because it's the hardest to fake. Real rain decays slowly (hours) because moisture is field-wide. Spilled water on a sensor in dry soil decays fast (10–30 min) because there's no surrounding moisture field — the water just drains away from a single wet patch.

After a rise event, watch for:
- Soil pct drops by > 5 pct within 30 min → **confirmed tampering**, retroactively void the credit, quarantine sensor for 6 hours
- Soil pct stays elevated for 2+ hours → confirmed natural moisture, credit promotes from `pending` to `confirmed`

### Retroactive correction via `rain_credits` table

This is critical: a credit issued at 10:00 AM might turn out to be tampering at 10:25 AM. The scheduler runs at 04:00 AM — by then the truth has to be in. Schema:

```sql
CREATE TABLE rain_credits (
    id INTEGER PRIMARY KEY,
    ts INTEGER NOT NULL,           -- when the rise was detected
    sensor_id INTEGER NOT NULL,
    mm REAL NOT NULL,              -- inferred rain in mm
    status TEXT NOT NULL,          -- 'pending' | 'confirmed' | 'voided'
    void_reason TEXT,              -- e.g. 'decay_signature', 'cross_sensor_mismatch'
    decided_at INTEGER             -- when status was finalized
);
```

`get_daily_rain_inferred_mm()` only sums `status = 'confirmed'` rows. Pending credits don't influence irrigation decisions. A safety check before each scheduled `run_cycle` re-evaluates any `pending` credits older than 2 hours and promotes/voids them.

### Quarantine state machine

```
HEALTHY → (tampering detected) → QUARANTINED (6 hours)
QUARANTINED → (reading stable within ±1 pct of baseline for 1 hour) → HEALTHY
QUARANTINED → (still elevated after 6 hours) → STUCK (alert + email)
```

While quarantined, the sensor:
- Still gets logged
- Contributes **0** to rain inference
- Doesn't trigger irrigation skips for the garden zone it's assigned to (zone reverts to model-only mode)
- Shows ⚠️ icon in dashboard so user can see "kid got the sensor again"

### Tampering tolerance — what realistically gets through

| Attack | Caught by |
|---|---|
| Pour 1 cup on one sensor | Layer 1 (rate) + Layer 4 (single sensor) + Layer 5 (decay) |
| Pour 1 cup on both sensors | Layer 3 (clear sky) + Layer 5 (decay) |
| Pour slowly over 10 min on both | Layer 3 (clear sky) + Layer 5 (decay) |
| Pour 1 cup on both on a cloudy day | Layer 5 (decay) |
| Pour 5 gal on both during actual rain when zones are off | Undetectable but harmless (rain was going to skip irrigation anyway) |

**Layer 5 is the safety net.** Even if a kid beats every other layer, the decay signature catches it ~30 min later, the credit gets voided, and the 04:00 scheduler sees truth.

### Fail-safe behavior

When in doubt, the system should water (skip the rain credit). Worst case of false-rejecting real rain = irrigates one extra time = wastes ~50 gal of water. Worst case of false-accepting tampering = skips one watering cycle = potentially stresses plants on a hot day. Better to over-water than to under-water.

### Implementation order (when sensors are installed)

1. **Layers 1, 2, 3** in first pass — cheap, work with 1 sensor, ~1 hour code:
   - `database.py::get_daily_rain_inferred_mm()` reading from `rain_credits` table
   - `database.py::record_soil_reading()` writes to existing soil table, then evaluates rate cap + irrigation correlation + weather corroboration before inserting `pending` row in `rain_credits`
   - Modify `irrigation.py::run_cycle` water-balance to add `get_daily_rain_inferred_mm()` to today's precipitation

2. **Layer 4** after second sensor is online — ~30 min:
   - Cross-sensor check inside `record_soil_reading` — require ≥2 sensors rising before crediting

3. **Layer 5 + retroactive voiding** after 2 weeks of baseline data — ~2 hours:
   - Need real soil-response curves from this specific soil to tune decay thresholds
   - Background job (every 15 min) re-evaluates `pending` credits, promotes/voids based on decay signature
   - Quarantine state machine + dashboard ⚠️ indicator

4. **Audit dashboard tile** — show last 7 days of credits with status, void reasons. Lets user see if a kid is actively messing with the system.

**Total work:** ~4 hours once sensors are physically installed. Defer all of it until then.

### Why this design

- **Quarantine, don't clean** — never try to "correct" a tampered reading; just stop trusting that sensor. Cleaning is fragile, quarantine is safe.
- **Pending → confirmed flow** — gives the system 2 hours to discover tampering before any irrigation decision uses the credit
- **Fail-open to model** — if all sensors are quarantined, the zone reverts to the ET₀ water-balance model it's used for the last year. Nothing breaks, nothing dies.
- **No manual override required** — per user requirement, the system handles tampering autonomously
- **Capped damage** — even an undetected attack costs at most one skipped watering, which is recoverable the next day

### Cross-references
- Rain detection investigation that led here: this same session (2026-06-03), probe results in `C:\Users\james\AppData\Local\Temp\rain-source-probe.py`
- Sensor config: `config.yaml → soil_0..soil_3` (all currently `false`)
- Hardware: capacitive soil probes already in the kit (no purchase needed)
- Related: `weather.py::get_current()` provides the cloud_cover + humidity for Layer 3 (no changes needed there)

---

## 2026-06-04 — Batch G: scheduling-cockpit (moisture_sim.html) audit & engine-parity fixes

**Context:** Post-ship audit of the "batch G" cockpit work under the standing "no more issues" mandate. Started as UX polish, became a deep parity audit between the **client-side schedule predictor** in `moisture_sim.html` and the real **`irrigation.py` engine**. The predictor runs entirely in the browser and does NOT know engine state — any constant it hardcodes that diverges from the engine makes the UI silently lie.

**Changes (all deployed to 192.168.0.109:5125 + pushed to `jamesearlpace/smart-garden`):**

| Tag | What | Commit | Issue |
|-----|------|--------|-------|
| G7 | Mobile sticky first column on `.az-table` (zone name stays visible while scrolling the all-zones table horizontally) | `f8291e5` | — |
| G8 | `predictZoneSchedule()` hardcoded `et0 * 0.90` Kc → now `getSeasonalKc(brain, nightMonth)` per forecast night. The 0.90 was only correct for sprinkler zones in June; wrong for Garden/Grapes drip year-round and all zones in peak summer. | `4e95b1b` | #27 |
| G9 | Three MORE hardcoded-0.90 spots found by grep: two additional next-watering projections + two display strings ("Kc 0.90 (active)" card, tune-panel hint). All now use real per-zone/season Kc. | `373ff75` | #27 |
| G10 | Single-zone "Next Expected Watering" banner showed a fake date for **manual-mode** zones (Garden, `auto_mode=false`). The banner has TWO implementations — `updateNextWateringBanner()` (has the guard, but is effectively dead) and an INLINE copy in the `Promise.all().then` (live, but dropped the guard when bug #23 inlined it). Added the manual/not-installed guard to the inline copy. | `7026138` | #28 |

**Verified live (Playwright):** Garden (manual) → "✋ Manual mode"; Front Yard A (auto) → predicted date. Garden summary card shows Kc 0.60 (drip early-summer), zero leftover `0.90` patterns, `getSeasonalKc` called in 8 places.

**Dormant-season parity (checked, no bug):** engine skips all irrigation when `season_idx < 0` (Nov-Feb, irrigation.py:453), so `zone["kc"][-1]` (Python negative-index wrap) is never reached. Predictor's `getSeasonalKc` returns `0` for dormant → both produce "no watering." Match.

**Lessons (→ memory `/memories/repo/smart-garden-mirror-layout.md`):**
- **A client-side predictor must mirror engine constants (Kc per zone/season) or the UI lies.** Three duplicated copies of the next-watering projection ALL shared the same Kc bug; two also had the manual-guard bug. Duplicated logic drifts.
- **A throw early in a `.then()` callback silently aborts all later UI updates** via `.catch`. The inline banner runs after `buildChart()`; if Chart.js (CDN) fails to load, `buildChart` throws and the banner stays blank. Pre-existing fragility, left as-is (Chart.js failing breaks the whole page anyway).
- **Playwright testing trap:** don't hammer `?nc=Date.now()` cache-buster reloads — they race the Chart.js CDN load and produce transient `Chart is not defined`, which looks like a real bug but isn't. Reload once cleanly and check `typeof Chart === 'function'`.

**Still open (flagged, awaiting James's horticulture call):** static tune-hint text (`moisture_sim.html` ~line 498) reads `"Turf=0.90, Garden=0.8-1.1, Grapes=0.4-0.7"` — Garden/Grapes ranges are SWAPPED vs actual config (Garden drip 0.5-0.7, Grapes drip 0.7-1.15). Cosmetic hint only; left for James to confirm the intended ranges.

### G11-G15 (2026-06-04 cont.) — "just make the website good" cockpit polish

Continued the audit. Five more real issues found and fixed (all deployed + pushed + issue-tracked):

| Tag | What | Commit | Issue |
|-----|------|--------|-------|
| G11 | Kc tune-hint text was wrong AND Garden/Grapes swapped → corrected to `Turf=0.85-0.95, Garden=0.5-0.7, Grapes=0.7-1.15` (matches config). Resolves the G10 open item above. | `6dd0052` | #30 |
| G12 | All-zones status table flagged manual/drip zones (Garden, Grapes) with alarming red "⚠ Below MAD" even though the engine never auto-waters them, and counted them in the "N zones below MAD now" total. Now neutral "Manual (drip)"/"Manual"/"Not installed" (new `.az-status-manual` class), excluded from the red count. Summary went from "3 zones below MAD" → "1 zone" (just the real auto zone). | `6dd0052` | #30 |
| G13 | Per-zone "📅 Watering" card's "Est. next" row was PERMANENTLY blank — `nextEst` was initialized to '—' and never computed. Removed the dead field (+ unused var); the top banner is the authoritative next-watering display. | `61df94f` | #30 |
| G14 | Next-watering banner intermittently blanked ("—") with a blank chart. Chart.js loads via `<script defer>` CDN; the inline script isn't deferred, so its `fetch().then()` could beat Chart.js → `buildChart` threw `Chart is not defined` → aborted the `.then` → banner never updated. Fix: buildChart retries instead of throwing + call site try/catch-wrapped. | `35d3914` | #29 |
| G15 | All-zones "Last run" column showed wrong times (Front Yard A "10.8d ago" when it watered 1h ago). `fmtLastWatered` took `waterings[length-1]` assuming sorted order, but `/api/moisture-data` returns waterings UNSORTED. Fixed to reduce-by-max-`start_ts`. | `b7a916b` | #29 |

**Verified live (Playwright):** all-zones "Last run" now matches single-zone "Last watered" for every zone; 5+4 rapid cache-busted reloads of Garden/Front Yard A all render banner+chart (previously flaky); manual zones show neutral status; Kc values correct (0.90 sprinkler / 0.60 drip).

**Data ordering facts (verified):** `/api/moisture-data` → `balances` is date-ASC sorted (safe to index `[length-1]`), but `waterings` is NOT sorted (always reduce by `start_ts`). Client `ZONES` global includes real `est_gpm` per zone, so gallon math is accurate.

**Lessons:** (1) A throw early in a `.then()` callback silently aborts every later UI update in that chain — wrap risky calls (like chart rendering) so they can't take down unrelated UI. (2) Never assume API array ordering — sort/reduce explicitly. (3) The "manual zone shouldn't look like it needs water" theme recurred across the banner (G10), status badge (G12), and was the root reason the hint/fields were misleading.

### G16-G17 (2026-06-04 cont.) — second polish pass

| Tag | What | Commit |
|-----|------|--------|
| G16 | Sub-minute watering runs (manual tests, drip pulses — e.g. a 13s valve test) rendered as "0 min (0.00\")" in the Watering History list and chart tooltip, looking like no-ops. Now show "<N> sec" for <60s and "<0.01\"" for tiny depths. | `c56931b` |
| G17 | Header moisture-% badge showed a meaningless "—%" in all-zones mode (it's per-zone only). Now hidden in all-zones mode, restored in single-zone. | `c934e4d` |

**Verified:** Garden history now reads "3 sec (<0.01\")" etc.; header badge hidden on all-zones / shows "44.9%" on single zone. Final health check: **0 console errors/warnings** across zones 0, 7, 8, all (Chart.js race fix holding). Cycle stats already correctly exclude sub-minute runs (`duration_sec <= 60` filter in computeStats), so the stat cards reflect real waterings. Mobile (390px) clean — no overflow, sticky column works.

**Net batch G total: G7-G17, 11 fixes, issues #27-#30 closed.** Cockpit logic + display now audited end-to-end.

### G18-G23 (2026-06-04 cont.) — whole-site fresh-eyes audit (Home, History, Settings, Map, Forecast)

Audited every page beyond the Schedule cockpit. Site structure: `/` index.html (Home + Zones + History + Settings + Cam as SPA panels), `/map`, `/forecast` (+ Forecast-vs-Actual sub-tab), `/moisture-sim`, `/login`.

| Tag | Page | What | Commit | Issue |
|-----|------|------|--------|-------|
| G18 | Home + History | Sub-minute runs showed "0.0 min" in Recent Activity feed (server `recent[].detail` in dashboard.py) + History detail tables → now "<N> sec". Added `fmtDur()` helper. | `ace5f99` | #33 |
| G19 | **Settings** | **HIGH: Settings never loaded config — every field blank.** Composite "settings" panel absorbed old `p-config`, but the loader only fired for `id==='config'` (dead id). Blank form + Save's `||0` fallback = silent wipe of all skip rules (rain/wind/freeze protection). Fix: fire loadConfig+loadTelemetry on `id==='settings'`. | `fb4f2f7` | #31 |
| G20 | Settings | Defensive guard: `cfgSave()` refuses to save if config not loaded, so a blank form can never zero out safety rules. | `427fed3` | #31 |
| G21 | Map + nav | map.html nav linked to `/history` `/sensors` (404 — not routes). index.html ignored `location.hash`, so Forecast page's `/#history` etc. didn't open the right panel. Fixed both. | `74ef7a7` | #32 |
| G22 | Forecast | Humidity always "?" (`w.humidity_pct`→`w.humidity`); Rain always "0mm" (`w.rain_forecast_mm`→`w.precip_mm`, so real rain never showed); manual zones predicted "Today" (API now returns auto_mode, template shows "Manual"). | `756cbbe` | #33 |
| G23 | Forecast-vs-Actual | Manual zones stored "Water today" in daily snapshot (polluted accuracy) → now `predicted_skip=manual_mode` in irrigation.py `save_daily_forecast_snapshot` (future snapshots only). "Watered 0 min" → "<N> sec". | `2437996` | #33 |

**Biggest catch: G19** — the Settings page was a latent data-loss bug. Saving from the (always-blank) form would have written 0 to every skip rule, disabling rain/wind/freeze skip protection on a live irrigation system.

**Verified:** all pages load with 0 console errors; Settings populates real config; hash deep-links open correct panels; Forecast shows Humidity 74% / real rain / Manual zones; engine health OK after irrigation.py change. Login page clean. Cam panel shows "Waiting for first image" — the water-meter-cam is a separate service (offline), not a bug in this site.

**Recurring theme across the whole site:** "a manual-mode zone must never look like the engine will auto-water it" — fixed on the banner (G10), all-zones status (G12), Forecast tab (G22), and Forecast-vs-Actual snapshot (G23).

**Net whole-site audit: G7-G23, 17 fixes, issues #27-#33 closed.**





