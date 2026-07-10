#!/bin/bash
cd ~/smart-garden-server
echo '=== repaired hourly shape (should show flat idle + event spikes, real reads) ==='
sqlite3 -header meter_ledger.db "SELECT strftime('%m-%d %H',ts) hr, ROUND(MIN(committed_cf),2) lo, ROUND(MAX(committed_cf),2) hi, ROUND(MAX(committed_cf)-MIN(committed_cf),2) climb_cf, SUM(method='read') reads, SUM(method='propagated') interp FROM meter_reading WHERE ts >= '2026-07-08T22:00:00' AND ts < '2026-07-09T16:04:00' GROUP BY hr ORDER BY hr;"
echo
echo '=== continuity: last freeze-window row -> re-anchor -> live ==='
sqlite3 meter_ledger.db "SELECT ts, committed_cf, method FROM meter_reading WHERE ts BETWEEN '2026-07-09T15:50:00' AND '2026-07-09T16:06:00' ORDER BY ts LIMIT 12;"
echo
echo '=== reconcile (defensibility) ==='
./.venv/bin/python meter_ledger.py reconcile 2>&1 | tail -6
