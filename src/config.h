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

// L298N H-Bridge control pins (2 GPIOs per valve)
// Board 1: Valves 1 & 2
#define VALVE1_IN1     25
#define VALVE1_IN2     26
#define VALVE2_IN1     27
#define VALVE2_IN2     14

// Board 2: Valves 3 & 4
#define VALVE3_IN1     16
#define VALVE3_IN2     17
#define VALVE4_IN1     18
#define VALVE4_IN2     19

// Board 3: Valves 5 & 6
#define VALVE5_IN1     21
#define VALVE5_IN2     22
#define VALVE6_IN1     23
#define VALVE6_IN2     13

// Board 4: Valve 7
#define VALVE7_IN1     5
#define VALVE7_IN2     15

// ============================================================
// System Settings
// ============================================================
#define NUM_VALVES         7
#define NUM_SOIL_SENSORS   4
#define VALVE_PULSE_MS     100   // How long to pulse the solenoid (ms)
#define SENSOR_READ_INTERVAL_MS  60000  // Read sensors every 60 seconds
#define WEB_SERVER_PORT    80

// ============================================================
// Telemetry Settings
// ============================================================
#define EVENT_RING_SIZE    100   // Max valve/system events kept in memory
#define NVS_NAMESPACE      "smartgarden"  // Non-volatile storage namespace

// ============================================================
// Power Management
// ============================================================
#define BOOT_CPU_MHZ          80    // CPU freq during boot (lower = less current draw)
#define RUN_CPU_MHZ           240   // CPU freq after WiFi connects (full speed)
#define SAFE_MODE_THRESHOLD   20    // Consecutive crashes before entering safe mode (bumped from 5: TWDT now catches real hangs; safe mode shouldn't trip on transient brownouts)
#define SAFE_MODE_DELAY_SEC   15    // Extra stabilization delay in safe mode
#define WIFI_TX_DBM           WIFI_POWER_8_5dBm  // Reduced TX power (default is 19.5dBm)

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
