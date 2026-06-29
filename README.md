# Smart Garden

Solar-powered ESP32 firmware for a small sprinkler controller. It drives DC
latching solenoid valves, exposes a simple LAN REST API, and includes a few
firmware-level safety checks so a scheduler bug cannot leave water running
forever.

This repo is the public reference version: enough to build your own controller,
without personal network settings, zone maps, logs, or deployment data.

![Wiring overview](docs/wiring-diagram.svg)

## What It Does

- Controls up to 10 DC latching sprinkler valves.
- Uses an MCP23017 I/O expander plus L298N H-bridge boards.
- Runs from a 12 V battery and solar charge controller.
- Provides local endpoints for status, valve open/close, close-all, events, and
  reboot.
- Falls back to a conservative schedule if the external scheduler stops polling.
- Force-closes any valve that exceeds the firmware runtime cap.

## Hardware

| Part | Notes |
| --- | --- |
| ESP32-U | ESP32 board with an external antenna connector. |
| MCP23017 | I2C I/O expander for additional valve-control pins. |
| L298N H-bridges | One board per two DC latching valves. |
| DC latching solenoids | Pulse open, pulse close, no holding current. |
| 12 V battery + solar panel | Keeps the controller independent from mains power. |

## Quick Start

```bash
git clone https://github.com/jamesearlpace/smart-garden.git
cd smart-garden
cp src/config.h.example src/config.h
```

Edit `src/config.h` with your WiFi, local IP settings, dashboard URL, and reboot
token. Then build and upload with PlatformIO:

```bash
pio run -t upload
pio device monitor
```

`src/config.h` is ignored by git. Keep WiFi credentials, local IP addresses, and
tokens out of the repo.

## REST API

| Endpoint | Method | Purpose |
| --- | --- | --- |
| `/api/status` | GET | Controller status, valve state, battery, RSSI, uptime. |
| `/api/valve?n=3&action=open` | GET | Open one valve. |
| `/api/valve?n=3&action=close` | GET | Close one valve. |
| `/api/closeall` | GET | Close every valve. |
| `/api/events` | GET | Recent controller events. |
| `/api/reboot?token=...` | POST | Soft reboot with a shared token. |

## Why Latching Valves

Standard irrigation valves need continuous power while open. DC latching valves
only need short open/close pulses, which makes a battery and solar design much
more practical.

## License

MIT
