#!/bin/bash
set -e
cd ~/smart-garden-server
STAMP=$(date +%Y%m%d-%H%M%S)
cp config.yaml ~/meter-history-backups/config.yaml.pre-weather-min100-${STAMP}
python3 - <<'PY'
from pathlib import Path
p=Path('config.yaml')
s=p.read_text()
s=s.replace('  min_scale_pct: 0\n', '  min_scale_pct: 100\n')
p.write_text(s)
print('set weather_adjustment.min_scale_pct = 100')
PY
echo 'password123' | sudo -S systemctl restart smart-garden-server >/dev/null 2>&1
sleep 5
systemctl is-active smart-garden-server

echo '=== weather adjustment config ==='
sed -n '/weather_adjustment:/,/^soil:/p' config.yaml

echo '=== schedule API next water minutes ==='
echo 'password123' | sudo -S bash tools/authcurl.sh GET /api/schedule-7day 2>/dev/null | tail -n +2 > /tmp/sched7.json
python3 - <<'PY'
import json
d=json.load(open('/tmp/sched7.json'))
for zid in ['0','1','2','3','4','5','6']:
    nw=d.get('next_water',{}).get(zid)
    print(zid, nw)
PY
