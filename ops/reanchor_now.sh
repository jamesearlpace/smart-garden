#!/bin/bash
cd ~/smart-garden-server
PW=password123

echo "=== try up to 6 recent frames for a high-conf oracle read ==="
TRUE=$(./.venv/bin/python - <<'PY'
import glob, os, vision_oracle
frames = sorted(glob.glob(os.path.expanduser('~/meter-archive/*.jpg')))[-6:]
best = ''
for f in reversed(frames):
    try:
        r = vision_oracle.read_meter(open(f,'rb').read(), rotate180=True, hint=None)
        v = r.get('digits') or ''
        print('  ', os.path.basename(f), r.get('value'), r.get('confidence'), r.get('readable'))
        if r.get('ok') and r.get('confidence')=='high' and r.get('readable') and v:
            best = v; break
    except Exception as e:
        print('  err', e)
print('BEST='+best)
PY
)
VAL=$(echo "$TRUE" | sed -n 's/^BEST=//p')
echo "$TRUE" | grep -v '^BEST='
# floor: never anchor below the last confirmed high-conf read 95483460
if [ -z "$VAL" ] || [ "$VAL" -lt 95483460 ] 2>/dev/null; then
  echo "using safe floor 095483460 (fresh read empty or below floor)"
  VAL=095483460
fi
echo "=== re-anchor to $VAL ==="
echo "$PW" | sudo -S bash tools/authcurl.sh POST /api/cam/reanchor-manual "{\"value\":\"$VAL\"}" | sed -n '2p'
