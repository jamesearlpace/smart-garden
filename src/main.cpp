/*
 * Smart Garden Controller — ESP32 Firmware
 * 
 * Controls 7 DC latching solenoid valves via L298N H-bridges,
 * reads soil moisture and temperature sensors, serves a web UI
 * for manual control, and optionally publishes to MQTT.
 * 
 * Hardware: HiLetgo ESP-WROOM-32 + L298N + Orbit 57861 solenoids
 * Power: 12V SLA battery + 10W solar panel + Renogy Wanderer
 */

#include <Arduino.h>
#include "soc/soc.h"
#include "soc/rtc_cntl_reg.h"
#include "esp_system.h"  // esp_reset_reason()
#include "esp_sleep.h"   // esp_deep_sleep_start(), esp_light_sleep_start()
#include "esp_wifi.h"    // esp_wifi_set_ps() for light sleep WiFi power save
#include "esp_ota_ops.h" // esp_ota_mark_app_valid_cancel_rollback()
#include "esp_task_wdt.h" // task watchdog timer
#include <WiFi.h>
#include <WebServer.h>
#include <DHT.h>
#include <ArduinoJson.h>
#include <ArduinoOTA.h>
#include <Preferences.h>
#include <Adafruit_MCP23X17.h>
#include "config.h"

#if MQTT_ENABLED
#include <PubSubClient.h>
WiFiClient espClient;
PubSubClient mqtt(espClient);
#endif

// ============================================================
// Telemetry — boot count, event log, valve counters
// ============================================================

// ============================================================
// Power Test Mode — bare minimum firmware for buck converter testing.
// Built with: pio run -e power-test --target upload --upload-port COM3
// No WiFi, no GPIO, no sensors. Just proves the ESP32 can boot.
// ============================================================
#ifdef POWER_TEST_ONLY
void setup() {
    WRITE_PERI_REG(RTC_CNTL_BROWN_OUT_REG, 0);
    setCpuFrequencyMhz(80);  // Minimum current draw
    Serial.begin(115200);
    delay(100);
    Serial.println();
    Serial.println("==========================================");
    Serial.println("  POWER TEST MODE — no WiFi, no GPIO");
    Serial.println("==========================================");
    Serial.printf("  CPU freq: %u MHz\n", getCpuFrequencyMhz());
    Serial.printf("  Reset reason: %d\n", (int)esp_reset_reason());
    Serial.printf("  Free heap: %u / %u bytes\n", ESP.getFreeHeap(), ESP.getHeapSize());
    Serial.printf("  Chip temp: %.1f°C / %.1f°F\n", temperatureRead(), temperatureRead() * 9.0/5.0 + 32.0);
    Serial.printf("  Flash size: %u bytes\n", ESP.getFlashChipSize());
    Serial.printf("  SDK: %s\n", ESP.getSdkVersion());
    Serial.println("==========================================");
    Serial.println("If you see this repeating, the buck converter");
    Serial.println("can't sustain even idle ESP32 power draw.");
    Serial.println("If this is stable, try: pio run -e esp32 --target upload");
    Serial.println("==========================================");
}

void loop() {
    static unsigned long lastPrint = 0;
    static uint32_t heartbeat = 0;
    if (millis() - lastPrint >= 2000) {
        lastPrint = millis();
        heartbeat++;
        Serial.printf("[POWER OK] #%u  uptime=%lus  heap=%u  temp=%.1f°C\n",
            heartbeat, millis() / 1000, ESP.getFreeHeap(), temperatureRead());
    }
}
#else  // Full firmware below
// ============================================================

Preferences nvs;
Adafruit_MCP23X17 mcp;
uint32_t bootCount = 0;
uint32_t crashCount = 0;
bool safeMode = false;
esp_reset_reason_t lastResetReason = ESP_RST_UNKNOWN;
unsigned long bootTimeMillis = 0;  // millis() at boot for uptime calc

// ============================================================
// Fallback watering schedule \u2014 activates when server is silent
// ============================================================
// Updated by every authenticated API hit; "server is alive" signal.
// Initialized to 0 so fallback won't fire until at least one server contact
// (or until uptime exceeds FALLBACK_SERVER_SILENT_HOURS \u2014 see logic in loop).
unsigned long lastServerContactMs = 0;

// Light sleep — tracks last API activity to stay awake during manual control
unsigned long lastApiActivityMs = 0;      // any HTTP request
unsigned long lastValveCloseMs = 0;       // last valve close event

struct FallbackZone {
    uint16_t intervalHours;   // run every N hours; 0 = disabled
    uint16_t durationMin;     // for M minutes
    uint16_t offsetHours;     // initial stagger from boot/activation
};

// Conservative defaults: every zone every 48h, staggered by 1h.
// Survival watering, not optimal \u2014 enough to keep plants alive for weeks.
const FallbackZone FALLBACK_SCHEDULE[NUM_VALVES] = {
    {48, 15, 0},   // Zone 1 - Garden (drip)
    {48, 20, 1},   // Zone 2 - Grapes (drip)
    {48, 25, 2},   // Zone 3 - Fruit Trees
    {48, 12, 3},   // Zone 4 - South Lawn
    {48, 15, 4},   // Zone 5 - East Lawn
    {48, 15, 5},   // Zone 6 - West/NW Lawn
    {48, 15, 6},   // Zone 7 - NE Lawn
    {48, 10, 7},   // Zone 8 - Peonies (drip)
    {48, 15, 8},   // Zone 9 - Garden (drip)
    { 0,  0, 0},   // Zone 10 - Spare (disabled)
};

// Per-zone runtime tracking (not persisted; resets at boot)
unsigned long fallbackLastRunMs[NUM_VALVES] = {0};
unsigned long fallbackCloseAtMs[NUM_VALVES] = {0};  // 0 = no pending close
bool fallbackActive = false;  // true when server has been silent long enough

// Ring buffer for timestamped events
struct Event {
    unsigned long uptimeMs;   // millis() when event occurred
    char type[12];            // "valve", "boot", "wifi", "error"
    char detail[48];          // e.g. "Valve 3 OPENED (api)"
};
Event eventRing[EVENT_RING_SIZE];
int eventHead = 0;    // next write position
int eventCount = 0;   // total events stored

void logEvent(const char* type, const char* detail) {
    Event& e = eventRing[eventHead];
    e.uptimeMs = millis();
    strncpy(e.type, type, sizeof(e.type) - 1);
    e.type[sizeof(e.type) - 1] = '\0';
    strncpy(e.detail, detail, sizeof(e.detail) - 1);
    e.detail[sizeof(e.detail) - 1] = '\0';
    eventHead = (eventHead + 1) % EVENT_RING_SIZE;
    if (eventCount < EVENT_RING_SIZE) eventCount++;
}

