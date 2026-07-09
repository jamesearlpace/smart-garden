#!/bin/bash
cd ~/smart-garden-server
echo 'password123' | sudo -S bash tools/authcurl.sh GET '/api/cam/status' 2>/dev/null | sed -n '2p' > /tmp/st.json
./.venv/bin/python - <<'PY'
import json
d = json.load(open('/tmp/st.json'))
a = d['accepted_meter']; o = d['oracle']
print('committed_cf:', a['committed_cf'], '| method:', a['method'], '| reader:', a['reader'], '| raw:', a.get('raw_reading'))
print('oracle day_calls:', o['day_calls'], '| cap_eff:', o['daily_cap_effective'])
print('banked:', d['ocr'].get('banked'))
PY
echo '--- last 6 ledger rows ---'
sqlite3 meter_ledger.db "SELECT ts, committed_cf, method, confidence FROM meter_reading ORDER BY ts DESC LIMIT 6;"
echo '--- oracle spend since restart (today) ---'
sqlite3 smart-garden.db "SELECT COUNT(*), ROUND(COALESCE(SUM(usd),0),3) FROM oracle_spend WHERE ts >= '2026-07-09T16:02:00';"
