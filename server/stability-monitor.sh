#!/bin/bash
# Overnight stability monitor — logs ESP32 status every 5 minutes
LOG=~/smart-garden-stability.log
echo '=== Smart Garden Stability Soak Started ===' >> "$LOG"
echo "Start: $(date)" >> "$LOG"
echo '---' >> "$LOG"

while true; do
    RESP=$(curl -s --connect-timeout 5 http://192.168.0.150/api/status 2>/dev/null)
    if [ -z "$RESP" ]; then
        echo "$(date '+%Y-%m-%d %H:%M:%S') | OFFLINE — no response" >> "$LOG"
    else
        UPTIME=$(echo "$RESP" | python3 -c "import sys,json; d=json.load(sys.stdin)['system']; print(f\"boot={d['bootCount']} up={d['uptimeSec']}s heap={d['heapPct']}% rssi={d['wifiRSSI']} reconnects={d['wifiReconnects']}\")" 2>/dev/null)
        if [ -z "$UPTIME" ]; then
            echo "$(date '+%Y-%m-%d %H:%M:%S') | PARSE ERROR — raw: ${RESP:0:100}" >> "$LOG"
        else
            echo "$(date '+%Y-%m-%d %H:%M:%S') | $UPTIME" >> "$LOG"
        fi
    fi
    sleep 300
done