// Per-valve actuation counters (persisted in NVS)
uint32_t valveOpenCount[NUM_VALVES] = {0};
uint32_t valveCloseCount[NUM_VALVES] = {0};
unsigned long valveLastOpenedMs[NUM_VALVES] = {0};  // millis() of last open

void saveValveCounters() {
    nvs.begin(NVS_NAMESPACE, false);
    for (int i = 0; i < NUM_VALVES; i++) {
        char keyO[12], keyC[12];
        snprintf(keyO, sizeof(keyO), "vOpen%d", i);
        snprintf(keyC, sizeof(keyC), "vClose%d", i);
        nvs.putUInt(keyO, valveOpenCount[i]);
        nvs.putUInt(keyC, valveCloseCount[i]);
    }
    nvs.end();
}

void loadValveCounters() {
    nvs.begin(NVS_NAMESPACE, true);
    for (int i = 0; i < NUM_VALVES; i++) {
        char keyO[12], keyC[12];
        snprintf(keyO, sizeof(keyO), "vOpen%d", i);
        snprintf(keyC, sizeof(keyC), "vClose%d", i);
        valveOpenCount[i] = nvs.getUInt(keyO, 0);
        valveCloseCount[i] = nvs.getUInt(keyC, 0);
    }
    nvs.end();
}

// WiFi reconnect counter
uint32_t wifiReconnects = 0;

// Adaptive TX power — current ladder index (0 = lowest, ADAPTIVE_TX_LEVELS-1 = max)
int adaptiveTxIndex = ADAPTIVE_TX_LEVELS - 1;  // start at max, let it step down

// ============================================================
// Valve control
// ============================================================
struct Valve {
    uint8_t in1;
    uint8_t in2;
    bool isOpen;
    bool useMCP;       // true = MCP23017 I/O expander, false = direct ESP32 GPIO
    const char* name;
};

// Power gate: NPN/P-FET cascade. GPIO HIGH -> NPN on -> P-FET on -> 12V to L298Ns.
// Default LOW = L298Ns unpowered (saves 25-50 mA idle).
static inline void enableDriverPower() {
    digitalWrite(POWER_GATE_PIN, HIGH);
    delay(GATE_SETTLE_MS);
}
static inline void disableDriverPower() {
    digitalWrite(POWER_GATE_PIN, LOW);
}

// Read battery voltage via divider on GPIO 36. Ratio calibrated from LVD trip point.
// Averages 8 samples to denoise. Returns volts.
// IMPORTANT: only call from the main loop task. ADC1 is shared with soil pins;
// concurrent reads from the web server task can wedge the WebServer handler.
float readBatteryVoltage() {
    uint32_t acc = 0;
    for (int i = 0; i < 8; i++) acc += analogRead(BATTERY_ADC_PIN);
    float raw = acc / 8.0f;
    return raw * (3.3f / 4095.0f) * BATTERY_DIVIDER_RATIO;
}

// Cached battery voltage updated in readSensors(). HTTP handler reads this
// instead of calling readBatteryVoltage() directly (avoids ADC contention).
volatile float cachedBatteryV = 0.0f;

Valve valves[NUM_VALVES] = {
    //  in1            in2            open   MCP?   name
    {VALVE1_IN1,  VALVE1_IN2,  false, true,  "Zone 1"},
    {VALVE2_IN1,  VALVE2_IN2,  false, true,  "Zone 2"},
    {VALVE3_IN1,  VALVE3_IN2,  false, true,  "Zone 3"},
    {VALVE4_IN1,  VALVE4_IN2,  false, true,  "Zone 4"},
    {VALVE5_IN1,  VALVE5_IN2,  false, VALVE5_MCP, "Zone 5"},
    {VALVE6_IN1,  VALVE6_IN2,  false, VALVE6_MCP, "Zone 6"},
    {VALVE7_IN1,  VALVE7_IN2,  false, VALVE7_MCP, "Zone 7"},
    {VALVE8_IN1,  VALVE8_IN2,  false, VALVE8_MCP, "Zone 8"},
    {VALVE9_IN1,  VALVE9_IN2,  false, VALVE9_MCP, "Zone 9"},
    {VALVE10_IN1, VALVE10_IN2, false, false, "Zone 10"},
};

void openValve(int idx) {
    if (idx < 0 || idx >= NUM_VALVES) return;
    Valve& v = valves[idx];
    enableDriverPower();
    if (v.useMCP) {
        mcp.digitalWrite(v.in1, HIGH);
        mcp.digitalWrite(v.in2, LOW);
        delay(VALVE_PULSE_MS);
        mcp.digitalWrite(v.in1, LOW);
        mcp.digitalWrite(v.in2, LOW);
    } else {
        digitalWrite(v.in1, HIGH);
        digitalWrite(v.in2, LOW);
        delay(VALVE_PULSE_MS);
        digitalWrite(v.in1, LOW);
        digitalWrite(v.in2, LOW);
    }
    disableDriverPower();
    v.isOpen = true;
    valveOpenCount[idx]++;
    valveLastOpenedMs[idx] = millis();
    Serial.printf("Valve %d OPENED (%s) [total: %u]\n", idx + 1, v.name, valveOpenCount[idx]);
    char detail[48];
    snprintf(detail, sizeof(detail), "Valve %d OPENED (%s)", idx + 1, v.name);
    logEvent("valve", detail);
}

void closeValve(int idx) {
    if (idx < 0 || idx >= NUM_VALVES) return;
    Valve& v = valves[idx];
    // Calculate how long the valve was open
    unsigned long durationSec = 0;
    if (v.isOpen && valveLastOpenedMs[idx] > 0) {
        durationSec = (millis() - valveLastOpenedMs[idx]) / 1000;
    }
    enableDriverPower();
    if (v.useMCP) {
        mcp.digitalWrite(v.in1, LOW);
        mcp.digitalWrite(v.in2, HIGH);
        delay(VALVE_PULSE_MS);
        mcp.digitalWrite(v.in1, LOW);
        mcp.digitalWrite(v.in2, LOW);
    } else {
        digitalWrite(v.in1, LOW);
        digitalWrite(v.in2, HIGH);
        delay(VALVE_PULSE_MS);
        digitalWrite(v.in1, LOW);
        digitalWrite(v.in2, LOW);
    }
    disableDriverPower();
    v.isOpen = false;
    valveCloseCount[idx]++;
    lastValveCloseMs = millis();  // light sleep: stay awake briefly after valve activity
    Serial.printf("Valve %d CLOSED (%s) [total: %u, was open %lus]\n", idx + 1, v.name, valveCloseCount[idx], durationSec);
    char detail[48];
    snprintf(detail, sizeof(detail), "Valve %d CLOSED (%lus open)", idx + 1, durationSec);
    logEvent("valve", detail);
    saveValveCounters();  // Persist to NVS
}

