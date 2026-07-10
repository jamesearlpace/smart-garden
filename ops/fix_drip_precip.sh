#!/bin/bash
cd ~/smart-garden-server
./.venv/bin/python - <<'PY'
import re
lines = open("config.yaml").read().split("\n")
cur=None; fixed=[]
for i,ln in enumerate(lines):
    m=re.match(r'^- id:\s*(\d+)', ln)
    if m: cur=int(m.group(1)); continue
    if cur in (7,8):
        mp=re.match(r'^(\s*)precip_rate_iph:\s*([\d.]+)\s*$', ln)
        if mp and mp.group(2)!="0.4":
            lines[i]=f"{mp.group(1)}precip_rate_iph: 0.4"
            fixed.append(cur)
open("config.yaml","w").write("\n".join(lines))
print("restored drip zones to 0.4:", fixed)
PY
echo 'password123' | sudo -S systemctl restart smart-garden-server && sleep 5 && systemctl is-active smart-garden-server
echo '=== final precip per zone ==='
bash /tmp/zones_list.sh
