#!/bin/bash
cd ~/smart-garden-server
echo '=== oracle spend by day, June+July (see natural cycle reset) ==='
sqlite3 smart-garden.db "SELECT date(ts) d, COUNT(*) calls, ROUND(SUM(usd),2) usd FROM oracle_spend WHERE ts >= '2026-06-01' GROUP BY d ORDER BY d;"
echo
echo '=== monthly totals ==='
sqlite3 smart-garden.db "SELECT strftime('%Y-%m',ts) m, ROUND(SUM(usd),2) usd, COUNT(*) calls FROM oracle_spend GROUP BY m ORDER BY m;"
echo
echo '=== what does the app compute as budget summary NOW ==='
echo 'password123' | sudo -S bash tools/authcurl.sh GET '/api/cam/status' 2>/dev/null | sed -n '2p' | ./.venv/bin/python -c "import sys,json; d=json.load(sys.stdin); print(json.dumps(d.get('oracle',{}), indent=2))"
