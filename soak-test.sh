#!/bin/bash
echo "=== Extended soak test: 10 requests with various gaps ==="
for gap in 60 120 180 300 60 30 15 5 2 1; do
    sleep $gap
    ts=$(date +%H:%M:%S)
    code=$(curl -s --max-time 5 -o /dev/null -w "%{http_code}" http://192.168.0.150/api/status)
    echo "$ts after_${gap}s: $code"
done
echo "=== Done ==="
