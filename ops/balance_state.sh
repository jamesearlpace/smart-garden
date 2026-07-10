#!/bin/bash
cd ~/smart-garden-server
echo '=== soil_balance schema ==='
sqlite3 smart-garden.db ".schema soil_balance" | head -20
echo
echo '=== current balance vs MAD via app functions ==='
./.venv/bin/python - <<'PY'
import yaml, database as db
cfg = yaml.safe_load(open('config.yaml'))
zones = {z['id']: z for z in cfg['zones']}
print(f"{'zone':>4} {'name':20} {'balance_mm':>10} {'mad_mm':>8} {'taw_mm':>8} state")
for zid in range(7):
    b = db.get_soil_balance(zid)
    if not b:
        print(f"{zid:>4} {zones[zid]['name']:20} (no balance row)"); continue
    bal = b.get('balance_mm'); mad = b.get('mad_mm'); taw = b.get('taw_mm')
    st = 'WATER' if (bal is not None and mad is not None and bal <= mad) else 'ok'
    print(f"{zid:>4} {zones[zid]['name']:20} {bal:>10.1f} {mad:>8.1f} {str(taw):>8} {st}")
PY
