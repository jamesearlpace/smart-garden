#!/bin/bash
cd ~/smart-garden-server
echo '=== overnight oracle reads from the reread cache (22:00 -> 08:00) ==='
./.venv/bin/python - <<'PY'
import json
c = json.load(open("tools/reread_cache_20260709_freeze.json"))
rows = []
for fn, rec in c.items():
    ts = rec.get("ts","")
    if "2026-07-08T22" <= ts or ts < "2026-07-09T08":
        if ("2026-07-08T22" <= ts <= "2026-07-08T23:59") or ("2026-07-09T00" <= ts <= "2026-07-09T08:00"):
            rows.append((ts, rec.get("value"), rec.get("confidence"), rec.get("ok")))
rows.sort()
prev=None
for ts,v,conf,ok in rows:
    d=""
    if v and prev: d=f"  d={ (v-prev)/1000.0:+.3f}cf"
    print(f"{ts}  val={v}  cf={(v/1000.0) if v else None}  conf={conf}{d}")
    if v and ok and conf=='high': prev=v
PY
echo
echo '=== ledger committed across the overnight (every ~30min) ==='
sqlite3 meter_ledger.db "SELECT ts, committed_cf, method FROM meter_reading WHERE ts BETWEEN '2026-07-08T22:29:00' AND '2026-07-09T08:00:00' AND (strftime('%M',ts) IN ('00','30') OR method='read') ORDER BY ts;" | head -60
