#!/bin/bash
cd ~/smart-garden-server
# restore cache from the pre-overnight-fix backup (has all 150 reads incl the real morning climb)
CACHE_BAK=$(ls -t ~/meter-history-backups/reread_cache_freeze.json.pre-overnight-fix-* | head -1)
echo "restoring cache from $CACHE_BAK"
cp "$CACHE_BAK" tools/reread_cache_20260709_freeze.json
echo "=== remove ONLY the 2 isolated overnight spikes (02:30 and 07:00, val 95449963) ==="
./.venv/bin/python - <<'PY'
import json
p = "tools/reread_cache_20260709_freeze.json"
c = json.load(open(p))
removed=[]
for fn, rec in list(c.items()):
    ts=rec.get("ts",""); v=rec.get("value")
    # isolated overnight spikes: exactly 95449963 between 02:00 and 07:30 (surrounded by ~95442-95445)
    if v==95449963 and "2026-07-09T02:15:00" <= ts <= "2026-07-09T07:15:00":
        removed.append((ts,v)); del c[fn]
json.dump(c, open(p,"w"))
print("removed", len(removed), "isolated spikes:", removed)
PY
echo "=== re-apply from corrected cache ==="
./.venv/bin/python tools/reread_20260709_freeze.py apply 2>&1 | tail -5
echo "=== re-clamp ==="
bash /tmp/mono_clamp.sh 2>&1 | grep -E 'clamped|remaining'
echo "=== dryrun: event measurements + overnight unattributed ==="
./.venv/bin/python tools/reread_20260709_freeze.py dryrun 2>&1 | sed -n '/PER-EVENT/,/ROW REWRITE/p'
echo "=== day total 07-09 ==="
sqlite3 meter_ledger.db "SELECT date, ROUND(gallons,1) FROM usage_daily WHERE date='2026-07-09';"
