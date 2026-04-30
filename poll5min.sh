#!/bin/bash
ok=0
fail=0
PARSE='
import sys, json
d = json.load(sys.stdin)
s = d["system"]
print("OK rssi=%d boot=%d uptime=%ds bat=%.2fV heap=%d" % (s["wifiRSSI"], s["bootCount"], s["uptimeSec"], s["batteryV"], s["freeHeap"]))
'
for i in $(seq 1 10); do
  ts=$(date +%H:%M:%S)
  out=$(curl -s --max-time 8 http://192.168.0.150/api/status)
  if [ -n "$out" ]; then
    parsed=$(echo "$out" | python3 -c "$PARSE" 2>&1)
    printf '%s try %2d: %s\n' "$ts" "$i" "$parsed"
    ok=$((ok+1))
  else
    printf '%s try %2d: TIMEOUT\n' "$ts" "$i"
    fail=$((fail+1))
  fi
  [ $i -lt 10 ] && sleep 30
done
echo "=== $ok OK, $fail TIMEOUT (over ~5 min) ==="
