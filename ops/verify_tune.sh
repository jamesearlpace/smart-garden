#!/bin/bash
cd ~/smart-garden-server
echo '=== recompute soil balances with corrected precip (flush the over-credit) ==='
./.venv/bin/python - <<'PY'
import irrigation, database as db
try:
    eng = irrigation.IrrigationEngine() if hasattr(irrigation,'IrrigationEngine') else None
except Exception as e:
    eng = None
    print("engine init note:", e)
# try common recompute entrypoints
done=False
for name in ("update_daily_balances","recompute_balances","backfill_balances"):
    fn = getattr(eng, name, None) if eng else None
    if fn:
        try:
            fn(); print("ran", name); done=True; break
        except Exception as e:
            print(name,"err",e)
if not done:
    print("no direct recompute entrypoint found via engine; balances will update on the 11 PM cycle")
PY
echo
echo '=== latest soil balance vs MAD per zone (WATER = will irrigate) ==='
sqlite3 -header smart-garden.db "SELECT s.zone_id, ROUND(s.balance_mm,1) balance, ROUND(s.mad_mm,1) mad, CASE WHEN s.balance_mm<=s.mad_mm THEN 'WATER' ELSE 'ok' END st, s.day FROM soil_balance s JOIN (SELECT zone_id, MAX(day) md FROM soil_balance GROUP BY zone_id) t ON s.zone_id=t.zone_id AND s.day=t.md WHERE s.zone_id BETWEEN 0 AND 6 ORDER BY s.zone_id;"
