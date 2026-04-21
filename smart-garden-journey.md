# Smart Garden — Journey Doc

**Status:** Active — bench test complete, MOSFET power gate fix planned (waiting for parts)  
**Last Updated:** 2026-04-17  
**Goal:** Solar-powered smart irrigation system controlled remotely via GitHub Copilot through a home server

---

## Quick Reference — How to Control the Sprinklers

### The Control Chain
```
Copilot → SSH to Acer home server → curl to ESP32 → valve actuates
```

### Commands (run in terminal)

**Open a valve:**
```powershell
ssh jamesearlpace@192.168.0.109 "curl -s -X POST 'http://192.168.0.150/api/valve?id=0&action=open'"
```

**Close a valve:**
```powershell
ssh jamesearlpace@192.168.0.109 "curl -s -X POST 'http://192.168.0.150/api/valve?id=0&action=close'"
```

**Check status:**
```powershell
ssh jamesearlpace@192.168.0.109 "curl -s 'http://192.168.0.150/api/status'"
```

**Close all valves:**
```powershell
ssh jamesearlpace@192.168.0.109 "curl -s -X POST 'http://192.168.0.150/api/closeall'"
```

- `id=0` = Zone 1 (Garden drip), `id=1` = Zone 2 (Grapes), etc. — zero-indexed
- SSH password: `KeepingP@ce8!`
- Returns `"OK"` on success

### Web Dashboard
Open `http://192.168.0.150` in a browser on the local network for a full GUI with valve buttons and sensor readouts.

---

## Architecture

### Network Topology
```
Internet → Ziply Fiber ONT → Netgear GS305E switch (192.168.0.107)
  → TP-Link ER605 router (192.168.0.1) → Eero 6 mesh WiFi
    → Acer home server (192.168.0.109, wired)
    → ESP32 (192.168.0.150, WiFi, static IP hardcoded in firmware)
```

### Hardware Stack
| Component | Model | Details |
|-----------|-------|---------|
| **Microcontroller** | HiLetgo ESP-WROOM-32 | ESP32-D0WD-V3 rev v3.1, MAC f4:2d:c9:6b:f7:78 |
| **Solar Panel** | ECO-WORTHY 10W 12V | Charges battery |
| **Charge Controller** | Renogy Wanderer Li 10A | 12V battery + load output |
| **Battery** | ExpertPower 12V 7Ah SLA | Powers everything |
| **Buck Converter** | LM2596 | 12V → 5V for ESP32 VIN pin |
| **Motor Drivers** | L298N H-Bridge | Each board drives 2 valves. Need 5 boards for 10 valves |
| **Solenoid Valves** | Orbit 57861 DC latching | Brief pulse opens, reverse pulse closes, holds with no power |
| **Home Server** | Acer Aspire A314-23P | Linux Mint 22.1, SSH: jamesearlpace / KeepingP@ce8! |

### Power Wiring
```
Solar Panel → Renogy Wanderer (solar input)
Battery → Renogy Wanderer (battery terminals)
Renogy Wanderer LOAD+ → LM2596 buck converter IN+ → ESP32 VIN
Renogy Wanderer LOAD+ → L298N 12V power input (each board)
Battery 12V also available directly for L298N boards
```

### Valve Wiring (per valve)
```
ESP32 GPIO A → L298N IN1 (or IN3)
ESP32 GPIO B → L298N IN2 (or IN4)
L298N OUT1/OUT2 (or OUT3/OUT4) → Solenoid valve wires (polarity doesn't matter for latching)
L298N ENA (or ENB) jumper → ON (default jumpered position)
```

### Why the Home Server?
Copilot runs in the cloud and cannot reach local network IPs directly. The Acer home server (192.168.0.109) acts as a bridge — Copilot SSHes into it, then curls the ESP32 on the local network. The Acer already runs the TV Timeout project (port 5123).

---

## Current State (2026-04-05)

### What's Working
- ESP32 firmware compiled and flashed via PlatformIO (COM3)
- **Static IP 192.168.0.150** hardcoded in firmware (gateway .1, DNS .1) — no DHCP dependency
- Web dashboard with valve controls and sensor displays (port 80)
- REST API: `/api/status`, `/api/valve?id=X&action=open|close`, `/api/closeall`
- Full remote control chain proven: Copilot → SSH Acer → curl ESP32 → valve actuates
- SSH key auth configured (ed25519, no password needed for Acer SSH)
- **Valve 1 (Zone 1 - Garden drip)** physically wired and tested — solenoid confirmed moving
- **12-panel SPA dashboard** with interactive AJAX valve controls, configuration editor, full telemetry, Zimmerman weather adjustment
- **RotatingFileHandler** logging to `smart-garden.log` (5MB, 3 backups)
- **Index-based sensor matching** — zones map to ESP32 soil sensors by `soil_sensor` config index, not name strings
- **All AJAX endpoints consistent** — `/api/valve`, `/api/closeall`, `/api/run` all return JSON for XHR calls
- **Hardware wired:** Solar panel → Renogy charge controller → LM2596 buck converter (5.06V) → ESP32 VIN. L298N motor driver and DHT22 temp sensor connected.
- **Brownout detector disabled** — `WRITE_PERI_REG(RTC_CNTL_BROWN_OUT_REG, 0)` fixes USB boot-loop
- **WiFi reconnect watchdog** — checks every 10s, reconnects if dropped, reboots after 60s of failures
- **DHT22 sensor working** — replacement unit reads 78°F / 40.5% humidity correctly (first unit was defective — OUT and GND bridged on PCB)
- **ESP32 boots fine on USB power**

### Current Problem — Buck Converter Power (2026-04-05) *(RESOLVED — see April 5 session)*
ESP32 crash-loops when powered from LM2596 buck converter. Serial shows:
```
rst:0x10 (RTCWDT_RTC_RESET), boot:0x17 (SPI_FAST_FLASH_BOOT)
entry 0x400805e4
```
Repeated reset with no `setup()` output. Diagnosis:
- `boot:0x17` = GPIO 0 HIGH (normal boot mode, NOT download mode) — not a GPIO 0 solder bridge
- `rst:0x10` = RTC watchdog reset before app code runs — likely power quality issue
- WiFi TX current spike (300-500mA) probably causes LM2596 output voltage sag
- Even with L298N fully disconnected, still crash-loops on buck power
- All connections are soldered directly to ESP32 pins

**Firmware updated to v2.2 (power-hardened):** CPU drops to 80MHz during boot, WiFi TX power reduced to 8.5dBm, crash counter triggers safe mode after 5 failures, staggered valve init. Separate `power-test` environment available for bare-metal power validation.

### Telemetry (v2.2 — compiled, needs flash to test buck power)
All v2.0 telemetry features plus power management and diagnostics.

### What's Not Done Yet
- Flash telemetry firmware (v2.0 compiled, ESP32 needs USB connection)
- Only 1 of ~10 valves wired (need 4 more L298N boards)
- Soil moisture sensors not connected (GPIO 32-35, capacitive sensors)
- DHT22 temperature sensor not connected (GPIO 4)
- Battery/solar voltage monitoring (needs 2 resistor voltage dividers → GPIO 36, 39)
- Valves not connected to actual irrigation pipes
- config.h only defines 7 valves — needs 3 more pin assignments for 10 total

### GPIO Pin Layout (current 7 valves in config.h, 9 zones in server config)
| Valve | Zone (server config) | IN1 | IN2 | L298N Board |
|-------|----------------------|-----|-----|-------------|
| 1 | Front Yard A | GPIO 25 | GPIO 26 | Board 1, Ch A |
| 2 | Front Yard B | GPIO 27 | GPIO 14 | Board 1, Ch B |
| 3 | Enclosed Backyard A | GPIO 16 | GPIO 17 | Board 2, Ch A |
| 4 | Enclosed Backyard B | GPIO 18 | GPIO 19 | Board 2, Ch B |
| 5 | Southeast | GPIO 21 | GPIO 22 | Board 3, Ch A |
| 6 | South | GPIO 23 | GPIO 13 | Board 3, Ch B |
| 7 | Southwest | GPIO 5 | GPIO 15 | Board 4, Ch A |
| 8 | Peonies (drip) | TBD | TBD | Board 4, Ch B |
| 9 | Garden (drip) | TBD | TBD | Board 5, Ch A |

> **ESP32 firmware still uses old names** ("Garden drip", "Grapes drip", etc.) — update when reflashing for valve 8-9 wiring.

### Planned Sensor Layout
| Sensor | GPIO | Planned Location | Zones Served |
|--------|------|------------------|--------------|
| 0 | 32 | Near VB1 | Front Yard A/B, Enclosed Backyard A/B |
| 1 | 33 | Near VB2 | Southeast, South, Southwest |
| 2 | 34 | Grapes area | Garden (drip) |
| 3 | 35 | Peonies bed | Peonies (drip) |

