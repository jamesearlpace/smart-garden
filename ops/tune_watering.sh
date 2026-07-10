#!/bin/bash
cd ~/smart-garden-server
cp config.yaml ~/meter-history-backups/config.yaml.pre-watering-tune-$(date +%Y%m%d-%H%M%S)
./.venv/bin/python - <<'PY'
import re
path = "config.yaml"
lines = open(path).read().split("\n")
# turf/sprinkler zones to correct (NOT drip 7,8 or spare 9)
TARGET = {0,1,2,3,4,5,6}
NEW_PRECIP = "0.6"     # realistic rotor rate (was 1.0-1.5, which over-credited 2-3x)
NEW_MAXRUN = "45"      # allow longer sessions (was 30)
cur = None
changed = []
for i, ln in enumerate(lines):
    m = re.match(r'^- id:\s*(\d+)', ln)
    if m:
        cur = int(m.group(1)); continue
    if cur in TARGET:
        mp = re.match(r'^(\s*)precip_rate_iph:\s*([\d.]+)\s*$', ln)
        if mp:
            old = mp.group(2)
            lines[i] = f"{mp.group(1)}precip_rate_iph: {NEW_PRECIP}"
            changed.append((cur,"precip_rate_iph",old,NEW_PRECIP)); continue
        mr = re.match(r'^(\s*)max_runtime_min:\s*([\d.]+)\s*$', ln)
        if mr:
            old = mr.group(2)
            lines[i] = f"{mr.group(1)}max_runtime_min: {NEW_MAXRUN}"
            changed.append((cur,"max_runtime_min",old,NEW_MAXRUN))
open(path,"w").write("\n".join(lines))
print("changes:")
for z,f,o,n in changed: print(f"  zone {z}: {f} {o} -> {n}")
print(f"total {len(changed)} edits")
PY
echo '=== verify battery_calibration + sensor cal untouched (still present) ==='
grep -c 'battery_calibration\|precip_rate_iph\|max_runtime_min' config.yaml
echo '=== new per-zone values ==='
bash /tmp/zones_list.sh 2>/dev/null || ./.venv/bin/python -c "import yaml; [print(x['id'], x.get('name'), 'precip', x.get('precip_rate_iph'), 'maxrun', x.get('max_runtime_min')) for x in yaml.safe_load(open('config.yaml'))['zones']]"
