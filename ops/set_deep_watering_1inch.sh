#!/bin/bash
set -e
cd ~/smart-garden-server
STAMP=$(date +%Y%m%d-%H%M%S)
cp config.yaml ~/meter-history-backups/config.yaml.pre-deep-watering-${STAMP}
./.venv/bin/python - <<'PY'
import re
path = "config.yaml"
lines = open(path).read().split("\n")
cur = None
changes = []
for i, ln in enumerate(lines):
    if ln.startswith("  valve_timeout_sec:"):
        old = ln.split(":",1)[1].strip()
        lines[i] = "  valve_timeout_sec: 7200"
        changes.append(("esp32", "valve_timeout_sec", old, "7200"))
    elif ln.startswith("  start:"):
        old = ln.split(":",1)[1].strip()
        lines[i] = "  start: 00:00"
        changes.append(("watering_window", "start", old, "00:00"))
    elif ln.startswith("  end:") and cur is None:
        old = ln.split(":",1)[1].strip()
        lines[i] = "  end: 10:00"
        changes.append(("watering_window", "end", old, "10:00"))
    m = re.match(r'^- id:\s*(\d+)', ln)
    if m:
        cur = int(m.group(1))
        continue
    if cur is not None and 0 <= cur <= 6:
        mm = re.match(r'^(\s*)max_runtime_min:\s*([\d.]+)\s*$', ln)
        if mm:
            old = mm.group(2)
            lines[i] = f"{mm.group(1)}max_runtime_min: 80"
            changes.append((f"zone {cur}", "max_runtime_min", old, "80"))
open(path, "w").write("\n".join(lines))
print("changes:")
for obj, field, old, new in changes:
    print(f"  {obj}: {field} {old} -> {new}")
PY
echo 'password123' | sudo -S systemctl restart smart-garden-server
sleep 5
systemctl is-active smart-garden-server
echo '=== final window / timeout ==='
sed -n '1,16p' config.yaml
echo '=== final zone config ==='
bash /tmp/zones_list.sh | head -9
