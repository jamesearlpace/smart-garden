#!/bin/sh
set -eu
cd "$HOME/smart-garden-server"
cookie=$(sudo bash tools/authcookie.sh --header)
curl -sS -H "$cookie" -o /tmp/conv.json -w 'valid:%{http_code} time:%{time_total}\n' 'http://127.0.0.1:5125/api/cam/convergence?hours=24'
curl -sS -H "$cookie" -o /tmp/bad.json -w 'bad:%{http_code} time:%{time_total}\n' 'http://127.0.0.1:5125/api/cam/convergence?hours=abc'
python3 - <<'PY'
import json
d = json.load(open('/tmp/conv.json'))
print(d.get('ok'), len(d.get('history', [])), d.get('coverage'))
print(json.load(open('/tmp/bad.json')))
PY
sha256sum dashboard.py meter_archive.py templates/convergence.html