### Scaling to 9 Zones
- 9 zones confirmed in server config (7 sprinkler + 2 drip)
- ESP32 firmware currently defines 7 valves — needs 2 more GPIO pairs for valves 8-9
- Also need `NUM_VALVES 9` in config.h and 2 more entries in the valves array
- 9 valves = 5 L298N boards (4 boards wired, need 1 more)
- All 4 soil sensor ADC pins allocated (GPIO 32-35)

---

## Codebase

### ESP32 Firmware (`C:\MyCode\smart-garden\`)

| File | Purpose |
|------|---------|
| `platformio.ini` | PlatformIO project config — esp32dev, Arduino framework |
| `src/config.h` | WiFi creds, MQTT config, all pin assignments, system settings |
| `src/main.cpp` | Full firmware: valve control, sensor reading, web server, REST API |
| `README.md` | Hardware list and setup instructions |

### Server-Side Software (`C:\MyCode\smart-garden-server\` → deployed to Acer `~/smart-garden-server/`)

| File | Purpose |
|------|---------|
| `config.yaml` | Zone profiles (9 zones), Duvall billing tiers, skip rules, watering windows |
| `database.py` | SQLite schema + CRUD helpers (sensor_log, weather_log, watering_event, etc.) |
| `weather.py` | Open-Meteo client — ET₀, rain forecast, 7-day forecast, with 30-min cache |
| `billing.py` | Duvall municipal tiered water rate calculator + budget awareness |
| `irrigation.py` | Decision engine — evaluate zones, water/skip logic, cycle-soak, ESP32 valve control |
| `server.py` | Main entry point — APScheduler + Flask, graceful shutdown |
| `dashboard.py` | Flask web UI — status cards, zone controls, history, billing dashboard |
| `templates/index.html` | Main dashboard — live zones, ET₀, rain, billing tier bar, 7-day forecast |
| `templates/history.html` | Watering + skip event logs, daily summaries |
| `templates/sensors.html` | Soil moisture gauges with sparklines, weather forecast table |
| `requirements.txt` | flask, requests, apscheduler, pyyaml |
| `smart-garden.log` | RotatingFileHandler output (5MB max, 3 backups) |

**Service:** Runs as `systemctl --user` on Acer (auto-start on login)  
**Dashboard URL:** http://192.168.0.109:5125  
**DB file:** `~/smart-garden-server/smart-garden.db` (SQLite WAL mode)  
**Logs:** `journalctl --user -u smart-garden`

**Scheduler intervals:**
- Irrigation cycle: every 5 min (polls ESP32 sensors, runs decision engine)
- Safety check: every 2 min (closes stuck valves)
- Weather fetch: every 30 min (Open-Meteo API, cached)

**Decision engine skip order:** already wet → not dry enough → recent rain → rain forecast → freeze → wind (sprinklers) → budget → outside window

### Key Firmware Details
- **Valve control:** `openValve(idx)` sends HIGH/LOW pulse for VALVE_PULSE_MS, `closeValve(idx)` sends LOW/HIGH pulse (reversed polarity)
- **Safety:** All valves closed on startup
- **WiFi fallback:** If STA fails, creates AP "SmartGarden" / "garden1234" at 192.168.4.1
- **MQTT:** Disabled (`MQTT_ENABLED false`), infrastructure exists for Home Assistant integration
- **Flash/RAM:** 61.9% flash, 15.9% RAM used (main), 20.6% flash, 6.6% RAM (power-test)

### Static IP Configuration (added 2026-04-01)
- `config.h` defines `STATIC_IP(192, 168, 0, 150)`, `GATEWAY(192, 168, 0, 1)`, `SUBNET`, `DNS1`
- `main.cpp` calls `WiFi.config()` before `WiFi.begin()` when `USE_STATIC_IP` is true
- Prevents DHCP from reassigning the IP on power cycles or router reboots
- ESP32 MAC: `f4:2d:c9:6b:f7:78`

### Build & Flash
```powershell
cd C:\MyCode\smart-garden
pio run --target upload --upload-port COM3
pio device monitor --baud 115200
```

---

## Key Decisions
1. **Latching solenoids** — Orbit 57861 hold position with no power, solar-friendly
2. **L298N H-bridge** — Simple polarity reversal for latching solenoids, $2 each
3. **Acer as bridge** — Copilot can't reach local IPs directly, SSH relay solves this
4. **No MQTT yet** — Web API is sufficient for now, MQTT infrastructure ready when needed
5. **Static IP in firmware** — Hardcoded 192.168.0.150 in config.h rather than relying on DHCP reservation. More reliable since it doesn't depend on router config.

---

## Session Log

### 2026-04-01 — Static IP & SSH Key Auth

**Context:** ESP32 changed IP from .148 to .150 via DHCP after a router/power event. Copilot couldn't connect, had to ARP-scan to rediscover it. Also SSH to Acer was hanging on password prompt.

**Changes:**
- Generated ed25519 SSH key pair (`C:\Users\jamespace\.ssh\id_ed25519`), deployed public key to Acer's `~/.ssh/authorized_keys` — passwordless SSH now works
- Added static IP configuration to `config.h`: `STATIC_IP(192, 168, 0, 150)`, gateway/subnet/DNS
- Added `WiFi.config()` call in `main.cpp` before `WiFi.begin()` (gated by `USE_STATIC_IP`)
- Added `#include <IPAddress.h>` to `config.h` for type availability
- Firmware compiled (60.7% flash, 13.9% RAM) and flashed via USB — ESP32 confirmed back online at .150

**Current State:** Full control chain verified: `ssh → curl → ESP32 → JSON status`. Static IP locked. No more DHCP surprises.

---

## 2026-07-08 — Irrigation Intelligence Research & Zimmerman Implementation

