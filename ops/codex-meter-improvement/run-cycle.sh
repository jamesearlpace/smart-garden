#!/usr/bin/env bash
set -uo pipefail

PATH=/home/john/.nvm/versions/node/v22.23.1/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
HOME=/home/john
CODEX_HOME=/home/john/.codex
export PATH HOME CODEX_HOME
unset OPENAI_API_KEY AZURE_OPENAI_API_KEY ANTHROPIC_API_KEY || true

CODEX=/home/john/.nvm/versions/node/v22.23.1/bin/codex
WORKSPACE=/home/john/codex-workspace/smart-garden-meter
DEFINITION_DIR="$WORKSPACE/ops/codex-meter-improvement"
STATE=/home/john/.local/share/smart-garden-meter-improvement
CONTEXT="$STATE/context"
LAB="$STATE/lab"
STAMP=$(date +%Y%m%d-%H%M%S)
RUN="$STATE/runs/$STAMP"
JOURNAL="$STATE/meter-improvement-journey.md"

mkdir -p "$RUN" "$LAB" /home/john/.local/share/codex-jobs
chmod 700 "$STATE" "$STATE/runs" "$RUN" "$LAB"

exec 9>"$STATE/cycle.lock"
if ! flock -n 9; then
  printf 'status=skipped\nreason=same_job_active\ncompleted=%s\n' "$(date --iso-8601=seconds)" >"$RUN/status"
  exit 0
fi

exec 8>/home/john/.local/share/codex-jobs/global.lock
if ! flock -n 8; then
  printf 'status=skipped\nreason=other_codex_job_active\ncompleted=%s\n' "$(date --iso-8601=seconds)" >"$RUN/status"
  exit 0
fi

ln -sfn "$RUN" "$STATE/latest"

sanitize_stream() {
  sed -E \
    -e 's/(Authorization: Bearer )[A-Za-z0-9._~+=\/-]+/\1[REDACTED]/g' \
    -e 's/((PIN|PASSWORD|TOKEN|API_KEY)=)[^[:space:]]+/\1[REDACTED]/g' \
    -e 's#(/etc/[^[:space:]]*(password|token|secret)[^[:space:]]*)#[REDACTED_SECRET_PATH]#Ig'
}

run_stage() {
  local limit="$1"
  local output="$2"
  local log="$3"
  local prompt="$4"
  shift 4
  printf '%s' "$prompt" | timeout "$limit" "$CODEX" exec \
    --ephemeral --color never -m gpt-5.5 \
    -c 'model_reasoning_effort="xhigh"' -c 'approval_policy="never"' \
    -C "$WORKSPACE" -s danger-full-access "$@" -o "$output" - 2>&1 | sanitize_stream >"$log"
  return "${PIPESTATUS[1]}"
}

AUDIT_PROMPT=$(cat <<PROMPT
You are stage 1 of the recurring smart-garden water-meter camera improvement loop. Audit evidence only; do not modify files, databases, Git, services, timers, models, labels, or remote state.

Read the repo AGENTS.md when present, meter-data-layer-journey.md, meter-cnn-journey.md, $CONTEXT/RCA-water-meter-camera-authority-2026-07-16.md, $CONTEXT/BUG-water-meter-reader-stale-no-live-medians-2026-07-16.md, $CONTEXT/WATER-USAGE-SUCCESS-CRITERIA.md, and the last 250 lines of $JOURNAL when present. Treat the Acer at ssh acer (/home/jamesearlpace/smart-garden-server) as live/source-of-truth and the tower at ssh jackmint as the GPU/model host. Use only bounded read-only SSH, GET, journal, file, image, and SQLite checks. Never print credentials, household non-sprinkler usage details, or unrelated camera imagery.

Emphasize completed sprinkler events since the last successful cycle, falling back to the last 24 hours. Apply every Water Usage success criterion to exact event windows: nonzero bars, physical gallons/GPM agreement, cumulative agreement, advancing register line, clicked image/read agreement, and median/integrity agreement. Separate camera freshness, immutable raw OCR, constrained output, propagated/held lock, verified event authority, derived charts, and zone medians. Stale means unknown, never zero. Review existing lab experiments and do not repeat a failed hypothesis without materially new evidence.

Use at most 16 terminal/remote commands. Do not call paid vision providers. Return only the required structured audit JSON.
PROMPT
)
run_stage 18m "$RUN/audit.json" "$RUN/audit.log" "$AUDIT_PROMPT" \
  --output-schema "$DEFINITION_DIR/audit.schema.json"
AUDIT_RC=$?
if [[ ! -s "$RUN/audit.json" ]]; then
  printf '{"status":"blocked","window":"unknown","new_event_count":0,"contract_failures":[],"reader_state":{"camera_fresh":false,"raw_reader":"unknown","event_authority":"unknown","pending_events":0,"verified_coverage":"unknown","summary":"Audit failed; see audit.log."},"evidence_gaps":["audit exit %s"],"previous_experiments":[],"recommended_focus":"Restore a valid read-only audit."}\n' "$AUDIT_RC" >"$RUN/audit.json"
