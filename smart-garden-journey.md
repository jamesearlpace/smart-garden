# Smart Garden — Journey Doc

**Status:** Active — first valve tested, server-side irrigation engine deployed  
**Last Updated:** 2026-04-02  
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

## Current State (2026-04-01)

### What's Working
- ESP32 firmware compiled and flashed via PlatformIO (COM3)
- **Static IP 192.168.0.150** hardcoded in firmware (gateway .1, DNS .1) — no DHCP dependency
- Web dashboard with valve controls and sensor displays (port 80)
- REST API: `/api/status`, `/api/valve?id=X&action=open|close`, `/api/closeall`
- Full remote control chain proven: Copilot → SSH Acer → curl ESP32 → valve actuates
- SSH key auth configured (ed25519, no password needed for Acer SSH)
- **Valve 1 (Zone 1 - Garden drip)** physically wired and tested — solenoid confirmed moving

### Telemetry (v2.0 — compiled, awaiting flash)
Firmware built but ESP32 not on USB. Flash when next connected.

**New API endpoints:**
- `/api/status` — now includes `system` object: uptime, boot count, WiFi RSSI, free heap, chip temp, event count, per-valve open/close counters
- `/api/events` — ring buffer of last 100 timestamped events (valve actions, boots, errors), newest first
- `/api/valvestats` — per-valve lifetime actuation counts

**New firmware features:**
- **NVS persistence** — boot count and per-valve actuation counters survive power cycles
- **Event ring buffer** — 100 events in RAM, each with uptime timestamp, type, and detail
- **Valve duration tracking** — logs how long each valve was open when closed
- **System metrics** — WiFi RSSI, free heap %, ESP32 die temp, uptime
- **Web dashboard v2** — tabbed UI with System panel (6 cards), improved valve rows showing actuation counts, Event Log tab

**Resource usage:** 61.8% flash, 15.9% RAM (up from 60.7% / 13.9%)

### What's Not Done Yet
- Flash telemetry firmware (v2.0 compiled, ESP32 needs USB connection)
- Only 1 of ~10 valves wired (need 4 more L298N boards)
- Soil moisture sensors not connected (GPIO 32-35, capacitive sensors)
- DHT22 temperature sensor not connected (GPIO 4)
- Battery/solar voltage monitoring (needs 2 resistor voltage dividers → GPIO 36, 39)
- Valves not connected to actual irrigation pipes
- config.h only defines 7 valves — needs 3 more pin assignments for 10 total

### GPIO Pin Layout (current 7 valves in config.h)
| Valve | Zone | IN1 | IN2 | L298N Board |
|-------|------|-----|-----|-------------|
| 1 | Garden drip | GPIO 25 | GPIO 26 | Board 1, Ch A |
| 2 | Grapes drip | GPIO 27 | GPIO 14 | Board 1, Ch B |
| 3 | Fruit Trees | GPIO 16 | GPIO 17 | Board 2, Ch A |
| 4 | South Lawn | GPIO 18 | GPIO 19 | Board 2, Ch B |
| 5 | East Lawn | GPIO 21 | GPIO 22 | Board 3, Ch A |
| 6 | North Beds | GPIO 23 | GPIO 13 | Board 3, Ch B |
| 7 | West Strip | GPIO 5 | GPIO 15 | Board 4, Ch A |

### Scaling to 10 Valves
- ESP32 has enough GPIOs for 10 valves (20 pins) but requires using boot-sensitive pins (0, 2, 12)
- 8 valves = comfortable, 9-10 = need boot-sensitive GPIOs or an MCP23017 I2C expander
- 10 valves = 5 L298N boards

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
| `config.yaml` | Zone profiles (7 zones), Duvall billing tiers, skip rules, watering windows |
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
- **Flash/RAM:** 60.7% flash, 13.9% RAM used

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

## Next Steps
1. Order 4 more L298N boards for remaining valves
2. Add 3 more valve pin definitions to config.h (valves 8-10)
3. Wire remaining valves
4. Connect soil moisture sensors and DHT22
5. Build server-side automation on Acer (Python service with scheduling)
6. Connect to actual irrigation pipes
