#!/bin/bash
cd ~/smart-garden-server
echo '=== last non-held moves ==='
sqlite3 meter_ledger.db "SELECT ts, committed_cf, method, reader FROM meter_reading WHERE method NOT IN ('held') ORDER BY ts DESC LIMIT 10;"
echo '=== distinct committed values last 3 days ==='
sqlite3 meter_ledger.db "SELECT date(ts) d, MIN(committed_cf), MAX(committed_cf), COUNT(*) FROM meter_reading WHERE ts > datetime('now','-3 days') GROUP BY d;"
echo '=== oracle_spend schema ==='
sqlite3 smart-garden.db ".schema oracle_spend"
echo '=== oracle_spend recent ==='
sqlite3 smart-garden.db "SELECT * FROM oracle_spend ORDER BY rowid DESC LIMIT 8;"
echo '=== oracle env in systemd ==='
systemctl show smart-garden-server -p Environment | tr ' ' '\n' | grep -i -E 'ORACLE|BUDGET' || echo '(none in unit env)'
echo '=== oracle drop-ins ==='
ls -la /etc/systemd/system/smart-garden-server.service.d/ 2>/dev/null
grep -r -i -E 'ORACLE|BUDGET' /etc/systemd/system/smart-garden-server.service.d/ 2>/dev/null || echo '(no oracle drop-ins)'
