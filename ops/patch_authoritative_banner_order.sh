#!/bin/bash
set -e
cd ~/smart-garden-server
STAMP=$(date +%Y%m%d-%H%M%S)
cp templates/moisture_sim.html ~/meter-history-backups/moisture_sim.html.pre-authoritative-banner-order-${STAMP}
python3 - <<'PY'
from pathlib import Path
p=Path('templates/moisture_sim.html')
s=p.read_text()
old="""        } catch(e) { console.error('Banner error:', e); }
      }
    }).catch(function(err) {"""
new="""        } catch(e) { console.error('Banner error:', e); }
        // Final authoritative override: the inline predictor above is useful as
        // a fallback, but the server /api/schedule-7day mirrors the real engine
        // and already accounts for group sync, weather scale, and serial start
        // times. Run this LAST so the banner cannot drift to stale ~58min values.
        try {
          fetchSchedule7().then(function() {
            if (allZonesMode) return;
            var cz2 = null;
            for (var ci2 = 0; ci2 < ZONES.length; ci2++) { if (ZONES[ci2].id === currentZoneId) { cz2 = ZONES[ci2]; break; } }
            if (!cz2 || cz2.auto_mode === false || !cz2.installed) return;
            var sn2 = schedNextWaterText(currentZoneId);
            if (!sn2) return;
            var nwVal2 = document.getElementById('nw-value');
            var nwDet2 = document.getElementById('nw-detail');
            var nwBanner2 = document.getElementById('next-water-banner');
            if (nwVal2) { nwVal2.textContent = sn2.value; nwVal2.style.color = sn2.color; }
            if (nwDet2) nwDet2.textContent = sn2.detail;
            if (nwBanner2) nwBanner2.style.display = '';
          });
        } catch(e2) { console.error('Authoritative banner override error:', e2); }
      }
    }).catch(function(err) {"""
if old not in s:
    raise SystemExit('target block not found')
s=s.replace(old,new,1)
p.write_text(s)
print('patched authoritative banner override order')
PY
echo 'password123' | sudo -S systemctl restart smart-garden-server >/dev/null 2>&1
sleep 5
systemctl is-active smart-garden-server
# Verify the live HTML contains the new marker and schedule API still returns 80 for zone 1
echo '=== marker ==='
grep -n 'Final authoritative override' templates/moisture_sim.html
echo '=== schedule zone 1 ==='
echo 'password123' | sudo -S bash tools/authcurl.sh GET /api/schedule-7day 2>/dev/null | grep -m1 '^{' > /tmp/sched7.json
python3 - <<'PY'
import json
d=json.load(open('/tmp/sched7.json'))
print(d['next_water'].get('1'))
PY
