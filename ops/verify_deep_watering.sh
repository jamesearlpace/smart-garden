#!/bin/bash
cd ~/smart-garden-server
echo '=== current balances after recompute ==='
./.venv/bin/python - <<'PY'
import database as db, yaml
zones={z['id']:z for z in yaml.safe_load(open('config.yaml'))['zones']}
print(f"{'z':>2} {'name':22} {'bal':>6} {'mad':>6} state")
for zid in range(7):
    b=db.get_soil_balance(zid)
    bal=b['balance_mm']; mad=b['mad_mm']
    print(f"{zid:>2} {zones[zid]['name'][:22]:22} {bal:6.1f} {mad:6.1f} {'WATER' if bal<=mad else 'ok'}")
PY
echo
echo '=== runtime math ==='
./.venv/bin/python - <<'PY'
pr=0.11
minutes=80
inch=pr*(minutes/60.0)
print(f"80 min at 0.11 in/hr = {inch:.3f} in per watering")
print(f"if daily = {inch*7:.2f} in/week")
print("7 turf zones x 80 min = 560 min = 9h20m; window 00:00-10:00 = 10h, fits with ~40 min slack")
PY
