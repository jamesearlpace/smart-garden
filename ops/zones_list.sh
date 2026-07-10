#!/bin/bash
cd ~/smart-garden-server
./.venv/bin/python - <<'PY'
import yaml
z = yaml.safe_load(open('config.yaml'))['zones']
print(f"{'id':>3} {'name':24} {'heads':>5} {'precip_cfg':>10} {'est_gpm':>7} {'type':10} desc")
for x in z:
    print(f"{x['id']:>3} {str(x.get('name','')):24} {str(x.get('heads','?')):>5} {str(x.get('precip_rate_iph','?')):>10} {str(x.get('est_gpm','?')):>7} {str(x.get('type','')):10} {x.get('description','')}")
PY
