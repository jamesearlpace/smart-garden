#!/bin/bash
set -e
cd ~/smart-garden-server
STAMP=$(date +%Y%m%d-%H%M%S)
cp templates/moisture_sim.html ~/meter-history-backups/moisture_sim.html.pre-banner-time-${STAMP}
python3 - <<'PY'
from pathlib import Path
p=Path('templates/moisture_sim.html')
s=p.read_text()
repls={
    'if (estDate.getHours() >= 7) estDate.setDate(estDate.getDate() + 1);':
        'if (estDate.getHours() >= 10) estDate.setDate(estDate.getDate() + 1);',
    'estDate.setHours(4, 0, 0, 0);':
        'estDate.setHours(0, 0, 0, 0);',
    'estDate2.setHours(4, 0, 0, 0);':
        'estDate2.setHours(0, 0, 0, 0);',
    "if (d.getHours() >= 7) d.setDate(d.getDate() + 1);":
        "if (d.getHours() >= 10) d.setDate(d.getDate() + 1);",
    "if past 7 AM": "if past 10 AM",
    "today's 4 AM": "today's 12 AM",
    "tomorrow's 4 AM": "tomorrow's 12 AM",
    "past 4 AM today": "past 12 AM today",
}
missing=[]
for old,new in repls.items():
    if old not in s:
        missing.append(old)
    s=s.replace(old,new)
p.write_text(s)
print('patched banner times')
if missing:
    print('missing:', missing)
PY
echo 'password123' | sudo -S systemctl restart smart-garden-server >/dev/null 2>&1
sleep 5
systemctl is-active smart-garden-server
grep -nE 'setHours\(|getHours\(\) >=|past 10 AM|~12 AM' templates/moisture_sim.html | sed -n '1,40p'