void closeAllValves() {
    for (int i = 0; i < NUM_VALVES; i++) {
        closeValve(i);
    }
}

// ============================================================
// Sensors
// ============================================================
DHT dht(DHT_PIN, DHT_TYPE);

const uint8_t soilPins[NUM_SOIL_SENSORS] = {
    SOIL_SENSOR_1, SOIL_SENSOR_2, SOIL_SENSOR_3, SOIL_SENSOR_4
};
const char* soilNames[NUM_SOIL_SENSORS] = {
    "Garden", "Grapes", "Fruit Trees", "South Lawn"
};

float temperature = 0;
float humidity = 0;
int soilValues[NUM_SOIL_SENSORS] = {0};
int soilPercent[NUM_SOIL_SENSORS] = {0};
unsigned long lastSensorRead = 0;

// Calibration values for capacitive soil moisture sensor
// Dry air = ~3500-4095, Fully wet = ~1200-1800
// Adjust after testing YOUR sensors
#define SOIL_DRY   3500
#define SOIL_WET   1500

int soilToPercent(int raw) {
    int pct = map(raw, SOIL_DRY, SOIL_WET, 0, 100);
    return constrain(pct, 0, 100);
}

void readSensors() {
    temperature = dht.readTemperature(true);  // Fahrenheit
    humidity = dht.readHumidity();

    for (int i = 0; i < NUM_SOIL_SENSORS; i++) {
        soilValues[i] = analogRead(soilPins[i]);
        soilPercent[i] = soilToPercent(soilValues[i]);
    }

    // Sample battery voltage in the same task to avoid ADC1 contention with HTTP handler
    cachedBatteryV = readBatteryVoltage();

    Serial.printf("Temp: %.1f°F  Humidity: %.1f%%\n", temperature, humidity);
    for (int i = 0; i < NUM_SOIL_SENSORS; i++) {
        Serial.printf("Soil %d (%s): raw=%d  moisture=%d%%\n",
                       i + 1, soilNames[i], soilValues[i], soilPercent[i]);
    }
}

// ============================================================
// Web Server
// ============================================================
WebServer server(WEB_SERVER_PORT);

// Redirect to the real dashboard on the Acer home server.
// The ESP32 only serves the REST API — the UI lives at http://192.168.0.109:5125
void handleRoot() {
    String html = R"rawliteral(
<!DOCTYPE html>
<html>
<head>
    <meta http-equiv="refresh" content="0;url=http://192.168.0.109:5125">
    <title>Smart Garden</title>
</head>
<body style="font-family:sans-serif;background:#1a1a2e;color:#eee;display:flex;align-items:center;justify-content:center;height:100vh;margin:0">
    <div style="text-align:center">
        <p>Redirecting to <a href="http://192.168.0.109:5125" style="color:#4ecca3">Smart Garden Dashboard</a>...</p>
        <p style="font-size:12px;color:#666;margin-top:20px">ESP32 API available at /api/status, /api/valve, /api/closeall, /api/events</p>
    </div>
</body>
</html>
)rawliteral";
    server.send(200, "text/html", html);
}

// API: Get system status as JSON
void handleApiStatus() {
    lastServerContactMs = millis();  // server heartbeat
    // NOTE: Do NOT set lastApiActivityMs here — status polls should not
    // prevent light sleep. Only state-changing commands (valve, closeall,
    // reboot) keep the chip fully awake. The chip wakes from light sleep
    // to serve this request (~50ms), then goes back to sleep.
    JsonDocument doc;
    doc["temp"] = isnan(temperature) ? 0 : temperature;
    doc["hum"] = isnan(humidity) ? 0 : humidity;

    JsonArray soilArr = doc["soil"].to<JsonArray>();
    for (int i = 0; i < NUM_SOIL_SENSORS; i++) {
        JsonObject s = soilArr.add<JsonObject>();
        s["name"] = soilNames[i];
        s["raw"] = soilValues[i];
        s["pct"] = soilPercent[i];
    }

    JsonArray valveArr = doc["valves"].to<JsonArray>();
    for (int i = 0; i < NUM_VALVES; i++) {
        JsonObject v = valveArr.add<JsonObject>();
        v["name"] = valves[i].name;
        v["open"] = valves[i].isOpen;
        v["openCount"] = valveOpenCount[i];
        v["closeCount"] = valveCloseCount[i];
        // If valve is currently open, show how long
        if (valves[i].isOpen && valveLastOpenedMs[i] > 0) {
            v["openForSec"] = (millis() - valveLastOpenedMs[i]) / 1000;
        }
    }

    // System telemetry
    JsonObject sys = doc["system"].to<JsonObject>();
    sys["uptimeSec"] = millis() / 1000;
    sys["uptimeHours"] = (float)(millis() / 1000) / 3600.0;
    sys["bootCount"] = bootCount;
    sys["freeHeap"] = ESP.getFreeHeap();
    sys["totalHeap"] = ESP.getHeapSize();
    sys["heapPct"] = (int)(100.0 * ESP.getFreeHeap() / ESP.getHeapSize());
    sys["chipTempC"] = temperatureRead();
    sys["chipTempF"] = temperatureRead() * 9.0 / 5.0 + 32.0;
    sys["batteryV"] = cachedBatteryV;
    sys["wifiRSSI"] = WiFi.RSSI();
    sys["wifiReconnects"] = wifiReconnects;
    sys["txPowerRaw"] = (int)WiFi.getTxPower();  // [#6] runtime regulatory cap, varies between boots
    sys["txAdaptiveLevel"] = adaptiveTxIndex;     // 0=lowest, ADAPTIVE_TX_LEVELS-1=max
    sys["ip"] = WiFi.localIP().toString();
    sys["mac"] = WiFi.macAddress();
    sys["eventCount"] = eventCount;

    // Health insights
    JsonObject health = doc["health"].to<JsonObject>();
    health["crashCount"] = crashCount;
    health["safeMode"] = safeMode;
    health["resetReason"] = (int)lastResetReason;
    const char* resetNames[] = {"Unknown","PowerOn","EXT","SW","Panic","IntWDT","TaskWDT","WDT","DeepSleep","Brownout","SDIO"};
    int ri = (int)lastResetReason;
    health["resetReasonName"] = (ri >= 0 && ri <= 10) ? resetNames[ri] : "Other";
    health["deepSleepThreshold"] = SAFE_MODE_THRESHOLD * 2;
    health["safeModeThreshold"] = SAFE_MODE_THRESHOLD;
    // Valve health: detect crash-loop evidence (close count >> open count)
    int totalOpens = 0, totalCloses = 0;
    for (int i = 0; i < NUM_VALVES; i++) { totalOpens += valveOpenCount[i]; totalCloses += valveCloseCount[i]; }
    health["totalValveOpens"] = totalOpens;
    health["totalValveCloses"] = totalCloses;
    health["valveCloseOpenRatio"] = totalOpens > 0 ? (float)totalCloses / totalOpens : 0;
    health["crashLoopEvidence"] = (totalCloses > totalOpens * 3 && bootCount > 100);

    // Fallback schedule status
    JsonObject fb = doc["fallback"].to<JsonObject>();
    fb["active"] = fallbackActive;
    fb["serverSilentSec"] = lastServerContactMs > 0 ? (millis() - lastServerContactMs) / 1000 : -1;
    fb["silenceThresholdSec"] = FALLBACK_SERVER_SILENT_HOURS * 3600;
    JsonArray fbZones = fb["zones"].to<JsonArray>();
    for (int i = 0; i < NUM_VALVES; i++) {
        JsonObject z = fbZones.add<JsonObject>();
        z["intervalHours"] = FALLBACK_SCHEDULE[i].intervalHours;
        z["durationMin"] = FALLBACK_SCHEDULE[i].durationMin;
        z["lastRunSec"] = fallbackLastRunMs[i] > 0 ? (millis() - fallbackLastRunMs[i]) / 1000 : -1;
    }

    String json;
    serializeJson(doc, json);
    server.send(200, "application/json", json);
}

