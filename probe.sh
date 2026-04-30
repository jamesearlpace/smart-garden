#!/bin/bash
ping -c 3 192.168.0.150
echo '---'
for i in 1 2 3; do
  printf 'poll %d: ' "$i"
  curl -s --max-time 8 -o /dev/null -w 'http=%{http_code} time=%{time_total}s\n' http://192.168.0.150/api/status
  sleep 2
done
