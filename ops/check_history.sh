#!/bin/bash
cd ~/smart-garden-server
echo '=== distinct committed values 07-08 20:00 -> now (shape of the freeze) ==='
sqlite3 meter_ledger.db "SELECT committed_cf, method, COUNT(*) n, MIN(ts) first_ts, MAX(ts) last_ts FROM meter_reading WHERE ts >= '2026-07-08T20:00:00' GROUP BY committed_cf, method ORDER BY first_ts;"
echo
echo '=== the jump: rows around the re-anchor 16:04 ==='
sqlite3 meter_ledger.db "SELECT ts, committed_cf, method, confidence FROM meter_reading WHERE ts BETWEEN '2026-07-09T16:03:00' AND '2026-07-09T16:06:00' ORDER BY ts;"
echo
echo '=== archive frame coverage during freeze window (07-08 22:30 -> 07-09 16:04) ==='
echo -n 'frames in window: '
ls ~/meter-archive/*.jpg 2>/dev/null | awk -F/ '{print $NF}' | awk '$0 >= "20260708-223000" && $0 <= "20260709-160400"' | wc -l
echo '  (first / last few:)'
ls ~/meter-archive/*.jpg 2>/dev/null | awk -F/ '{print $NF}' | awk '$0 >= "20260708-223000" && $0 <= "20260709-160400"' | head -2
ls ~/meter-archive/*.jpg 2>/dev/null | awk -F/ '{print $NF}' | awk '$0 >= "20260708-223000" && $0 <= "20260709-160400"' | tail -2
echo
echo '=== watering events during the freeze (engine knows what ran) ==='
sqlite3 smart-garden.db "SELECT start_ts, end_ts, zone_id, est_gallons, trigger_reason FROM watering_event WHERE start_ts >= '2026-07-08T22:00:00' ORDER BY start_ts;" 2>&1