// API: Open or close a single valve
void handleApiValve() {
    lastServerContactMs = millis();  // server heartbeat
    lastApiActivityMs = millis();    // keep awake for manual control
    if (!server.hasArg("id") || !server.hasArg("action")) {
        server.send(400, "text/plain", "Missing id or action");
        return;
    }
    int id = server.arg("id").toInt();
    String action = server.arg("action");

    if (id < 0 || id >= NUM_VALVES) {
        server.send(400, "text/plain", "Invalid valve id");
        return;
    }

    if (action == "open") {
        openValve(id);
    } else if (action == "close") {
        closeValve(id);
    } else {
        server.send(400, "text/plain", "Invalid action");
        return;
    }
    server.send(200, "text/plain", "OK");
}

// API: Close all valves
void handleApiCloseAll() {
    lastServerContactMs = millis();  // server heartbeat
    lastApiActivityMs = millis();    // keep awake for manual control
    closeAllValves();
    server.send(200, "text/plain", "All valves closed");
}

// API: Remote reboot. POST /api/reboot?token=...              -> soft reboot
//                    POST /api/reboot?token=...&clear=1       -> reset crash counter, then reboot
// Lets us recover from safe-mode without USB access.
// Token check prevents accidental reboots from LAN scanners / mistyped curls.
void handleApiReboot() {
    lastServerContactMs = millis();  // server heartbeat
    lastApiActivityMs = millis();    // keep awake for manual control
    if (server.arg("token") != API_REBOOT_TOKEN) {
        server.send(401, "text/plain", "unauthorized");
        return;
    }
    bool clearCrash = (server.arg("clear") == "1");
    if (clearCrash) {
        nvs.begin(NVS_NAMESPACE, false);
        nvs.putUInt("crashCnt", 0);
        nvs.end();
        Serial.println("[REBOOT] Crash counter cleared via API");
    }
    closeAllValves();  // safe state before restart
    logEvent("reboot", clearCrash ? "api (cleared)" : "api");
    String msg = clearCrash ? "Rebooting (crash counter cleared)" : "Rebooting";
    server.send(200, "text/plain", msg);
    delay(500);  // let the response flush
    ESP.restart();
}

// API: Get event log as JSON array (newest first)
void handleApiEvents() {
    JsonDocument doc;
    JsonArray arr = doc.to<JsonArray>();

    // Walk the ring buffer from newest to oldest
    for (int i = 0; i < eventCount; i++) {
        int idx = (eventHead - 1 - i + EVENT_RING_SIZE) % EVENT_RING_SIZE;
        JsonObject e = arr.add<JsonObject>();
        e["uptimeSec"] = eventRing[idx].uptimeMs / 1000;
        e["type"] = eventRing[idx].type;
        e["detail"] = eventRing[idx].detail;
    }

    String json;
    serializeJson(doc, json);
    server.send(200, "application/json", json);
}

// API: Scan all ADC1 pins to find connected sensors
void handleApiScan() {
    const int adcPins[] = {32, 33, 34, 35, 36, 39};
    const int numPins = 6;
    JsonDocument doc;
    JsonArray arr = doc["pins"].to<JsonArray>();
    for (int i = 0; i < numPins; i++) {
        JsonObject pin = arr.add<JsonObject>();
        pin["gpio"] = adcPins[i];
        pin["raw"] = analogRead(adcPins[i]);
    }
    String json;
    serializeJson(doc, json);
    server.send(200, "application/json", json);
}

// API: Get valve lifetime statistics
void handleApiValveStats() {
    JsonDocument doc;
    JsonArray arr = doc["valves"].to<JsonArray>();
    for (int i = 0; i < NUM_VALVES; i++) {
        JsonObject v = arr.add<JsonObject>();
        v["id"] = i;
        v["name"] = valves[i].name;
        v["openCount"] = valveOpenCount[i];
        v["closeCount"] = valveCloseCount[i];
        v["isOpen"] = valves[i].isOpen;
        if (valves[i].isOpen && valveLastOpenedMs[i] > 0) {
            v["currentOpenSec"] = (millis() - valveLastOpenedMs[i]) / 1000;
        }
    }
    doc["bootCount"] = bootCount;
    doc["uptimeSec"] = millis() / 1000;

    String json;
    serializeJson(doc, json);
    server.send(200, "application/json", json);
}

// ============================================================
// MQTT (optional)
// ============================================================
#if MQTT_ENABLED
void mqttReconnect() {
    if (mqtt.connected()) return;
    Serial.print("MQTT connecting...");
    String clientId = "smart-garden-" + String(random(0xffff), HEX);
    if (mqtt.connect(clientId.c_str(), MQTT_USER, MQTT_PASS)) {
        Serial.println("connected");
        mqtt.subscribe("garden/valve/+/set");
    } else {
        Serial.printf("failed (rc=%d)\n", mqtt.state());
    }
}

void mqttCallback(char* topic, byte* payload, unsigned int length) {
    String msg;
    for (unsigned int i = 0; i < length; i++) msg += (char)payload[i];

    // Topic format: garden/valve/0/set  (payload: "open" or "close")
    String t = String(topic);
    int slashIdx = t.indexOf("/valve/");
    if (slashIdx < 0) return;
    int valveIdx = t.substring(slashIdx + 7, t.indexOf("/set")).toInt();

    if (msg == "open") openValve(valveIdx);
    else if (msg == "close") closeValve(valveIdx);
}

