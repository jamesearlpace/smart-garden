#!/bin/bash
cd ~/smart-garden-server
STAMP=$(date +%Y%m%d-%H%M%S)
cp meter_ledger.db ~/meter-history-backups/meter_ledger.db.pre-overnight-fix-$STAMP
cp tools/reread_cache_20260709_freeze.json ~/meter-history-backups/reread_cache_freeze.json.pre-overnight-fix-$STAMP
echo "=== drop overnight misreads (value>=95449000 in 22:30->08:10 window; true overnight is 95442-95446) ==="
./.venv/bin/python - <<'PY'
import json
p = "tools/reread_cache_20260709_freeze.json"
c = json.load(open(p))
removed = []
for fn, rec in list(c.items()):
    ts = rec.get("ts","")
    v = rec.get("value")
    if v and "2026-07-08T22:30:00" <= ts <= "2026-07-09T08:10:00" and v >= 95449000:
        removed.append((ts, v))
        del c[fn]
json.dump(c, open(p,"w"))
print("removed", len(removed), "overnight misreads:")
for ts,v in sorted(removed): print("   ", ts, v)
PY
echo "=== re-apply (rebuilds window from cleaned cache, backs up again) ==="
./.venv/bin/python tools/reread_20260709_freeze.py apply 2>&1 | tail -6
echo "=== re-run monotonic clamp for any residual ==="
bash /tmp/mono_clamp.sh 2>&1 | grep -E 'clamped|remaining'
echo "=== verify overnight climb now (solid anchors) ==="
sqlite3 meter_ledger.db "SELECT strftime('%m-%d %H:%M',ts) t, committed_cf FROM meter_reading WHERE ts IN ('2026-07-08T22:30:00','2026-07-09T00:00:05','2026-07-09T02:00:11','2026-07-09T04:00:18','2026-07-09T06:00:24','2026-07-09T07:56:43') ORDER BY t;"
