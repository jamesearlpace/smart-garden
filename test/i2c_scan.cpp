#include <Arduino.h>
#include <Wire.h>

void setup() {
    Serial.begin(115200);
    delay(2000);
    Serial.println("\n=== I2C Scanner ===");
    Wire.begin(21, 22);  // SDA=21, SCL=22
}

void loop() {
    Serial.println("Scanning...");
    int found = 0;
    for (byte addr = 1; addr < 127; addr++) {
        Wire.beginTransmission(addr);
        if (Wire.endTransmission() == 0) {
            Serial.printf("  Found device at 0x%02X", addr);
            if (addr == 0x20) Serial.print(" <-- MCP23017!");
            Serial.println();
            found++;
        }
    }
    if (found == 0) Serial.println("  No I2C devices found!");
    else Serial.printf("  %d device(s) found\n", found);
    Serial.println();
    delay(3000);
}