void mqttPublishStatus() {
    if (!mqtt.connected()) return;

    JsonDocument doc;
    doc["temp"] = isnan(temperature) ? 0 : temperature;
    doc["hum"] = isnan(humidity) ? 0 : humidity;
    for (int i = 0; i < NUM_SOIL_SENSORS; i++) {
        doc["soil"][i] = soilPercent[i];
    }
    for (int i = 0; i < NUM_VALVES; i++) {
        doc["valve"][i] = valves[i].isOpen ? 1 : 0;
    }
    String json;
    serializeJson(doc, json);
    mqtt.publish("garden/status", json.c_str());
}
#endif

// ============================================================
// WiFi Setup
// ============================================================
void setupWiFi() {
    Serial.printf("Connecting to WiFi: %s", WIFI_SSID);
    WiFi.mode(WIFI_STA);

    #if USE_STATIC_IP
    WiFi.config(STATIC_IP, GATEWAY, SUBNET, DNS1);
    Serial.printf(" (static IP: %s)", STATIC_IP.toString().c_str());
    #endif

    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
    bool txOk = WiFi.setTxPower(WIFI_BOOT_TX_DBM);  // Boot at low TX to prevent brownout on buck converter
    int txRaw = (int)WiFi.getTxPower();
    Serial.printf(" (boot TX: %.1f dBm, raw=%d, setter=%s) [low-boot strategy]\n",
                  txRaw / 4.0, txRaw, txOk ? "true" : "false");
    WiFi.setAutoReconnect(true);
    WiFi.persistent(true);

    int attempts = 0;
    while (WiFi.status() != WL_CONNECTED && attempts < 40) {
        delay(500);
        Serial.print(".");
        attempts++;
        // At halfway point, bump to full TX — if low-boot TX can't reach the AP,
        // full power might. Brownout risk is lower after 10s of stable runtime.
        if (attempts == 20) {
            WiFi.setTxPower(WIFI_TX_DBM);
            Serial.print("[TX bump mid-connect]");
        }
    }

    if (WiFi.status() == WL_CONNECTED) {
        WiFi.setSleep(false);  // Disable modem sleep during initial connect — re-enabled
                               // by light sleep path when idle (esp_wifi_set_ps).
        // Bump TX power to full now that WiFi is connected and power has stabilized
        bool txOk2 = WiFi.setTxPower(WIFI_TX_DBM);
        int txRaw2 = (int)WiFi.getTxPower();
        Serial.printf("  [TX bump] post-connect TX: %.1f dBm, raw=%d, setter=%s\n",
                      txRaw2 / 4.0, txRaw2, txOk2 ? "true" : "false");
        Serial.println();
        Serial.println("========================================");
        Serial.printf("  WiFi connected! IP: %s\n", WiFi.localIP().toString().c_str());
        Serial.printf("  Open http://%s in your browser\n", WiFi.localIP().toString().c_str());
        Serial.println("========================================");
    } else {
        Serial.println("\nWiFi FAILED — starting AP mode");
        WiFi.mode(WIFI_AP);
        WiFi.softAP("SmartGarden", "garden1234");
        Serial.printf("  AP IP: %s\n", WiFi.softAPIP().toString().c_str());
        Serial.println("  Connect to WiFi 'SmartGarden' (password: garden1234)");
        Serial.printf("  Then open http://%s\n", WiFi.softAPIP().toString().c_str());
    }
}

