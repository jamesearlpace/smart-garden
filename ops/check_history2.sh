#!/bin/bash
cd ~/smart-garden-server
echo '=== hourly shape of freeze window (min/max committed, methods) ==='
sqlite3 -header meter_ledger.db "SELECT strftime('%m-%d %H',ts) hr, ROUND(MIN(committed_cf),2) lo, ROUND(MAX(committed_cf),2) hi, ROUND(MAX(committed_cf)-MIN(committed_cf),2) climb_cf, COUNT(*) n, SUM(method='read') reads, SUM(method='propagated') interp, SUM(method='held') held FROM meter_reading WHERE ts >= '2026-07-08T22:00:00' GROUP BY hr ORDER BY hr;"
echo
echo '=== archive frames per hour during freeze (can we re-read for true values?) ==='
ls ~/meter-archive/*.jpg 2>/dev/null | awk -F/ '{print $NF}' | awk '$0>="20260708-220000" && $0<="20260709-160500"{print substr($0,1,11)}' | sort | uniq -c
echo
echo '=== watering events since 07-08 22:00 (engine ground truth) ==='
sqlite3 -header smart-garden.db "SELECT start_ts, end_ts, zone_id, ROUND(est_gallons,1) est_gal, trigger_reason FROM watering_event WHERE start_ts >= '2026-07-08T22:00:00' ORDER BY start_ts;"
