#!/bin/bash
set -e
cd ~/smart-garden-server
STAMP=$(date +%Y%m%d-%H%M%S)
cp config.yaml ~/meter-history-backups/config.yaml.pre-window-quote-${STAMP}
./.venv/bin/python - <<'PY'
path='config.yaml'
lines=open(path).read().split('\n')
in_window=False
for i,line in enumerate(lines):
    if line.strip() == 'watering_window:':
        in_window=True
        continue
    if in_window and line and not line.startswith(' '):
        in_window=False
    if in_window:
        if line.startswith('  start:'):
            lines[i] = "  start: '00:00'"
        elif line.startswith('  end:'):
            lines[i] = "  end: '10:00'"
open(path,'w').write('\n'.join(lines))
print('quoted watering_window start/end')
PY
echo 'password123' | sudo -S systemctl restart smart-garden-server
sleep 5
systemctl is-active smart-garden-server
echo 'password123' | sudo -S bash tools/authcurl.sh GET /api/config 2>/dev/null | sed -n '2p' > /tmp/sg_config_live.json
./.venv/bin/python - <<'PY'
import json
cfg=json.load(open('/tmp/sg_config_live.json'))
print(cfg['watering_window'])
print(type(cfg['watering_window']['start']).__name__, type(cfg['watering_window']['end']).__name__)
PY