// ============================================================
// Setup & Loop
// ============================================================
void setup() {
    WRITE_PERI_REG(RTC_CNTL_BROWN_OUT_REG, 0);  // disable brownout detector
    setCpuFrequencyMhz(BOOT_CPU_MHZ);  // Reduce current draw during boot (80MHz vs 240MHz)
    Serial.begin(115200);
    delay(100);

    // === DIAGNOSTIC: early serial before any peripheral init ===
    Serial.println();
    Serial.println("=== POWER DIAG: serial OK ===");
    Serial.printf("  CPU freq: %u MHz (reduced for boot)\n", getCpuFrequencyMhz());
    Serial.printf("  Reset reason: %d\n", (int)esp_reset_reason());
    Serial.printf("  Free heap: %u bytes\n", ESP.getFreeHeap());
    Serial.printf("  Chip temp: %.1f°C\n", temperatureRead());

    // === Crash counter — detect repeated power failures ===
    nvs.begin(NVS_NAMESPACE, false);
    crashCount = nvs.getUInt("crashCnt", 0) + 1;
    nvs.putUInt("crashCnt", crashCount);
    bootCount = nvs.getUInt("bootCount", 0) + 1;
    nvs.putUInt("bootCount", bootCount);
    nvs.end();

    lastResetReason = esp_reset_reason();
    safeMode = (crashCount >= SAFE_MODE_THRESHOLD);
    int stabilizeDelay = safeMode ? SAFE_MODE_DELAY_SEC : 3;

    // === Battery protection: if crash-looping too fast, deep sleep to preserve battery ===
    // Store last boot timestamp in NVS. If we've hit SAFE_MODE_THRESHOLD crashes
    // and the system is STILL crash-looping, go to deep sleep for 10 minutes.
    //
    // Deep sleep wake recovery: when waking FROM deep sleep, cap crashCount at
    // SAFE_MODE_THRESHOLD so we get another SAFE_MODE_THRESHOLD attempts before
    // sleeping again. This creates a retry pattern:
    //   try N times → sleep 10min → try N times → sleep 10min → ...
    // instead of permanent lockout.
    if (lastResetReason == ESP_RST_DEEPSLEEP && crashCount >= SAFE_MODE_THRESHOLD * 2) {
        crashCount = SAFE_MODE_THRESHOLD;  // give another round of attempts
        nvs.begin(NVS_NAMESPACE, false);
        nvs.putUInt("crashCnt", crashCount);
        nvs.end();
        Serial.printf("[RECOVERY] Woke from deep sleep — crashCount capped to %u for retry\n", crashCount);
    }
    if (crashCount >= SAFE_MODE_THRESHOLD * 2) {
        Serial.printf("!!! BATTERY PROTECTION — %u consecutive crashes !!!\n", crashCount);
        Serial.println("!!! Entering deep sleep for 10 minutes to preserve battery !!!");
        Serial.flush();
        esp_sleep_enable_timer_wakeup(10ULL * 60 * 1000000);  // 10 minutes in microseconds
        esp_deep_sleep_start();
    }

    Serial.printf("  Boot #%u, crash counter: %u/%u\n", bootCount, crashCount, SAFE_MODE_THRESHOLD);
    if (safeMode) {
        Serial.println("!!! SAFE MODE — too many consecutive crashes !!!");
        Serial.println("!!! Extra stabilization delay, reduced WiFi TX power !!!");
        Serial.println("!!! Will auto-clear after successful WiFi connect !!!");
    }
    Serial.printf("=== Waiting %ds for power to stabilize ===\n", stabilizeDelay);
    delay(stabilizeDelay * 1000);
    Serial.println("=== Stabilization complete, starting init ===");

    Serial.println("\n🌱 Smart Garden Controller v2.2 (power-hardened)");
    Serial.println("================================");
    bootTimeMillis = millis();

    // Load persisted valve counters
    Serial.println("[INIT] Loading valve counters...");
    loadValveCounters();
    logEvent("boot", safeMode ? "Safe mode boot" : "System started");

    // Initialize power gate (default LOW = L298Ns unpowered)
    pinMode(POWER_GATE_PIN, OUTPUT);
    digitalWrite(POWER_GATE_PIN, LOW);

    // Initialize battery voltage ADC
    pinMode(BATTERY_ADC_PIN, INPUT);
    analogSetPinAttenuation(BATTERY_ADC_PIN, ADC_11db);  // 0-3.3V range
    cachedBatteryV = readBatteryVoltage();  // Prime cache for first /api/status

    // Initialize MCP23017 I/O expander for valve control
    Serial.println("[INIT] Initializing MCP23017 I/O expander...");
    Wire.begin(MCP_SDA_PIN, MCP_SCL_PIN);
    if (!mcp.begin_I2C(MCP23017_ADDR, &Wire)) {
        Serial.println("[INIT] ERROR: MCP23017 not found! Valve control will fail.");
        logEvent("error", "MCP23017 not found");
    } else {
        Serial.printf("[INIT] MCP23017 found at 0x%02X\n", MCP23017_ADDR);
    }

    // Configure valve pins — each valve specifies MCP or GPIO via useMCP flag
    Serial.println("[INIT] Configuring valve pins...");
    for (int i = 0; i < NUM_VALVES; i++) {
        if (valves[i].useMCP) {
            mcp.pinMode(valves[i].in1, OUTPUT);
            mcp.pinMode(valves[i].in2, OUTPUT);
            mcp.digitalWrite(valves[i].in1, LOW);
            mcp.digitalWrite(valves[i].in2, LOW);
        } else {
            pinMode(valves[i].in1, OUTPUT);
            pinMode(valves[i].in2, OUTPUT);
            digitalWrite(valves[i].in1, LOW);
            digitalWrite(valves[i].in2, LOW);
        }
    }

    // Close all valves ONLY on clean boot (power-on or manual reset).
    // Skip on crash reboots to avoid the battery-drain spiral:
    //   crash → reboot → close-all pulse (heavy 12V draw) → crash → repeat × 1000+
    esp_reset_reason_t reason = esp_reset_reason();
    bool cleanBoot = (reason == ESP_RST_POWERON || reason == ESP_RST_SW || reason == ESP_RST_DEEPSLEEP);
    if (cleanBoot && !safeMode) {
        Serial.println("[INIT] Clean boot — closing all valves (safe startup)...");
        for (int i = 0; i < NUM_VALVES; i++) {
            closeValve(i);
            delay(200);  // Stagger valve pulses to avoid simultaneous current draw
        }
    } else {
        Serial.printf("[INIT] Skipping close-all (reset reason=%d, safeMode=%d) — preserving battery\n",
                      (int)reason, safeMode);
    }

    // Initialize sensors
    Serial.println("[INIT] Starting DHT22 + soil sensors...");
    dht.begin();
    for (int i = 0; i < NUM_SOIL_SENSORS; i++) {
        pinMode(soilPins[i], INPUT);
    }

    // WiFi — biggest current draw, most likely to trigger power issues
    Serial.println("[INIT] === Starting WiFi (high current draw) ===");
    setupWiFi();

    // If WiFi connected successfully, reset crash counter and restore full CPU speed
    if (WiFi.status() == WL_CONNECTED) {
        nvs.begin(NVS_NAMESPACE, false);
        nvs.putUInt("crashCnt", 0);  // Reset — we survived boot
        nvs.end();
        setCpuFrequencyMhz(RUN_CPU_MHZ);
        Serial.printf("[INIT] Crash counter reset. CPU boosted to %u MHz\n", getCpuFrequencyMhz());
    } else {
        Serial.println("[INIT] WiFi failed — crash counter NOT reset, staying at low CPU freq");
    }

    // Web server routes
    server.on("/", handleRoot);
    server.on("/api/status", HTTP_GET, handleApiStatus);
    server.on("/api/valve", HTTP_POST, handleApiValve);
    server.on("/api/closeall", HTTP_POST, handleApiCloseAll);
    server.on("/api/reboot", HTTP_POST, handleApiReboot);
    server.on("/api/events", HTTP_GET, handleApiEvents);
    server.on("/api/valvestats", HTTP_GET, handleApiValveStats);
    server.on("/api/scan", HTTP_GET, handleApiScan);
    server.begin();
    Serial.println("Web server started");

    // MQTT
    #if MQTT_ENABLED
    mqtt.setServer(MQTT_SERVER, MQTT_PORT);
    mqtt.setCallback(mqttCallback);
    #endif

    // OTA firmware updates — allows wireless flashing via PlatformIO
    ArduinoOTA.setHostname("smart-garden");
    ArduinoOTA.onStart([]() {
        Serial.println("[OTA] Update starting...");
        // Close all valves before OTA (safe state during reflash)
        for (int i = 0; i < NUM_VALVES; i++) {
            closeValve(i);
        }
    });
    ArduinoOTA.onEnd([]()   { Serial.println("\n[OTA] Update complete — rebooting"); });
    ArduinoOTA.onError([](ota_error_t err) { Serial.printf("[OTA] Error %u\n", err); });
    ArduinoOTA.onProgress([](unsigned int progress, unsigned int total) {
        Serial.printf("[OTA] %u%%\r", progress * 100 / total);
        esp_task_wdt_reset();  // OTA upload can take >30s; feed WDT each chunk
    });
#ifdef ENABLE_OTA
    ArduinoOTA.begin();
    Serial.println("[INIT] OTA updates enabled (hostname: smart-garden)");
#else
    // OTA disabled at runtime: wall-charger voltage sag during high-TX OTA bursts
    // brownout-resets the chip mid-flash, corrupting partition state. USB flash only.
    // To re-enable for bench testing on USB power, build with -DENABLE_OTA.
    Serial.println("[INIT] OTA disabled (USB flash only — see config.h)");
#endif

    // Initial sensor read
    readSensors();
    lastSensorRead = millis();

    // Task watchdog — hangs in loop() (blocked WiFi reconnect, stuck handler) trigger
    // a panic + reboot after TWDT_TIMEOUT_S, instead of going safe-mode-forever.
    // Subscribed AFTER setupWiFi() because that has 20s of blocking delay() loops.
    esp_task_wdt_init(TWDT_TIMEOUT_S, true);  // panic on timeout
    esp_task_wdt_add(NULL);                    // watch the main loop task
    Serial.printf("[INIT] Task watchdog enabled (%ds timeout)\n", TWDT_TIMEOUT_S);

    Serial.println("[INIT] Setup complete — system running");
    Serial.printf("[INIT] Free heap after init: %u bytes\n", ESP.getFreeHeap());
}

