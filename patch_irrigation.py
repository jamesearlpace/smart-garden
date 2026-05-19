#!/usr/bin/env python3
"""Patch irrigation.py: move health/sensor logging before installed_zones check."""
import re

with open("/home/jamesearlpace/smart-garden-server/irrigation.py", "r") as f:
    code = f.read()

old = '''        installed_zones = [
            zone for zone in self.config["zones"]
            if zone.get("installed", False)
        ]
        if not installed_zones:
            log.info("No installed zones configured — skipping cycle")
            return []

        # Decision cycle needs current truth, not a 12s-old cache.
        status = self.get_esp32_status(force_fresh=True)
        if not status:
            log.error("Cannot reach ESP32 — skipping cycle")
            return

        # Log system health
        system = status.get("system", {})
        health = status.get("health", {})
        if system:
            db.log_system_health(
                uptime_sec=system.get("uptimeSec", 0),
                wifi_rssi=system.get("wifiRSSI", 0),
                heap_pct=system.get("heapPct", 0),
                chip_temp_f=system.get("chipTempF", 0),
                boot_count=system.get("bootCount", 0),
                battery_v=system.get("batteryV"),
                wifi_reconnects=system.get("wifiReconnects"),
                crash_count=health.get("crashCount"),
                tx_power_raw=system.get("txPowerRaw"),
            )'''

new = '''        # Always fetch ESP32 status and log health/sensors, even with no installed zones.
        status = self.get_esp32_status(force_fresh=True)
        if status:
            system = status.get("system", {})
            health = status.get("health", {})
            if system:
                db.log_system_health(
                    uptime_sec=system.get("uptimeSec", 0),
                    wifi_rssi=system.get("wifiRSSI", 0),
                    heap_pct=system.get("heapPct", 0),
                    chip_temp_f=system.get("chipTempF", 0),
                    boot_count=system.get("bootCount", 0),
                    battery_v=system.get("batteryV"),
                    wifi_reconnects=system.get("wifiReconnects"),
                    crash_count=health.get("crashCount"),
                    tx_power_raw=system.get("txPowerRaw"),
                )

        installed_zones = [
            zone for zone in self.config["zones"]
            if zone.get("installed", False)
        ]
        if not installed_zones:
            log.info("No installed zones configured — skipping irrigation decisions")
            return []

        if not status:
            log.error("Cannot reach ESP32 — skipping cycle")
            return'''

if old in code:
    code = code.replace(old, new)
    with open("/home/jamesearlpace/smart-garden-server/irrigation.py", "w") as f:
        f.write(code)
    print("PATCHED OK")
else:
    print("ERROR: old pattern not found — check for whitespace differences")