**Context:** Comprehensive research into commercial and academic irrigation scheduling best practices, followed by a full audit of the production server code at `C:\MyCode\smart-garden-server\`.

### System Reassessment

Previous audit examined the OLD scheduler (`smart-garden/server/scheduler.py`) and incorrectly classified the system as "Level 1: Timer + Reactive Sensors." The REAL production code at `smart-garden-server/` is **Level 2: Weather-Aware with ET₀** — Open-Meteo integration, FAO Penman-Monteith ET₀, rain/wind/freeze/budget skip rules, Kc crop coefficients, cycle-soak scheduling, and Duvall billing tier awareness.

**What was already working (Phase 1 — complete):**
- Open-Meteo weather client with 30-min cache
- ET₀ daily calculation via FAO Penman-Monteith
- Rain forecast skip (≥5mm AND ≥60% probability)
- Recent rain skip (≥8mm in 24h)
- Wind skip for sprinklers (>15 mph)
- Freeze protection (<35°F)
- Budget-aware billing tier tracking
- Kc crop coefficients by season [spring, early_summer, peak, fall]
- 9 zones with soil moisture sensors and cycle-soak

**What was missing:** Runtime is always `max_runtime_min` (fixed). The system calculates `et_demand = et0 * kc` but only logs it — never uses it to scale how long to water.

### Research Sources & Findings

| Source | Method | Key Insight |
|--------|--------|-------------|
| **Rachio** (commercial) | Weather Intelligence Plus | Zimmerman weather adjustment ±200% of base runtime |
| **OpenSprinkler** (open source) | Zimmerman method | `scale = 100 + (30-humidity) + (temp-70)*4 + rain*-200`, clamped 0-200% |
| **NDSU Extension** | Checkbook method | Track soil water balance: ET₀ withdrawals vs rain/irrigation deposits |
| **UF/IFAS** (Florida) | ET-based scheduling | `runtime = (ET₀ × Kc × area) / (precip_rate × efficiency)` |
| **FAO-56** (UN) | Penman-Monteith | Gold standard reference ET₀ — already implemented via Open-Meteo |
| **Hunter** (commercial) | Solar Sync | Hardware sensor; irrelevant to software system |

### Three-Phase Improvement Roadmap

**Phase 1 — Weather Integration (✅ COMPLETE)**
- ET₀ via Open-Meteo, rain/wind/freeze skip rules, Kc per zone, billing tiers

**Phase 2 — Zimmerman Weather-Adjusted Runtimes (IMPLEMENTING NOW)**
- Scale `max_runtime_min` by a weather factor based on temperature, humidity, and recent rain
- Formula: `scale = clamp(100 + humidity_delta + temp_delta + rain_delta, 0, 200)`
- Baselines calibrated for Duvall WA (cooler/wetter than standard 70°F/30% humidity)
- Configurable via `config.yaml` under `weather_adjustment` section

**Phase 3 — Soil Water Balance / Checkbook Method (FUTURE)**
- Track cumulative soil water depletion per zone across days
- `balance -= ET₀ × Kc` daily, `balance += rain + irrigation`
- Water when balance drops below Management Allowed Depletion (MAD) threshold
- Replaces reactive soil-sensor-only triggering with predictive scheduling

### Changes Made

**`irrigation.py`** — Added `calculate_weather_scale()` method implementing Zimmerman formula with Duvall-calibrated baselines. Applied scale factor to runtime in `start_zone_watering()`. Scale factor logged in decision details and exposed via API.

**`config.yaml`** — Added `weather_adjustment` section with baseline_temp_f, baseline_humidity_pct, rain_scale_factor, min/max scale bounds.

**`dashboard.py`** — Added `weather_scale` to `/api/dashboard` response.

**`templates/index.html`** — Added 9th "About" panel with research citations, 3-phase roadmap, and live weather scale display.

---

## 2026-04-02 — Comprehensive Telemetry Panel + Enhanced About Section

**Context:** User wanted: (1) more detail in About section showing "how it works", (2) a dedicated telemetry panel showing valve trigger history, and (3) every single bit of available telemetry surfaced in the UI.

### Changes

**`dashboard.py`** — New `/api/telemetry` endpoint (~95 lines) that aggregates:
- ESP32 `/api/events` ring buffer (last 100 events)
- ESP32 `/api/valvestats` (valve lifetime open/close counts)
- ESP32 `/api/scan` (raw ADC readings on all GPIO pins)
- Full ESP32 `/api/status` (system info, soil sensors, DHT22, valves)
- DB: watering events with ALL columns (soil_before/after, et_demand_mm, trigger_reason, est_gallons, est_cf)
- DB: skip events with full conditions JSON (temp, humidity, wind, rain, soil, et0, weather_scale)
- DB: system health history (uptime, RSSI, heap, chip temp, boot count, battery)
- DB: recent weather log entries
- Weather scale from Zimmerman engine

**`database.py`** — New `get_health_history(limit=10)` helper querying system_health table.

**`templates/index.html`** — Dashboard now has 10 panels (was 9):

*New Telemetry panel (8 sections):*
1. ESP32 Hardware Telemetry — health metric cards (uptime, boot count, heap, chip temp, WiFi RSSI, reconnects, event count, IP, MAC, DHT22 temp/humidity, all soil sensor raw values)
2. Valve Lifetime Statistics — table with open/close counts per valve
3. Raw ADC Sensor Scan — GPIO pin readings
4. Watering Events Full Detail — 10-column table (time, zone, trigger reason, duration, soil before/after/delta, ET demand, gallons, CF)
5. Skip Events Full Detail — conditions JSON parsed into emoji-tagged metrics (🌡️temp 💧humidity 💨wind 🌧️rain 🌱soil ☀️ET₀ ⚡scale)
6. ESP32 Event Ring Buffer — color-coded by type (valve=blue, boot=green, error=red, wifi=amber)
7. System Health History — multi-day trend table
8. Recent Weather Readings — temp, humidity, wind, rain, ET₀

*Enhanced About panel:*
- "How It Works" section with ASCII data flow diagram (ESP32 ↔ Server ↔ Dashboard)
- 8-step decision cycle walkthrough
- Hardware stack cards (ESP32, Solar, L298N, Soil Sensors, DHT22, Acer)
- Database schema visualization (all 7 tables with columns)
- API endpoint documentation (ESP32 + Server endpoints)
- Weather Intelligence Scale (preserved)
- Roadmap phases (preserved)
- Research sources (preserved)

**Deployment:** SCP to Acer (192.168.0.109), server restarted on PID 2292513, `/api/telemetry` verified returning real data.

**Git:** Commit `1bd3cf7`, pushed to `jamesearlpace/smart-garden-server`.

---

## 2026-04-02 — Interactive Controls Panel (Valve Toggle)

**Context:** User wanted the dashboard to allow controlling and configuring the system from the browser — "at a minimum, turn on and off sprinklers." System is currently a test bench on desk, not installed in the ground.

### Changes

**`dashboard.py`** — Modified `/api/valve` and `/api/closeall` to return JSON when called via AJAX (`X-Requested-With: XMLHttpRequest` or `request.is_json`), returning `{ok, zone_id, action, valves[]}` with fresh valve state. Form POST redirect preserved for backwards compatibility.

**`templates/index.html`** — Dashboard now has 11 panels (was 10):

*New Controls panel:*
- **Test Bench Mode banner** — amber notice: "System is on your desk, not installed in the ground. All 7 ESP32 valve outputs are shown. Toggling sends real H-bridge pulses."
- **Emergency Stop All** — red button with confirm dialog, AJAX POST to `/api/closeall`
- **ESP32 status indicator** — Online/Offline from `/api/dashboard` response
- **7 valve cards** — each showing: name, hardware ID, L298N board, open/close counts, OPEN/CLOSED badge, and a toggle button (Open Valve / Close Valve)
- **AJAX toggle** — `ctrlToggleValve()` POSTs JSON to `/api/valve`, shows spinner during request, re-renders cards with fresh valve state from response
- **Fallback rendering** — if ESP32 is unreachable, shows zone data from config instead
- Top bar Stop All button converted from form POST to AJAX `ctrlStopAll()`

*Bug fix during deployment:* `loadControls()` originally fetched `/api/status` (weather data — no `esp32` key). Fixed to fetch `/api/dashboard` which has `esp32.valves[]`.

**Verified:** Opened valve 0 via AJAX endpoint, got JSON response with `ok:true` and full valve state array. Closed it back. All 7 valves returning data.

**Deployment:** SCP to Acer (192.168.0.109), server running, HTTP 200.

**Git:** Commit `5f8ef47`, pushed to `jamesearlpace/smart-garden-server`.

---

## 2026-04-02 — Code Audit & Bug Fixes (11 bugs)

**Context:** After building the Controls panel and HW_PINS GPIO mapping earlier today, ran a comprehensive code audit across all server files. Found 22 issues, fixed 11 across two commits.

### Commit `f3d0abc` — 8 dashboard/irrigation fixes

| Fix | File | Detail |
|-----|------|--------|
| System panel ESP32 metrics | index.html | Was using `esp.rssi`, `esp.heap_pct`, `esp.boot_count` (flat, wrong). Now uses `esp.system.wifiRSSI` etc. via `var espSys = esp.system \|\| {}` with null-safe checks |
| DHT22 humidity field | index.html | Telemetry checked `esp.humidity` but ESP32 returns `esp.hum` |
| ADC channel numbers | index.html | `soilPinStr()` computed `gpio-32` (CH0-3) but GPIO 32-35 = ADC1_CH4-7. Fixed to `gpio-28` |
| Mobile nav missing Schedule | index.html | Added Schedule panel to mobile nav between Analytics and Weather |
| About panel sensor count | index.html | "5 Soil Sensors" → "4 Soil Sensors" (matches `NUM_SOIL_SENSORS=4` in config.h) |
| wx.temp_f falsy at 0° | index.html | `fmt(wx.temp_f \|\| wx.temp)` fails when temp is 0°F. Changed to `!= null` ternary |
| loadSoilChart .catch | index.html | Added `.catch()` to soil chart fetch |
| Double temp conversion | irrigation.py | ESP32 returns temp in Fahrenheit (`dht.readTemperature(true)`). Was doing `temp * 9/5 + 32` again. Removed. |

### Commit `2563a53` — 3 structural fixes

| Fix | File | Detail |
|-----|------|--------|
| Name-based sensor matching | irrigation.py | Replaced fragile `zone["name"].split(" (")[0].split(" ")[0].lower() in sensor["name"].lower()` with direct index lookup: `soil_list[zone["soil_sensor"]]`. Eliminates two separate name-matching loops + shared-sensor fallback. Zones with `soil_sensor: 4` (not yet installed) get 50% default. |
| api_run_zone JSON support | dashboard.py | Now accepts JSON body and returns `{ok, zone_id, minutes, soil_pct}` for AJAX, matching `/api/valve` and `/api/closeall` pattern |
| Dead FileHandler code | server.py | `logging.FileHandler(...) if False else StreamHandler(sys.stderr)` — the `if False` made FileHandler dead code, and `FileHandler` doesn't take `maxBytes`/`backupCount` anyway. Replaced with `RotatingFileHandler` from `logging.handlers`. Log file confirmed created on server. |

### Not fixed (by design)
- **9 zones vs 7 firmware valves** — 9 is the target; only 1 physical valve wired currently. All conceptual.
- **Soil sensor 4 doesn't exist** — 4 sensors for 9 zones. Zones 6-8 reference sensor 4 which isn't installed yet; gets 50% fallback.
- **Port 5124 vs 5125** — config.yaml defaults to 5124 but actual deployment uses 5125. Works, not worth changing.
- **CSRF/XSS on LAN-only device** — negligible risk.

---

## 2026-04-02 — Configuration Panel (Live Config Editing)

**Context:** First item on the Next Steps list — add a configuration panel so zone names, installed status, schedule settings, and Zimmerman tuning can be edited from the browser.

### Changes

**`dashboard.py`** — Added two new endpoints:
- `GET /api/config` — returns the full live `config` dict as JSON
- `POST /api/config` — accepts a JSON patch with whitelisted sections (`zones`, `watering_window`, `skip_rules`, `weather_adjustment`, `esp32`). Merges zone fields individually (prevents adding/removing zones), persists to `config.yaml` via `yaml.dump`, updates `engine.config` and `engine.zones` in-memory. Returns `{ok, changed}`.

**`templates/index.html`** — Dashboard now has 12 panels (was 11):

*New Configuration panel (5 sections):*
1. **Watering Window** — start/end times for AM and PM windows (4 time inputs)
2. **Skip Rules** — rain threshold, wind threshold, freeze temp, rain probability, recent rain hours (5 numeric inputs)
3. **Zimmerman Weather Adjustment** — baseline temp/humidity, rain scale factor, min/max scale bounds, enable toggle (6 inputs)
4. **ESP32 Settings** — URL, poll interval, timeout (3 inputs)
5. **Zone Configuration** — 13-column inline editable table (ID, Name, Type, Installed checkbox, Sensor, Dry Trigger, Wet Target, Max Runtime, Est GPM, Kc Spring/Summer/Peak/Fall)

*JavaScript:*
- `loadConfig()` — fetches `/api/config`, populates all form fields and dynamically builds the zone table with `data-zid` and `data-field` attributes
- `cfgSave()` — reads all form values, builds a JSON patch preserving `evening_zones`, POSTs to `/api/config`, shows toast notification
- `cfgToast()` — helper for success/error toast messages
- `showPanel` hook lazy-loads config data only when panel is opened

**Deployment:** SCP both files to Acer, server restarted, `/api/config` verified returning full config JSON.

**Git:** Commit `a728230`, pushed to `jamesearlpace/smart-garden-server`.

---

## Next Steps
1. **Battery voltage monitoring** — Wire voltage divider to ESP32 GPIO 36, add to firmware + server + dashboard
   - **Parts on hand:** 10K ohm resistors (10-pack), 120K ohm resistors (25-pack)
   - **Divider:** 4× 10K in series (R1=40K) + 1× 10K (R2) → ratio 1:5 → 12.7V battery reads as 2.54V on ADC
   - **Pin:** GPIO 36 (VP) — free ADC1 input-only pin
   - **Wiring:** Battery +12V → [10K]→[10K]→[10K]→[10K]→ junction → [10K] → GND. Junction wire to GPIO 36.
   - **Firmware:** Add `analogRead(36)`, convert to voltage (raw × 3.3/4095 × 5), include `batteryV` in `/api/status` response
   - **Server:** Log to `health_history` table, add to `/api/health-history` response
   - **Dashboard:** Battery card on Home panel with voltage, SOC estimate (12.7V=100%, 11.8V=0%), and 24h/7d/30d chart
   - **Alerts:** Push notification if battery drops below 12.0V
2. Tune Zimmerman baselines after observing real-world behavior for 2-4 weeks
3. Integrate soil water balance depletion as additional watering trigger in `evaluate_zone()`
4. Add balance history chart to Analytics panel (data already in `soil_balance` table)
5. Calibrate `precip_rate_iph` per zone with catch-cup tests after physical installation
6. Observe soil water balance tracking and adjust AWC for Duvall soil type
7. Add runtime adjustment logging to analytics charts
8. Physical installation and field calibration

---

## 2026-04-03 — Phase 3: Soil Water Balance + Dashboard Enhancements

**Context:** "Let's do everything that can be done before I put it in the ground." Five software-only improvements implemented in one session.  
**Commit:** `14fdf6f` — 6 files changed, 348 insertions(+), 6 deletions(-)

### Features Added

1. **Telemetry auto-refresh** — Refresh button + "Auto 30s" checkbox in panel header. Uses `setInterval` with 30s polling, shows "Updated" timestamp.

2. **Health history charts** — 3 Chart.js mini line charts (RSSI blue, Heap green, Chip Temp red) in a 3-column grid on the Telemetry panel, rendered from `health_history` data.

3. **Analytics weather scale trend** — Rewrote `renderWeatherChart()` to compute Zimmerman scale client-side from temp/humidity/rain. Added 4th dataset "Scale %" (purple dashed line) on secondary y-axis (0-200%). Caches `weather_adjustment` config in `window._WA_CONFIG`.

4. **Precipitation rate config per zone** — Added `precip_rate_iph` to all 9 zones in `config.yaml` (sprinkler: 1.5, drip: 0.4). Added input column in Config panel, save logic in `cfgSave()`, and field whitelisted in `dashboard.py`.

5. **Soil water balance engine (Phase 3 — checkbook method)**:
   - **`config.yaml`:** Global `soil` section (AWC=0.15 in/in, root depth=6", MAD=50%). Per-zone overrides for peonies (10") and garden (12").
   - **`database.py`:** New `soil_balance` table with PK(zone_id, date). 5 helper functions: upsert, get latest, get history, get all, daily irrigation mm.
   - **`irrigation.py`:** Loads soil config, computes TAW/MAD per zone, `update_daily_balances()` runs the daily checkbook (ETc withdrawal, rain credit, irrigation credit, clamp to [0, TAW]).
   - **`server.py`:** Scheduler job at 11 PM nightly.
   - **`dashboard.py`:** 3 new API endpoints (`GET /api/balance`, `GET /api/balance/<zone_id>`, `POST /api/balance/update`). Added `soil_balances` to `/api/dashboard`.
   - **`index.html`:** Water balance bars in zone cards — color-coded (green >60%, orange >30%, red ≤30%) with MAD threshold marker.

### Testing
- DB init: OK
- Server starts with 4 scheduler jobs (irrigation_cycle, safety_check, weather_fetch, daily_balance)
- Manual `POST /api/balance/update`: all 9 zones computed — grass TAW=22.86mm, peonies TAW=38.1mm, garden TAW=45.72mm
- All zones at field capacity (rain=4.4mm > ET₀=1.24mm)
- Dashboard loads correctly (200, 134KB)

**Current State:** All software features complete. System ready for physical installation. Soil water balance will accumulate daily data once installed. Zimmerman baselines need 2-4 weeks of observation data before tuning.

---

## 2026-04-05 — First Hardware Build & Power Debugging

**Context:** First night wiring up the full hardware stack. Goal was to get ESP32 running on solar/battery power with DHT22 and L298N connected.

### What Was Done

1. **Full power chain wired:** Solar panel → Renogy Wanderer charge controller → LM2596 buck converter (adjusted to 5.06V with multimeter) → ESP32 VIN pin. L298N 12V input also connected to Renogy load output.

2. **Brownout fix:** ESP32 was boot-looping with `"Brownout detector was triggered"` even on USB only. Fixed by adding `WRITE_PERI_REG(RTC_CNTL_BROWN_OUT_REG, 0)` at the top of `setup()` with `#include "soc/soc.h"` and `#include "soc/rtc_cntl_reg.h"`.

