#!/bin/bash
cd ~/smart-garden-server
echo '=== tail of freeze window -> re-anchor (check monotonic connect) ==='
sqlite3 meter_ledger.db "SELECT ts, committed_cf, method FROM meter_reading WHERE ts BETWEEN '2026-07-09T15:40:00' AND '2026-07-09T16:06:00' ORDER BY ts;" | awk 'NR%8==1 || $0 ~ /read|held/'
echo
echo '=== any backward (non-monotonic) steps in freeze window? ==='
sqlite3 meter_ledger.db "SELECT ts, committed_cf FROM meter_reading WHERE ts >= '2026-07-08T22:00:00' AND ts < '2026-07-09T16:10:00' ORDER BY ts;" | ./.venv/bin/python -c "
import sys
prev=None; back=0; last=None
for line in sys.stdin:
    ts,cf=line.strip().split('|'); cf=float(cf)
    if prev is not None and cf < prev-0.05:
        back+=1
        if back<=5: print('  DOWN', last, prev, '->', ts, cf)
    prev=cf; last=ts
print('total backward steps >0.05cf:', back)
"
echo
echo '=== day total 07-09 (ledger high-water usage) ==='
sqlite3 meter_ledger.db "SELECT date, gallons, n_readings, n_image_backed, n_fresh_reads, method FROM usage_daily WHERE date IN ('2026-07-08','2026-07-09');" 2>&1
