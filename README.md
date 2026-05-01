# Smart Garden ESP32 Firmware

ESP32-based irrigation controller for the Pace family smart garden.

## Hardware
- ESP32-WROOM-32U Dev Board (external antenna, MAC `68:FE:71:0C:BA:98`)
- Waveshare MCP23017 I/O Expansion Board (I2C address 0x27)
- 2.4 GHz external antenna (U.FL/IPEX connector)
- Renogy Wanderer 10A PWM Charge Controller
- ExpertPower 12V 7Ah SLA Battery
- ECO-WORTHY 10W 12V Solar Panel
- LM2596 Buck Converter (12V → 5V)
- IRF4905 P-channel MOSFET + 2N3904 NPN (power gate for L298N boards)
- L298N H-Bridge Motor Drivers (×5)
- Orbit 57861 DC Latching Solenoids (×10 max, 1 wired)
- Capacitive Soil Moisture Sensors (×4 planned, 1 connected)
- DHT22 Temperature & Humidity Sensor
- Decoupling caps: 1000µF + 100nF on 3.3V rail, 1000µF on buck output

## Architecture

### Valve Control
Valves 1-8 are controlled via the MCP23017 I/O expander over I2C (GPIO 21/22).
Valves 9-10 are controlled directly from ESP32 GPIO 25/26 and 27/14.

| Valve | MCP23017 Pin | L298N Board | Zone Name |
|-------|-------------|-------------|-----------|
| 1 | PA0/PA1 | Board 1 Ch A | Garden (drip) |
| 2 | PA2/PA3 | Board 1 Ch B | Grapes (drip) |
| 3 | PA4/PA5 | Board 2 Ch A | Fruit Trees |
| 4 | PA6/PA7 | Board 2 Ch B | South Lawn |
| 5 | PB0/PB1 | Board 3 Ch A | East Lawn |
| 6 | PB2/PB3 | Board 3 Ch B | West/NW Lawn |
| 7 | PB4/PB5 | Board 4 Ch A | NE Lawn |
| 8 | PB6/PB7 | Board 4 Ch B | Peonies (drip) |
| 9 | GPIO 25/26 | Board 5 Ch A | Garden (drip) |
| 10 | GPIO 27/14 | Board 5 Ch B | Spare |

### Power Gate
MOSFET power gate on GPIO 2 controls 12V to all L298N boards.
Boots low TX (8.5 dBm) to prevent brownout, bumps to 19.5 dBm after WiFi connects.

### Sensors
| Sensor | ESP32 Pin |
|--------|-----------|
| DHT22 | GPIO 4 |
| Soil 1 | GPIO 32 |
| Soil 2 | GPIO 33 |
| Soil 3 | GPIO 34 |
| Soil 4 | GPIO 35 |
| Battery voltage (6:1 divider) | GPIO 36 (SVP) |

## Setup

### 1. Install PlatformIO
In VS Code: Extensions → search "PlatformIO IDE" → Install

### 2. Build & Upload
1. Connect ESP32 via USB
2. Open this folder in VS Code
3. PlatformIO will auto-detect the project
4. Click the checkmark (✓) in the bottom toolbar to build
5. Click the arrow (→) to upload to the ESP32

### 3. Configure WiFi
Edit `src/config.h` with your WiFi SSID and password.

### 4. Monitor
Click the plug icon in PlatformIO toolbar, or:
```
pio device monitor --baud 115200
```

## Web Interface
Once powered on and connected to WiFi, open the ESP32's IP address in a browser.
The IP is printed to Serial on boot — check the monitor output.
