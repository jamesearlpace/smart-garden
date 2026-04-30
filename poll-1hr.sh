#!/bin/bash
# Long-running ESP32 web server reliability test.
# Polls every 30s for 1 hour (120 iterations).
# Output appended to /tmp/esp32-poll.log so we can review later.
LOG=/tmp/esp32-poll.log
PARSE='
import sys, json
d = json.load(sys.stdin)
s = d["system"]
print("OK rssi=%d boot=%d uptime=%ds bat=%.2fV heap=%d" % (s["wifiRSSI"], s["bootCount"], s["uptimeSec"], s["batteryV"], s["freeHeap"]))
'
ok=0
fail=0
echo "=== START $(date) ===" >> $LOG
for i in $(seq 1 120); do
  ts=$(date +%H:%M:%S)
  out=$(curl -s --max-time 8 http://192.168.0.150/api/status)
  if [ -n "$out" ]; then
    parsed=$(echo "$out" | python3 -c "$PARSE" 2>&1)
    printf '%s try %3d: %s\n' "$ts" "$i" "$parsed" >> $LOG
    ok=$((ok+1))
  else
    printf '%s try %3d: TIMEOUT\n' "$ts" "$i" >> $LOG
    fail=$((fail+1))
  fi
  sleep 30
done
echo "=== END $(date) :: $ok OK, $fail TIMEOUT ===" >> $LOG
