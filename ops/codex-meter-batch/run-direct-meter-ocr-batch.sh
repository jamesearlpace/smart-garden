#!/usr/bin/env bash
set -euo pipefail

PATH=/home/john/.nvm/versions/node/v22.23.1/bin:/usr/local/bin:/usr/bin:/bin
HOME=/home/john
CODEX_HOME=/home/john/.codex
export PATH HOME CODEX_HOME
unset OPENAI_API_KEY AZURE_OPENAI_API_KEY ANTHROPIC_API_KEY || true

STATE=/home/john/.local/share/smart-garden-meter-ocr-batch
LAB=/home/john/.local/share/smart-garden-meter-improvement/lab/chronological_codex_sequence_meter_authority_benchmark_20260721
SUMMARY=/home/john/.local/share/smart-garden-meter-improvement/runs/20260721-085316/artifacts/guarded_boundary_policy_v2_summary_20260721-085316.json
RESUME="$LAB/backlog_attempts/backlog_resume_state.json"
mkdir -p "$STATE/runs"
STAMP=$(date +%Y%m%d-%H%M%S)
RUN="$STATE/runs/$STAMP"
mkdir -p "$RUN"
ln -sfn "$RUN" "$STATE/latest"

exec 9>"$STATE/worker.lock"
flock -n 9 || exit 0
exec 8>/home/john/.local/share/codex-jobs/global.lock
flock -n 8 || { printf 'status=skipped\nreason=other_codex_job_active\n' >"$RUN/status"; exit 0; }

if [[ ! -f "$SUMMARY" ]]; then
  printf 'status=blocked\nreason=missing_holdout_summary\n' >"$RUN/status"
  exit 0
fi

FALSE_ACCEPTS=$(python3 -c 'import json,sys; print(int(json.load(open(sys.argv[1])).get("false_accept_count",0)))' "$SUMMARY")
if (( FALSE_ACCEPTS > 0 )); then
  printf 'status=blocked\nreason=verified_holdout_false_accept\nfalse_accept_count=%s\n' "$FALSE_ACCEPTS" >"$RUN/status"
  exit 0
fi

cd "$LAB"
export METER_STAGE3_COMPACT_REASONING=low
export METER_STAGE3_COMPACT_TIMEOUT_SEC=180
EVENT_IDS=$(python3 -c 'import json,sys; print(" ".join(map(str,json.load(open(sys.argv[1])).get("next_recommended_batch_event_ids",[])[:2])))' "$RESUME")
if [[ -z "$EVENT_IDS" ]]; then
  printf 'status=complete\nreason=backlog_empty\n' >"$RUN/status"
  exit 0
fi
python3 -c 'import json,sys; import chronological_meter_benchmark as b; inv=b.inventory(); corp=json.load(open(b.ARTIFACTS/"benchmark_corpus.json")); ids=list(map(int,sys.argv[1:])); c=dict(corp); c["holdout_event_ids"]=[]; c["calibration_event_ids"]=[]; c["recoverable_queue_event_ids"]=ids; b.build_packs(inv,c,0,len(ids))' $EVENT_IDS
timeout 8m python3 run_shadow_backlog_batch_085316.py $EVENT_IDS >"$RUN/output.json" 2>"$RUN/error.log" || RC=$?
RC=${RC:-0}
printf 'status=%s\nexit_code=%s\ncompleted=%s\n' "$([[ $RC -eq 0 ]] && echo success || echo failed)" "$RC" "$(date --iso-8601=seconds)" >"$RUN/status"
exit "$RC"