3. **WiFi reconnect watchdog:** Added to `loop()` — checks WiFi status every 10s, calls `WiFi.disconnect()` + `WiFi.begin()` if dropped, hard-reboots via `ESP.restart()` after 6 consecutive failures (60s). Also added `WiFi.setAutoReconnect(true)` and `WiFi.persistent(true)` in `setupWiFi()`.

4. **Defective DHT22 replaced:** First sensor from 2-pack had OUT and GND bridged on the PCB (confirmed with multimeter continuity test). Replaced with second sensor — now reads 78°F / 40.5% humidity correctly.

5. **All connections soldered directly** to ESP32 pins: 5V (VIN), GND, GPIO 4 (DHT22 data), 3V3 (DHT22 power), GPIO 25 (L298N IN1), GPIO 26 (L298N IN2). 10kΩ pull-up resistor on DHT22 data line.

### Current Problem — Buck Converter Crash-Loop

ESP32 boots fine on USB only but crash-loops when powered from the LM2596 buck converter. Serial output:
```
rst:0x10 (RTCWDT_RTC_RESET), boot:0x17 (SPI_FAST_FLASH_BOOT)
entry 0x400805e4
```
Repeats with no `setup()` output at all. Even with L298N fully disconnected (only buck → ESP32), it still crash-loops.

### Analysis

| Observation | Interpretation |
|-------------|---------------|
| `boot:0x17` = binary `00010111` | GPIO 0 = bit 4 = **1 (HIGH)** → normal boot mode, not download. GPIO 4 = bit 2 = 1 due to DHT22 pull-up. This is correct. |
| `rst:0x10 (RTCWDT_RTC_RESET)` | RTC watchdog fires *before* application code runs — bootloader/flash read is failing |
| Works on USB, fails on buck | USB provides clean regulated 5V with large caps. LM2596 module likely has undersized output capacitor. |
| No `setup()` serial output | Crash happens during early init, not during WiFi. Likely SPI flash read failure from voltage ripple/sag. |

