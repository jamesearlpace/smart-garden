#!/bin/bash
cd ~/smart-garden-server
PW=password123
echo '=== current meter_state.json ==='
cat /tmp/meter_state.json 2>/dev/null; echo
echo '=== truth guard file ==='
cat ~/meter-truth-guard.json 2>/dev/null | head -c 600; echo
echo '=== 3 fresh oracle reads for consensus true value ==='
./.venv/bin/python - <<'PY'
import glob, os, vision_oracle
frames = sorted(glob.glob(os.path.expanduser('~/meter-archive/*.jpg')))[-3:]
for f in reversed(frames):
    r = vision_oracle.read_meter(open(f,'rb').read(), rotate180=True, hint=None)
    print('  ', os.path.basename(f), r.get('value'), r.get('confidence'))
PY
echo '=== reliable re-anchor: stop -> write state -> start ==='
TS=$(date +%s)
echo "$PW" | sudo -S systemctl stop smart-garden-server
printf '{"last_good": 95485318, "lock_ts": %s}\n' "$TS" > /tmp/meter_state.json
cat /tmp/meter_state.json
echo "$PW" | sudo -S systemctl start smart-garden-server
sleep 8
systemctl is-active smart-garden-server
echo '=== verify ==='
sqlite3 meter_ledger.db "SELECT ts, committed_cf, method FROM meter_reading ORDER BY ts DESC LIMIT 4;"
