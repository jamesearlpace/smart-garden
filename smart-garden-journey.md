# Smart Garden — Journey Doc

**Status:** V4 firmware on chip (commit `fdd6300`). Web server wedge MITIGATED — firmware socket reset handles short gaps, server-side retry catches the rest. Server RUNNING with zero lost cycles in 10-min production test. Battery voltage pipeline wired end-to-end. Overnight soak in progress.
**Last Updated:** 2026-04-26 23:45
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

## Open issues

| Repo | # | Sev | Summary |
|------|---|-----|---------|
| smart-garden | [#2](https://github.com/jamesearlpace/smart-garden/issues/2) | Low | Re-enable OTA — needs decoupling cap + bench test |
| smart-garden | [#4](https://github.com/jamesearlpace/smart-garden/issues/4) | Meta | Recurrent AI mistake: premature "ship it" claims |
| smart-garden | [#1](https://github.com/jamesearlpace/smart-garden/issues/1) | Meta | (Earlier) contradictory OTA claims |
| smart-garden | — | Low | Web server wedge at 120s+ idle gaps — firmware fix incomplete, **MITIGATED by server-side retry** (2026-04-26). Not blocking outdoor deployment. |
| smart-garden | — | Low | Wire voltage divider (4×10kΩ + 1×10kΩ) from battery to GPIO 36 — currently floating, reads noise |
| smart-garden-server | (closed) | — | Chip-temp false positives — fixed by 3-consecutive-sample hysteresis in `_check_chip_temp` (deployed 2026-04-22). |
| smart-garden-server | (closed) | — | #10 TIME_WAIT, #11 emoji bug, #12 reboot wiring all closed in 2026-04-21 session |
| smart-garden-server | ✅ closed | — | dashboard.py bypass routes — **FIXED** `624b6d9` (2026-04-26). All 5 routes now use cached/pooled calls. |

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

---

## Current device state (as of 2026-04-26 23:45)

- Firmware: **V4** on chip (commit `fdd6300`) — V2 cached-battery + WiFi.setSleep(false) + periodic server.close()/begin() every 10s + OTA disabled + TWDT 60s + valve hard-max 95min + fallback schedule
- Server: **RUNNING** (systemd `smart-garden-server`, PID 367672, port 5125)
- Power: Victron charger → 12V SLA → LM2596 buck (**USB unplugged**)
- **Wedge status: MITIGATED** — firmware socket reset handles short gaps, server retry catches longer ones. 10-min production test: 2/2 cycles, 0 skips.
- Battery monitoring: pipeline complete (firmware → server → DB → chart), voltage divider not yet wired to GPIO 36
- Overnight soak running — telemetry recording every 5 min
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

## Recently shipped (last 7 days)

| Date | Change | Commit |
|------|--------|--------|
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
