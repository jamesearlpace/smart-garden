# Smart Garden — Journey Doc

**Status:** Stable. Chip on wall charger at deployed location. RSSI -36, 0 reconnects, OTA disabled (USB-only flashes). Server has gated `/api/reboot` (default-disabled). Ntfy alerts working (no emoji bug).
**Last Updated:** 2026-04-22
**Goal:** Solar-powered smart irrigation controlled remotely via Copilot through home server.

> **Full history → [smart-garden-journey-archive.md](smart-garden-journey-archive.md)** (84KB, all dated session logs, hardware build notes, deployment post-mortems). This doc keeps only what every new session needs.

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

# Open / close valve (id=0..6, zero-indexed)
ssh jamesearlpace@192.168.0.109 "curl -s -X POST 'http://192.168.0.150/api/valve?id=0&action=open'"
ssh jamesearlpace@192.168.0.109 "curl -s -X POST 'http://192.168.0.150/api/valve?id=0&action=close'"

# Close all
ssh jamesearlpace@192.168.0.109 "curl -s -X POST 'http://192.168.0.150/api/closeall'"

# Server dashboard
http://192.168.0.109:5125
```

### Deploy server changes
```powershell
cd C:\MyCode\smart-garden-server
scp <file>.py jamesearlpace@192.168.0.109:~/smart-garden-server/
ssh jamesearlpace@192.168.0.109 "sudo systemctl restart smart-garden-server.service"
```
**NOT a git repo on the server** — deploy by scp, not pull.

### Flash firmware (USB only — OTA disabled)
```powershell
cd C:\MyCode\smart-garden
pio run -e esp32 --target upload --upload-port COM3
pio device monitor --baud 115200
```

---

## Architecture

### Hardware
| Component | Model | Notes |
|-----------|-------|-------|
| MCU | HiLetgo ESP-WROOM-32 | MAC `f4:2d:c9:6b:f7:78`, static IP 192.168.0.150 |
| Solar | ECO-WORTHY 10W 12V | ~1.6 Ah/day in Duvall WA |
| Charge ctrl | Renogy Wanderer Li 10A | Battery + load output. **Brownout source.** |
| Battery | ExpertPower 12V 7Ah SLA | |
| Buck | LM2596 | 12V → 5V to ESP32 VIN |
| H-bridge | L298N × 5 | 2 valves per board, 10 valves max |
| Valves | Orbit 57861 DC latching | Pulse open, reverse pulse close |
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

---

## Critical reliability rules

### Brownout = root cause of every recent failure
The Wanderer load output sags voltage during high-current bursts. **Affects every high-current op:**
- OTA upload → bricks chip (5–10% into upload)
- `ESP.restart()` via `/api/reboot` → bricks chip
- Suspected: simultaneous valve pulses, WiFi reconnect storms

**Mitigation in firmware** (already deployed, `7ba2262`):
- `WIFI_TX_DBM = WIFI_POWER_19_5dBm` (was throttled to 8.5)
- ArduinoOTA wrapped in `#ifdef ENABLE_OTA` (default OFF)
- Close-all valves only on clean boot, not crash reboots
- Deep sleep 10 min after 10 consecutive crashes (battery protection)

**Mitigation in server** (deployed `a89dc35`):
- `/api/reboot` returns HTTP 503 unless `SMART_GARDEN_REBOOT_ENABLED=1` env var is set

**Real fix (not yet done):** 1000µF + 100nF decoupling cap on 3.3V rail. See GitHub issue #2.

### Verification playbook — confirm "still healthy"

**A. Quick health probe (30s)**
```powershell
ssh jamesearlpace@192.168.0.109 "curl -s --max-time 8 http://192.168.0.150/api/status" | python -c "import sys,json; d=json.load(sys.stdin); s=d['system']; h=d.get('health',{}); print(f'boot={s[\"bootCount\"]} uptime={s[\"uptimeSec\"]}s rssi={s[\"wifiRSSI\"]} reconnects={s[\"wifiReconnects\"]} crashCount={h.get(\"crashCount\")} safeMode={h.get(\"safeMode\")} temp={s.get(\"chipTempC\")}')"
```
Good: rssi -29 to -50, reconnects 0, safeMode False, uptime > 600s, chipTempC < 90.
Red flags: rssi worse than -65, reconnects climbing, safeMode True.

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

## Open issues

| Repo | # | Sev | Summary |
|------|---|-----|---------|
| smart-garden | [#2](https://github.com/jamesearlpace/smart-garden/issues/2) | Low | Re-enable OTA — needs decoupling cap + bench test |
| smart-garden | [#4](https://github.com/jamesearlpace/smart-garden/issues/4) | Meta | Recurrent AI mistake: premature "ship it" claims |
| smart-garden | [#1](https://github.com/jamesearlpace/smart-garden/issues/1) | Meta | (Earlier) contradictory OTA claims |
| smart-garden-server | (closed) | — | #10 TIME_WAIT, #11 emoji bug, #12 reboot wiring all closed in 2026-04-21 session |

---

## Codebase map

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
4. **No MQTT** — REST is enough
5. **Static IP in firmware** — 192.168.0.150 hardcoded, no DHCP dependency
6. **OTA disabled by default** — Wanderer brownouts make it unsafe; USB-only flashing accepted
7. **Server `/api/reboot` gated default-off** — Same brownout root cause
8. **Two-DB architecture** — Collector writes to one, dashboard falls back to it when main DB stale (resilience over root-cause fix for unknown SIGKILL source)

---

## Hardware to-do (when parts arrive)

Per archive 2026-04-14: P-channel MOSFET power gate for L298N rail + ESP32 deep sleep between watering windows. Estimated battery draw 76-148 mA → 11-18 mA (battery life 2-3 days → ~20 days).

Parts ordered: 10kΩ + 1kΩ resistors. **TO ORDER:** IRF4905 P-FET, 2N3904 NPN. Full circuit + wiring steps in archive.

---

## Recently shipped (last 7 days)

| Date | Change | Commit |
|------|--------|--------|
| 2026-04-22 | Gated `/api/reboot` 503-by-default, irrigation.py reboot wrapper, config.yaml token | `a89dc35` (server) |
| 2026-04-21 | ASCII-strip ntfy title (#11) | `51eb250` (server) |
| 2026-04-21 | TX 19.5dBm + ArduinoOTA `#ifdef`-gated | `7ba2262` (firmware) |
| 2026-04-21 | TIME_WAIT fix: status cache 30s + retries 0 + debounce 5 polls | `a7a1114` (server) |
| 2026-04-17 | Stale dashboard fix — collector DB fallback | `a614302` (server) |

For older entries see [smart-garden-journey-archive.md](smart-garden-journey-archive.md).