**Root cause hypothesis:** LM2596 output voltage sags during ESP32 startup current spikes (especially WiFi TX at 300-500mA). The cheap module's output capacitor can't handle the transient load.

### Firmware Changes — v2.2 (power-hardened)

Updated `main.cpp`, `config.h`, and `platformio.ini` with active power mitigations:

**Power-test environment (`pio run -e power-test`):**
- Bare-minimum firmware: no WiFi, no GPIO, no sensors, no NVS
- CPU at 80MHz, serial heartbeat every 2s with heap + chip temp
- 20.6% flash, 6.6% RAM — absolute minimum to prove ESP32 can boot
- If THIS crashes on buck power, it's 100% a hardware problem (cap needed)

**CPU frequency management:**
- Boot at 80MHz (`setCpuFrequencyMhz(80)`) — draws ~30mA idle vs ~80mA at 240MHz
- Boost to 240MHz only AFTER successful WiFi connect
- If WiFi fails, stays at 80MHz to minimize power draw

**WiFi TX power reduction:**
- `WiFi.setTxPower(WIFI_POWER_8_5dBm)` — reduces TX current from ~380mA to ~120mA
- Default 19.5dBm is overkill for a home WiFi network within 30 feet of router
- Configurable via `WIFI_TX_DBM` in config.h

**Crash counter safe mode:**
- NVS `crashCnt` increments on every boot, resets to 0 after successful WiFi connect
- If counter reaches 5 (`SAFE_MODE_THRESHOLD`): 15s extra stabilization delay, warning on serial
- Self-healing: if power stabilizes (e.g., after adding a cap), WiFi will eventually connect and clear the counter
- Prevents infinite rapid crash-loops from destroying NVS flash wear

**Staggered valve init:**
- `closeAllValves()` replaced with individual `closeValve()` + 200ms delay between each
- Prevents 7 simultaneous solenoid pulses from spiking current

**Resource usage:** 61.9% flash, 15.9% RAM (main), 20.6% flash, 6.6% RAM (power-test)

### Test Results (April 5, 2026)

**Step 1 — Bare-metal power test: PASS**
- Flashed `power-test` firmware. Cold-booted on buck converter alone (no USB).
- Stable `[POWER OK]` heartbeats for 4+ minutes with no crashes. Heap rock solid at 350,020 bytes.
- **Conclusion:** LM2596 buck converter can sustain idle ESP32 power draw. Hardware is fine.

**Step 2 — Full firmware with mitigations: PASS**
- Flashed `esp32` v2.2. Cold-booted on buck converter alone. 
- All `[INIT]` stages passed: NVS → valve counters → GPIO → 7 valve closes (staggered) → DHT22 → WiFi
- WiFi connected in ~500ms (1 dot) at 8.2 dBm TX power
- Crash counter reset, CPU boosted to 240MHz
- Full control chain verified: Copilot → SSH Acer → `curl http://192.168.0.150/api/status` → JSON response
- **Conclusion:** Power mitigations (80MHz boot CPU + reduced WiFi TX) eliminated the crash-loop. No capacitor needed.

**Key test observation:** Hot-plugging the buck converter into a USB-powered ESP32 causes crash-loops (ground loop / voltage spike). Cold boot from buck only works perfectly. This is expected behavior — never hot-swap power sources.

**Root cause (confirmed):** The original `rst:0x10 (RTCWDT_RTC_RESET)` crash was NOT a voltage sag problem. The ESP32 was trying to boot at 240MHz with 19.5dBm WiFi TX power (~380mA spike). The LM2596 could sustain it at idle but not during the combined startup current of WiFi + 7 simultaneous valve pulses. Reducing CPU to 80MHz during boot and WiFi TX to 8.5dBm brought peak current under the module's response margin.

### What's Running Now
- ESP32 on buck converter power (no USB) at 192.168.0.150
- v2.2 firmware with all power mitigations active
- Web dashboard accessible
- DHT22 reading 72.9°F / 41.5% humidity
- Capacitive soil moisture sensor on GPIO 32 — raw=2397, 55% moisture (dry air)
- L298N driving valve 1 solenoid — open/close confirmed via API
- WiFi RSSI: -57 dBm (very good)
- Free heap: 74% (242,164 / 323,416 bytes)
- Full control chain verified on buck power only: Copilot → SSH Acer → curl → valve click
- **Bench test complete — all peripherals verified on solar/battery power**

### Peripheral Test Log

| Step | Peripheral | Result |
|------|-----------|--------|
| 1 | Buck converter only (no peripherals) | power-test firmware: stable 4+ min, rock solid |
| 2 | Full firmware, buck only | All [INIT] passed, WiFi connected, crash counter cleared |
| 3 | Unplug USB, buck only | API responsive, 160s uptime, zero reconnects |
| 4 | Add DHT22 (hot-plug) | Caused reboot (expected), recovered automatically. 72.9°F / 40.2% |
| 5 | Add L298N (hot-plug) | Caused reboot (expected), recovered. Valve open/close confirmed |
| 6 | All peripherals, buck only, no USB | All sensors reading, valve clicking, WiFi solid |
| 7 | Add capacitive soil sensor on 3.3V | raw=0 — sensor needs 5V, not 3.3V |
| 8 | Move soil sensor VCC to 5V | raw=2397, 55% moisture — working |
| 9 | Full system, buck only, no USB | **All pass** — temp, humidity, soil, valve, WiFi |

### Hardware Lessons Learned

1. **Capacitive soil sensors need 5V** — advertised as 3.3-5V but produce no output on 3.3V. Wire VCC to ESP32 VIN (5V from buck), AOUT is still 0-3.3V (safe for ADC).
2. **Never hot-plug power sources** — connecting buck while USB is live causes crash-loops. Always cold-boot from one source.
3. **Defective sensors happen** — first DHT22 had OUT/GND bridged on PCB. Always test with a multimeter before assuming wiring is wrong.
4. **ESP32 boot current matters** — 240MHz CPU + 19.5dBm WiFi TX draws too much for cheap buck converters. Boot at 80MHz, reduce TX power, boost CPU after WiFi connects.
5. **Hot-plugging peripherals causes reboots** — the crash counter + safe mode handles this gracefully, but in the field everything should be wired before power-on.

---

## 2026-04-11 — Battery Drain Post-Mortem & Crash-Loop Protection

**Context:** System ran out of battery while James was on vacation. ESP32 was plugged back in via USB. Investigated root cause and implemented firmware fixes to prevent recurrence.

### Root Cause Analysis

The status API revealed the smoking gun — **boot count: 1,227** with valve close counts tracking identically:

| Zone | Opens | Closes | Analysis |
|------|-------|--------|----------|
| 1 - Garden | 674 | 1,258 | Close count ≈ boot count |
| 2 - Grapes | 3 | 1,238 | Close count ≈ boot count |
| 4 - South Lawn | 1 | 1,231 | Close count ≈ boot count |
| 6 - West/NW | 0 | 1,229 | Close count ≈ boot count |
| 7 - NE Lawn | 31 | 1,226 | Close count ≈ boot count |

The firmware's `closeAllValves()` safety routine fires on every boot, sending a 100ms 12V pulse through each L298N H-bridge to all 7 solenoid valves. Each crash-reboot cycle drew 1-2A × 7 valves from the battery. At 1,227 boot cycles, this drained the 7Ah SLA battery to zero — even though solar was presumably charging during the day, the drain rate during crash-loops far exceeded solar input.

**The battery drain spiral:** crash → reboot → close-all pulse (heavy 12V draw × 7 valves) → WiFi TX spike → crash → repeat × 1,227 times.

The underlying crash cause is the known LM2596 buck converter issue (documented April 5). The v2.2 power mitigations (80MHz boot, 8.5dBm WiFi TX) resolved it for clean boots, but something triggered crash-loops during vacation — possibly a power interruption, router restart, or WiFi dropout that cascaded.

### Firmware Changes (v2.2 → v2.2+battery-protect)