void loop() {
    esp_task_wdt_reset();  // feed task watchdog every iteration
#ifdef ENABLE_OTA
    ArduinoOTA.handle();
#endif
    server.handleClient();

    // Workaround for ESP32 WebServer/lwIP socket stale-PCB bug:
    // After serving a connection, the underlying TCP PCB lingers in TIME_WAIT
    // and can block new accepts on the single-client listen socket. Periodically
    // cycling close()/begin() forces a fresh listen socket if the server is idle.
    {
        static unsigned long lastServerReset = 0;
        if (millis() - lastServerReset >= 10000) {  // every 10s
            lastServerReset = millis();
            server.close();
            server.begin();
        }
    }

    // Valve safety net — independent firmware-side max runtime cap.
    // Protects against server crash, lost close-ACK, dead Mint server, network drop.
    // Runs every loop iteration; force-closes any valve open beyond VALVE_HARD_MAX_MS.
    for (int i = 0; i < NUM_VALVES; i++) {
        if (valves[i].isOpen && valveLastOpenedMs[i] > 0 &&
            (millis() - valveLastOpenedMs[i]) > VALVE_HARD_MAX_MS) {
            Serial.printf("[SAFETY] Valve %d force-closed (open >%lu min)\n",
                          i + 1, VALVE_HARD_MAX_MS / 60000UL);
            logEvent("safety", "force_close_max_runtime");
            closeValve(i);
        }
    }

    // Fallback schedule — if Mint server has been silent for too long, we run
    // a conservative built-in schedule so the yard survives a server outage.
    // "Silent" = no API hit for FALLBACK_SERVER_SILENT_HOURS, OR no contact since boot
    // and uptime now exceeds that threshold (covers "server was already dead at boot").
    {
        unsigned long silentMs = lastServerContactMs > 0
            ? (millis() - lastServerContactMs)
            : (millis() - bootTimeMillis);
        bool wasActive = fallbackActive;
        fallbackActive = (silentMs >= (unsigned long)FALLBACK_SERVER_SILENT_HOURS * 3600UL * 1000UL);

        if (fallbackActive && !wasActive) {
            Serial.printf("[FALLBACK] Activated — server silent %lus\n", silentMs / 1000);
            logEvent("fallback", "activated");
        } else if (!fallbackActive && wasActive) {
            Serial.println("[FALLBACK] Deactivated — server contact restored");
            logEvent("fallback", "deactivated");
        }

        if (fallbackActive) {
            // Close any fallback-opened valves whose runtime expired
            for (int i = 0; i < NUM_VALVES; i++) {
                if (fallbackCloseAtMs[i] != 0 && millis() >= fallbackCloseAtMs[i]) {
                    Serial.printf("[FALLBACK] Closing zone %d (runtime complete)\n", i + 1);
                    logEvent("fallback", "close");
                    closeValve(i);
                    fallbackCloseAtMs[i] = 0;
                }
            }
            // Open zones whose interval has elapsed (one at a time — don't pile up flow)
            bool anyOpen = false;
            for (int i = 0; i < NUM_VALVES; i++) if (valves[i].isOpen) { anyOpen = true; break; }
            if (!anyOpen) {
                for (int i = 0; i < NUM_VALVES; i++) {
                    const FallbackZone& fz = FALLBACK_SCHEDULE[i];
                    if (fz.intervalHours == 0) continue;  // disabled
                    unsigned long intervalMs = (unsigned long)fz.intervalHours * 3600UL * 1000UL;
                    unsigned long offsetMs   = (unsigned long)fz.offsetHours   * 3600UL * 1000UL;
                    bool dueByInterval = (fallbackLastRunMs[i] != 0) &&
                                         (millis() - fallbackLastRunMs[i] >= intervalMs);
                    bool dueFirstRun   = (fallbackLastRunMs[i] == 0) &&
                                         (millis() - bootTimeMillis >= offsetMs);
                    if (dueByInterval || dueFirstRun) {
                        Serial.printf("[FALLBACK] Opening zone %d for %u min\n",
                                      i + 1, fz.durationMin);
                        logEvent("fallback", "open");
                        openValve(i);
                        fallbackLastRunMs[i] = millis();
                        fallbackCloseAtMs[i] = millis() + (unsigned long)fz.durationMin * 60UL * 1000UL;
                        break;  // only start one zone per loop iteration
                    }
                }
            }
        } else {
            // Server alive — abandon any pending fallback closes (server owns valves now)
            // but DON'T force-close: server may have legitimately reopened a valve.
            for (int i = 0; i < NUM_VALVES; i++) fallbackCloseAtMs[i] = 0;
        }
    }

    // Scheduled "spring cleaning" reboot — OpenSprinkler pattern. A planned reboot
    // beats slow heap leaks, socket descriptor exhaustion, or accumulated state bugs.
    // Only fires after WEEKLY_REBOOT_HOURS of uptime to avoid boot loops.
    #if WEEKLY_REBOOT_HOURS > 0
    static unsigned long uptimeAtBoot = millis();
    if ((millis() - uptimeAtBoot) >= (unsigned long)WEEKLY_REBOOT_HOURS * 3600UL * 1000UL) {
        Serial.printf("[REBOOT] Scheduled weekly reboot after %u hours uptime\n", WEEKLY_REBOOT_HOURS);
        logEvent("boot", "scheduled_reboot");
        for (int i = 0; i < NUM_VALVES; i++) closeValve(i);  // safe state
        delay(500);
        ESP.restart();
    }
    #endif

    // OTA rollback validation: once we've been up and stable for 60 seconds with WiFi,
    // mark this firmware image as "valid". If a future OTA push boots into an image that
    // crashes before reaching this point, the bootloader rolls back to the last good image.
    // No-op unless CONFIG_BOOTLOADER_APP_ROLLBACK_ENABLE is set in sdkconfig — but harmless
    // either way, and gives us the safety net for free if rollback is later enabled.
    static bool otaMarkedValid = false;
    if (!otaMarkedValid && WiFi.status() == WL_CONNECTED && millis() - bootTimeMillis > 60000) {
        esp_err_t err = esp_ota_mark_app_valid_cancel_rollback();
        if (err == ESP_OK) {
            Serial.println("[OTA] Image marked valid — rollback cancelled");
        } else if (err != ESP_ERR_OTA_ROLLBACK_INVALID_STATE) {
            Serial.printf("[OTA] mark_valid err: 0x%x (rollback likely disabled in sdkconfig)\n", err);
        }
        otaMarkedValid = true;
    }

    // WiFi watchdog — reconnect if dropped, reboot as last resort.
    // Old threshold was 6 (60s) — caused a 38-reboot crash loop on 2026-04-27
    // when the router was briefly unavailable. Now 30 (5 min) to give the
    // router time to recover from updates/reboots/channel switches.
    static unsigned long lastWifiCheck = 0;
    static int wifiFailCount = 0;
    if (millis() - lastWifiCheck >= 10000) {  // check every 10s
        lastWifiCheck = millis();
        if (WiFi.status() != WL_CONNECTED) {
            wifiFailCount++;
            Serial.printf("WiFi disconnected (attempt %d/30)... reconnecting\n", wifiFailCount);
            WiFi.disconnect(true);       // disconnect and clear saved credentials
            WiFi.mode(WIFI_STA);          // ensure STA mode (fixes AP-mode trap after setupWiFi failure)
            #if USE_STATIC_IP
            WiFi.config(STATIC_IP, GATEWAY, SUBNET, DNS1);
            #endif
            // Use FULL TX power for reconnect — boot TX (8.5 dBm) is too weak for
            // marginal signal locations. The brownout risk only applies during cold boot.
            WiFi.setTxPower(WIFI_TX_DBM);
            WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
            wifiReconnects++;
            logEvent("wifi", "reconnect");
            if (wifiFailCount >= 30) {  // 5 min of failures — close valves, then reboot
                Serial.println("[SAFETY] WiFi failed 30 times — closing all valves before reboot");
                logEvent("error", "wifi_reboot");
                for (int i = 0; i < NUM_VALVES; i++) {
                    if (valves[i].isOpen) closeValve(i);
                }
                delay(500);
                ESP.restart();
            }
        } else {
            if (wifiFailCount > 0) {
                // WiFi just recovered — reset crash counter so we don't stay in
                // safe mode or spiral into deep sleep lockout.
                nvs.begin(NVS_NAMESPACE, false);
                nvs.putUInt("crashCnt", 0);
                nvs.end();
                crashCount = 0;
                safeMode = false;
                Serial.printf("[RECOVERY] WiFi reconnected after %d attempts — crash counter cleared\n", wifiFailCount);
            }
            wifiFailCount = 0;
        }
    }

    // Adaptive TX power — step down when signal is strong, step up when weak.
    // Saves 30-60 mA at low TX vs max. Only runs when WiFi is connected.
    #if ADAPTIVE_TX_ENABLED
    {
        static unsigned long lastAdaptiveTx = 0;
        if (WiFi.status() == WL_CONNECTED && millis() - lastAdaptiveTx >= ADAPTIVE_TX_INTERVAL_MS) {
            lastAdaptiveTx = millis();
            int rssi = WiFi.RSSI();
            int oldIndex = adaptiveTxIndex;

            if (rssi > ADAPTIVE_TX_RSSI_STRONG && adaptiveTxIndex > 0) {
                adaptiveTxIndex--;  // signal strong — step down to save power
            } else if (rssi < ADAPTIVE_TX_RSSI_WEAK && adaptiveTxIndex < ADAPTIVE_TX_LEVELS - 1) {
                adaptiveTxIndex++;  // signal weak — step up for reliability
            }
            // Between thresholds → hold (hysteresis)

            if (adaptiveTxIndex != oldIndex) {
                WiFi.setTxPower(ADAPTIVE_TX_LADDER[adaptiveTxIndex]);
                int txRaw = (int)WiFi.getTxPower();
                Serial.printf("[ADAPTIVE TX] RSSI=%d → step %s: level %d/%d (%.1f dBm, raw=%d)\n",
                              rssi, adaptiveTxIndex < oldIndex ? "DOWN" : "UP",
                              adaptiveTxIndex, ADAPTIVE_TX_LEVELS - 1,
                              txRaw / 4.0, txRaw);
            }
        }
    }
    #endif

    // Read sensors periodically
    if (millis() - lastSensorRead >= SENSOR_READ_INTERVAL_MS) {
        readSensors();
        lastSensorRead = millis();
        Serial.printf("[HOURLY] Battery=%.2fV RSSI=%d Heap=%u Temp=%.1fC\n",
                      cachedBatteryV, WiFi.RSSI(), ESP.getFreeHeap(), temperatureRead());

        #if MQTT_ENABLED
        mqttPublishStatus();
        #endif
    }

    #if MQTT_ENABLED
    if (!mqtt.connected()) mqttReconnect();
    mqtt.loop();
    #endif

    // ================================================================
    // Light sleep — save power when idle, wake on WiFi/timer
    // ================================================================
    #if LIGHT_SLEEP_ENABLED
    {
        // Stay fully awake if:
        //  1. Any valve is currently open
        //  2. Recent API activity (manual control / calibration session)
        //  3. Recent valve close (let things settle)
        bool anyValveOpen = false;
        for (int i = 0; i < NUM_VALVES; i++) {
            if (valves[i].isOpen) { anyValveOpen = true; break; }
        }
        bool recentApi = (lastApiActivityMs > 0) &&
                         (millis() - lastApiActivityMs < AWAKE_HOLD_MS);
        bool recentValve = (lastValveCloseMs > 0) &&
                           (millis() - lastValveCloseMs < AWAKE_HOLD_VALVE_MS);

        if (!anyValveOpen && !recentApi && !recentValve) {
            // Enable WiFi modem sleep (keeps association, wakes on incoming packet)
            esp_wifi_set_ps(WIFI_PS_MIN_MODEM);
            // Light sleep — CPU halts, WiFi stays associated, wakes on:
            //   - timer (LIGHT_SLEEP_INTERVAL_MS)
            //   - incoming WiFi packet (HTTP request)
            esp_sleep_enable_timer_wakeup(LIGHT_SLEEP_INTERVAL_MS * 1000ULL);  // microseconds
            esp_sleep_enable_wifi_wakeup();
            esp_light_sleep_start();
        }
    }
    #endif
}

#endif // POWER_TEST_ONLY
