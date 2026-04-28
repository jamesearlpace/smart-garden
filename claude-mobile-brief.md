# Smart Garden — Brief for Claude (mobile)

> Paste this whole file into a new Claude conversation (or save it as the
> "knowledge" / custom instructions of a Claude Project named "Smart Garden")
> so Claude has full context when I chat from my phone.
> Last updated: 2026-04-27.

---

## Who I am and what I'm doing

I'm James Pace. I'm building a **solar-powered smart irrigation system** for
my yard in Duvall, WA. The system is already built and running — I'm now in
the operations / iteration phase (reliability fixes, hardware upgrades, new
features). I do the dev work in VS Code on my desktop with GitHub Copilot,
and I want to talk through ideas / plan / debug with you (Claude) from my
phone when I'm away from the computer.

**What I want from you in this thread:**
- Be a thinking partner and engineer. Push back when I'm wrong.
- Don't write giant code dumps unless I ask. Prefer diffs / pseudo-code /
  bullet plans I can hand to Copilot back at the desktop.
- Assume I'm technical (former dev, currently a Microsoft AI/Apps tech lead).
  Skip beginner explanations.
- When I describe a symptom, ask the diagnostic questions a senior embedded
  engineer would ask before proposing fixes.

---

## System architecture (one-paragraph version)

An ESP32 (HiLetgo ESP-WROOM-32, static IP **192.168.0.150**) sits in a
weatherproof box outside, powered by a 10W solar panel → Renogy Wanderer
charge controller → 12V 7Ah SLA battery → LM2596 buck to 5V into ESP32 VIN.
The ESP32 drives **L298N H-bridges** that pulse **Orbit 57861 DC latching
solenoids** (latching = no holding current, just a pulse to flip state).
There are 7 valves wired today, capacity for 10. Soil moisture sensors
(capacitive) + a DHT22 feed a small REST API on the ESP32.

A **Linux Mint mini-PC ("Acer", 192.168.0.109)** sits indoors as the
always-on bridge. It runs a Flask + waitress + APScheduler + SQLite
**smart-garden-server** on port **5125** that:
- Polls the ESP32 every 5 min, stores telemetry in SQLite (WAL).
- Pulls weather from Open-Meteo (cached 30 min), computes ET₀, decides which
  zones to water and when based on `config.yaml`.
- Serves a dashboard at `http://192.168.0.109:5125`.
- Pushes alerts to **ntfy.sh/smart-garden-james** (NOT Pushover — old refs
  to Pushover are stale).
- Exposes a gated `/api/reboot` for the ESP32 (default-disabled because of
  brownouts — see below).

Control chain when I'm on my desktop:
`Copilot → SSH Acer → curl ESP32 → valve actuates`.

```
Ziply Fiber → Netgear GS305E → TP-Link ER605 (.1) → Eero 6
  ├─ Acer (.109, wired)
  └─ ESP32 (.150, WiFi static)
```

---

## Current status (as of 2026-04-27 evening)

**On desk near router, master firmware reflashed, wedge bug remains open.**

