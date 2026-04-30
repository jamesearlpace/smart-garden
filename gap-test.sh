#!/bin/bash
curl -s --max-time 3 -o /dev/null -w "baseline: %{http_code}\n" http://192.168.0.150/api/status
for gap in 5 10 15 20 25 30; do
    sleep $gap
    curl -s --max-time 3 -o /dev/null -w "after_${gap}s: %{http_code}\n" http://192.168.0.150/api/status
done
