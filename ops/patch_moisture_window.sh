#!/bin/bash
set -e
cd ~/smart-garden-server
STAMP=$(date +%Y%m%d-%H%M%S)
cp templates/moisture_sim.html ~/meter-history-backups/moisture_sim.html.pre-window-patch-${STAMP}
python3 - <<'PY'
from pathlib import Path
p = Path('templates/moisture_sim.html')
s = p.read_text()
repls = {
    'if (h >= 4 && h < 7 && moisture < madPct && isInFuture && minutesWateredToday < zone.maxRuntimeMin)':
        'if (h >= 0 && h < 10 && moisture < madPct && isInFuture && minutesWateredToday < zone.maxRuntimeMin)',
    'Predicted auto-watering: if below MAD during 4-7AM window':
        'Predicted auto-watering: if below MAD during configured 00:00-10:00 window',
    "if (armed && h >= 4 && h < 6 && !recovering && !decidedToday)":
        "if (armed && h >= 0 && h < 10 && !recovering && !decidedToday)",
    "if (h >= 6) moisture += irrigDailyPct;":
        "if (h >= 10) moisture += irrigDailyPct;",
    "else if (h >= 4) moisture += irrigDailyPct * ((h - 4) / 2);":
        "else if (h >= 0) moisture += irrigDailyPct * Math.min(1, h / 10);",
    "~4 AM": "~12 AM",
    "4 AM window": "12 AM window",
    "next 4 AM": "next 12 AM",
    "next 4-7 AM window": "next 00:00-10:00 window",
    "Night index 0 = next 4 AM": "Night index 0 = next 12 AM",
    "tonight/tomorrow 4 AM": "tonight/tomorrow 12 AM",
}
missing=[]
for old,new in repls.items():
    if old not in s:
        missing.append(old)
    s = s.replace(old,new)
p.write_text(s)
print('patched moisture_sim.html')
if missing:
    print('missing patterns:')
    for m in missing:
        print('  ', m)
PY
echo 'password123' | sudo -S systemctl restart smart-garden-server >/dev/null 2>&1
sleep 5
systemctl is-active smart-garden-server
echo '=== remaining stale 4 AM / 4-7 references ==='
grep -nE '4 AM|4-7AM|h >= 4|h < 7|h < 6' templates/moisture_sim.html || true
echo '=== new references ==='
grep -nE '00:00-10:00|~12 AM|h >= 0|h < 10' templates/moisture_sim.html | head -30
