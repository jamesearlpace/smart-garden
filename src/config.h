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
// Each valve specifies useMCP flag — allows mixed MCP/GPIO at any position.

// Board 3: Valves 1 & 2 (PB0-PB3)
#define VALVE1_IN1     8   // PB0
#define VALVE1_IN2     9   // PB1
#define VALVE2_IN1     11  // PB3 (swapped — physically reversed wiring)
#define VALVE2_IN2     10  // PB2

// Board 4: Valves 3 & 4 (PB4-PB7)
#define VALVE3_IN1     12  // PB4
#define VALVE3_IN2     13  // PB5
#define VALVE4_IN1     15  // PB7 (swapped — physically reversed wiring)
#define VALVE4_IN2     14  // PB6

// Valve 5 = was valve 9 (ESP32 GPIO — board 5)
#define VALVE5_IN1     25  // ESP32 GPIO 25
#define VALVE5_IN2     26  // ESP32 GPIO 26
#define VALVE5_MCP     false

// Valve 6 = was valve 5 (MCP PA0-PA1 — board 1)
#define VALVE6_IN1     0   // PA0
#define VALVE6_IN2     1   // PA1
#define VALVE6_MCP     true

// Valve 7 = was valve 8 (MCP PA7/PA6 swapped — board 2)
#define VALVE7_IN1     7   // PA7 (swapped — wires reversed)
#define VALVE7_IN2     6   // PA6
#define VALVE7_MCP     true

// Valve 8 = was valve 7 (MCP PA4-PA5 — board 2)
#define VALVE8_IN1     4   // PA4
#define VALVE8_IN2     5   // PA5
#define VALVE8_MCP     true

// Valve 9 = was valve 6 (MCP PA3/PA2 swapped — board 1)
#define VALVE9_IN1     3   // PA3 (swapped — wires reversed)
#define VALVE9_IN2     2   // PA2
#define VALVE9_MCP     true

// Board 5: Valve 10 — direct ESP32 GPIO (spare)
#define VALVE10_IN1    27  // ESP32 GPIO 27
#define VALVE10_IN2    14  // ESP32 GPIO 14

// Power gate (P-FET via NPN level shifter): HIGH = L298Ns powered, LOW = idle.
// GPIO 2 is also onboard LED -> visual indicator. Strapping pin defaults LOW
// at boot, which is the safe state (gate OFF).
#define POWER_GATE_PIN     2
#define GATE_SETTLE_MS     5     // Settle time after enabling 12V before pulsing valve

// Battery voltage divider on GPIO 36 (VP).
// Calibrated 2026-05-27: Wanderer LVD trips at 11.1V, last ADC reading was 10.6V
// with ratio 6.0 → true ratio = 6.0 * (11.1/10.6) = 6.283. Verify with multimeter.
#define BATTERY_ADC_PIN          36
#define BATTERY_DIVIDER_RATIO    6.283f

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
#define SENSOR_READ_INTERVAL_MS  3600000  // Read sensors every 60 minutes (hourly voltage report)

// ============================================================
// Light Sleep — power saving between activity
// ============================================================
#define WIFI_MODEM_SLEEP_ENABLED  true    // WiFi radio sleeps between DTIM beacons (~30-50 mA savings)
// NOTE: CPU light sleep (esp_light_sleep_start) is DISABLED — causes Eero deauth.
// #define LIGHT_SLEEP_ENABLED   false
#define LIGHT_SLEEP_INTERVAL_MS  100     // (unused — light sleep disabled)
#define AWAKE_HOLD_MS            300000  // Stay fully awake 5 min after last API hit (for calibration)
#define AWAKE_HOLD_VALVE_MS      60000   // Stay awake 60s after last valve close
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
#define RUN_CPU_MHZ           160   // CPU freq after WiFi connects (160 saves ~15% power vs 240, still fast enough for WiFi + web server)
#define SAFE_MODE_THRESHOLD   20    // Consecutive crashes before entering safe mode (bumped from 5: TWDT now catches real hangs; safe mode shouldn't trip on transient brownouts)
#define SAFE_MODE_DELAY_SEC   15    // Extra stabilization delay in safe mode
#define WIFI_TX_DBM           WIFI_POWER_19_5dBm  // TX power after WiFi connects (full range for reliability)
#define WIFI_BOOT_TX_DBM      WIFI_POWER_8_5dBm   // TX power during boot (low current to prevent brownout on buck converter)

// Adaptive TX power — lower TX when signal is strong, raise when weak.
// Saves ~30-60 mA at low power vs max power. Checked every 30s in loop().
// Hysteresis band prevents oscillation (must cross both thresholds to change).
#define ADAPTIVE_TX_ENABLED       true
#define ADAPTIVE_TX_INTERVAL_MS   30000              // How often to evaluate (30s)
#define ADAPTIVE_TX_RSSI_STRONG   -50                // RSSI above this → step down TX
#define ADAPTIVE_TX_RSSI_WEAK     -65                // RSSI below this → step up TX
// Between -50 and -65 → hold current level (hysteresis dead zone)
// Power ladder (low to high). ESP-IDF silently caps to regulatory max.
#define ADAPTIVE_TX_LEVELS        4
static const wifi_power_t ADAPTIVE_TX_LADDER[] = {
    WIFI_POWER_8_5dBm,    // ~8.5 dBm  — minimal, fine at RSSI > -50
    WIFI_POWER_13dBm,     // ~13 dBm
    WIFI_POWER_17dBm,     // ~17 dBm
    WIFI_POWER_19_5dBm,   // ~19.5 dBm — max, last resort
};

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
