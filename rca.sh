#!/bin/bash
echo "=== 1. SIGNAL QUALITY ==="
curl -s -m 5 http://192.168.0.150/api/status 2>/dev/null | python3 -c '
import sys,json
try:
    d=json.load(sys.stdin)
    s=d["system"]
    h=d.get("health",{})
    print(f"rssi={s[\"wifiRSSI\"]} txPower={s[\"txPowerRaw\"]} uptime={s[\"uptimeSec\"]}s boot={s[\"bootCount\"]} reconnects={s[\"wifiReconnects\"]} resetReason={h.get(\"resetReasonName\")} crashCount={h.get(\"crashCount\")} safeMode={h.get(\"safeMode\")}")
except:
    print("ESP32 UNREACHABLE via HTTP")
'

echo ""
echo "=== 2. PING CHECK ==="
ping -c 3 -W 2 192.168.0.150

echo ""
echo "=== 3. PORT 80 STATE ==="
nmap -p 80 192.168.0.150 2>/dev/null | grep 80

echo ""
echo "=== 4. SERVER POLL PATTERN (last 10 min) ==="
journalctl -u smart-garden-server --no-pager --since "10 min ago" 2>/dev/null | grep -E "run_cycle|safety_check|AlertMonitor|log_server_health|status failed" | awk '{print $3, $NF}' | tail -30

echo ""
echo "=== 5. EERO WIFI CHANNEL ==="
# Check what channel the Eero is using
iw dev enx306893abb190 scan 2>/dev/null | grep -A5 "TellMyWifiLoveHer" | head -10 || echo "iw scan not available (need root)"

echo ""
echo "=== 6. ARP TABLE FOR .150 ==="
arp -n | grep 150

echo ""
echo "=== 7. TCPDUMP - 10 sec capture of ESP32 traffic ==="
timeout 10 tcpdump -i any -n -c 30 "host 192.168.0.150 and port 80" 2>/dev/null || echo "tcpdump needs root - trying sudo"
echo "KeepingP@ce8!" | sudo -S timeout 10 tcpdump -i any -n -c 30 "host 192.168.0.150 and port 80" 2>/dev/null