- **Wedge bug ([#5](https://github.com/jamesearlpace/smart-garden/issues/5)) confirmed reproducible at production cadence** — 5/7 fail in 30-min soak today. Server retry pattern absorbs most instances. Self-recovery confirmed n=2.
- **ESPAsyncWebServer migration TESTED and RULED OUT** today (2026-04-27 19:00). Identical SYN→RST(win=0) signature. Bug is below app layer (lwIP / WiFi driver). Branch `feature/async-webserver` (commit `f943a95`) preserved.
- **TX power telemetry pipeline shipped** (firmware + server + dashboard column). 4 boots sampled today: TX 7.8 / 14.3 / 14.8 / 14.0 dBm — all below 19.5 dBm target. See [#6](https://github.com/jamesearlpace/smart-garden/issues/6).
- **WiFi watchdog tuning shipped** (60s→5min threshold + close-all-valves before reboot) — commit `53a91d9`.
- **Battery divider 5:1→6:1 wired** (commit `a01b3f5`), needs verification.
- **User buying 1000µF + 100nF decoupling caps** (issue [#2](https://github.com/jamesearlpace/smart-garden/issues/2)). Fixes brownout class but NOT the wedge.
- **Next candidates for the wedge** (in priority order): ESP-IDF v5.x upgrade via arduino-esp32 v3.x, `WiFi.setCountry()` experiment, sdkconfig `lwip_max_listening` bump, OR smart-plug out-of-band recovery.

OTA flashing is **disabled by default** (USB-only) because of brownouts.

---

## The big lesson — brownouts are the root cause of everything

The Renogy Wanderer's load output sags voltage during high-current bursts.
This has caused every major failure I've had:
- OTA upload bricks the chip 5-10% in
- `ESP.restart()` via the API bricks the chip
- Probably also: simultaneous valve pulses, WiFi reconnect storms

**Mitigations already shipped (firmware, commit `7ba2262`):**
- WiFi TX power back to 19.5 dBm (was throttled to 8.5 trying to fix range
  — wrong fix, made WiFi worse without helping the real issue)
- ArduinoOTA wrapped in `#ifdef ENABLE_OTA`, default OFF
- Close-all-valves only on clean boot, not crash reboots (avoids pulse
  storm during a brownout-induced crash loop)
- After 10 consecutive crashes, deep-sleep 10 min to protect battery

**Mitigations already shipped (server, `a89dc35`):**
- `/api/reboot` returns HTTP 503 unless `SMART_GARDEN_REBOOT_ENABLED=1`

**Real fix not yet done:** add a 1000µF + 100nF decoupling cap on the 3.3V
rail. Tracked as smart-garden GitHub issue #2.

---

## Hardware to-do (when parts arrive)

Goal: **cut idle battery draw from ~76-148 mA to ~11-18 mA** (battery life
goes 2-3 days → ~20 days). Two changes:

1. **P-channel MOSFET power gate on the L298N rail** so the H-bridges are
   completely de-powered between watering windows. Need:
   - IRF4905 P-FET (TO-220) — **TO ORDER**
   - 2N3904 NPN level shifter — **TO ORDER**
   - 10kΩ resistor (gate pull-up, default OFF) — ✅ ordered
   - 1kΩ resistor (base resistor for NPN) — ✅ ordered
2. **ESP32 deep sleep between watering windows.** Wake on RTC alarm or
   external trigger.

Newer "to order" list (consolidated in archive 2026-04-?? entry):
- **2N7000 N-MOSFET (10-pack)** — soil sensor GND switch
- **Capacitive soil sensor (3.3V, e.g. DFRobot v2.0) ×5** — replace
  resistive sensors I have now
- **DHT22 ×1** — second sensor, one inside the enclosure and one outside

Total new parts cost ~$15-25.

---

## Server features already shipped (active monitoring, 2026-04-22)

The Acer's `AlertMonitor` runs every poll cycle. Fires ntfy alerts for:
- ESP32 unreachable >15 min
- Crash loop (>5 reboots in 1h)
- Safe mode active
- Free heap <15%
- Sensor flatline/railed >48h
- NVS counter delta — `bootCount` / `wifiReconnects` / `crashCount` going
  up between polls (steady-state on wall power = 0 delta, any change = news)
- Chip temp >85°C — **with 3-consecutive-sample hysteresis** because the
  ESP32 internal temp sensor is famously noisy on individual reads (real
  die temp is ~78°C steady; spikes to 100°C+ for one sample then back to
  78°C are sensor glitches, not thermal events — die can't cool 30°C in
  4 minutes)
- 8 AM daily digest summarizing 24h
- Startup ping 10s after server start = "pipeline alive" confirmation
- 30 min cooldown per alert key so it doesn't spam

---

## Decision-engine logic (irrigation skip order)

In order, the scheduler skips a zone if:
1. Already wet
2. Not dry enough
3. Recent rain
4. Rain forecast
5. Freeze
6. Wind (sprinklers only)
7. Over budget
8. Outside watering window

Scheduler intervals: irrigation cycle 5 min, safety check 2 min, weather
fetch 30 min, daily soil balance 11 PM.

---

## Codebase map (in case I quote a file)

**Firmware** lives at `C:\MyCode\smart-garden\` on my desktop:
- `platformio.ini` — `esp32` env (USB COM3) + `ota` env (default off)
- `src/config.h` — WiFi creds, pin assignments, `API_REBOOT_TOKEN`,
  `WIFI_TX_DBM`
- `src/main.cpp` — valve control, sensors, web server, REST API,
  NVS-persistent boot count + crash counter

**Server** lives at `C:\MyCode\smart-garden-server\` on desktop, deployed
via `scp` to Acer at `~/smart-garden-server/` (NOT a git repo on the
server — deploy is `scp file.py jamesearlpace@192.168.0.109:...` then
`sudo systemctl restart smart-garden-server.service`):
- `config.yaml` — zones, billing, weather adjustment, esp32 reboot_token
- `database.py` — SQLite schema + helpers
- `weather.py` — Open-Meteo client, ET₀, 30-min cache
- `irrigation.py` — decision engine + ESP32 HTTP layer + `reboot_esp32()`
- `dashboard.py` — Flask UI + REST endpoints (incl. gated `/api/reboot`)
- `notifications.py` — ntfy.sh sender (ASCII-only title)
- `server.py` — APScheduler + Flask entry

There's also a **secondary collector** writing to a separate
`~/smart-garden/server/smart-garden.db` every 60s. If the main DB is >10
min stale, the dashboard falls back to it. This is resilience plumbing
because I had an unexplained SIGKILL on the main process and decided two
DBs was cheaper than chasing the root cause.

---

## Common commands (so you can suggest exact-syntax fixes)

```powershell
# Status from desktop
ssh jamesearlpace@192.168.0.109 "curl -s http://192.168.0.150/api/status"

# Open / close valve (id=0..6, zero-indexed)
ssh jamesearlpace@192.168.0.109 "curl -s -X POST 'http://192.168.0.150/api/valve?id=0&action=open'"
ssh jamesearlpace@192.168.0.109 "curl -s -X POST 'http://192.168.0.150/api/valve?id=0&action=close'"

# Close everything
ssh jamesearlpace@192.168.0.109 "curl -s -X POST 'http://192.168.0.150/api/closeall'"

# Server logs
ssh jamesearlpace@192.168.0.109 "journalctl -u smart-garden-server.service -f"

# Flash firmware (USB only, OTA disabled)
cd C:\MyCode\smart-garden
pio run -e esp32 --target upload --upload-port COM3
pio device monitor --baud 115200
```

---

## Open issues / things on my mind

- **smart-garden #2** (low) — re-enable OTA, blocked on the 1000µF/100nF
  decoupling cap + bench test
- **smart-garden #4** (meta) — recurrent AI mistake: don't claim "ship it"
  before health probe + 5-min dashboard cadence on the actual deployed
  power source. I broke this rule 4× in one session.
- **Antenna upgrade research** (#9) — RSSI is fine indoors, but want a
  better external antenna for the outdoor enclosure. Not yet ordered.
- The **chip-temp false positive** alerts — fixed via hysteresis. Don't
  panic if I mention "temp alert" — verify it's a sustained reading first.
- I want to start thinking about **a second ESP32 deployment** (separate
  zone of the yard, or front yard) — haven't designed that yet.
- I want a **mobile-friendly dashboard view** of the server. Currently the
  dashboard at `:5125` is desktop-only. Maybe a small companion view, or a
  Home Assistant integration, or just a better-styled mobile route.

---

## Known false starts / stale references — ignore

- **Pushover** — used briefly, replaced by ntfy. If something old says
  Pushover, it's stale.
- **OTA-as-the-deploy-path** — abandoned. USB-only.
- **Throttling WiFi TX to 8.5 dBm** — undone, made things worse.

---

## What to ask me when I start a new conversation

If I open with something like "the watering didn't run last night" or
"chip is offline" — before guessing, ask:
1. Did I just re-deploy outside, or is it still the indoor soak?
2. Latest output from the health probe (status JSON)?
3. Any ntfy alerts in the last 24h?
4. Did anything change on my home network (Eero firmware update,
   Ziply outage, new device)?

For hardware questions, ask what's actually on hand vs. on order — the
parts list above is the source of truth but I might have ordered more
since 2026-04-22.

---

End of brief. Reply with "Got it — Smart Garden context loaded" so I know
you read it, then wait for my actual question.