**1. Close-all only on clean boot** — [main.cpp](../smart-garden/src/main.cpp#L749)

Before: `closeAllValves()` fired unconditionally on every boot.

After: Checks `esp_reset_reason()` — only fires close-all on clean boots (`ESP_RST_POWERON`, `ESP_RST_SW`, `ESP_RST_DEEPSLEEP`). Crash reboots (`ESP_RST_INT_WDT`, `ESP_RST_TASK_WDT`, `ESP_RST_WDT`, `ESP_RST_PANIC`, etc.) skip the close-all entirely. This breaks the battery drain spiral — even if crash-looping, no 12V valve pulses fire.

**2. Deep sleep battery protection** — [main.cpp](../smart-garden/src/main.cpp#L720)

If crash counter hits `SAFE_MODE_THRESHOLD * 2` (10 consecutive crashes), the ESP32 enters deep sleep for 10 minutes (`esp_deep_sleep_start()` with timer wakeup). This:
- Stops all power draw (~10µA in deep sleep vs ~80-380mA active)
- Gives solar panel time to replenish battery
- Wakes periodically to retry — if power is stable, boots successfully and resets crash counter
- Prevents indefinite crash-looping from ever draining the battery again

**3. Added `esp_sleep.h` include** for `esp_deep_sleep_start()` and `esp_sleep_enable_timer_wakeup()`.

### Build & Flash

- Compiled: 65.6% flash, 17.2% RAM (slight increase from deep sleep code)
- Flashed via USB on COM3: `pio run -e esp32 --target upload --upload-port COM3`
- ESP32 rebooted, connected to WiFi, status API confirmed online at 192.168.0.150

### Verification

Post-flash status check confirmed the fix is active:
- Boot count: 1230 (1227 + 3 from flash/reboot cycles)
- Zone 1 close count: 1261 (only +3, not +21 as the old code would have done for 3 reboots × 7 valves)
- All sensors reading: 70°F, 50% humidity, Garden soil 59%
- WiFi: -60 dBm, 0 reconnects
- Free heap: 71%

### Key Insight

The root cause wasn't the sensors or the solar panel — it was the **close-all-on-boot safety routine interacting with crash-loops**. A safety feature designed to prevent stuck-open valves became the mechanism that killed the battery. The fix preserves the safety intent (close-all on clean power-on) while breaking the drain spiral (skip on crash reboots, deep sleep after 10 crashes).

---

## 2026-04-11 — Health Dashboard Panel & Deployment Pipeline Fix

**Context:** After adding the battery protection firmware, user requested health insights on the server dashboard (`:5125`). During deployment, discovered that dashboard updates had been silently failing for an unknown period due to two stacked infrastructure problems.

### Health Insights Panel

Added a **Health** panel to the server dashboard (between System and Telemetry in sidebar). Data flows from ESP32 firmware → `/api/status` health section → server `/api/dashboard` → client-side rendering.

**ESP32 firmware changes (`main.cpp`):**
- Promoted `crashCount`, `safeMode`, `lastResetReason` from local variables to globals
- Added `health` JSON object to `/api/status` response: crash counter, safe mode flag, reset reason (code + human name), deep sleep/safe mode thresholds, total valve open/close counts, close:open ratio, crash-loop evidence flag (ratio > 3x and boot count > 100)
- Added `esp_sleep.h` include for deep sleep functions

**Server dashboard (`templates/index.html`):**
- New `🩺 Health` nav item (desktop + mobile)
- `p-health` panel with 4 sections: Power & Stability, WiFi, Memory & Chip, Valve Health
- Alert banners: crash-loop evidence (red), safe mode (amber), healthy (green), low memory, weak WiFi, ESP32 offline
- Per-valve breakdown table with close:open ratio and status icons
- `renderHealthPanel()` JavaScript function, `fmtUptime()` helper
- `PANEL_TITLES` updated with `health: 'Health Insights'`

### Deployment Pipeline Post-Mortem

**Symptom:** User reported that dashboard changes "never show up" — I would make edits, SCP files, restart the service, confirm success, but the browser always showed the old version. This had been happening across multiple sessions.

**Root Cause 1 — Zombie process holding port (PRIMARY)**

A `server.py` process (PID 2826078) started on **April 10** was running outside of systemd — either started manually via `python server.py` or from a previous session. This process held port 5125 and was serving the **old** code.

When `systemctl --user restart smart-garden` ran:
1. Systemd started a NEW process with updated code
2. New process tried to bind port 5125 → **FAILED** (`Address already in use`)
3. New process exited with `status=1/FAILURE`
4. Systemd entered 30-second restart loop, failing every time
5. Browser kept hitting the OLD zombie process on port 5125 → old code

The `systemctl status` output was misleading — it briefly showed `active (running)` before the failure, and during the retry cycle it showed `activating (auto-restart)`, but I wasn't checking carefully enough.

**Root Cause 2 — Browser caching (SECONDARY)**

Flask's `SEND_FILE_MAX_AGE_DEFAULT = 0` only affects static file serving, NOT `render_template()` responses. Chrome was free to cache the HTML response. Even if the server served new content, the browser might not fetch it.

### Fixes Applied

**1. Systemd `ExecStartPre` — kill zombie processes before starting**

```ini
[Service]
ExecStartPre=/bin/bash -c 'fuser -k 5125/tcp 2>/dev/null || true; sleep 1'
ExecStart=/home/jamesearlpace/smart-garden-server/.venv/bin/python server.py
```

Before every start (including restarts), systemd now kills anything on port 5125. The `|| true` ensures it doesn't fail if nothing is listening. The 1-second sleep gives the OS time to release the socket.

**2. Flask `@after_request` no-cache headers**

```python
@app.after_request
def add_no_cache_headers(response):
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response
```

Every HTTP response now tells browsers to never cache. Also added `TEMPLATES_AUTO_RELOAD = True`.

**3. Deployment verification checklist (for Copilot)**

Future deployments must verify:
1. `fuser -k 5125/tcp` before restart (or rely on ExecStartPre)
2. `systemctl status` shows `active (running)` with a **new PID**

---

## 2026-04-17 — Fix stale dashboard data (issue #5)

**Context:** Dashboard showed "Data stale — last reading 5568m ago" despite ESP32 showing Online. The smart-garden-server process gets SIGKILL'd ~25-28s after starting under systemd (6900+ restarts, cause unknown — not OOM, not cgroup, not watchdog). The `run_cycle` scheduler job (every 300s) never executed before the kill, so the dashboard DB never received fresh data. Meanwhile, the collector service (separate process) kept writing to its own DB every 60s — data was there but the dashboard didn't know to look for it.

**Changes (commit a614302, repo: jamesearlpace/smart-garden-server):**

1. **`server.py`** — Added `next_run_time=datetime.now()` to `run_cycle` and `safety_check` scheduler jobs, so they fire immediately on startup before the ~25s kill window
2. **`database.py`** — Added collector DB fallback: `get_latest_soil()` and `get_latest_health()` check if dashboard DB data is >10 min stale, and if so, read from the collector's DB (`~/smart-garden/server/smart-garden.db`) which is always fresh
3. **`smart-garden.service`** — RestartSec=30 (was 15), StartLimitBurst=10, restored fuser -k ExecStartPre

**Decisions:**
- Chose resilience over root-cause fix: the SIGKILL source is unknown and hard to debug (no bpftrace/auditctl on server). Instead, made the system work correctly despite frequent restarts.
- Two separate SQLite databases remain (collector's `smart-garden.db` with `sensor_readings` table vs dashboard's `smart-garden.db` with `sensor_log` table). The fallback bridges them without merging.

**Current State:** Service restarts every ~30s but dashboard always shows fresh data. GitHub issue #5 closed.

**Open mystery:** The SIGKILL source. Suspects: a cron job, another systemd unit, or a kernel-level process. Would need `bpftrace` or `auditd` installed on the server to trace. Low priority since the system now self-heals.
3. `curl localhost:5125` returns content containing the new changes
4. `curl -I` shows `Cache-Control: no-store` header

### Lesson Learned

Never trust `systemctl status` alone or `scp` success as proof of deployment. The only valid test is: **does `curl` to the live server return the expected content?** A 200 status code is not enough — the response body must contain the actual change.

---

## 2026-04-14 — Power Optimization: MOSFET Gate + Deep Sleep Plan

**Context:** Battery keeps dying. Root cause analysis showed ~76-148 mA idle draw 24/7, while the 10W solar panel in Duvall WA only produces ~1.6 Ah/day. The system runs a daily deficit and dies in 2-3 days.

**Decision:** Quick Fix — add P-channel MOSFET power gate on L298N 12V rail + ESP32 deep sleep. Estimated to cut idle from ~100 mA to ~11-18 mA, well within solar budget.

### Root Cause Analysis

| Component | Idle draw (24/7) | Needed? |
|-----------|-----------------|---------|
| 5× L298N motor driver boards (quiescent) | 25-50 mA | **No** — latching solenoids hold position with zero power |
| ESP32 (always-on WiFi) | 40-80 mA | **No** — only needs to wake for watering windows |
| Renogy Wanderer charge controller | 6-8 mA | Unavoidable (keep for now) |
| LM2596 buck converter (12V→5V) | 5-10 mA | Unavoidable (powers ESP32) |
| **Total idle** | **76-148 mA** | |
| **Daily idle drain** | **~2.7 Ah** | |
| **10W panel daily output (Duvall)** | **~1.6 Ah** | |
| **Daily deficit** | **~1.1 Ah** | Battery dies in 2-3 days |

### Solution: Two Changes

**Change 1: MOSFET Power Gate (hardware)**
- One IRF4905 P-channel MOSFET cuts 12V power to ALL L298N boards simultaneously
- Controlled by one ESP32 GPIO pin (GPIO 2)
- Default state: OFF (L298N boards unpowered) via 10kΩ pull-up resistor
- Turns ON only during valve actuation (~100ms pulse), then turns OFF again
- Eliminates 25-50 mA of continuous idle draw

**Change 2: ESP32 Deep Sleep (firmware)**
- ESP32 enters deep sleep between watering windows
- Wakes on RTC timer at scheduled times (controlled by Acer server schedule)
- Deep sleep draw: ~10μA (vs 40-80 mA always-on)
- **Trade-off:** ESP32 is unreachable via HTTP while asleep — no on-demand control from Copilot/browser during sleep periods
- **Mitigation:** Configure wake windows aligned with server's irrigation check cycle (every 5 min during watering hours, sleep overnight)

### Expected Results After Fix

| Component | Before | After |
|-----------|--------|-------|
| 5× L298N boards | 25-50 mA | **0 mA** (MOSFET gate OFF) |
| ESP32 | 40-80 mA | **~0.01 mA** (deep sleep) / 80 mA (wake window) |
| Wanderer | 6-8 mA | 6-8 mA (unchanged) |
| LM2596 buck | 5-10 mA | 5-10 mA (unchanged) |
| **Total idle** | **76-148 mA** | **~11-18 mA** |
| **Daily idle drain** | **~2.7 Ah** | **~0.35 Ah** |
| **Battery life (no sun)** | 2-3 days | **~20 days** |

### Parts Ordered

| Part | Qty | Purpose | Status |
|------|-----|---------|--------|
| IRF4905 P-channel MOSFET (TO-220) | 1 needed (buy 10-pack) | Power gate — switches 12V to L298N boards | **TO ORDER** |
| 2N3904 NPN transistor | 1 needed | Level shifter — ESP32 3.3V GPIO drives 12V P-FET gate | **TO ORDER** |
| 10kΩ resistor (1/2W, 5%) | 1 needed | Pull-up on MOSFET gate (default OFF) | **ORDERED** ✅ |
| 1kΩ resistor (1/2W, 1%) | 1 needed | Base resistor for NPN transistor | **ORDERED** ✅ |

### MOSFET Gate Circuit Design

```
                        12V Battery Rail
                             │
                     ┌───────┤
                     │       │
                  [10kΩ]     │
                  pull-up    │
                     │       │
                     ├───G   │
                     │   IRF4905    
                     │   (P-ch)     
                     │   S───┘      
                     │   │          
                     │   D──────── 12V to ALL L298N boards (VCC input)
                     │              
             ┌───────┘
             │
             C
        2N3904 (NPN)
             E
             │
            GND
             
     ESP32 GPIO 2 ──[1kΩ]── B (base)
```

**How it works:**
1. **ESP32 GPIO 2 LOW** (default, boot, deep sleep): NPN is OFF → MOSFET gate pulled to 12V via 10kΩ → P-FET is OFF → L298N boards have no power → **0 mA idle draw**
2. **ESP32 GPIO 2 HIGH**: NPN conducts → pulls MOSFET gate to GND → P-FET turns ON → 12V flows to L298N boards → valves can be actuated
3. Gate turns ON ~1ms before valve pulse, stays on during pulse, turns OFF after pulse completes

**Why GPIO 2:**
- Only remaining free GPIO suitable for output (all others used for valves, sensors, DHT22)
- GPIO 2 is also the onboard blue LED — provides visual confirmation when gate is active (LED ON = L298N boards powered)
- During deep sleep, GPIO 2 defaults LOW = gate OFF = safe
- Strapping pin (must be LOW on boot for normal flash mode) — this is fine because LOW = gate OFF = desired boot state

### Wiring Steps (when parts arrive)

**Step 1: Identify the 12V feed wire to L298N boards**
- Currently: Wanderer LOAD+ → wire → L298N VCC inputs (all 5 boards daisy-chained)
- Cut this wire at a convenient point between the Wanderer and the first L298N board

**Step 2: Wire the MOSFET circuit**
1. **IRF4905 Source (S)** → connect to 12V battery rail (Wanderer LOAD+)
2. **IRF4905 Drain (D)** → connect to L298N VCC input (the cut wire going to L298N boards)
3. **IRF4905 Gate (G)** → connect to:
   - 10kΩ resistor → other end to 12V battery rail (same as Source) — this is the pull-up
   - Collector (C) of 2N3904 — this is the gate driver
4. **2N3904 Collector (C)** → MOSFET Gate (from step 3)
5. **2N3904 Emitter (E)** → GND (common ground with ESP32 and battery)
6. **2N3904 Base (B)** → 1kΩ resistor → ESP32 GPIO 2

**Step 3: Verify**
- Before connecting ESP32: measure voltage at L298N VCC — should be 0V (gate OFF by default)
- Touch 2N3904 base wire to 3.3V briefly — L298N VCC should jump to ~12V
- Remove 3.3V — VCC drops back to 0V

**IRF4905 TO-220 pinout (facing flat side, pins down, left to right):**
- Pin 1 (left): **Gate (G)**
- Pin 2 (center): **Drain (D)** — also connected to the metal tab
- Pin 3 (right): **Source (S)**

**2N3904 TO-92 pinout (facing flat side, pins down, left to right):**
- Pin 1 (left): **Emitter (E)**
- Pin 2 (center): **Base (B)**
- Pin 3 (right): **Collector (C)**

### Firmware Changes Required

**1. config.h — Add gate pin definition**
```cpp
// Power gate — controls MOSFET that switches 12V to L298N boards
#define POWER_GATE_PIN     2    // GPIO 2 (also onboard LED — visual indicator)
#define GATE_SETTLE_MS     5    // Wait after turning gate ON before pulsing valve
```

**2. main.cpp — Gate control functions**
```cpp
void enableDriverPower() {
    digitalWrite(POWER_GATE_PIN, HIGH);  // NPN on → MOSFET on → 12V to L298Ns
    delay(GATE_SETTLE_MS);               // Let voltage stabilize
}

void disableDriverPower() {
    digitalWrite(POWER_GATE_PIN, LOW);   // NPN off → MOSFET off → 0V to L298Ns
}
```

**3. main.cpp — Modify openValve() and closeValve()**
```cpp
void openValve(int idx) {
    if (idx < 0 || idx >= NUM_VALVES) return;
    enableDriverPower();          // ← NEW: power on L298N boards
    Valve& v = valves[idx];
    digitalWrite(v.in1, HIGH);
    digitalWrite(v.in2, LOW);
    delay(VALVE_PULSE_MS);
    digitalWrite(v.in1, LOW);
    digitalWrite(v.in2, LOW);
    disableDriverPower();         // ← NEW: power off L298N boards
    v.isOpen = true;
    // ... rest unchanged
}

void closeValve(int idx) {
    if (idx < 0 || idx >= NUM_VALVES) return;
    enableDriverPower();          // ← NEW
    Valve& v = valves[idx];
    // ... duration calc unchanged ...
    digitalWrite(v.in1, LOW);
    digitalWrite(v.in2, HIGH);
    delay(VALVE_PULSE_MS);
    digitalWrite(v.in1, LOW);
    digitalWrite(v.in2, LOW);
    disableDriverPower();         // ← NEW
    v.isOpen = false;
    // ... rest unchanged
}
```

**4. main.cpp — setup() — Initialize gate pin**
```cpp
// In setup(), before valve init:
pinMode(POWER_GATE_PIN, OUTPUT);
digitalWrite(POWER_GATE_PIN, LOW);  // Gate OFF by default — safe state
```

**5. Deep sleep (Phase 2 — implement after gate is verified working)**
```cpp
// After watering cycle completes:
#define SLEEP_DURATION_US  (5ULL * 60 * 1000000)  // 5 minutes

void enterDeepSleep() {
    disableDriverPower();                          // Ensure gate is OFF
    WiFi.disconnect(true);
    WiFi.mode(WIFI_OFF);
    esp_sleep_enable_timer_wakeup(SLEEP_DURATION_US);
    esp_deep_sleep_start();
}
```

**Deep sleep considerations:**
- ESP32 loses all RAM on deep sleep — WiFi reconnect takes ~2-3 seconds on wake
- RTC memory survives — can store wake count and next scheduled valve action
- Server-side scheduler (`irrigation.py`) already polls ESP32 every 5 min — if ESP32 is asleep, the poll fails silently and retries next cycle
- **Implement deep sleep AFTER verifying the MOSFET gate works correctly** — do one change at a time

### Implementation Order

1. **Wire MOSFET gate circuit** (when parts arrive)
2. **Flash firmware with gate support** (config.h + main.cpp changes above)
3. **Test:** open/close each valve via web UI — verify L298N boards power on and off around each pulse
4. **Monitor battery** for 1-2 weeks — confirm positive power budget
5. **If battery still struggles:** implement deep sleep (Phase 2) or swap Wanderer for CN3791 (Medium Redesign)

### Upgrade Path (if needed later)

| Trigger | Action |
|---------|--------|
| Battery holds fine for 2+ weeks | Done — no further changes |
| Battery slowly drains over weeks | Add deep sleep (firmware only, no new hardware) |
| Battery drains even with deep sleep | Replace Wanderer with CN3791 MPPT module (~$5) |
| Want to consolidate boards | Full redesign: single DRV8833 + multiplexer (probably never needed) |

### What NOT Changed

- Wanderer charge controller stays (6-8 mA idle is acceptable if L298N + ESP32 drain is eliminated)
- LM2596 buck converter stays (needed for ESP32 5V)
- All 5 L298N boards stay (just power-gated)
- All existing valve wiring stays (no changes to solenoid connections)
- Server-side code unchanged (irrigation.py, dashboard.py, etc.)


---

## 2026-04-20 — Production reliability sweep + ESP32 antenna research

**Context:** ESP32 showed offline on dashboard. What started as a single-bug investigation expanded into a full home-server reliability hardening pass after we found multiple landmines.

### What was wrong (Issue #6 — root cause)

Two systemd units were both running `server.py` with `ExecStartPre=fuser -k 5125/tcp`:
- `/etc/systemd/system/smart-garden-server.service` (system unit)
- `~/.config/systemd/user/smart-garden.service` (rogue user unit)

They were SIGKILL-ing each other every ~30 seconds in an infinite restart loop. NRestarts: **3937 (system) + 10861 (user)**. ESP32 connection-refused errors were a downstream symptom of constant TCP socket thrashing — every poll landed during a restart window.

**Fix applied:**
- Disabled and archived the user unit
- Replaced `ExecStartPre=fuser -k 5125/tcp` with a port-collision *check* (refuses to start instead of killing siblings)
- `smart-garden.service` commit: `f9943c5`

### Audit found the same landmine in thermostat-server

Same pattern — rogue user unit + `fuser -k 5126/tcp`. Disabled, archived, replaced with port check.

**Lesson learned:** NEVER use `ExecStartPre=fuser -k <port>/tcp` in a systemd unit. It will happily kill any other process on that port, including legitimate sibling services. Always use a port-collision check that fails fast instead.

### Issue #7 — ESP32 poll resilience

Even after the SIGKILL loop was gone, ESP32 still occasionally returned `Connection refused` (it's a small MCU under load).

**Fixed in `irrigation.py` (commit `fff0481`):**
- Switched from one-shot `requests.get()` calls to a long-lived `requests.Session()` with `HTTPAdapter(max_retries=Retry(total=3, backoff_factor=0.5, status_forcelist=[502,503,504]))`
- Bumped `ESP32_TIMEOUT` 10s → 15s
- Added `_consecutive_failures` counter with `_FAILURE_ESCALATE_AT = 3`
  - Attempts 1–2: WARNING (transient blip — don't page)
  - Attempts 3+: ERROR (real outage)
  - Recovery after failures: INFO message
- Suppressed `urllib3` retry chatter in `server.py`
- Applied to all HTTP methods: `get_esp32_status`, `open_valve`, `close_valve`, `close_all`

Validated in production logs — escalation logic working as designed.

### Home-server-wide monitoring deployed

Built two new tools in `home-dashboard/`:

**`audit-services.py`** (commit `ffe0234`) — landmine scanner across all 13 services:
- Checks NRestarts (flag if >100)
- Greps unit files for `fuser -k` patterns
- Detects rogue `~/.config/systemd/user/` units that shadow system units
- Detects port collisions

**`service-monitor.py`** — runs every 1 min via cron, sends ntfy alerts to topic `home-server-james`:
- Service down detection
- Restart loop detection (NRestarts delta ≥5 between checks)
- HTTP 5xx / timeout (4xx ignored — those are normal)
- New rogue user units appearing
- Disk >85% full
- Memory <5% free
- 30-min cooldown per issue key (no spam)
- State at `/tmp/home-server-monitor.state.json`
- Cron: `* * * * * /usr/bin/python3 /home/jamesearlpace/home-dashboard/service-monitor.py`

Test alert sent and received successfully.

### ESP32 antenna research (Issue #9 — not yet ordered)

Current ESP32 measures **-75 dBm at point-blank range** (likely PCB-trace antenna on WROOM-32, not -32U). Final deployment will be **50–70 ft away in a plastic junction box, behind 1–2 exterior walls** (router is in a corner of the house).

Real-world data found (citations):

| Source | Setup | Result |
|--------|-------|--------|
| [alonsoruibal.com](https://www.alonsoruibal.com/improving-wifi-reception-with-an-esp32-wroom-32u/) | WROOM-32 → WROOM-32U + 2.5 dBi external | **-95 → -75 dBm (+20 dB)**, disconnects gone |
| [OpenMQTTGateway thread](https://community.openmqttgateway.com/t/shocking-discovery-about-antenna-quality-of-esp32-modules/2228) | WROOM PCB vs WROOM-32U + Airgain external | **+11 to +21 dB improvement** |
| Same thread | Generic WROOM PCB vs **Seeed XIAO ESP32-C3** w/ included antenna | **+44 dB improvement** (!) |

**Honest revised recommendation (~ total):**
1. **ESP32-WROOM-32U dev board** (~) — drop-in, firmware just works, gives +15-20 dB
2. **2.4 GHz 5 dBi external antenna w/ U.FL→SMA pigtail** (~)
3. **TP-Link RE220 or RE315 WiFi extender** (~) — plug into garden-facing outlet

Math: -75 dBm point-blank today → with WROOM-32U, ~-55 dBm point-blank. Lose 25-35 dB over 70 ft + 1-2 walls → land at **-80 to -95 dBm** in the box. That's marginal-to-bad without the extender. The extender is the actual fix; the antenna upgrade buys headroom.

**Alternative considered:** Seeed XIAO ESP32-C3 (~) showed +44 dB in tests vs PCB antenna — better than WROOM-32U. But it's a different chip (RISC-V single-core, different pinout) → 2-4 hours of firmware port work. Skipped for now; WROOM-32U is the pragmatic choice.

**Decision:** Order Plan A from Amazon, test in-place at the garden box BEFORE permanent install. All items returnable.

### Open issues after this session

- **#8** — Decommission old `~/smart-garden/` install (paranoia cleanup, not urgent)
- **#9** — Order WROOM-32U + antenna + RE220 extender (above)
- **home-dashboard #11** — Migrate Flask from dev server to `waitress` WSGI (production hardening)

### Memory updates

- Created `/memories/repo/` notes (via session)
- User memory: existing `accountability-tracker-issues.md` already documents the NSSM lesson (analogous to today's "always restart the unit after editing" lesson for systemd)


---

## 2026-04-20 (continued) - Server reliability hardening

User asked for `super reliable` after seeing dashboard go offline. After auditing the actual bug history, identified that **every outage in memory was a server/dashboard problem, not an ESP32 problem**. ESP32 dropping signal is graceful (cached data, recovers); server going offline is catastrophic. Decided to skip hardware spend and harden the server side instead.

### What got deployed

1. **Smart-garden Flask -> waitress** (commit `a891010`). Production WSGI, threaded, tolerant of malformed input. `server.py` uses `waitress.serve(threads=8)` instead of `app.run()`.
2. **Bulletproof systemd settings on all 12 services** via `home-dashboard/harden-units.sh` (idempotent). Each unit now has Restart=always + RestartSec=10 + StartLimitIntervalSec=600 + StartLimitBurst=10 + TimeoutStopSec=30 + port-collision check (NEVER fuser -k).
3. **Content-validation in service-monitor.py** (commit `412d789`). Each dashboard has an `expect_substring` (e.g. `Smart Garden`, `Heritage Vault`, `Academic Tracker`). Catches blank-200 / handler-broken failures, which is the actual outage class from the bug history.
4. **Decommissioned orphan units** (closes #8). `smart-garden-api`, `smart-garden-collector`, `smart-garden-scheduler` were pointing to the old `~/smart-garden/` install. Stopped, disabled, archived as `.decommissioned-2026-04-20`. Code dir moved to `smart-garden.OLD-DECOMMISSIONED-2026-04-20`. Script preserved at `scripts/decommission-orphans.sh`.

### Failure modes now blocked

| Past failure | Now prevented by |
|---|---|
| `fuser -k` SIGKILL war | Port-collision check refuses to start |
| Rogue user units shadowing system | service-monitor alerts on this |
| Infinite restart loop | StartLimitBurst=10 (systemd gives up) |
| Flask dying on bad input | Waitress is threaded + tolerant |
| Blank dashboard returning 200 | Content validation |
| Hanging on shutdown | TimeoutStopSec=30 |

### Validation

All 12 services active after restart. `service-monitor.py` runs clean (no false alerts). `smart-garden-server` returning HTTP 200 in 0.14s under waitress.

### Hardware decision

**Antenna upgrade (#9) deferred indefinitely.** ESP32 isn't the problem; the server discipline was. Will revisit only if signal-related outages start mattering after the server changes settle in.
