#!/usr/bin/env python3
"""Patch #2: move sensor + DHT + weather logging before installed_zones check."""

with open("/home/jamesearlpace/smart-garden-server/irrigation.py", "r") as f:
    code = f.read()

old = """        installed_zones = [
            zone for zone in self.config["zones"]
            if zone.get("installed", False)
        ]
        if not installed_zones:
            log.info("No installed zones configured — skipping irrigation decisions")
            return []

        if not status:
            log.error("Cannot reach ESP32 — skipping cycle")
            return

        # Log sensor data — based on sensors config section (independent of zones)
        soil_list = status.get("soil", [])
        sensors_cfg = self.config.get("sensors", {})
        for idx, sensor in enumerate(soil_list):
            if sensors_cfg.get(f"soil_{idx}", False):
                db.log_sensor(idx, sensor["pct"], sensor["raw"])

        # Log DHT22 data if present (ESP32 returns temp in Fahrenheit)
        temp = status.get("temp", 0)
        hum = status.get("hum", 0)
        if temp or hum:
            db.log_weather("dht22", temp_f=temp if temp else None,
                           humidity=hum)

        # Log weather API data
        current_wx = self.weather.get_current()
        if current_wx:
            et0 = self.weather.get_today_et0()
            db.log_weather("api",
                           temp_f=current_wx.get("temp_f"),
                           humidity=current_wx.get("humidity"),
                           wind_mph=current_wx.get("wind_mph"),
                           rain_mm=current_wx.get("precip_mm"),
                           et0_mm=et0,
                           solar_rad=current_wx.get("solar_rad"))"""

new = """        # Log sensor + weather data (runs even with no installed zones)
        if status:
            soil_list = status.get("soil", [])
            sensors_cfg = self.config.get("sensors", {})
            for idx, sensor in enumerate(soil_list):
                if sensors_cfg.get(f"soil_{idx}", False):
                    db.log_sensor(idx, sensor["pct"], sensor["raw"])

            temp = status.get("temp", 0)
            hum = status.get("hum", 0)
            if temp or hum:
                db.log_weather("dht22", temp_f=temp if temp else None,
                               humidity=hum)

        current_wx = self.weather.get_current()
        if current_wx:
            et0 = self.weather.get_today_et0()
            db.log_weather("api",
                           temp_f=current_wx.get("temp_f"),
                           humidity=current_wx.get("humidity"),
                           wind_mph=current_wx.get("wind_mph"),
                           rain_mm=current_wx.get("precip_mm"),
                           et0_mm=et0,
                           solar_rad=current_wx.get("solar_rad"))

        installed_zones = [
            zone for zone in self.config["zones"]
            if zone.get("installed", False)
        ]
        if not installed_zones:
            log.info("No installed zones configured — skipping irrigation decisions")
            return []

        if not status:
            log.error("Cannot reach ESP32 — skipping cycle")
            return"""

if old in code:
    code = code.replace(old, new)
    with open("/home/jamesearlpace/smart-garden-server/irrigation.py", "w") as f:
        f.write(code)
    print("PATCHED OK")
else:
    print("ERROR: pattern not found")
