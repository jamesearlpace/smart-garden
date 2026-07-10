#!/bin/bash
cd ~/smart-garden-server
echo '=== config.yaml zones section ==='
sed -n '/zones:/,/^[a-z]/p' config.yaml | head -120
echo
echo '=== measured per-zone flow (zone_flow_est) ==='
sqlite3 -header smart-garden.db "SELECT zone_id, ROUND(ewma_gpm,2) ewma_gpm, ROUND(median_gpm,2) median_gpm, ROUND(last_run_gpm,2) last_gpm, n_runs FROM zone_flow_est ORDER BY zone_id;"
echo
echo '=== median run duration per zone (last 30 days watering_event) ==='
sqlite3 -header smart-garden.db "SELECT zone_id, COUNT(*) runs, ROUND(AVG(duration_sec)/60.0,1) avg_min, ROUND(AVG(est_gallons),1) avg_gal FROM watering_event WHERE start_ts >= '2026-06-09' AND end_ts IS NOT NULL GROUP BY zone_id ORDER BY zone_id;"
