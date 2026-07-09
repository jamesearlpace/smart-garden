#!/bin/bash
cd ~/smart-garden-server
echo '=== training bank file count (was 8360 jpg / 8245 json at 15:50) ==='
echo -n 'jpg: '; ls ~/meter-training/*.jpg 2>/dev/null | wc -l
echo -n 'json: '; ls ~/meter-training/*.json 2>/dev/null | wc -l
echo -n 'newest 5 banked frames: '; echo
ls -t ~/meter-training/*.jpg 2>/dev/null | head -5 | xargs -n1 basename
echo
echo '=== cnn_eval rows logged since restart (oracle-vs-CNN = training signal) ==='
sqlite3 smart-garden.db "SELECT COUNT(*) FROM cnn_eval WHERE ts >= '2026-07-09T16:04:00';"
echo '--- recent cnn_eval (cnn vs oracle truth) ---'
sqlite3 smart-garden.db "SELECT ts, cnn_value, oracle_value, cnn_correct, model_version FROM cnn_eval ORDER BY ts DESC LIMIT 6;" 2>&1
echo
echo '=== cnn_daily today (should now show oracle_calls, evals, cnn_correct) ==='
sqlite3 smart-garden.db "SELECT date, frames, cnn_used, cnn_fellback, oracle_calls, evals, cnn_correct, model_version FROM cnn_daily WHERE date='2026-07-09';"
echo
echo '=== oracle label/correction stats from live status ==='
echo 'password123' | sudo -S bash tools/authcurl.sh GET '/api/cam/status' 2>/dev/null | sed -n '2p' > /tmp/st2.json
./.venv/bin/python - <<'PY'
import json
d=json.load(open('/tmp/st2.json'))
o=d.get('oracle',{})
print('oracle keys:', {k:o.get(k) for k in ('day_calls','labels','reanchors','corrections','dupes','calls')})
a=d.get('accepted_meter',{})
print('committed_cf:', a.get('committed_cf'), 'method:', a.get('method'))
PY
