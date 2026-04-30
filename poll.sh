#!/bin/bash
ok=0; fail=0
for i in $(seq 1 12); do
  printf '%s try %2d: ' "$(date +%H:%M:%S)" "$i"
  out=$(curl -s --max-time 6 http://192.168.0.150/api/status)
  if [ -n "$out" ]; then
    rssi=$(echo "$out" | python3 -c 'import sys,json; d=json.load(sys.stdin); print(d["system"]["wifiRSSI"])')
    boot=$(echo "$out" | python3 -c 'import sys,json; d=json.load(sys.stdin); print(d["system"]["bootCount"])')
    up=$(echo "$out" | python3 -c 'import sys,json; d=json.load(sys.stdin); print(d["system"]["uptimeSec"])')
    bat=$(echo "$out" | python3 -c 'import sys,json; d=json.load(sys.stdin); print(round(d["system"]["batteryV"],2))')
    echo "OK rssi=$rssi boot=$boot uptime=${up}s bat=${bat}V"
    ok=$((ok+1))
  else
    echo TIMEOUT
    fail=$((fail+1))
  fi
  sleep 5
done
echo "=== $ok OK, $fail TIMEOUT ==="