fi

EVAL_PROMPT=$(cat <<PROMPT
You are stage 2 of the recurring smart-garden water-meter camera improvement loop. Independently evaluate $RUN/audit.json and choose at most one bounded offline experiment. Do not modify files, databases, Git, services, timers, models, labels, or remote state.

Read the same context documents listed by stage 1 plus relevant implementation and existing artifacts under $LAB. Validate important claims with at most 10 bounded read-only commands. Reject blind CNN retraining, lower confidence thresholds, frame-random train/test splits, circular ground truth, smoothing presented as accuracy, paid-oracle calls, and any change to irrigation control. Prefer chronological holdouts, immutable photo-backed truth, zero false accepts, explicit rejection, and reusable benchmark improvements. If evidence is insufficient or no novel safe experiment exists, choose no_change or blocked.

The experiment must be executable entirely under $LAB and $RUN using read-only copies or reads from Acer/tower. It may not write Acer/tower, restart services, alter live databases, deploy product code, commit/push Git, or change watering behavior. Return only the required structured evaluation JSON.
PROMPT
)
run_stage 15m "$RUN/evaluation.json" "$RUN/evaluation.log" "$EVAL_PROMPT" \
  --output-schema "$DEFINITION_DIR/evaluation.schema.json"
EVAL_RC=$?
if [[ ! -s "$RUN/evaluation.json" ]]; then
  printf '{"decision":"blocked","hypothesis":"Evaluation failed.","experiment":{"id":"none","scope":"none","inputs":[],"method":[],"success_metrics":[],"stop_conditions":[]},"rationale":"See evaluation.log; exit %s.","safety":[]}' "$EVAL_RC" >"$RUN/evaluation.json"
fi

EXEC_PROMPT=$(cat <<PROMPT
You are stage 3 of the recurring smart-garden water-meter camera improvement loop. Read $RUN/audit.json and $RUN/evaluation.json, all named context documents, relevant implementation, and prior lab artifacts.

If evaluation.decision is run_experiment, execute exactly that one experiment. You may create or update only experiment code, copied inputs, manifests, and results under $LAB and $RUN. Remote Acer/tower access is read-only. Never modify live files or databases; never restart/enable/disable a service or timer; never open a valve; never change irrigation behavior, labels, accepted readings, canonical meter data, model checkpoints, Git state, or provider budgets; never call a paid vision provider. Do not weaken confidence, physical-consistency, chronological-holdout, or zero-false-accept gates.

Measure the declared metrics, preserve failures and rejected candidates, compare with the prior baseline, and state whether the hypothesis was supported. A higher coverage number is not an improvement if any false accept appears. If blocked or no_change, make no experimental change and explain why. Write a durable Markdown report with: Outcome; New evidence; Experiment and hypothesis; Dataset/provenance; Results versus baseline; Failure analysis; Safety; Reusable artifacts; Decision; Next non-repeating experiment. Include exact paths and commands but redact secrets and household details.
PROMPT
)
run_stage 30m "$RUN/execution.md" "$RUN/execution.log" "$EXEC_PROMPT"
EXEC_RC=$?
if [[ ! -s "$RUN/execution.md" ]]; then
  printf '# Outcome\n\nExecution failed with exit code %s. Review `%s/execution.log`; no live state was changed.\n' "$EXEC_RC" "$RUN" >"$RUN/execution.md"
fi

{
  printf '\n---\n\n## Cycle %s\n\n' "$(date --iso-8601=seconds)"
  printf '**Run:** `%s`  \n**Exit codes:** audit=%s evaluation=%s execution=%s\n\n' "$RUN" "$AUDIT_RC" "$EVAL_RC" "$EXEC_RC"
  printf '### Audit\n\n```json\n'; cat "$RUN/audit.json"; printf '\n```\n\n'
  printf '### Evaluation\n\n```json\n'; cat "$RUN/evaluation.json"; printf '\n```\n\n'
  cat "$RUN/execution.md"
  printf '\n'
} >>"$JOURNAL"

printf 'status=%s\naudit_rc=%s\nevaluation_rc=%s\nexecution_rc=%s\ncompleted=%s\nreport=%s\n' \
  "$([[ "$AUDIT_RC" -eq 0 && "$EVAL_RC" -eq 0 && "$EXEC_RC" -eq 0 ]] && echo success || echo failed)" \
  "$AUDIT_RC" "$EVAL_RC" "$EXEC_RC" "$(date --iso-8601=seconds)" "$RUN/execution.md" >"$RUN/status"

find "$STATE/runs" -mindepth 1 -maxdepth 1 -type d -mtime +365 -exec rm -rf -- {} +

[[ "$AUDIT_RC" -eq 0 && "$EVAL_RC" -eq 0 && "$EXEC_RC" -eq 0 ]]
