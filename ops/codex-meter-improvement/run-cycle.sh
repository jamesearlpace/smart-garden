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
ln -sfn "$RUN" "$STATE/latest"

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

Read the repo AGENTS.md when present, smart-garden-journey.md, meter-data-layer-journey.md, meter-cnn-journey.md, $CONTEXT/RCA-water-meter-camera-authority-2026-07-16.md, $CONTEXT/BUG-water-meter-reader-stale-no-live-medians-2026-07-16.md, $CONTEXT/WATER-USAGE-SUCCESS-CRITERIA.md, and the last 250 lines of $JOURNAL when present. Treat the Acer at ssh acer (/home/jamesearlpace/smart-garden-server) as live/source-of-truth and the tower at ssh jackmint as the GPU/model host. Use only bounded read-only SSH, GET, journal, file, image, and SQLite checks. Never print credentials, household non-sprinkler usage details, or unrelated camera imagery.

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
You are stage 2 of the recurring smart-garden water-meter camera improvement loop. Independently evaluate $RUN/audit.json and choose one bounded improvement workstream. This evaluation stage is read-only, but it may approve stage 3 to implement and deploy a proven meter-camera/OCR or Water Usage fix under the executor's promotion gates.

Read the same context documents listed by stage 1 plus relevant live implementation and existing artifacts under $LAB. Validate important claims with at most 10 bounded read-only commands. Reject blind CNN retraining, lower confidence thresholds, frame-random train/test splits, circular ground truth, smoothing presented as accuracy, and any change to irrigation control. Prefer chronological holdouts, immutable photo-backed truth, zero false accepts, explicit rejection, and changes that improve what James can see on the live Water Usage site. If prior lab evidence already proves a deterministic data-contract or presentation fix, approve implementation, deployment, and verification in this cycle rather than requesting another equivalent offline experiment.

The initial experiment and all pre-deployment validation must be executable under $LAB and $RUN using copies or read-only Acer/tower evidence. The approved workstream may then authorize the executor to edit and deploy allowlisted meter-camera/OCR or Water Usage files, restart only the required measurement/web service, and verify production under the executor's backup, idle-valve, test, rollback, and zero-false-accept rules. Paid vision use is allowed only when already configured and budget-safe; never change provider budgets. Return only the required structured evaluation JSON.

The unfinished priority is the RCA's chronological crop/model/sequence recognition benchmark. Do not treat the two failed GPT-5.5 Codex events as proof that Codex vision cannot help: the journey records one exact blind six-frame GPT-4o event and calls for a broader controlled benchmark. Unless newer evidence makes it impossible, select a materially different Codex-subscription vision experiment using historical start/end sequences, settled post-close frames, calibrated digit crops and restrained variants, multi-frame chronological reasoning, rolling-suffix/carry reconciliation, and deterministic physical validation. Optimize for trustworthy event delta rather than perfect independent nine-digit transcription. Measure zero false accepts first and coverage second across multiple chronological events and leading-digit ranges. Do not merely restate prior failures or substitute duration-based reconstruction for recognition research.
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

If evaluation.decision is run_experiment, execute that workstream. Reuse prior successful lab artifacts instead of repeating them. When evidence supports an allowlisted production improvement, implement, deploy, and verify it during this cycle rather than stopping at a report. Continue with directly related, non-repeating work while runtime remains; stop only when there is no evidence-backed next action, a concrete promotion gate blocks progress, or less than five minutes remain.

Offline experimentation may create or update experiment code, copied inputs, manifests, and results under $LAB and $RUN. Preserve failures and rejected candidates, compare every iteration with the prior baseline, and require zero false accepts; higher coverage is not an improvement if any false accept appears.

For Codex-subscription vision research, read and reuse ops/codex_meter_boundary_reader.py and its artifacts, but do not assume its current prompt/preprocessing is optimal. Test materially different chronological presentations and delta-oriented tasks grounded by immutable event images. A useful result is a reproducible benchmark or improved guarded reader, not an unsupported claim. Keep all results shadow-only until the promotion gates below pass.

You may automatically deploy a proven live meter-camera/OCR fix to Acer or the tower only when every applicable gate below passes:

1. The change is limited to camera capture, OCR/model inference, meter provenance, event authority, meter health, or Water Usage presentation. Never change irrigation.py, valve control, ET/water-balance decisions, schedules, zone enablement, automatic/manual modes, watering thresholds, or provider budgets.
2. Reproduce the defect and prove the candidate on chronological photo-backed holdouts. Recognition/model/acceptance changes require zero false accepts plus the RCA's required new-event shadow gate (at least 30 new physical events unless the context explicitly documents that this gate already passed). Pure deterministic data-contract or presentation fixes may use focused tests plus exact historical/live contract replays when no recognition authority changes.
3. Do not lower confidence, physical-consistency, independent-evidence, chronological-holdout, or rejection gates. Do not use circular labels, smoothing, propagated locks, or the candidate reader as ground truth.
4. Immediately before mutation, prove no valve is active. If watering is active or state is uncertain, do not wait and do not deploy; retain the proven candidate for a future idle cycle.
5. Back up every live file before replacement. Do not write a live SQLite database unless the approved fix strictly requires it; then stop smart-garden-server first, back up the exact DB, use a transaction, and restore/restart automatically on any failure.
6. Deploy only the allowlisted measurement files needed for the proven fix: vision_oracle.py, meter_archive.py, meter_ledger.py, meter_phase_tracker.py, verified_run_meter.py, flow_monitor.py, meter-specific tools, meter-specific templates, or tower meter-cnn service/model files. dashboard.py is allowed only for meter-camera or Water Usage code with focused tests proving unrelated routes unchanged. No other live file is authorized.
7. Run focused tests before deployment, then verify smart-garden-server, /login, camera freshness, reader health, exact Water Usage contracts, service restart count, and the measured defect. Roll back automatically if any verification fails.
8. Save the candidate patch, pre/post hashes, backups, commands, tests, deployment manifest, and rollback instructions under $RUN and $LAB. Never expose credentials or unrelated household data. Do not commit unrelated work. Because the Windows canonical checkout is dirty, leave a clean patch artifact for later reconciliation instead of force-merging or overwriting that checkout.

If blocked or no_change, explain why. Write a durable Markdown report with: Outcome; New evidence; Experiments and hypotheses; Dataset/provenance; Results versus baseline; Promotion-gate assessment; Live changes or why none; Tests and post-deploy verification; Backups and rollback; Failure analysis; Reusable artifacts; Decision; Next non-repeating action. Include exact paths and commands but redact secrets and household details.
PROMPT
)
run_stage 60m "$RUN/execution.md" "$RUN/execution.log" "$EXEC_PROMPT"
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

# Preserve all run history. Future supervisors and experiment gates need old
# artifacts to distinguish real progress from repeated or regressed hypotheses.

[[ "$AUDIT_RC" -eq 0 && "$EVAL_RC" -eq 0 && "$EXEC_RC" -eq 0 ]]
