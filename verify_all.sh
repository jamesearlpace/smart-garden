#!/bin/bash
echo "=========================================="
echo "  FULL SYSTEM VERIFICATION — $(date)"
echo "=========================================="
echo ""

echo "=== 1. ESP32 SMART GARDEN ==="
STATUS=$(curl -s -m 5 http://192.168.0.150/api/status 2>/dev/null)
if [ -n "$STATUS" ]; then
    echo "$STATUS" | python3 -c "
import sys,json
d=json.load(sys.stdin)
s=d['system']; h=d.get('health',{})
print(f'  Status:      ONLINE')
print(f'  MAC:         {s[\"mac\"]}')
print(f'  IP:          {s[\"ip\"]}')
print(f'  Uptime:      {s[\"uptimeSec\"]}s ({s[\"uptimeSec\"]//60}m)')
print(f'  Battery:     {s[\"batteryV\"]:.2f}V')
print(f'  RSSI:        {s[\"wifiRSSI\"]} dBm')
print(f'  Temp:        {d[\"temp\"]:.1f}F / {d[\"hum\"]:.0f}% humidity')
print(f'  Boot #:      {s[\"bootCount\"]}')
print(f'  Reconnects:  {s[\"wifiReconnects\"]}')
print(f'  Crashes:     {h.get(\"crashCount\",\"?\")}')
print(f'  Safe Mode:   {h.get(\"safeMode\",\"?\")}')
"
else
    echo "  FAILED — ESP32 unreachable"
fi

echo ""
echo "=== 2. IP CONFLICT CHECK (.150) ==="
CONFLICT=0
for i in 1 2 3 4 5; do
    ip neigh del 192.168.0.150 dev enx306893abb190 2>/dev/null
    ping -c 1 -W 1 192.168.0.150 >/dev/null 2>&1
    MAC=$(arp -n | grep "192.168.0.150" | awk '{print $3}')
    if [ "$MAC" != "68:fe:71:0c:ba:98" ]; then
        echo "  CONFLICT on probe $i: $MAC (expected 68:fe:71:0c:ba:98)"
        CONFLICT=1
    fi
done
if [ $CONFLICT -eq 0 ]; then
    echo "  PASS — 5/5 probes = 68:fe:71:0c:ba:98 (ESP32)"
fi

echo ""
echo "=== 3. SMART GARDEN SERVER ==="
echo -n "  Service:     "; systemctl is-active smart-garden-server
echo -n "  Port 5125:   "; curl -s -m 3 http://localhost:5125/api/health | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'OK — esp32_reachable={d[\"esp32_reachable\"]}')" 2>/dev/null || echo "FAILED"
LATEST=$(sqlite3 ~/smart-garden-server/smart-garden.db "SELECT ts, battery_v, wifi_rssi FROM system_health ORDER BY id DESC LIMIT 1;" 2>/dev/null)
echo "  Latest DB:   $LATEST"

echo ""
echo "=== 4. HOME-NET-WATCH ==="
echo -n "  Service:     "; systemctl is-active home-net-watch
echo -n "  Port 5123:   "; curl -s -m 3 http://localhost:5123/api/health 2>/dev/null | head -c 50 || echo "no health endpoint"
echo ""
FIVE_AGO=$(date -d "-5 minutes" +"%Y-%m-%dT%H:%M:%S")
DNS_COUNT=$(sqlite3 /var/lib/home-net-watch/dns_log.db "SELECT COUNT(*) FROM dns_queries WHERE timestamp > '$FIVE_AGO';" 2>/dev/null)
TLS_COUNT=$(sqlite3 /var/lib/home-net-watch/dns_log.db "SELECT COUNT(*) FROM tls_connections WHERE timestamp > '$FIVE_AGO';" 2>/dev/null)
DNS_MACS=$(sqlite3 /var/lib/home-net-watch/dns_log.db "SELECT COUNT(DISTINCT src_mac) FROM dns_queries WHERE timestamp > '$FIVE_AGO';" 2>/dev/null)
echo "  DNS (5min):  $DNS_COUNT queries from $DNS_MACS devices"
echo "  TLS (5min):  $TLS_COUNT connections"

echo ""
echo "=== 5. WATCHTOWER ==="
echo -n "  Service:     "; systemctl is-active watchtower
echo -n "  Port 5128:   "; curl -s -m 3 http://localhost:5128/api/health 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'OK — last_activity={d.get(\"hours_since_last_activity\",\"?\"):.1f}h ago')" 2>/dev/null || echo "FAILED"

echo ""
echo "=== 6. XFINITY BRIDGE MODE ==="
echo -n "  WiFi CJWII:  "
if iwlist enx306893abb190 scan 2>/dev/null | grep -q "CJWII"; then
    echo "STILL BROADCASTING (bridge mode not working)"
else
    echo "NOT FOUND (bridge mode confirmed)"
fi

echo ""
echo "=========================================="
echo "  VERIFICATION COMPLETE"
echo "=========================================="
