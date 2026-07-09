#!/bin/bash
set -e
cd ~/smart-garden-server
D=/etc/systemd/system/smart-garden-server.service.d
STAMP=$(date +%Y%m%d-%H%M%S)
PW=password123

echo "=== 1. Back up + remove the \$10 local-first throttle ==="
sudo -S cp "$D/zzz-openai-local-first.conf" "/tmp/zzz-openai-local-first.conf.bak.$STAMP" <<<"$PW" 2>/dev/null
echo "$PW" | sudo -S rm -f "$D/zzz-openai-local-first.conf"
echo "removed (backup in /tmp/zzz-openai-local-first.conf.bak.$STAMP)"

echo "=== 2. Write consolidated live-first oracle config ==="
echo "$PW" | sudo -S tee "$D/zzzz-oracle-live-first.conf" >/dev/null <<'CONF'
[Service]
# 2026-07-09 (issue #43): REMOVED the $10 local-first throttle + calendar-month
# cycle bug that silently froze the meter for a day. Philosophy: the oracle is
# an INVESTMENT in training data, not a running cost. Every oracle call banks a
# verified gold label (METER_BANK_ENABLED=1) so the CNN retrains toward reading
# WITHOUT the LLM. No budget *lock* (BUDGET_ENABLED=0 -> effective cap = DAILY_CAP,
# never zeroed); spend is still recorded in oracle_spend for visibility. DAILY_CAP
# is a runaway ceiling only. Cycle day 10 matches the real Azure billing cycle
# (10th->9th) so the budget SUMMARY is accurate.
Environment=METER_ORACLE_BUDGET_ENABLED=0
Environment=METER_ORACLE_MONTHLY_BUDGET_USD=150
Environment=METER_ORACLE_BUDGET_CYCLE_START_DAY=10
Environment=METER_ORACLE_DAILY_CAP=1500
Environment=METER_ORACLE_DAILY_MIN=0
Environment=METER_ORACLE_VERIFY_SECS=20
Environment=METER_ORACLE_MIN_INTERVAL=10
Environment=METER_ORACLE_LOWCONF_INTERVAL=15
Environment=METER_ORACLE_QUOTA_BACKOFF_SECS=1800
# Bank every read as gold training data (this is what buys the no-LLM future).
Environment=METER_BANK_ENABLED=1
# Keep the historical archive-repair oracle paths modest so they don't re-storm;
# the LIVE reader is what banks NEW leading-edge gold, not archive re-reads.
Environment=METER_ARCHIVE_REREAD_BUDGET=20
Environment=METER_ARCHIVE_REPROCESS_MAX_ORACLE=5
Environment=METER_CONVERGE_DRAIN_DAILY_CAP=0
CONF
echo "wrote $D/zzzz-oracle-live-first.conf"

echo "=== 3. daemon-reload + restart ==="
echo "$PW" | sudo -S systemctl daemon-reload
echo "$PW" | sudo -S systemctl restart smart-garden-server
sleep 6
systemctl is-active smart-garden-server

echo "=== 4. Effective oracle config now ==="
systemctl show smart-garden-server -p Environment | tr ' ' '\n' | grep -E 'BUDGET_ENABLED|MONTHLY_BUDGET|CYCLE_START|DAILY_CAP|DAILY_MIN|BANK_ENABLED' | sort -u

echo "=== 5. Fresh oracle read of newest frame (true value for re-anchor) ==="
TRUE=$(./.venv/bin/python - <<'PY'
import glob, os
import vision_oracle
f = sorted(glob.glob(os.path.expanduser('~/meter-archive/*.jpg')))[-1]
r = vision_oracle.read_meter(open(f,'rb').read(), rotate180=True, hint=None)
print(r.get('digits') if (r.get('ok') and r.get('confidence')=='high' and r.get('readable')) else '')
PY
)
echo "oracle true value: '$TRUE'"

if [ -n "$TRUE" ]; then
  echo "=== 6. Re-anchor lock to $TRUE ==="
  echo "$PW" | sudo -S bash tools/authcurl.sh POST /api/cam/reanchor-manual "{\"value\":\"$TRUE\"}" | sed -n '2p'
else
  echo "=== 6. SKIPPED re-anchor — oracle read not high-conf; will let live oracle heal ==="
fi

echo "=== 7. Verify status ==="
echo "$PW" | sudo -S bash tools/authcurl.sh GET '/api/cam/status' 2>/dev/null | sed -n '2p' | ./.venv/bin/python -c "import sys,json;d=json.load(sys.stdin);a=d.get('accepted_meter',{});o=d.get('oracle',{});print('committed_cf:',a.get('committed_cf'),'method:',a.get('method'));print('oracle daily_cap_effective:',o.get('daily_cap_effective'),'day_calls:',o.get('day_calls'));b=o.get('budget',{});print('budget cycle_start_day:',b.get('cycle_start_day'),'month_start:',b.get('month_start'),'spent:',b.get('spent_month_usd'))"
