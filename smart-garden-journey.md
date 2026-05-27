# Smart Garden — Journey Doc

**Status:** 🔴 **ESP32 in WiFi lockout — RCA done, fix committed, needs flash.** Three bugs found: low TX on reconnect, crash counter not clearing on loop() recovery, no TX bump during setup connect. Fix in commit `27f087f` + voltage ratio fix — both pending USB flash at junction box.
**Last Updated:** 2026-05-27
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
| MCU | ESP32-WROOM-32U | External antenna, MAC `68:FE:71:0C:BA:98`, static IP 192.168.0.150 |
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

### WiFi lockout RCA (commit `27f087f`, pending flash)

**Symptom:** ESP32 has power (LEDs on) but never connects to WiFi from deployed location. Worked fine indoors during flash.

**Root cause — three compounding bugs:**

1. **Low TX power on reconnect (8.5 dBm instead of 19.5 dBm).** `setupWiFi()` boots at `WIFI_BOOT_TX_DBM` (8.5 dBm) to prevent brownout. If WiFi fails to connect in setup, TX is never bumped to full. The loop() watchdog then retries at 8.5 dBm — **12× weaker than full power.** From the junction box at the edge of WiFi range, 8.5 dBm can't reach the AP.

2. **Crash counter never resets on loop() WiFi recovery.** `crashCount` resets to 0 ONLY if WiFi connects during `setup()` (line 813). If WiFi later connects via the loop() watchdog, the crash counter stays high. So even successful recovery doesn't prevent the crash counter from climbing to the deep sleep threshold on the next reboot.

3. **No TX power escalation during setup connect.** `setupWiFi()` tries 40 attempts (20s) all at 8.5 dBm. If the AP is reachable at full power but not at boot power, all 40 attempts fail.

**The lockout spiral:**
```
Boot → low TX (8.5 dBm) → WiFi fails 40 attempts → AP mode
  → loop() watchdog retries at 8.5 dBm × 30 (5 min) → ESP.restart()
  → crashCount++ → repeat 20 times → deep sleep 10 min
  → wake → cap crashCount to 20 → repeat cycle forever
```

**Fixes applied (commit `27f087f`):**

1. **`WiFi.setTxPower(WIFI_TX_DBM)` in loop() reconnect** — reconnect attempts use full 19.5 dBm, not boot 8.5 dBm. Brownout risk is negligible after initial boot.

2. **Crash counter reset on loop() WiFi recovery** — when `wifiFailCount` transitions from >0 to 0 (WiFi reconnected), clear `crashCnt` in NVS and reset `safeMode`. Prevents deep sleep lockout spiral.

3. **Mid-connect TX bump in setupWiFi()** — at attempt 20 (10s into connect), bump TX from boot to full. Gives the brownout-safe window, then escalates power for weak-signal locations.

**Also pending flash:** voltage ratio fix (6.283f) from earlier commit.

**To deploy:** Take laptop to junction box, plug USB, flash + verify:
```
cd C:\MyCode\smart-garden
~\.platformio\penv\Scripts\pio.exe run -e esp32 --target upload --upload-port COM5
~\.platformio\penv\Scripts\pio.exe device monitor --baud 115200 --port COM5
```

### Battery voltage calibration (applied)

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

**Next steps when ESP32 comes back online:**
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
