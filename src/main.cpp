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
#include <WiFi.h>
#include <WebServer.h>
#include <DHT.h>
#include <ArduinoJson.h>
#include <Preferences.h>
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
uint32_t bootCount = 0;
unsigned long bootTimeMillis = 0;  // millis() at boot for uptime calc

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

// ============================================================
// Valve control
// ============================================================
struct Valve {
    uint8_t in1;
    uint8_t in2;
    bool isOpen;
    const char* name;
};

Valve valves[NUM_VALVES] = {
    {VALVE1_IN1, VALVE1_IN2, false, "Zone 1 - Garden (drip)"},
    {VALVE2_IN1, VALVE2_IN2, false, "Zone 2 - Grapes (drip)"},
    {VALVE3_IN1, VALVE3_IN2, false, "Zone 3 - Fruit Trees"},
    {VALVE4_IN1, VALVE4_IN2, false, "Zone 4 - South Lawn"},
    {VALVE5_IN1, VALVE5_IN2, false, "Zone 5 - East Lawn"},
    {VALVE6_IN1, VALVE6_IN2, false, "Zone 6 - West/NW Lawn"},
    {VALVE7_IN1, VALVE7_IN2, false, "Zone 7 - NE Lawn"},
};

void openValve(int idx) {
    if (idx < 0 || idx >= NUM_VALVES) return;
    Valve& v = valves[idx];
    digitalWrite(v.in1, HIGH);
    digitalWrite(v.in2, LOW);
    delay(VALVE_PULSE_MS);
    digitalWrite(v.in1, LOW);
    digitalWrite(v.in2, LOW);
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
    digitalWrite(v.in1, LOW);
    digitalWrite(v.in2, HIGH);
    delay(VALVE_PULSE_MS);
    digitalWrite(v.in1, LOW);
    digitalWrite(v.in2, LOW);
    v.isOpen = false;
    valveCloseCount[idx]++;
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

// Serve the main control page
void handleRoot() {
    String html = R"rawliteral(
<!DOCTYPE html>
<html>
<head>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Smart Garden</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { font-family: -apple-system, sans-serif; background: #1a1a2e; color: #eee; padding: 16px; }
        h1 { color: #4ecca3; margin-bottom: 16px; font-size: 24px; }
        h2 { color: #4ecca3; margin: 20px 0 10px; font-size: 18px; }
        .card { background: #16213e; border-radius: 12px; padding: 16px; margin-bottom: 12px; }
        .sensor-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 10px; }
        .sensor { background: #0f3460; border-radius: 8px; padding: 12px; text-align: center; }
        .sensor .value { font-size: 28px; font-weight: bold; color: #4ecca3; }
        .sensor .label { font-size: 12px; color: #aaa; margin-top: 4px; }
        .valve-row { display: flex; align-items: center; justify-content: space-between;
                     padding: 12px 0; border-bottom: 1px solid #0f3460; }
        .valve-row:last-child { border-bottom: none; }
        .valve-name { font-size: 14px; flex: 1; }
        .valve-meta { font-size: 11px; color: #888; margin: 0 8px; }
        .valve-status { font-size: 13px; margin: 0 12px; min-width: 50px; text-align: center; }
        .valve-status.open { color: #4ecca3; font-weight: bold; }
        .valve-status.closed { color: #666; }
        .btn { border: none; border-radius: 8px; padding: 10px 20px; font-size: 14px;
               cursor: pointer; font-weight: bold; min-width: 80px; }
        .btn-open { background: #4ecca3; color: #1a1a2e; }
        .btn-close { background: #e74c3c; color: #fff; }
        .btn-close-all { background: #e74c3c; color: #fff; width: 100%; padding: 14px;
                         font-size: 16px; margin-top: 12px; border-radius: 12px; }
        .btn:active { transform: scale(0.95); }
        .moisture-bar { height: 8px; background: #0f3460; border-radius: 4px; margin-top: 6px; }
        .moisture-fill { height: 100%; border-radius: 4px; background: #4ecca3; transition: width 0.5s; }
        .sys-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(120px, 1fr)); gap: 8px; }
        .sys-item { background: #0f3460; border-radius: 8px; padding: 10px; text-align: center; }
        .sys-item .value { font-size: 22px; font-weight: bold; color: #e2b93d; }
        .sys-item .label { font-size: 11px; color: #aaa; margin-top: 2px; }
        .event-list { max-height: 300px; overflow-y: auto; font-size: 12px; font-family: monospace; }
        .event-row { padding: 4px 0; border-bottom: 1px solid #0f3460; display: flex; gap: 10px; }
        .event-time { color: #e2b93d; min-width: 70px; }
        .event-type { color: #4ecca3; min-width: 50px; }
        .event-detail { color: #ccc; }
        .rssi-good { color: #4ecca3; }
        .rssi-ok { color: #e2b93d; }
        .rssi-bad { color: #e74c3c; }
        #status { text-align: center; color: #666; font-size: 12px; margin-top: 12px; }
        .tabs { display: flex; gap: 8px; margin-bottom: 12px; }
        .tab { padding: 8px 16px; border-radius: 8px; background: #0f3460; color: #aaa;
               cursor: pointer; font-size: 13px; border: none; }
        .tab.active { background: #4ecca3; color: #1a1a2e; font-weight: bold; }
        .tab-content { display: none; }
        .tab-content.active { display: block; }
    </style>
</head>
<body>
    <h1>🌱 Smart Garden</h1>

    <div class="tabs">
        <button class="tab active" onclick="showTab('main')">Dashboard</button>
        <button class="tab" onclick="showTab('events')">Event Log</button>
    </div>

    <div id="tab-main" class="tab-content active">
        <h2>System</h2>
        <div class="card">
            <div class="sys-grid" id="sysinfo">Loading...</div>
        </div>

        <h2>Sensors</h2>
        <div class="card">
            <div class="sensor-grid" id="sensors">Loading...</div>
        </div>

        <h2>Valves</h2>
        <div class="card" id="valves">Loading...</div>
        <button class="btn btn-close-all" onclick="closeAll()">🛑 Close All Valves</button>
    </div>

    <div id="tab-events" class="tab-content">
        <h2>Recent Events</h2>
        <div class="card">
            <div class="event-list" id="eventlog">Loading...</div>
        </div>
    </div>

    <div id="status"></div>

    <script>
        function showTab(name) {
            document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
            document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
            document.getElementById('tab-' + name).classList.add('active');
            event.target.classList.add('active');
            if (name === 'events') loadEvents();
        }

        function fmtUptime(sec) {
            const d = Math.floor(sec / 86400);
            const h = Math.floor((sec % 86400) / 3600);
            const m = Math.floor((sec % 3600) / 60);
            if (d > 0) return d + 'd ' + h + 'h ' + m + 'm';
            if (h > 0) return h + 'h ' + m + 'm';
            return m + 'm ' + (sec % 60) + 's';
        }

        function rssiClass(rssi) {
            if (rssi > -50) return 'rssi-good';
            if (rssi > -70) return 'rssi-ok';
            return 'rssi-bad';
        }

        function rssiLabel(rssi) {
            if (rssi > -50) return 'Excellent';
            if (rssi > -60) return 'Good';
            if (rssi > -70) return 'Fair';
            return 'Weak';
        }

        function refresh() {
            fetch('/api/status')
                .then(r => r.json())
                .then(d => {
                    const s = d.system || {};

                    // System info
                    let si = '';
                    si += `<div class="sys-item"><div class="value">${fmtUptime(s.uptimeSec||0)}</div><div class="label">Uptime</div></div>`;
                    si += `<div class="sys-item"><div class="value">${s.bootCount||0}</div><div class="label">Boot Count</div></div>`;
                    si += `<div class="sys-item"><div class="value ${rssiClass(s.wifiRSSI||0)}">${s.wifiRSSI||0} dBm</div><div class="label">WiFi ${rssiLabel(s.wifiRSSI||0)}</div></div>`;
                    si += `<div class="sys-item"><div class="value">${s.heapPct||0}%</div><div class="label">Free Memory</div></div>`;
                    si += `<div class="sys-item"><div class="value">${(s.chipTempF||0).toFixed(0)}°F</div><div class="label">Chip Temp</div></div>`;
                    si += `<div class="sys-item"><div class="value">${s.eventCount||0}</div><div class="label">Events Logged</div></div>`;
                    document.getElementById('sysinfo').innerHTML = si;

                    // Sensors
                    let sh = `
                        <div class="sensor">
                            <div class="value">${d.temp.toFixed(1)}°F</div>
                            <div class="label">Temperature</div>
                        </div>
                        <div class="sensor">
                            <div class="value">${d.hum.toFixed(0)}%</div>
                            <div class="label">Humidity</div>
                        </div>`;
                    d.soil.forEach(s => {
                        sh += `<div class="sensor">
                            <div class="value">${s.pct}%</div>
                            <div class="label">${s.name}</div>
                            <div class="moisture-bar"><div class="moisture-fill" style="width:${s.pct}%"></div></div>
                        </div>`;
                    });
                    document.getElementById('sensors').innerHTML = sh;

                    // Valves
                    let vh = '';
                    d.valves.forEach((v, i) => {
                        const cls = v.open ? 'open' : 'closed';
                        const txt = v.open ? 'OPEN' : 'CLOSED';
                        const meta = v.open && v.openForSec
                            ? `open ${fmtUptime(v.openForSec)}`
                            : `${v.openCount||0} opens / ${v.closeCount||0} closes`;
                        const btn = v.open
                            ? `<button class="btn btn-close" onclick="valve(${i},'close')">Close</button>`
                            : `<button class="btn btn-open" onclick="valve(${i},'open')">Open</button>`;
                        vh += `<div class="valve-row">
                            <span class="valve-name">${v.name}</span>
                            <span class="valve-meta">${meta}</span>
                            <span class="valve-status ${cls}">${txt}</span>
                            ${btn}
                        </div>`;
                    });
                    document.getElementById('valves').innerHTML = vh;
                    document.getElementById('status').textContent = 'Last updated: ' + new Date().toLocaleTimeString();
                })
                .catch(() => {
                    document.getElementById('status').textContent = 'Connection lost — retrying...';
                });
        }

        function loadEvents() {
            fetch('/api/events')
                .then(r => r.json())
                .then(events => {
                    let html = '';
                    events.forEach(e => {
                        html += `<div class="event-row">
                            <span class="event-time">${fmtUptime(e.uptimeSec)}</span>
                            <span class="event-type">${e.type}</span>
                            <span class="event-detail">${e.detail}</span>
                        </div>`;
                    });
                    document.getElementById('eventlog').innerHTML = html || '<div style="color:#666">No events yet</div>';
                });
        }

        function valve(idx, action) {
            fetch(`/api/valve?id=${idx}&action=${action}`, {method:'POST'})
                .then(() => setTimeout(refresh, 300));
        }

        function closeAll() {
            if (confirm('Close ALL valves?'))
                fetch('/api/closeall', {method:'POST'})
                    .then(() => setTimeout(refresh, 500));
        }

        refresh();
        setInterval(refresh, 5000);
    </script>
</body>
</html>
)rawliteral";
    server.send(200, "text/html", html);
}

// API: Get system status as JSON
void handleApiStatus() {
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
    sys["wifiRSSI"] = WiFi.RSSI();
    sys["wifiReconnects"] = wifiReconnects;
    sys["ip"] = WiFi.localIP().toString();
    sys["mac"] = WiFi.macAddress();
    sys["eventCount"] = eventCount;

    String json;
    serializeJson(doc, json);
    server.send(200, "application/json", json);
}

// API: Open or close a single valve
void handleApiValve() {
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
    closeAllValves();
    server.send(200, "text/plain", "All valves closed");
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
    WiFi.setTxPower(WIFI_TX_DBM);  // Reduce TX power: ~120mA vs ~380mA at default 19.5dBm
    Serial.printf(" (TX power: %.1f dBm)\n", WiFi.getTxPower() / 4.0);
    WiFi.setAutoReconnect(true);
    WiFi.persistent(true);

    int attempts = 0;
    while (WiFi.status() != WL_CONNECTED && attempts < 40) {
        delay(500);
        Serial.print(".");
        attempts++;
    }

    if (WiFi.status() == WL_CONNECTED) {
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
    uint32_t crashCount = nvs.getUInt("crashCnt", 0) + 1;
    nvs.putUInt("crashCnt", crashCount);
    bootCount = nvs.getUInt("bootCount", 0) + 1;
    nvs.putUInt("bootCount", bootCount);
    nvs.end();

    bool safeMode = (crashCount >= SAFE_MODE_THRESHOLD);
    int stabilizeDelay = safeMode ? SAFE_MODE_DELAY_SEC : 3;

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

    // Initialize valve pins
    Serial.println("[INIT] Configuring GPIO pins...");
    for (int i = 0; i < NUM_VALVES; i++) {
        pinMode(valves[i].in1, OUTPUT);
        pinMode(valves[i].in2, OUTPUT);
        digitalWrite(valves[i].in1, LOW);
        digitalWrite(valves[i].in2, LOW);
    }

    // Close all valves on startup (safe state) — stagger to limit current spikes
    Serial.println("[INIT] Closing all valves (safe startup)...");
    for (int i = 0; i < NUM_VALVES; i++) {
        closeValve(i);
        delay(200);  // Stagger valve pulses to avoid simultaneous current draw
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

    // Initial sensor read
    readSensors();
    lastSensorRead = millis();

    Serial.println("[INIT] Setup complete — system running");
    Serial.printf("[INIT] Free heap after init: %u bytes\n", ESP.getFreeHeap());
}

void loop() {
    server.handleClient();

    // WiFi watchdog — reconnect if dropped, reboot if stuck
    static unsigned long lastWifiCheck = 0;
    static int wifiFailCount = 0;
    if (millis() - lastWifiCheck >= 10000) {  // check every 10s
        lastWifiCheck = millis();
        if (WiFi.status() != WL_CONNECTED) {
            wifiFailCount++;
            Serial.printf("WiFi disconnected (attempt %d)... reconnecting\n", wifiFailCount);
            WiFi.disconnect();
            WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
            wifiReconnects++;
            logEvent("wifi", "reconnect");
            if (wifiFailCount >= 6) {  // 60s of failures — hard reboot
                Serial.println("WiFi failed 6 times — rebooting");
                logEvent("error", "wifi_reboot");
                delay(500);
                ESP.restart();
            }
        } else {
            wifiFailCount = 0;
        }
    }

    // Read sensors periodically
    if (millis() - lastSensorRead >= SENSOR_READ_INTERVAL_MS) {
        readSensors();
        lastSensorRead = millis();

        #if MQTT_ENABLED
        mqttPublishStatus();
        #endif
    }

    #if MQTT_ENABLED
    if (!mqtt.connected()) mqttReconnect();
    mqtt.loop();
    #endif
}

#endif // POWER_TEST_ONLY
