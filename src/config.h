#ifndef CONFIG_H
#define CONFIG_H

#include <IPAddress.h>  // For static IP configuration

// ============================================================
// WiFi Configuration — EDIT THESE
// ============================================================
const char* WIFI_SSID     = "TellMyWifiLoveHer";
const char* WIFI_PASSWORD  = "keepingpace";

// Static IP configuration (prevents DHCP from reassigning)
#define USE_STATIC_IP true
IPAddress STATIC_IP(192, 168, 0, 150);
IPAddress GATEWAY(192, 168, 0, 1);
IPAddress SUBNET(255, 255, 255, 0);
IPAddress DNS1(192, 168, 0, 1);

// ============================================================
// MQTT Configuration (optional — for Home Assistant / Node-RED)
// Leave MQTT_ENABLED false if you just want the web interface
// ============================================================
#define MQTT_ENABLED false
const char* MQTT_SERVER   = "192.168.1.100";  // Your MQTT broker IP
const int   MQTT_PORT     = 1883;
const char* MQTT_USER     = "";               // Leave empty if no auth
const char* MQTT_PASS     = "";

// ============================================================
// Pin Assignments — match the wiring guide
// ============================================================

// Soil moisture sensors (analog input)
#define SOIL_SENSOR_1  32  // Zone 1 - Garden
#define SOIL_SENSOR_2  33  // Zone 2 - Grapes
#define SOIL_SENSOR_3  34  // Zone 3 - Fruit trees
#define SOIL_SENSOR_4  35  // Zone 4 - South lawn

// DHT22 temperature & humidity
#define DHT_PIN        4
#define DHT_TYPE       DHT22

// L298N H-Bridge control pins — ALL on MCP23017 I/O expander
// Pin numbers are MCP23017 pin numbers (0-15): PA0-PA7 = 0-7, PB0-PB7 = 8-15
// Board 1: Valves 1 & 2 (PA0-PA3)
#define VALVE1_IN1     0   // PA0
#define VALVE1_IN2     1   // PA1
#define VALVE2_IN1     2   // PA2
#define VALVE2_IN2     3   // PA3

// Board 2: Valves 3 & 4 (PA4-PA7)
#define VALVE3_IN1     4   // PA4
#define VALVE3_IN2     5   // PA5
#define VALVE4_IN1     6   // PA6
#define VALVE4_IN2     7   // PA7

// Board 3: Valves 5 & 6 (PB0-PB3)
#define VALVE5_IN1     8   // PB0
#define VALVE5_IN2     9   // PB1
#define VALVE6_IN1     10  // PB2
#define VALVE6_IN2     11  // PB3

// Board 4: Valves 7 & 8 (PB4-PB7)
#define VALVE7_IN1     12  // PB4
#define VALVE7_IN2     13  // PB5
#define VALVE8_IN1     14  // PB6
#define VALVE8_IN2     15  // PB7

// Board 5: Valves 9 & 10 — direct ESP32 GPIOs (MCP23017 full)
#define VALVE9_IN1     25  // ESP32 GPIO 25
#define VALVE9_IN2     26  // ESP32 GPIO 26
#define VALVE10_IN1    27  // ESP32 GPIO 27
#define VALVE10_IN2    14  // ESP32 GPIO 14
#define VALVES_ON_MCP  8   // first 8 valves use MCP23017, rest use ESP32 GPIO

// Power gate (P-FET via NPN level shifter): HIGH = L298Ns powered, LOW = idle.
// GPIO 2 is also onboard LED -> visual indicator. Strapping pin defaults LOW
// at boot, which is the safe state (gate OFF).
#define POWER_GATE_PIN     2
#define GATE_SETTLE_MS     5     // Settle time after enabling 12V before pulsing valve

// Battery voltage divider: 5x10k (R1=50k) + 1x10k (R2) on GPIO 36 (VP).
// Ratio 6 -> 12.7V battery reads 2.12V, 14.4V reads 2.40V (within ADC range).
#define BATTERY_ADC_PIN          36
#define BATTERY_DIVIDER_RATIO    6.0f

// ============================================================
// System Settings
// ============================================================
#define NUM_VALVES         10
#define NUM_SOIL_SENSORS   4

// MCP23017 I/O expander — valves 1-8 on expander, address 0x27
#define MCP23017_ADDR      0x27
#define MCP_SDA_PIN        21
#define MCP_SCL_PIN        22
#define VALVE_PULSE_MS     100   // How long to pulse the solenoid (ms)
#define SENSOR_READ_INTERVAL_MS  60000  // Read sensors every 60 seconds
#define WEB_SERVER_PORT    80

// ============================================================
// Telemetry Settings
// ============================================================
#define EVENT_RING_SIZE    100   // Max valve/system events kept in memory
#define NVS_NAMESPACE      "smartgarden"  // Non-volatile storage namespace

// ============================================================
// API Auth — shared secret for state-changing endpoints
// ============================================================
// Required as ?token=... on /api/reboot. Anyone on the LAN could otherwise
// reboot the chip with a single curl. Not high-value security (LAN is
// trusted-ish), but stops accidental reboots from scripts/scans.
// To rotate: change here, OTA flash, update any callers (server doesn't
// call /api/reboot; this is for manual curl from your laptop).
#define API_REBOOT_TOKEN   "garden-reboot-9847"

// ============================================================
// Power Management
// ============================================================
#define BOOT_CPU_MHZ          80    // CPU freq during boot (lower = less current draw)
#define RUN_CPU_MHZ           240   // CPU freq after WiFi connects (full speed)
#define SAFE_MODE_THRESHOLD   20    // Consecutive crashes before entering safe mode (bumped from 5: TWDT now catches real hangs; safe mode shouldn't trip on transient brownouts)
#define SAFE_MODE_DELAY_SEC   15    // Extra stabilization delay in safe mode
#define WIFI_TX_DBM           WIFI_POWER_19_5dBm  // TX power after WiFi connects (full range for reliability)
#define WIFI_BOOT_TX_DBM      WIFI_POWER_8_5dBm   // TX power during boot (low current to prevent brownout on buck converter)

// ============================================================
// Reliability — task watchdog + scheduled reboot
// ============================================================
#define TWDT_TIMEOUT_S        60    // Task watchdog timeout (must exceed longest blocking op, incl. OTA chunk)
#define WEEKLY_REBOOT_HOURS   168   // Scheduled "spring cleaning" reboot interval (0 = disabled)
#define WEEKLY_REBOOT_HOUR    3     // Local hour-of-day to perform reboot (only fires when uptime >= WEEKLY_REBOOT_HOURS)

// Independent firmware-side max valve runtime. Protects against server crash,
// lost close-ACK, dead Mint server, network partition. If a valve is open
// longer than this, ESP32 force-closes it regardless of who told it to open.
// Must exceed longest legitimate watering duration (server hard cap is 90 min).
#define VALVE_HARD_MAX_MS     (95UL * 60UL * 1000UL)   // 95 minutes

// ============================================================
// Fallback watering schedule — fires when Mint server has been silent
// for FALLBACK_SERVER_SILENT_HOURS+ hours. Lets the yard survive total
// loss of the scheduler service (server crash, network partition, vacation).
// Each zone runs every intervalHours for durationMin, staggered by offsetHours
// so they don't all run at once. Set intervalHours=0 to disable a zone.
// ============================================================
#define FALLBACK_SERVER_SILENT_HOURS  24

#endif // CONFIG_H
