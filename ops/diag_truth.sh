#!/bin/bash
cd ~/smart-garden-server
echo '=== July oracle spend (cycle from day 1) ==='
sqlite3 smart-garden.db "SELECT date(ts) d, COUNT(*) calls, ROUND(SUM(usd),2) usd FROM oracle_spend WHERE ts >= '2026-07-01' GROUP BY d ORDER BY d;"
echo '--- July total ---'
sqlite3 smart-garden.db "SELECT ROUND(SUM(usd),2) FROM oracle_spend WHERE ts >= '2026-07-01';"
echo
echo '=== newest archive photo (for eyeball truth) ==='
ls -t ~/meter-archive/*.jpg 2>/dev/null | head -1
echo
echo '=== does oracle read the current frame? (direct vision_oracle test) ==='
./.venv/bin/python - <<'PY'
import glob, os
try:
    import vision_oracle
    frames = sorted(glob.glob(os.path.expanduser('~/meter-archive/*.jpg')))
    if not frames:
        print('no frames'); raise SystemExit
    f = frames[-1]
    print('frame:', os.path.basename(f))
    data = open(f,'rb').read()
    r = vision_oracle.read_meter(data, rotate180=True, hint=None)
    print('oracle result:', {k:r.get(k) for k in ('ok','value','digits','confidence','readable','error')})
except Exception as e:
    import traceback; traceback.print_exc()
PY
