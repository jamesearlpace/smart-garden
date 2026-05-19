#!/bin/bash
echo "=== ARP CONFLICT CHECK ==="
for i in $(seq 1 10); do
    ip neigh del 192.168.0.150 dev enx306893abb190 2>/dev/null
    ping -c 1 -W 1 192.168.0.150 >/dev/null 2>&1
    MAC=$(arp -n | grep "192.168.0.150" | awk '{print $3}')
    echo "probe $i: $MAC"
    sleep 1
done
echo ""
echo "=== ESP32 STATUS ==="
curl -s -m 5 http://192.168.0.150/api/status 2>/dev/null | python3 -c "
import sys,json
d=json.load(sys.stdin)
s=d['system']
print(f\"MAC={s['mac']} Battery={s['batteryV']:.2f}V Uptime={s['uptimeSec']}s RSSI={s['wifiRSSI']}\")
" 2>/dev/null || echo "ESP32 unreachable"
