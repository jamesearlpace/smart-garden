#!/bin/bash
V=$(curl -s -m 5 http://192.168.0.150/api/status 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); print(f\"{d['system']['batteryV']:.2f}\")" 2>/dev/null)
if [ -n "$V" ]; then
    echo "Battery: ${V}V (live)"
else
    echo "ESP32 wedged — last DB reading:"
    sqlite3 ~/smart-garden-server/smart-garden.db "SELECT ts, battery_v FROM system_health WHERE battery_v IS NOT NULL ORDER BY id DESC LIMIT 1;"
fi
