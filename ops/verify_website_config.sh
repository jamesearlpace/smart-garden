#!/bin/bash
cd ~/smart-garden-server
PW=password123

echo '=== service ==='
systemctl is-active smart-garden-server

echo '=== live /api/config values ==='
echo "$PW" | sudo -S bash tools/authcurl.sh GET /api/config 2>/dev/null | sed -n '2p' > /tmp/sg_config_live.json
./.venv/bin/python - <<'PY'
import json
cfg=json.load(open('/tmp/sg_config_live.json'))
print('watering_window:', cfg['watering_window'])
print('valve_timeout_sec:', cfg['esp32'].get('valve_timeout_sec'))
for z in cfg['zones'][:9]:
    print(f"zone {z['id']}: {z.get('name')} precip={z.get('precip_rate_iph')} maxrun={z.get('max_runtime_min')} type={z.get('type')}")
PY

echo '=== page routes ==='
for route in / /api/config /api/balance; do
  code=$(echo "$PW" | sudo -S bash tools/authcurl.sh GET "$route" 2>/dev/null | sed -n '1p' | awk '{print $2}')
  echo "$route -> $code"
done
