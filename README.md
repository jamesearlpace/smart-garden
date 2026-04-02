# Smart Garden ESP32 Firmware

ESP32-based irrigation controller for the Pace family smart garden.

## Hardware
- HiLetgo ESP-WROOM-32 Dev Board
- Renogy Wanderer 10A PWM Charge Controller
- ExpertPower 12V 7Ah SLA Battery
- ECO-WORTHY 10W 12V Solar Panel
- LM2596 Buck Converter (12V → 5V)
- L298N H-Bridge Motor Drivers (×4)
- Orbit 57861 DC Latching Solenoids (×7)
- Capacitive Soil Moisture Sensors (×4)
- DHT22 Temperature & Humidity Sensor

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
