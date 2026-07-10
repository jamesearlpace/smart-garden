#!/bin/bash
cd ~/smart-garden-server
echo '=== live current committed ==='
sqlite3 meter_ledger.db "SELECT ts, committed_cf, method FROM meter_reading ORDER BY ts DESC LIMIT 2;"
echo '=== 07-09 min/max + first/last ==='
sqlite3 meter_ledger.db "SELECT ROUND(MIN(committed_cf),2) mn, ROUND(MAX(committed_cf),2) mx FROM meter_reading WHERE ts>='2026-07-09T00:00:00' AND ts<'2026-07-10T00:00:00';"
echo '=== biggest forward single-step jumps on 07-09 (spikes inflate high-water) ==='
sqlite3 meter_ledger.db "SELECT ts, committed_cf FROM meter_reading WHERE ts>='2026-07-09T00:00:00' ORDER BY ts;" | ./.venv/bin/python -c "
import sys
prev=None; pts=None
jumps=[]
for line in sys.stdin:
    ts,cf=line.strip().split('|'); cf=float(cf)
    if prev is not None:
        d=cf-prev
        if d>1.0: jumps.append((round(d,2),pts,prev,ts,cf))
    prev=cf; pts=ts
jumps.sort(reverse=True)
for d,pts,pv,ts,cf in jumps[:10]: print(f'  +{d}cf  {pts}({pv}) -> {ts}({cf})')
"
echo '=== watering events 07-09 after noon (real afternoon/evening use) ==='
sqlite3 smart-garden.db "SELECT start_ts, end_ts, zone_id, ROUND(est_gallons,1) FROM watering_event WHERE start_ts>='2026-07-09T11:00:00' ORDER BY start_ts;"
