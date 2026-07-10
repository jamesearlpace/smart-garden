#!/bin/bash
cd ~/smart-garden-server
cp meter_ledger.db ~/meter-history-backups/meter_ledger.db.pre-monoclamp-$(date +%Y%m%d-%H%M%S)
./.venv/bin/python - <<'PY'
import sqlite3
db = "meter_ledger.db"
c = sqlite3.connect(db)
c.row_factory = sqlite3.Row
W0, W1 = "2026-07-08T22:00:00", "2026-07-09T16:04:53"
rows = c.execute("SELECT rowid, ts, committed, committed_cf, method FROM meter_reading WHERE ts>=? AND ts<? ORDER BY ts", (W0, W1)).fetchall()
run_max = None
fixed = 0
for r in rows:
    v = r["committed"]
    if run_max is not None and v < run_max:
        newv = run_max
        c.execute("UPDATE meter_reading SET committed=?, committed_cf=?, method=CASE WHEN method='held' THEN 'interpolated' ELSE method END WHERE rowid=?",
                  (newv, newv/1000.0, r["rowid"]))
        fixed += 1
    else:
        run_max = v
c.commit()
print(f"clamped {fixed} backward rows in window; final run_max={run_max} ({(run_max or 0)/1000.0} cf)")
# verify no backward steps remain
rows = c.execute("SELECT committed_cf FROM meter_reading WHERE ts>=? AND ts<? ORDER BY ts", (W0, W1)).fetchall()
prev=None; back=0
for r in rows:
    cf=r["committed_cf"]
    if prev is not None and cf < prev-0.05: back+=1
    prev=cf
print("remaining backward steps >0.05cf:", back)
c.close()
PY
echo '=== tail after clamp ==='
sqlite3 meter_ledger.db "SELECT ts, committed_cf, method FROM meter_reading WHERE ts BETWEEN '2026-07-09T16:03:00' AND '2026-07-09T16:05:30' ORDER BY ts;"
