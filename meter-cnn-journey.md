# Meter CNN — Model Quality & Path to ~100%

> Journey doc for the water-meter digit CNN: the data audit, the model-quality
> upgrades, the benchmark audit, and the (negative) fusion experiment that
> reframed what "~100% accuracy" even means here. Captured 2026-06-20.
>
> Companion to `smart-garden-journey.md`. The OCR/CNN system reads a Sensus 9-digit
> LCD water meter from a fixed camera; a small CNN runs on the tower (jackmint
> 192.168.0.120, `~/meter-cnn/`), the Flask app + lock run on the Acer
> (192.168.0.109, `~/smart-garden-server/`).

## ⚠️ RECURRING LOOP — READ THIS BEFORE "just retrain the CNN"

**This exact problem has recurred at least 4 times (2026-06-16, 06-21, 07-04, 07-08). It is a STRUCTURAL loop, not a bug you can retrain away. If you're here because "the meter shows wrong readings / raw CNN is garbage again," you are in the loop. Don't just retrain — that's step 4 of the loop.**

**The loop:**
1. The physical meter advances into a NEW leading-edge digit range.
2. The CNN has ~no verified training data there → it collapses the high/middle digits, snapping the value back toward its last-trained range (e.g. 2026-07-08: true `095354`, raw CNN `095054` — the `3` read as `0`).
3. We diagnose "CNN ~0% / high-digit regression." (True, but expected.)
4. We bank gpt-4o-oracle labels of current frames + gated-retrain → new champion (v5→v6→v8) → fixed *within the just-labeled range only*.
5. The gpt-4o oracle's quota/rate limit runs out (HTTP 429). Because the oracle is ALSO the live reader + recovery + label source, grading and labeling stop and the display goes stale. **This 429 is the real user-visible failure every time** (happened again 2026-07-08 during the water-usage repair — Azure rate-limited the bulk reads).
6. The meter keeps climbing → new leading edge → GOTO 1.

**What does NOT break the loop (documented dead-ends — do NOT re-propose without new evidence):**
- Retraining again (temporary; the meter always outruns the freshly-labeled range within days).
- Manual re-anchoring (trains nothing — "bailing water, not fixing the leak").
- Multi-frame fusion (glare is systematic, not random → confidently wrong; offline-proven).
- Lowering the accept threshold to make the CNN "look active" (commits wrong reads).
- A polarizing lens / hardware fix (James will not buy one — off the table).
- Constrained decode promoted to truth (positive-feedback flaw; left DISABLED).

**Root structural cause:** the CNN is perpetually one step behind the meter's leading edge, and it can only learn a range AFTER the expensive, rate-limited gpt-4o oracle labels it — but that same oracle is the live reader AND recovery path on one shared metered quota, so it keeps running out. Reader + labeler + recovery are a single metered dependency that structurally can't keep up.

**Durable EXITS (the only things that actually break the loop — pursue these, not another retrain):**
1. **Move the oracle/labeler to a LOCAL vision model on the tower** (jackmint already runs `ollama` with `moondream`, plus `meter-ocr`). Unmetered → it can read + grade + label every frame continuously and never 429. This removes the quota bottleneck behind every documented outage, and it matches the 3-server plan (vision compute on the tower). **Highest leverage.** (Caveat: validate a local VLM's digit accuracy vs gpt-4o first — moondream is 1B and unproven on this LCD.)
2. **Pre-train the CNN across the FULL future digit range** with synthetic Sensus-LCD renders (all `09xxxx…` prefixes, not just recent ones), so it is never out-of-distribution at the leading edge.
3. **Accept whole-cubic-foot as the honest ceiling** — read positions 0–6 reliably (they drive the usage total) and stop fighting the mid-roll last 2 digits (blur-limited, ~unwinnable).

**Live state 2026-07-08 evening:** tower CNN = `loc2-v9` (threshold 0.95), promoted by a strict oracle-only retrain after exporting 348 newly reviewed archive frames. The committed water-usage values are currently correct because they were re-anchored from real photo reads on 07-08 (see `meter-data-layer-journey.md`), NOT because the CNN is now a safe single-frame authority. `loc2-v9` improves the hard benchmark, but the durable production path is still the guarded low-digit phase tracker plus sparse trusted anchors.

**Live state 2026-07-09 (issue #43 — the loop bit us again, via budget this time):** the meter FROZE for ~15h at `95376.901` because the 07-08 local-first experiment throttled the oracle to `$10/mo` AND the budget pacer measured spend against the wrong window (calendar month vs Natalie's real 10th→9th Azure cycle) → `daily_cap_effective=0` → oracle fully off → CNN blind at the `9548x` edge → nothing could read → frozen. ~797 gal unmeasured. Fixed: `zzzz-oracle-live-first.conf` (`BUDGET_ENABLED=0` removes the lock, `DAILY_CAP=1500` ceiling, `CYCLE_START_DAY=10`, `BANK_ENABLED=1`), removed the `$10` throttle, re-anchored to `95485.318` via the reliable stop→write-`meter_state.json`→start method (the `/reanchor-manual` API only moved the in-memory lock, not the committed ledger). Reader live again, banking gold, feeding the gated retrain. Full RCA: `rca-meter-freeze-2026-07-09.md` + GitHub issue #43.

---

## 2026-07-08 — "Out-of-the-box" reader exploration (gpt-4o TPM bump, local VLM, Azure Read)

Session goal: get a cheaper/more reliable reader than the metered gpt-4o. Findings:

**gpt-4o rate limit raised.** Azure deployment `smartgardenai1490` gpt-4o capacity **20K→48K TPM** (regional limit 49K). The 429s were a per-minute TPM cap, NOT a spent budget. It's on Natalie's VS Enterprise sub (~$150/mo credit = the real "monthly budget"). See `/memories/repo/smart-garden-meter.md` for the exact `az` command.

**Tower can't run a strong local VLM.** GTX 970 = 4 GB VRAM. `moondream:1b` (1.3 GB) and `qwen2.5:3b` text (2.24 GB) fit fully on GPU. But `qwen2.5vl:3b` **vision** is **8.6 GB** → only 166 MB fit on GPU, rest on CPU → **minutes/frame, impractical.** So a GPU-resident vision model on this box is limited to ~≤3.5 GB (moondream-class, untested for digit accuracy). Bench script: `ocr-harness/bench_local_vlm.py` (vs gpt-4o truth in reread_cache).

**Azure AI Vision "Read" OCR — promising, cheap, but needs preprocessing.** Dedicated vision resource `water-meter-vision-382d9` is DELETED (DNS dead); use the live AIServices `smartgardenai1490` at `eastus.api.cognitive.microsoft.com` (AZURE_OPENAI_KEY works for `/computervision/imageanalysis:analyze?api-version=2024-02-01&features=read`). Bench script: `ocr-harness/bench_azure_read.py`. Result on 13 real frames: **the correct meter digits are usually present in the raw OCR** (e.g. `095361945` exact; `195376592` = right digits + stray leading `1`), but strict 9-digit match was ~8% because of: (1) SENSUS logo + "Mfg Date 06/2016 Replace by 06/2036" text on the meter face polluting the read, (2) a stray leading char (the "S" misread as `1`) shifting the number, (3) glare on the high `095` digits — the SAME failure that kills the CNN. A quick hand-guessed LCD crop made it WORSE (clipped digits; note the 180° rotation mirrors the crop box).

**Conclusion (reframes the whole problem):** OCR capability is NOT the blocker — **gpt-4o AND Azure Read both read these digits.** The universal missing piece across every method (CNN, gpt-4o, Azure, PaddleOCR) is **preprocessing: a correct tight digit crop + deglare + anchoring the static high `095` digits** (they barely change day-to-day). That's a bounded engineering task, not model-shopping.

**Recommended next step:** reuse the tower CNN's EXISTING digit-region crop ("loc2", on the tower at `/home/jack/meter-cnn/`, not in this repo) → feed that clean crop to Azure Read (cheap) → score. If cheap OCR nails a clean crop, it becomes the free always-available reader and the recurring loop is broken. Also consider: track low-digit deltas + re-anchor high digits daily; and (hardware, James-resistant) a pulse/reed sensor to skip OCR entirely.

**Tower networking gap:** `jackmint` (192.168.0.120) is on a FLAKY WiFi card — dropped to 100% loss under the model-download load, needed a reboot, ~12 ms/5% loss even when "healthy" (vs the NUC/Acer wired gigabit <1 ms/0%). TO-DO: wire it (onboard RJ-45 or a ~$15 USB-gigabit dongle like the Acer's). Not urgent for reads (tiny payloads, inference-bound) but essential for reliability if the tower becomes the primary reader.

---

## 2026-07-08 — Azure Read clean-crop benchmark: not enough with current camera quality

Context: James's immediate frustration is meter camera quality. We tested the highest-leverage idea from the OCR exploration: reuse the CNN's loc2 crop and feed clean crops to Azure Read instead of the noisy full frame.

Changes:
- Extended `ocr-harness/bench_azure_read.py` to benchmark crop variants (`legacy`, `loc2`, `loc2_pad`, `loc2_wide`, `digit_strip`, `digit_strip_pad`) and preprocessing variants (`rgb`, `gray`, `contrast`, `binary`) against the Jul 8 gpt-4o reread truth cache.
- Added optional `SAVE_CROPS=/tmp/...` output for visual inspection and suffix scoring (`suffix6`, `suffix5`) to measure whether Azure can at least read low digits for a future anchored-high-digits reader.
- Ran the harness on the Acer against archived meter frames and the live Azure AI Vision endpoint. No service/data changes.

Result:
- First focused pass (`N=6`, 9 picked frames after recency inclusion; `legacy`, `loc2`, `loc2_pad` x `rgb`, `contrast`, `binary`): best variant was only `loc2_pad/rgb`, `exact9=1/9`, `first6=1/9`. Contrast/binary generally made Azure read nothing.
- Second pass (`N=12`, 15 picked frames; `loc2_pad`, `legacy`, `digit_strip_pad`, RGB only): `best_any_variant` was `exact9=1/15`, `first6=1/15`, `suffix6=2/15`, `suffix5=3/15`.
- Visual crop inspection showed the real blocker: the current camera/crop often clips or washes out the left/high digits, while wider crops include crisp `Mfg Da` text that Azure reads instead of the faint LCD. Tight odometer strips remove the label but then Azure often reads nothing or only partial low digits.

Decision: Do **not** keep spending Azure calls on the current image stream as a reader. Azure Read may still be useful after camera/framing/lighting improves, but with today's camera quality it is not a cheap always-on replacement. The next lever is physical/image quality: get all 9 digits fully in frame with margin, reduce glare, and produce a crop where the odometer digits are sharper than the surrounding label text; then rerun `bench_azure_read.py`.

---

## 2026-07-08 — Creative software path: low-digit phase tracker prototype

Context: James said the camera quality cannot realistically be improved further and asked for software to get the rest of the way. The right reframing is **not** "read all 9 digits from one bad frame"; it is "track a monotonic physical counter over time."

Prototype:
- Added read-only harness `ocr-harness/eval_temporal_constrained_cnn.py`.
- It evaluates two non-OCR-style strategies against the Jul 6-8 gpt-4o truth cache:
  - tower CNN constrained decode: ask `/cnn?anchor=<lock>&ceil=<physical_window>` for the most likely value inside a plausible meter window.
  - suffix tracker: ignore broken high digits, use the CNN's low 3-5 digits as phase evidence, and choose the physically plausible next counter value whose suffix best matches.

Findings:
- Raw full-9 CNN exact remained `0/468`; full-frame OCR is the wrong target.
- Naively accepting every constrained decode eventually latches to a wrong high-digit path and fails over long windows.
- On a short 120-frame active-window sample, `suffix4_tol25` was promising: median error `6` counts (`0.045 gal`), `101/119` frames within `100` counts (`0.75 gal`), but with rare large slips.
- Over the full cache with 10-minute truth resets simulating sparse trusted anchors, `suffix4` still had a useful median (`65` counts = `0.486 gal`) but p95 failed from discrete `10k`-count slips. That is a guardrail/consensus problem, not a camera-quality problem.
- Event-local evaluation is the important result. Running `eval_temporal_constrained_cnn.py --events --summary-only` across 18 Jul 6-8 watering events showed:
  - raw full-9 CNN: `0/458` exact.
  - naive constrained full-value decode: median run-total error `2277.5` counts = `17.037 gal`; p90 `12013` counts.
  - `suffix4_tol25`: median run-total error `56` counts = `0.419 gal`; p90 `157` counts = `1.17 gal`; `348/458` frame locks within `100` counts.
  - worst suffix4 event was still off by `768` counts = `5.745 gal`, so this is not deployable without slip detection.
- James correctly pointed out the final camera location started earlier than Jul 6-8. Added archive-backed truth mode (`--truth-source archive`) and reran on post-final-location data from `2026-06-25T22:00:00`:
  - early slice through Jun 28: 9 events, `suffix4_tol25` was effectively exact (`median=0`, p90 `6` counts).
  - full post-final-location holdout: 87 events / 2971 evaluated frame transitions. `suffix4_tol25` had median run-total error `6` counts = `0.045 gal`, p90 `68` counts = `0.509 gal`, max `768` counts = `5.745 gal`, and `2813/2971` frame locks within `100` counts.
  - independent event-slope estimates did not beat greedy suffix4, but they are useful as a disagreement guard. With a 250-count greedy-vs-slope disagreement guard, 74/87 events would auto-accept with median `0.045 gal`, p90 `0.516 gal`, max `2.977 gal`, and 13 events would be flagged for sparse oracle/manual anchoring. With a 150-count guard, 62/87 events auto-accept, median `0.045 gal`, p90 `0.516 gal`, max `2.828 gal`, and 25 events are flagged.

Decision: The next software direction is a **run-local meter tracker**:
1. Keep high digits anchored from the last trusted oracle/manual/ledger anchor.
2. During active watering, use low 4 digit phase tracking plus physical max-flow and known zone-rate priors.
3. Require multi-frame consensus before allowing a suffix rollover or a 10k-count high-digit carry.
4. Hold/mark uncertain instead of committing when the tracker loses lock.
5. Use sparse gpt-4o/human anchors only to reset the high-order state, not to read every frame.

This is more promising than more Azure Vision calls on the current camera image. It is not ready to silently replace oracle/manual reads. Practical promotion path: use suffix4 as a **low-cost run estimator** with a quality grade. Auto-accept only when suffix4 and an independent event-slope check agree; otherwise mark the run `needs_anchor` and spend one sparse oracle/human read at the end of the run.

---

## 2026-07-08 - Phase-tracker decision layer tuned on final-location holdout

Context: After the first suffix-tracker result, James asked why the test was limited to Jul 6-8. The camera had been in its final location earlier, so the holdout was expanded to all archive-backed truth after `2026-06-25T22:00:00`.

Changes:
- Extended `ocr-harness/eval_temporal_constrained_cnn.py` with a production-shaped decision layer. It evaluates each watering event with:
  - greedy `suffix4_tol25` low-digit phase tracking.
  - independent event-slope estimate as a disagreement check.
  - suffix coverage, minimum frame count, and zone-rate prior checks.
  - `auto_accept` vs `needs_anchor` vs `reject` classification.
- Added decision-profile tuning output to the event summary. This is still read-only/offline; no live service or meter data was changed.

Validation:
- Full post-final-location holdout: `87` watering events, `2971` evaluated frame transitions.
- Raw full-9 CNN remained unusable for this purpose; the useful signal is the low 4 digits plus counter physics.
- Plain `suffix4_tol25`: median run-total error `6` counts (`0.045 gal`), p90 `68` counts (`0.509 gal`), max `768` counts (`5.745 gal`), frame locks within 100 counts `2813/2971 = 94.68%`.
- Tuned conservative profile: `guard_counts=400`, `min_coverage=0.85`, zone-rate ratio `[0.5, 1.8]`.
- That profile auto-accepted `40/87` historical events, marked `45` `needs_anchor`, and rejected `2`; accepted-event median error `0.015 gal`, p90 `0.374 gal`, max `0.711 gal`.
- Flag reasons across non-auto events: `low_suffix_coverage=22`, `zone_rate_outlier=25`, `too_few_frames=10`, `suffix_slope_disagree=3`.

Decision: Do not spend more effort trying to make Azure Read solve the current camera image. The better next implementation is a guarded event-local meter tracker: auto-commit only the conservative profile, mark the rest `needs_anchor`, and use one sparse oracle/human end anchor to resolve uncertain runs. This makes software absorb much of the bad camera quality without pretending every frame is readable.

Next:
- Implement the phase tracker behind a feature flag as a candidate event total provider, not as a raw per-frame reader.
- Store the decision grade and reasons on each event so Water Usage can show `auto_accept` vs `needs_anchor`.
- Keep oracle/manual anchors as the authority for flagged events and as periodic high-digit resets.

---

## 2026-07-08 - Phase tracker deployed in Water Usage shadow mode

Context: James wants the software path pushed as far as practical without silently corrupting the meter ledger. The first holdout used live tower HTTP reads; production can only depend on persisted `meter_reading.raw_reading`, so the deployed path was tuned against persisted raw evidence.

Changes:
- Added `server-prod/meter_phase_tracker.py`, a pure-Python read-only tracker that estimates event gallons from:
  - last committed reading before the event as the high-digit anchor.
  - raw CNN low-4-digit suffix during the event.
  - monotonic counter physics and max-flow ceiling.
  - independent event-slope estimate, suffix coverage, frame count, and zone-rate checks.
- Wired `/api/water-usage` to include `phase_tracker{}` and added a Water Usage card showing `auto_accept`, `needs_anchor`, and `reject` events. This is shadow mode only: `writes_ledger=false`.
- Deployed `meter_phase_tracker.py`, `dashboard.py`, and `templates/water_usage.html` to the Acer with timestamped backups and restarted `smart-garden-server`.
- Follow-up improvement: added `server-prod/tools/refresh_phase_tracker_cache.py` and `meter_phase_tracker.db`, a separate shadow cache of current tower-CNN reprocess reads. The API now uses a hybrid rule:
  - persisted ledger raw profile: `guard_counts=150`, `min_coverage=0.65`, zone ratio `[0.35, 2.5]`.
  - current-CNN phase cache profile: stricter `guard_counts=50`, `min_coverage=0.65`, zone ratio `[0.35, 2.5]`.
  - if both sources pass but disagree by more than 1 gallon, the event becomes `needs_anchor`.

Validation:
- Local and remote compile passed: `python3 -m py_compile meter_phase_tracker.py dashboard.py`.
- `/login` returned `200`; service restarted active.
- Authenticated `/api/water-usage?start=2026-07-08T00:00:00&end=2026-07-08T10:20:00&bucket_s=60` still reported total `823.76 gal`, integrity `missing_median=0`, `outlier=1`, and the tracker returned `13` events all `needs_anchor`. That is correct: several candidates are close, but persisted raw coverage/slope agreement is too weak in that repaired window and one event candidate is badly wrong.
- Long-window persisted-raw smoke test (`2026-06-25T22:00:00` to `2026-07-08T10:20:00`) returned `88` events: `20 auto_accept`, `56 needs_anchor`, `12 reject`; accepted-event max shadow error `0.576 gal`, p90 `0.554 gal`.
- Reprocessed the same long window through the current tower CNN into the separate phase cache (`5067` frames cached, no missing images/errors). A loose cache-only profile accepted `30` events but allowed a `1.13 gal` miss, so it was rejected.
- Deployed hybrid live result for that long window: `24 auto_accept`, `55 needs_anchor`, `9 reject`; accepted-event max shadow error `0.576 gal`, p90 `0.554 gal`; auto-accept sources were `10 ledger_raw`, `4 phase_cache`, `10 both`.
- After the strict `loc2-v9` retrain, refreshed the phase cache for the same `5067` frames. The live API still returned `24 auto_accept`, `55 needs_anchor`, `9 reject`; accepted-event max shadow error was `0.554 gal`, p90 `0.554 gal`. Auto-accept sources shifted to `13 ledger_raw`, `4 phase_cache`, `7 both`. This is a useful negative result: v9 improves the CNN benchmark, but it does not make the event tracker safe enough to broaden production auto-acceptance.

Decision: The safe deployed shape is now visible in the product: accept only when persisted raw or stricter current-CNN cache evidence is strong, otherwise surface `needs_anchor`. This is the closest software-only route to durable accuracy with the current camera because it prevents bad OCR from becoming invisible truth.

Next:
- Run shadow mode for new events and compare against authority/manual anchors.
- If the live card keeps accepted-event error under 1 gallon, add a DB-backed candidate table so decisions are retained historically.
- Only after retained shadow evidence stays clean should `auto_accept` events be allowed to fill missing event totals; `needs_anchor` must continue to require sparse authority/human confirmation.

---

## 2026-07-08 - Strict high-quality retrain promoted `loc2-v9`

Context: James asked whether more training should be done and specifically whether the dataset was limited to the highest-quality data. A normal retrain initially tried to include weak outside-tail labels; that was stopped. The accepted run used only oracle/reviewed training data plus the existing synthetic/recombined support, with outside-tail weak labels disabled.

Changes:
- Exported `348` newly reviewed high-quality archive labels before `2026-07-08T00:00:00` into the tower training bank.
- Ran a one-off strict tower retrain with `OUTSIDE_TAIL_TRUST=0.0`, `OUTSIDE_TAIL_MAX_ROWS=0`, and `OUTSIDE_TAIL_MAX_PER_LABEL=0`.
- The training log reported `1082` trusted propagation labels, `0` outside-tail labels, `7141` corrected manual overlay rows, `193` confirmed rows, and `8063` trusted labels in replay.

Validation:
- Champion `loc2-v8` hard benchmark: per-digit `0.817`, full-9 `0.498`.
- Challenger `loc2-v9` hard benchmark: per-digit `0.858`, full-9 `0.511`.
- Ground-truth replay improved from `0.936/0.798` to `0.946/0.806` digit/full-9 over `8063` trusted labels.
- Hard-frame eval: challenger fixed `5`, newly broke `2`, net `+3`.
- Regression set remained `0/9` for both champion and challenger.
- The gate promoted `loc2-v9`; tower `/health` now reports `version=loc2-v9`, model `/home/jack/meter-cnn/meter_cnn.pt`, threshold `0.95`.

Decision: This was the right retrain: high-quality labels only, hard-frame gate, no weak tail poisoning. It is a real incremental model improvement, not a full solution. The v9 phase-cache refresh did not broaden safe production auto-acceptance beyond `24/88` events, so Water Usage must keep treating the tracker as guarded shadow evidence until it has enough anchor coverage to prove broader accuracy.

Next: Keep collecting high-quality reviewed/oracle labels, but prioritize the event tracker and anchor workflow over chasing full-9 single-frame CNN accuracy. The near-term production improvement is to spend sparse trusted anchors on `needs_anchor` events, then let the low-digit tracker handle the easy events with explicit error bounds.

---

## 2026-07-08 - Phase tracker anchor queue deployed

Context: The shadow tracker was useful but still stopped at "needs_anchor" without making that state actionable. James pushed to keep going toward the actual goal: durable accuracy despite the camera.

Changes:
- Extended `meter_phase_tracker.db` with `phase_event_decision`, a shadow-only table that persists every tracker decision by `watering_event.id`.
- `/api/water-usage` now writes the current shadow decisions to that table whenever it evaluates a window. This does **not** write `meter_reading`, `watering_event`, `archive_frame`, or `flow_sample`.
- Added `/api/water-usage/phase-tracker/queue` to inspect persisted decisions by window/decision.
- Added `anchor_request{}` to each non-auto tracker event. It recommends two real-photo anchors: a start-side frame and an end-side frame, each with timestamp, image file, method/confidence, and a small frame-window for the existing photo modal.
- Updated the Water Usage tracker card to show anchor buttons for `needs_anchor`/`reject` rows. Buttons open the existing frame modal and correction flow around the recommended photo.
- Fixed early-reject tracker results so they keep `event_id`, `start`, `end`, and zone metadata; otherwise four insufficient-row rejects could not be persisted.

Validation:
- Local and remote `py_compile` passed.
- Deployed to Acer with timestamped backups and restarted `smart-garden-server`; service active.
- Full post-final-location window (`2026-06-25T22:00:00` to `2026-07-08T10:20:00`) still reports the same tracker decision profile: `24 auto_accept`, `55 needs_anchor`, `9 reject`.
- Persisted table now matches that live API exactly: `88` rows total with `24/55/9`.
- Queue check: all `55` `needs_anchor` rows have two recommended anchor frames.
- July 8 repair window remains unchanged: total `823.76 gal`, `missing_median=0`, `outlier=1`, and `13/13` events stay `needs_anchor`.

Decision: This is the correct next production shape. The software now separates "safe enough to estimate" from "needs sparse authority" and keeps a durable work queue without corrupting canonical history. The next promotion step is not automatic ledger writing yet; it is to resolve queue items with trusted photo/oracle anchors, compare the tracker candidate against those resolved totals, and only then allow `auto_accept` to fill missing event totals.

Next:
- Add a small resolver tool that consumes two trusted anchor readings for one queued event, computes the authoritative event gallons, and records the comparison in the phase DB.
- After enough resolved queue rows stay under the target error bound, add a guarded writer for `auto_accept` only. `needs_anchor` and `reject` must remain blocked until authority resolves them.

---

## 2026-07-08 - Resolver, guarded writer, and continuous timer shipped

Context: James correctly pushed that stopping at a queue still did not achieve the goal. The next requirement was an end-to-end path: evaluate, validate, safely apply only proven auto-accept totals, and keep running.

Changes:
- Added `phase_event_resolution` in `meter_phase_tracker.db`.
- Added `tools/resolve_phase_tracker_queue.py`, which resolves persisted tracker decisions against canonical ledger shadow truth and records candidate/authority/error/status.
- Added `/api/water-usage/phase-tracker/resolutions` and surfaced `resolution_summary` inside `/api/water-usage phase_tracker{}`.
- Added `tools/apply_phase_tracker_auto_accept.py`, a guarded writer for `watering_event.est_gallons/est_cf` only:
  - dry-run by default.
  - applies only `auto_accept_validated` rows.
  - requires promotion gate pass.
  - backs up `smart-garden.db` before writes.
  - records each write in `phase_event_apply`.
  - skips already-applied rows to avoid repeat audit spam.
- Added `tools/run_phase_tracker_pipeline.py`, an end-to-end runner:
  - optional phase-cache refresh.
  - local Water Usage API evaluation/persistence.
  - resolution scoring.
  - optional guarded auto-apply.
  - supports `--gate-start` so a small recent window can use the full validation corpus as the safety gate.
- Fixed an important feedback flaw: the tracker no longer prefers mutable `watering_event.est_gallons` as its prior when a zone prior exists. Zone median/estimate is the primary prior; event estimate is fallback only.
- Added a `frame_error_spread` guard: auto-accept requires `p95_frame_error_counts <= 100`. Evidence sweep showed this was the clean break point; `<=100` kept zero failures, while `<=125` let a `1.13 gal` bad accept through.
- Installed and enabled systemd timer `smart-garden-phase-tracker.timer` on the Acer. It runs every 30 minutes:
  - `run_phase_tracker_pipeline.py --days 2 --refresh-cache --apply-auto --require-integrity-ok --target-error-gal 0.75 --min-validated 20 --gate-start 2026-06-25T22:00:00`
  - The first timer run completed successfully as a no-op because current two-day integrity is not OK; blocked-by-integrity exits success so the timer stays healthy.

Validation:
- No-feedback + p95 guard full validation window (`2026-06-25T22:00:00` to `2026-07-08T10:20:00`): `34 auto_accept`, `45 needs_anchor`, `9 reject`.
- Resolver at `0.75 gal` target: `34` auto-accept rows, `0` failures, max accepted error `0.486 gal`.
- Guarded writer applied `43` validated event-estimate rows total (`24` before feedback fix, then `19` under the stricter p95/no-feedback profile), with backups:
  - `/home/jamesearlpace/meter-history-backups/20260708-215045-phase-auto-accept-preapply`
  - `/home/jamesearlpace/meter-history-backups/20260708-215816-phase-auto-accept-preapply`
- Post-apply dry-run is idempotent: `0` pending preview rows, `34` skipped as already applied under the current guard.
- July 8 hard window still has ledger total `823.76 gal`, `missing_median=0`, and the known `outlier=1`. The timer refuses current two-day auto-writes while that integrity warning is present.
- Timer state verified: `smart-garden-phase-tracker.timer` enabled/active; next run scheduled; last service run exited `0/SUCCESS`.
- Follow-up after the post-10:27 visual-anchor ledger repair: broadened validation back to camera cutover (`2026-06-24T17:03:00` to `2026-07-08T22:27:35`). Current result: `35 auto_accept`, `81 needs_anchor`, `17 reject`; promotion gate still passes at `<=0.75 gal` with `0` auto failures and max accepted error `0.486 gal`.
- Hardened long cache refreshes with `--allow-errors` so a single tower timeout is reported but does not abort an otherwise useful historical validation run.
- Adjusted `run_phase_tracker_pipeline.py --require-integrity-ok`: missing medians / error-severity warnings still block writes; median-outlier warnings alone do not. This matches the Water Usage semantics: outliers are review warnings, not proof the meter failed.

Decision: The production path is now end-to-end but guarded:
1. auto-accept only if tracker decision passes the no-feedback profile and p95 frame-spread guard,
2. validate against ledger shadow truth with target `<=0.75 gal`,
3. apply only validated auto-accept rows,
4. block recent-window auto-writes if Water Usage integrity is not OK,
5. keep all uncertain rows in the anchor queue.

Remaining hard limit: this still depends on the canonical ledger being correct enough to act as authority. When the ledger integrity card is not OK, the timer deliberately stops before canonical writes and leaves the queue for manual/oracle anchor resolution.

---

## TL;DR
- **✅ STUCK-LOCK ROOT CAUSE FIXED — self-healing now automatic (2026-06-23, see bottom entry "Self-healing stuck-lock recovery"):** The accuracy bug below (lock anchored wrong vs the glass, in EITHER direction) persisted because the per-frame physics cap (`ORACLE_MAX_ADVANCE`) blocked every honest correction once the lock was wrong by more than the cap — so the meter could only recover via a manual re-anchor. Root cause: **trust was gated by MAGNITUDE, not by EVIDENCE STRENGTH.** Fix: a consensus auto-heal — when many independent reads over minutes agree, cluster tightly (not erratic garble), and the authority model confirms on fresh frames, the system concludes the LOCK is wrong and auto-re-anchors to the live consensus (no hardcoded value, no human step). **Verified live:** lock auto-corrected `94740084 → 94791096` after a restart left it ~51 ft³ stale-low — 8 agreeing reads + 2 authority confirms over 208s, fully automatic. Works in both directions for any future stuck-lock cause.
- **🚨 ORIGINAL ACCURACY BUG (2026-06-23 — see bottom entry "Archive readings anchored ~42 ft³ high"):** The archive/history readings were reading **HIGH vs the physical meter glass** (e.g. system `094830801` while the LCD plainly shows `094788507`, ~+42 ft³ / ~315 gal). Systematic (positions 4–9), and the wrong values increase smoothly frame-to-frame, so the dashboard looked healthy. The **persistence** of this (the lock being unable to self-correct) is now fixed by the auto-heal above; per-frame read accuracy under glare is still imperfect but the system now recovers automatically instead of staying stranded.
- **▶ CURRENT STATE (2026-06-21 evening — START HERE; full detail in the bottom entry "Oracle-arbiter redesign"):**
  - **The oracle is the reader; the CNN is dead weight on the live path (~0%).** Architecture now: `gpt-4o-mini` does every cheap heartbeat read; `gpt-4o` confirms ONLY when the lock is about to MOVE (a correction), read unbiased. Lock = monotonic physics model the oracle can correct **both directions** (down-correction added — it can self-heal after an over-read).
  - **Accuracy (verified by independent audit): whole cubic foot 100% correct; last 2-3 digits lag/jitter ~hundreds of counts because the image is too blurry to read them.** Whole-cf is the honest ceiling — James will NOT buy a polarizing lens, so don't propose hardware fixes.
  - **How we measure it (the only non-circular way):** `meter_audit.py` + `meter-audit.timer` (every 20min, READ-ONLY, own `meter_audit.db`) reads each frame unbiased with BOTH models and logs lock_error / staleness / agreement / down-corrections. Run `meter_audit.py --report --hours=48`. **COST: ~$5-11/mo if left on** — stop with `sudo systemctl disable --now meter-audit.timer`.
  - **Git:** committed `f784305` in `c:\MyCode\smart-garden` (server-prod/), **NOT pushed**. Edit-mirror `smart-garden-server-live` is NOT a git repo; canonical tracked copies are in `smart-garden/server-prod/`.
  - **Open:** watch 24-48h audit to confirm it holds + catches a real overshoot. Constrained decode stays DISABLED (positive-feedback flaw).
- **(2026-06-21 CORRECTION) The LIVE CNN accuracy is ~0% on current frames, and has been for days** — graded by the oracle (`cnn_daily` table): 28% on 06-15 → 0% since 06-16 across v3/v4/v5. The offline benchmark (0.82) is MEANINGLESS for the live operating point.
- **The GPT-4o vision oracle is what actually keeps the meter readable** — the CNN falls back to it thousands of times/day. When the oracle's OpenAI quota dies (HTTP 429), there is NO working reader → display goes stale → user pain. That IS the failure chain (confirmed in logs 2026-06-21).
- **Re-anchoring manually does NOT train anything** — it only sets the lock momentarily; the next frame collapses again. Bailing water, not fixing the leak.
- **The quality-measurement system already exists**: `cnn_metrics.py` logs every oracle-vs-CNN comparison into `cnn_eval`/`cnn_daily` (live CNN accuracy time-series per version, free). It just had no UI and no oracle-down alert.
- **What actually fixes it:** (1) keep the OpenAI oracle funded (billing), (2) surface live accuracy + oracle health so failures aren't silent, (3) the oracle auto-banks every CNN miss as a gold correction (cnn said 094009→oracle 094596) — those current-glare frames train the CNN up from 0% over future retrains. The lock is a safety net, NOT "~100% correct."

## (superseded) earlier TL;DR
- ~~The system reading (running total / cost) is already ~100% correct~~ — the
  monotonic lock holds the true value and rejects bad per-frame reads.
- **Per-frame CNN accuracy is 95.1% per-digit / 67.3% full-9**, capped by (a)
  glare-degraded pixels and (b) noisy, leading-edge-starved training labels.
- **Multi-frame fusion does NOT fix it** (proven offline) — the glare bias is
  systematic, not random, so fusing correlated-wrong reads gives a confidently
  wrong answer.
- The only real levers for *per-frame* accuracy: **train on corrected glare
  frames** (the `/cam/review` + `/cam/test-audit` loop) and **reduce glare**
  (a ~$10 polarizing film). Not fusion, not more tracker code.

---

## SCOREBOARD (single source of truth — update on every promotion)

| Champion | Per-digit | Full-9 | Date | What it beat / note |
|----------|-----------|--------|------|---------------------|
| v5 | 0.9518 | 0.6726 | 2026-06-20 | current champion; synth+weighting and glare-aug both TIED, not promoted |
| v5 (re-measured) | **0.9601** | **0.8203** | 2026-06-21 | SAME model, scored on CLEANED benchmark — 0.673 was a wrong-label artifact. first-7=0.9141, first-6=0.9453. |
| v6 (NOT promoted) | 0.969 | 0.784 | 2026-06-21 | Trained on 52 new gold corrections. Better per-digit (0.969>0.958) but full-9 0.784<0.808 AND hard-frame net −3 (fixed 6, broke 9). Lateral/worse → KEEP v5. Gate worked. ~38min run (cache+early-stop). |

**Failed experiments (do NOT re-propose without new evidence):**
1. **Naive multi-frame fusion** — glare is systematic (constant over seconds); fusing correlated-wrong reads = confidently wrong. Offline-proven.
2. **Naive context-decoder** — overwrote fast low digits from a stale prior, 93%→66%; position-aware recovered to ~92% but never beat raw. Shelved.
3. **Aggressive augmentation stacking** — glare 0.55 + perspective + noise + jpeg cratered an 8-ep smoke to 0.142. Aug must stay harder-but-READABLE.
4. **Glare augmentation (softened)** — full retrain 0.664 vs 0.673, hard-frame net −1. Kept v5.
5. **Synthetic recombination + trust weighting** — full retrain EXACT TIE 0.6726. Kept v5.

---

## 2026-06-21 — FULL SESSION LOG (timestamped)

A long session that went from "polish the benchmark audit" to discovering the
live reader was 0% and shipping the real fix. Chronological:

| Time | Event | Commit |
|------|-------|--------|
| ~10:00 | **Smart benchmark audit** — `/cam/test-audit` runs the CNN per held-out frame, flags ONLY where it disagrees with the stored label (52/129 suspicious). James cleans labels. | `a97800b` |
| ~10:10 | **Remove button** on audit cards — discard cut-off/garbage frames to `~/meter-training/_discarded/` (reversible). | `0f4ca74` |
| ~10:15 | **Reviewed frames drop off** the suspicious list (corrected=True) so they stop reappearing on refresh; "N left to review". | `85594fe` |
| ~10:30 | **Benchmark composition analysis** + scoreboard + failed-experiments list added to this doc. | `0d309d4` |
| ~10:45 | **Honest re-measure on cleaned labels:** full-9 **0.8203** (was 0.6726), first-7 0.9141, per-digit 0.9601. The 0.673 was a WRONG-LABEL artifact — same model. | `2e64302` |
| 11:02–11:41 | **v6 retrain** on 52 new gold corrections. Result: per-digit 0.969 (>champ) but full-9 0.784 (<0.808) AND hard-frame net −3 (fixed 6, broke 9). **KEEP v5** — gate worked, v6 was lateral/worse. Run = 2324s (~38min). | — |
| ~11:50 | **Regression set** built — permanent hard-fail tests; `/cam/regression` page + ⚓ button; trainer forces them into TEST + gate blocks regressing on them. Seeded 10 (champ 0/10). | `3584c48` |
| (earlier) | **Retrain speed:** frame cache (`8471bd9`, ~15min faster, bit-identical) + early-stop (`59e8874`, ~25% faster, keeps best). GPU unusable (torch is CPU-only build; GTX 970). | — |
| ~12:10 | **Lock found STALE** (~29 min behind). James: "it's awful." Re-anchored manually to `094594906`, then the meter had advanced → `094596953`. | — |
| 12:31–12:47 | **ROOT CAUSE found in journalctl: HTTP 429 — OpenAI quota exceeded.** The GPT-4o oracle (the thing that keeps the meter readable when the CNN can't) was failing on every call. At 12:47 quota recovered and the system self-healed (re-anchor + auto-bank). | — |
| ~13:00 | **`/cam/quality` page + oracle-down RED alert** — surfaces the existing `cnn_metrics` oracle-graded CNN accuracy time-series + flags a quota outage instead of silent staleness. | `8b72757` |
| ~13:05 | **LIVE CNN accuracy revealed: ~0%** (cnn_daily: 28% 06-15 → 0% since 06-16). Offline 0.82 is meaningless for live. The oracle carries everything (thousands of fallbacks/day). | — |
| ~13:20 | **NEW HARD BENCHMARK** — test set = held-out oracle-caught CNN failures (529 hard frames, 195 current-edge). Champion v5 = **0.655** full-9 on the honest set (vs fake 0.82). Easy frames pushed to train. Retrain launched on it. | `8408fba` |
| ~13:40 | **CONSTRAINED DECODE (James's idea)** — offline test PROVED 0%→100% in-window on 60 live frames. Built into CNN service (`/cnn?anchor=&ceil=`) + live worker. **LIVE: display now reads `094598961` correct/high-conf** off the frames raw CNN garbles. Keeps lock fresh for FREE → slashes OpenAI cost. Env-gated, fresh-lock-only, forward-only bounded. | `a2a60e8` |

### Key numbers locked this session
- **Live CNN raw accuracy on current glare frames: 0%** (the real metric; offline 0.82 was a mirage).
- **Constrained decode: 0% → 100% in-window** on live frames (the fix).
- **Champion v5 on the HARD benchmark: full-9 0.655** (the honest bar going forward; was fake 0.82 on easy frames).
- **Hard-frame material available: 529** oracle-caught CNN failures, 195 current-edge.

### The corrected mental model (supersedes everything above)
1. The tiny CNN **cannot** read current high-glare frames raw (0%).
2. **Constrained decode** (read within the lock's plausible window) rescues it for FREE and keeps the display fresh — the primary live reader now.
3. The **GPT-4o oracle** is the recovery path (cold/stale lock) + drift spot-check + the source of gold training labels — used SPARINGLY now (cost control).
4. The **CNN itself** improves over retrains as oracle-banked current-glare frames accumulate, judged on the **hard benchmark** (the only honest gate).
5. **`/cam/quality`** shows the live truth + a red alert when the oracle (OpenAI) quota dies.

### Open follow-ups
- Keep OpenAI billing funded (oracle is the recovery + training-label source). Watch `/cam/quality`.
- Verify oracle call rate actually dropped after constrained decode (cost win) — check `cnn_daily.oracle_calls` trend.
- Hard-benchmark retrain result (launched ~13:21) — did a challenger beat champion's 0.655 on the hard set?
- Consider widening the constrained window / lowering oracle cap once the raw CNN improves.

---

## 2026-06-21 — Benchmark composition: 0.673 is partly a wrong-label artifact

Read-only analysis of the 128 held-out benchmark frames (during James's `/cam/test-audit` label cleaning):

- **NOT "easy historical frames."** Spans the meter's whole life `094009`→`094546` (current leading edge), fairly evenly, with a 9-frame cluster at the current value. **66% (85/128) are low-confidence / glare-hard.** Good, honest coverage — the doc's "benchmark of easy frames" worry is unfounded *for this set*.
- **Cleaning is visibly working:** champion–label disagreements dropped **52 → 25** as James fixed wrong labels. Champion now agrees with the cleaned label on **103/128 = 80%** — i.e. the frozen 0.673 was **depressed by wrong TEST labels, not a weak model.** True full-9 is climbing toward ~80%+.
- **Errors are concentrated in the LAST 2 digits.** Per-position mismatch (pos0=leftmost): `0,0,0,5,6,5,7,11,20`. pos7–8 = 31 of all mismatches; pos8 (ones-of-cf) alone = 20. High-order digits (pos0–6, which drive the usage total) are near-perfect; the wobble is the fast-spinning, mid-roll, **low-impact** last digit.
- **Reframe the metric:** full-9 over-penalizes the one digit that's hardest *and* least important. **First-7-digits accuracy** reflects real-world correctness and is likely >95%. Consider scoring/gating on first-7 (or weighting pos8 down) so real gains aren't masked by an unwinnable last-digit fight.

### Honest re-measure after cleaning (2026-06-21, 128 frames)
- **full-9 0.8203, first-7 0.9141, first-6 0.9453, per-digit 0.9601.** The frozen 0.6726 was a wrong-label artifact — the model never changed.
- Per-digit: pos0-2 100%, pos3-6 ~96%, pos7 93.8%, pos8 85.2%.
- 23 remaining full-9 misses = ~18 pos8 last-digit wobble (low-impact, mid-roll, ~unwinnable) + **5 glare-collapse on the CURRENT leading edge** (094530-094546 read as 094000xxx). The 5 collapse frames are the ONE real lever: bank+retrain on corrected current-glare frames.
- **GATE CAVEAT:** this eval used the Acer's cleaned labels (manual_labels overlay) via the live `/cnn`. The TOWER trainer's champion/challenger gate must use the SAME cleaned labels or it still measures 0.673 and won't see real gains. Verify label sync Acer->tower before next retrain.

---

## 1. The goal
James wants near-100% meter reading. Current per-frame CNN: **95.1% per-digit,
67.3% full-9** (0.951⁹ ≈ 0.63, consistent). To hit 99% *full-9* you'd need
**99.9% per-digit** — unreachable per-frame by training alone when the input
pixels are glare-degraded. Reframe: the target is **system-level ~100% on the
running total**, which is already achieved by the lock.

## 2. Training-data audit — the smoking guns
Audited 1,188 banked frames:

| Finding | Detail |
|---|---|
| **91% AI-labeled** | 1,078 oracle (GPT-4o), 93 auto, only **17 human**. |
| **~10%+ label error** | 107 manual corrections overrode a *wrong* oracle filename label — and that's only the ones caught. |
| **Long-tail per-digit** | pos 0/1/2 = `0`/`9`/`4` **100% constant** (model just parrots them); pos 3 only **6/10** values (dominated by `1`); pos 4–8 full 0–9. |
| **Leading-edge starvation** | The meter just climbed `0941xxx → 0945xxx`, so pos-3 `5` is barely in training → CNN collapses pos 3–5 to `000` (reads `094000661` vs true `094546764`). |
| Clean of corruption | manual == propagated (0 conflicts); propagation: anchor 304, confirmed 663, repaired 64, flagged 48, outside 54. |

**Core lesson: the CNN is always weakest at the LEADING EDGE** — the newest
high-digit values the meter just reached, where real labeled data is near-zero.

## 3. Model-quality upgrades (shipped, commit `dfdc58e`)
All in `~/meter-cnn/retrain.py` (tower) unless noted.

1. **Synthetic digit recombination.** The model pools width into 9 even columns
   (`AdaptiveAvgPool2d((1,9))`), so each digit ≈ 1/9 of the 256-px crop.
   `build_digit_library()` slices confidently-labeled TRAIN frames into 9 cells →
   `lib[d]` = real strips per digit 0–9 (pooled across *all* positions, so every
   digit has real examples even where a position never showed it). `synth_rows()`
   reassembles real strips into values the meter hasn't reached yet (prefix `094`
   fixed, pos-3 biased 5–9, pos 4–8 uniform). **Photorealistic, zero new human
   labels.** +600/retrain, TRAIN-ONLY (never the permanent hash holdout).
   `--no-synth` disables.
2. **Trust-weighted loss (oracle cleaning).** `gather_labels()` returns
   `(clean, trust)`; per-sample weights human **3.0** / anchor **2.5** / repaired
   **2.0** / confirmed **1.5** / oracle **1.0**. `CrossEntropyLoss(reduction='none')*w`.
   Noisy raw-oracle labels pull the model less.
3. **Active-learning queue** (Acer: `dashboard.py` + `cam_review.html`).
   `GET /api/cam/review-queue` lists frames the live pipeline couldn't read
   (`fresh_read` False + frame exists), newest first. `/cam/review` page shows
   each with on-demand CNN read + one-tap fix. Concentrates scarce human
   correction time on exactly the failing frames.

Plus dataset support for in-memory synthetic rows `{"img": 64×256 float32}` and
an `--epochs N` override for smoke tests.

## 4. Benchmark audit tool (shipped, commit `ba1ed8c`)
The held-out TEST set is ~91% oracle-labeled, so a **wrong test label caps
measured accuracy** (a correct model looks wrong, real gains stay hidden, the
gate stays blocked). `GET /api/cam/test-set` lists the held-out frames (same hash
as the trainer: `int(sha1(name),16)%100 < 12` → 129 frames). `/cam/test-audit`
page: each frame + label + **✓ Confirm / Fix** → `manual_labels.jsonl` (gold).
Cleaning the test labels makes the gate trustworthy and may reveal the model is
already better than 0.673. **(James to run — ~20 min of clicking.)**

## 5. Full retrain result — an exact tie
Ran the full 60-epoch gated retrain (`--force`, ~66 min):

```
CHAMPION v5  : per-digit 0.9518  full-9 0.6726
CHALLENGER v6: per-digit 0.9508  full-9 0.6726   ← exact tie
12:53 KEEP v5: strict: 0.673 <= champion 0.673
```

Trajectory: ep10 0.416 → ep30 0.575 → ep40 0.655 → ep50 0.664 → ep60 0.673.
The strict gate requires a *beat*, so a tie keeps v5 — model untouched.

**Why a tie:** the held-out benchmark is mostly *historical* `094xxx` frames the
model already nails, so it's **blind** to the synthetic data's real benefit
(reading the new `0945xx` edge). The benchmark *understates* v6's value. On KEEP
the challenger weights are discarded, so "shipping v6" would need a re-run with a
relaxed gate (~66 min) — not worth it for a measured tie. Let the synthetic +
weighting + `/cam/review` corrections compound in the **nightly** retrains; once
real `0945xx` corrections are in the train set, a future challenger will actually
beat 0.673 and promote on its own.

## 6. The fusion experiment — a useful NEGATIVE result
Hypothesis: median-fusing consecutive static frames would kill glare and improve
reads. **Tested offline before touching the live reader.** Compared single vs
median-of-5 CNN reads over a 150-s window (high-6 digits *cannot* change that
fast, so any variation = CNN error):

| | High-6 agreement | Distinct |
|---|---|---|
| Single frame | 30% | 4 |
| Median-fused | **46%** | 4 |

Fusion improved *consistency* (30→46%) **but the consensus was still WRONG** —
every read landed in `094000`–`094401`; the true value is `094546`. **Why:** the
glare is roughly *static* over seconds, so the CNN makes the *same* wrong guess
on every frame; median-fusing correlated-wrong reads = confidently wrong. Fusion
removes *random* noise, not *systematic* glare bias.

**Decision: do NOT deploy fusion.** It adds complexity and could entrench wrong
reads. The offline test cost ~10 min and saved a useless, risky live change.

## 7. The key insight: the system reading is already correct
At the same moment the CNN was reading `094000xxx`, the lock held
**`94546642`** (= 094546.642 ft³, the true value). The monotonic guard
**rejects every backwards garbage read** (you can't drop below the lock). So:
- The number that matters — running total, cost, usage — is **already ~100%**.
- The per-frame CNN being wrong does **not** corrupt it.
- The "monotonic tracker" idea is therefore **unnecessary** — the existing lock
  *is* that tracker, working as designed.

## 8. The real roadmap to per-frame ~100%
1. **Clean the benchmark** → `/cam/test-audit` (live; James's move). Tells the
   true score, unblocks the gate.
2. **Correct glare frames** → `/cam/review` feeds `0945xx` corrections into the
   nightly retrains. The actual model fix.
3. **Reduce glare** → a ~$10 polarizing film over the lens. The biggest physical
   lever; no model reads pixels the glare erased.
4. Nightly retrains (now armed with synthetic + weighting) compound automatically.

What does NOT help: multi-frame fusion (systematic glare), a new tracker (the
lock already does it), or more training without attacking glare/labels.

---

## Reference

**Files**
- Trainer: tower `~/meter-cnn/retrain.py` ↔ local `c:\MyCode\smart-garden\cnn\retrain.py`
- App + lock: Acer `~/smart-garden-server/dashboard.py` ↔ live mirror
  `c:\MyCode\smart-garden-server-live\dashboard.py` ↔ git `server-prod/dashboard.py`
- Pages (server-prod/templates, NOT live mirror): `cam_review.html`,
  `cam_testaudit.html`, `cam_reading.html`

**Endpoints**
- `GET /api/cam/review-queue?n=N` → frames to correct (active learning)
- `GET /api/cam/test-set?n=N` → held-out benchmark frames
- `GET /api/cam/reading/<rid>/cnn-read` → on-demand CNN read of a frame
- `POST /api/cam/usage-correct {label, id|file}` → write a gold correction
- Pages: `/cam/review`, `/cam/test-audit`, `/cam/reading/<rid>`

**Key numbers / dirs**
- Champion v5: 0.9518 per-digit, 0.6726 full-9. Gate = strict full-9 beat.
- Held-out hash: `int(sha1(name),16)%100 < 12`. ~67s/epoch, 60 epochs ≈ 70 min.
- Tower CNN: `http://192.168.0.120:5201/cnn`. Frames: Acer `/tmp/meter-frames`.
- BANK_DIR (gold frames) Acer `~/meter-training`; labels `~/cnn-dataset-oracle`.

**Tower deploy + retrain**
```
# deploy retrain.py: scp local -> Acer:/tmp -> tower:~/meter-cnn/ (backup first)
ssh Acer "ssh tower 'cd ~/meter-cnn && nohup ~/meter-ocr/.venv/bin/python \
  retrain.py --force > /tmp/retrain_full.log 2>&1 & echo PID-$!'"
# monitor: ~/meter-cnn/retrain.log (logs at ep%10 + final); retrain_status.json
```

---

## 2026-06-21 (evening) — Oracle-arbiter redesign: down-correction, hybrid, + independent audit

Constrained decode stayed DISABLED (commit `5d7241b`, positive-feedback drift flaw). Instead, made the **oracle the arbiter** that can move the lock both directions, cut cost, and — crucially — **built the first non-circular way to measure if the display is actually right.**

**Changes (deployed to Acer, healthy; git = `server-prod/`):**
- **Cost:** `ORACLE_MODEL=gpt-4o-mini` heartbeat (systemd drop-in). ~15-20x cheaper than gpt-4o.
- **Down-correction** (`dashboard.py _oracle_run`): the lock can now self-heal DOWN after an over-read. Fires only when the oracle's WHOLE-cubic-feet (`//1000`) is below the lock's (a real overshoot, never last-digit jitter). Splice guard stops a correct below-lock read being forced forward.
- **Hybrid arbiter:** mini does every cheap heartbeat read; **gpt-4o confirms ONLY when the lock is about to MOVE** (a correction), read UNBIASED (`hint=None`) so the lock's prefix can't bias it. Must agree on whole-cf or the move holds (fails safe). `vision_oracle.read_meter(model=...)` per-call override.
- **Independent audit** (`meter_audit.py` + `meter-audit.timer`, every 20 min, own `meter_audit.db`, READ-ONLY): samples the latest frame, reads it unbiased with BOTH models, logs `lock_error` vs that truth, staleness, two-model agreement, and down-corrections. `--report` summarises. **This is the only non-circular measure** — the oracle can't grade itself once it drives the display. Dark-frame skip avoids paying for black night frames.

**First live numbers (the honest answer to "is it accurate?"):**
- Lock vs independent dual-model truth: **whole cubic foot 100% correct**; last-3-digit error ~−522 counts (≈4 gal, lock lagging slightly behind active flow). Two-model agreement 100%. Staleness fine (~66s).
- The image genuinely can't yield the last 2-3 digits reliably (blurry/glared) — **whole-cf is the honest accuracy ceiling**, and we're hitting it.

**Corrected mental model (supersedes the constrained-decode model above):**
1. Live CNN ≈ 0% on glare frames — dead weight on the live path (cnn_eval: reads the middle digits totally wrong).
2. **The oracle is the reader.** mini = heartbeat, gpt-4o = authority on moves. Lock = monotonic physics model the oracle can correct both ways.
3. **The audit is how we know it works** — error/staleness/correction numbers from independent unbiased reads, not self-grading.

**Cost note (watch):** audit = 1 mini + 1 gpt-4o every 20 min, daylight-gated. ~$5-11/mo if left on 24/7. Stop with `sudo systemctl disable --now meter-audit.timer` after the measurement window, or lower the cadence.

**Next:** (a) read the 24-48h audit report to confirm it holds + catches a real overshoot; (b) consider mini-only on most audit samples + gpt-4o every Nth to cut cost; (c) forward-reads-never-corroborate-during-fast-flow is a separate pre-existing gap.

---

## 2026-06-21 (evening, pt 2) — CNN viability KILLED by data + literature. STOP re-proposing it.

Spent the rest of the session honestly stress-testing whether the CNN could be salvaged (narrow scope, bigger model, different architecture). Conclusion: **no — and don't revisit without new hardware.** Three independent lines of evidence:

**1. Per-position accuracy (399 real frames, cnn_eval vs oracle truth):**
- `p0:100% p1:100% p2:100%` (constant `094`, parroted) → `p3:5% p4:50% p5:55% p6:65% p7:61% p8:42%`.
- Last-N-digit exact: last1=42%, last2=29%, **last3=25%**, last4=23%, full9=0%.
- The "CNN reads the fast low digits well" belief was an ILLUSION from a few lucky frames. It reads NO digit position better than 65%. The narrow-scope "CNN does last 3, logic does the rest" idea is dead: 25% on the last 3.

**2. Root-cause split (what's actually wrong, from the per-position data):**
- **High changing digit (p3=5%) = DATA problem (leading edge), NOT glare.** Same glare didn't stop p0-2 reading 100%. The meter sits at one value for weeks → almost no training examples of the new digit → collapse. The edge keeps moving as the meter climbs, so it never resolves.
- **Fast low digits (p6-p8, 42-65%) = genuine IMAGE-QUALITY ceiling.** These cycle 0-9 constantly so they have FULL training coverage — yet cap at ~60%. That gap IS glare+blur+soft-lens. Even with perfect data, glare alone holds the low digits ~60%.
- **Camera angle/position drift = minor.** Proven: constant digits read 100% through all the drift; the generous crop + augmentation absorb it. Not the bottleneck.

**3. Literature (Laroca et al., the AMR research field — UFPR-AMR 2019, Copel-AMR 2021):**
- SOTA real-world AMR (12,500 field images, glare/dirt/rotation) reports **">99% recognition WHEN REJECTING low-confidence reads."** i.e. they hit 99% by NOT reading the hard frames — they reject + defer. That is EXACTLY our reject-to-LLM architecture. The literature validates what we built; it does NOT offer a CNN that reads glare frames.
- Their novel stage = corner-detection + perspective rectification → targets ANGLE/rotation, which we proved isn't our bottleneck.
- Their CNNs generalize because they train on THOUSANDS of DIFFERENT meters. We have ONE meter with a climbing leading edge → their diversity advantage doesn't transfer. Our single-meter coverage problem is structurally different (and in that sense harder).

**VERDICT:** The reader IS the LLM (gpt-4o-mini heartbeat + gpt-4o on moves). The CNN is dead weight on the live path and cannot be rescued by narrowing scope, a bigger model, or a different architecture on THIS hardware/data. The only theoretical paths left both need things James has ruled out or that don't pay off: (a) reduce glare = hardware (declined); (b) thousands of diverse meters = N/A; (c) distill gpt-4o reads into a bigger local student model = still hits the same glare information-loss wall, and `mini` already killed the cost motive. **Whole-cubic-foot is accurate and that's the win. Don't spend more nights on the CNN.**

## 2026-06-22 — Codex evaluation + lock-arbiter hardening

### What we measured (explicitly excluding outage concerns)
- Live cam telemetry proved there was a real outage/stale window (long lock-age rows with missing model reads). Per your instruction, those periods are now separated from quality scoring.
- Raw 24-48h audit headlines were still noisy (hallucinated `54xxxxxx`/`59xxxxxx` high-confidence reads and outage-stale rows), so the single raw metric was misleading by itself.
- On current blurry frames, unbiased authority reads frequently flip the leading digits (`94...` -> `54...`) and fail lock-moving confirmations even when heartbeat/corroboration are stable.

### Deployed fixes (Acer `~/smart-garden-server`)
1. `dashboard.py` authority confirm fallback:
  - Keep the first authority pass unbiased (`hint=None`).
  - If that fails on a FORWARD move, do one extra soft-hinted authority read anchored to the heartbeat candidate.
  - This is constrained to avoid creating new drift paths.
2. `dashboard.py` authority match rule:
  - Replaced strict whole-cf floor equality with count tolerance (`METER_ORACLE_AUTH_MATCH_COUNTS`, default `1000`) to avoid false disagreement at cubic-foot boundaries.
3. `dashboard.py` soft-hint safety cap:
  - Added `METER_ORACLE_SOFT_HINT_MAX_ADVANCE` (default `2500`) so soft-hint fallback cannot authorize large idle jumps from ambiguous frames.
  - Large moves still require stronger evidence and stay blocked by existing physics guards.
4. `meter_audit.py` trusted reporting subset:
  - Added outage/sanity-aware scoring in report output:
    - excludes dark/no-frame rows,
    - excludes stale outage-like rows (`METER_AUDIT_OUTAGE_STALE_S`, default `7200`),
    - requires model agreement,
    - filters obvious hallucinated value ranges.
  - Keeps the original raw report AND adds a trusted-subset section so we can compare honestly.
5. `dashboard.py` near-lock jitter refresh:
  - If oracle value is within the authority match tolerance of the current lock, treat it as same-state jitter and refresh lock time without moving the value.
  - This prevents fake "stale" conditions when blurry frames wobble a few digits around the same reading.

## 2026-06-23 — Long-term frame archive (1/min, 30 GB cap)

- Added a rolling, disk-capped image archive in `dashboard.py` (`_archive_frame` / `_archive_init`, hooked in `cam_upload`).
- Behavior: saves ONE cam frame per `METER_ARCHIVE_INTERVAL` (default 60s) to `METER_ARCHIVE_DIR` (default `~/meter-archive` on the Acer, persists across reboots), and FIFO-evicts the oldest files once the total exceeds `METER_ARCHIVE_MAX_BYTES` (default 30 GiB).
- The ESP32-CAM still pushes every ~5s for OCR accuracy; only the long-term archive is throttled to 1/min, so reading resolution is unchanged.
- Independent of the small inspection ring (`/tmp/meter-frames`, ~720 frames) and the training bank (`~/meter-training`).
- Surfaced in `/api/cam/status` under `archive` (files, gb, cap_gb, saved/evicted this session).
- Acer has 313 GB free, so 30 GB fits easily; at ~50 KB/frame and 1/min that's ~440 days before the cap starts rotating.
- Deployed + verified: archive inited "0 files", wrote the first frame on the next upload, and held at 1 file across multiple 5s uploads (throttle confirmed).

## 2026-06-23 — Archive history browser + per-image review + accurate usage graphs

James shifted the focus from real-time to **accurate historical insights**: show the full archived image history, let him review/refresh the value derived for any image, and graph water consumption accurately over time.

- **New module `meter_archive.py`** (isolated, own `meter_archive.db`, like `meter_audit.py`): one row per archived image — `ts, filename, reading, reading_cf, confidence, source, reviewed`. Helpers: `record`, `update_reading`, `delete_by_filename`, `get`, `neighbor_reading`, `bounds`, `list_range`, `count_range`, and `usage_series` (monotonic, physically-capped positive deltas → gallons, bucketed).
- **Free baseline reading per image:** `_archive_frame` now indexes each archived frame with the **live lock value at capture time** (`source=lock`). No per-image API cost — the live 5s OCR keeps the lock current; the archive just snapshots it once a minute. Evicted images' rows are pruned (`delete_by_filename`) so the DB tracks the rolling files.
- **On-demand refine** (the "review if something seems off" path):
  - `POST /api/cam/archive/reread {ts}` → reads that exact image with **gpt-4o** (accurate reader) + soft neighbor hint, updates the stored reading (`source=oracle`). Does NOT touch the live lock.
  - `POST /api/cam/archive/correct {ts, value}` → human 9-digit correction (`source=manual`, `reviewed=1`).
- **Accurate history graph:** `GET /api/cam/archive/usage?minutes=N` → `usage_series` sums only monotonic, plausibility-capped deltas (a single bad image can't fabricate usage), so correcting wrong readings makes the graph more accurate.
- **New page `/cam/archive`** (`cam_archive.html`): range chips (1h–30d), a gallons-per-bucket bar chart + cumulative line (Chart.js), and an image-history grid where each photo shows its derived reading with **Re-read (AI)** and **Fix** buttons. Nav link "🗂️ Meter Archive" added to `index.html`.
- `/api/cam/archive` lists images paginated (window/limit/offset/order, optional unreviewed filter) + archive bounds (total/oldest/newest).
- Deployed + verified: schema created, first frame indexed (`94740084` = 94740.084 ft³, source lock), `usage_series` runs clean, all routes return 200.
- NOTE: only images archived AFTER this deploy are indexed (the ~13 min of pre-index archive frames have no reading rows — negligible). Going forward every 1/min image is indexed.
- These changes improve decision quality without reopening the catastrophic jump/crash classes we already closed.
- Internet-down windows are now explicitly excluded from the quality score so they do not pollute model/arbitration evaluation.

## 2026-06-23 — OPEN BUG: archive readings anchored ~42 ft³ high vs the physical glass

**Observed (from the `/cam/archive` history grid, screenshot reviewed):**

| Frame (time) | Meter LCD (ground truth, visible in photo) | System "cnn" reading | Error |
|---|---|---|---|
| 13:44:34 | 094788**507** | 0948**30801** (94,830.801 ft³) | ~+42 ft³ high |
| 13:43:28 | 094788**434** | 0948**29934** (94,829.934 ft³) | ~+42 ft³ high |
| 13:41:19 | 094788… | 0948**29881** (94,829.881 ft³) | ~+42 ft³ high |

**Why this matters / what's actually wrong:**

1. **It is not last-digit jitter.** The first 3 digits match (`094`), but positions 4–9 are systematically off — the visible `788…` is being emitted as `830…`/`829…`. This is a whole-number disagreement of ~42 ft³ (~315 gallons), not the "last 2–3 digits lag" failure mode described in the TL;DR.
2. **The error is hidden behind a smooth curve.** The wrong values are *internally consistent* — they increase monotonically frame-to-frame (829881 → 829934 → 830801). Nothing crashes, nothing reads as stale, and the usage graph looks plausible. The only way to catch it is to compare the derived number against the actual glass (which is what surfaced it).
3. **It contradicts the standing accuracy claim.** The TL;DR asserts "whole cubic foot 100% correct." This frame set is whole-cf wrong by ~42, so that claim is at minimum incomplete — there is a regime (current conditions, 2026-06-23) where the whole-cf reading is confidently wrong.
4. **The learning loop can entrench it.** `_archive_frame` indexes each archived image with the **live lock value at capture time** (`source=lock`). If the lock itself is anchored ~42 high, every archived row inherits the wrong baseline. Worse, the oracle auto-banks CNN "misses" as gold corrections — if the oracle agrees with (or is hinted toward) the wrong anchor, the wrong value becomes a training label and future retrains learn toward it.

**Leading hypotheses (UNVERIFIED — do not act without checking):**
- **A. Wrong lock anchor.** The monotonic lock latched onto a ~42-high value during some earlier glare/correction event and has been incrementing from the bad baseline since. The archive (`source=lock`) would then faithfully record the wrong number. *Check:* compare live lock value vs a hand-read of the glass right now; inspect recent down-correction / re-anchor events in the lock state.
- **B. Systematic CNN/oracle mis-read of the middle digits** under current lighting (glare on the `788` band reads as `830`). *Check:* run `meter_audit.py --report --hours=48` and an unbiased `gpt-4o` re-read of these exact archived frames (`/api/cam/archive/reread`) and compare to the glass.
- **C. Stale neighbor-hint feedback.** The archive re-read path passes a "soft neighbor hint"; if the neighbors are already wrong, the hint biases the read toward the wrong value (the same positive-feedback flaw that killed constrained decode). *Check:* re-read one frame with NO hint vs with hint.

**What NOT to do (lessons already paid for):**
- Do NOT manually re-anchor as a "fix" — re-anchoring trains nothing; the next frame collapses again (bailing water, not fixing the leak).
- Do NOT let the bad reads feed the gold-label bank until root cause is known — that reinforces the error.
- Do NOT propose hardware (polarizing lens) — James has declined that.

**Status:** Documented only. No code changed for this bug. Root cause not yet isolated (A/B/C above). Next session: verify lock anchor vs glass first (cheapest, highest-probability), then unbiased re-read audit.

## 2026-06-23 — Self-healing stuck-lock recovery (RESOLVES the persistence of the bug above)

**Root cause (the real one, isolated):** The bug above persisted not because a wrong read happened once, but because **the lock could not self-correct once it was wrong by more than the per-frame cap.** The oracle pipeline has a hard guard — `phys_max` / `ORACLE_MAX_ADVANCE` (15,000 counts = 15 ft³) — that blocks any single committed move bigger than the cap. That guard is correct for ONE blurry frame (a digit-transposition garble must never ratchet the lock). But it was the ONLY arbiter of trust, so it treated *magnitude* as the signal. When the lock itself became wrong by more than 15 ft³ (a restart loading a stale persisted lock; the oracle being quota-blocked while real water flowed), every honest read was then "too far" from the bad lock, got blocked every cycle, and the meter could only recover by a human re-anchor. **Trust was gated by magnitude, not by evidence strength.**

**The fix (software, automatic, nothing hardcoded):** `_consensus_auto_heal()` in `dashboard.py`. It hooks the two physics-block sites. Every blocked read is recorded as a "the lock disagrees" vote. When the votes are:
- **sustained** (≥ `HEAL_MIN_READS`=6 reads persisting ≥ `HEAL_MIN_PERSIST_SECS`=120s),
- **stable** (cluster spread ≤ `HEAL_CLUSTER_TOL`=800 counts — a garble jitters by thousands, a stale-but-true value drifts by tens), and
- **independently confirmed** (≥ `HEAL_AUTHORITY_CONFIRMS`=2 fresh, unbiased authority-model reads agree, spaced ≥ `HEAL_CONFIRM_INTERVAL`=45s apart),

then the conclusion flips: the **lock** is wrong, not the reads → auto-re-anchor to the live consensus value, clear the truth-guard, log it. The heal target is **always** what the meter is actually reading right now (the authority model's own current value) — never a constant. Works in **either direction** (stuck-low forward heal, stuck-high backward heal) and for any future cause. All thresholds are env-tunable (`METER_HEAL_*`); none of them is the meter value.

**Why this is safe (doesn't re-open the catastrophic-jump class):** a single big jump is still blocked. Healing requires a multi-frame, multi-minute, tightly-clustered, two-model consensus — a systematic garble can't fake that across changing glare and different frames, and an opposite-direction one-off is filtered out by direction before it can poison the cluster. Magnitude no longer determines trust; accumulated evidence does.

**Observability:** `/api/cam/status` → new `auto_heal` block (`heals`, `pending_samples`, `confirms`, `confirms_required`, `last_heal_from/to/ts`). The truth-guard still latches + pauses label banking during the disagreement, then is auto-cleared by the heal.

**Verified live (2026-06-23 14:40):** after a service restart left the lock stale-low at `94,740,084` while the meter actually read ~`94,791,096` (~51 ft³ / ~382 gal gap, far beyond the 15 ft³ cap), the system healed itself: `AUTO-HEAL: lock 94740084 -> 094791096 (8 agreeing reads + 2 authority confirms over 208s) — stuck lock recovered with NO manual step`. Post-heal: `truth_guard.active=false`, `auto_heal.heals=1`. No human re-anchor was performed.

**Supersedes the "Do NOT manually re-anchor" guidance for this failure mode** — there is no longer a manual step; the system recovers on its own.
## 2026-06-29 - loc2-v4 fixed-camera hard-frame retrain

Context: The camera has been locked in its final position since `2026-06-25T22:00 Pacific`, so pre-cutoff ground truth is no longer useful for judging this model. The data-layer goal is no fake smoothing: raw OCR errors must stay visible, and only defensible committed values should feed the charts.

Changes:
- Updated `cnn/retrain.py` and `cnn_service.py` to use the final location-2 crop `(0.10, 0.45, 0.82, 0.73)` instead of the old location-1 crop.
- Fixed version bumping so `loc2-vN` promotes correctly.
- Added hard-frame training inclusion before `MAX_PER_LABEL`, with `HARD_TRAIN_WEIGHT=3.0`, so current oracle-caught misses are not accidentally excluded from training.
- Exported reviewed post-cutoff archive frames into the training/eval set and retrained on the tower.

Result:
- Promoted `loc2-v4`.
- Retrain eval: held-out hard frames `144`; challenger fixed `14`, newly broke `3`, net `+11`; regression set remained clean.
- Post-cutoff reviewed fixed-camera export direct score: `5707/5799 = 98.414%` full-9 exact.
- High-confidence band: `min_conf >= 0.90` scored `3798/3798 = 100.0%` exact on that export. The `>=0.70` band still had misses with `loc2-v4`, so production was tightened to `0.90`.

State: `loc2-v4` is materially better than `loc2-v3`, but raw OCR is not yet at the "virtually perfect" bar. Remaining misses are concentrated in low rolling digits and glare/ambiguity cases. The safe operating policy is to accept only the exact high-confidence band and keep oracle/review/context commits explicitly labeled.

## 2026-06-29 - loc2-v5 after fixing bad post-cutoff ground truth

Context: A visual review of the remaining fixed-camera misses found a poisoned manual label block: `2026-06-28T20:30:16 -> 21:45:16` was labeled/committed as `95031090`, but representative images plainly read `95031097`. This lowered honest model scoring and trained the CNN toward the wrong final digit.

Changes:
- Corrected the archive/ledger plateau to `95031097` after DB backups.
- Appended manual-label overrides for the existing `095031090_*_oracle.jpg` training-bank files so they train as `095031097`.
- Forced a new tower retrain and promoted `loc2-v5`.
- Raised server-side production acceptance to `min_conf >= 0.97`; `loc2-v5` has three post-cutoff misses above `0.90`, with the highest remaining miss at `0.957`.

Result:
- Promoted `loc2-v5`.
- Gated retrain: hard holdout full-9 `0.410` vs corrected `loc2-v4` champion `0.333`.
- Ground-truth replay: challenger `0.940/0.815` vs champion `0.938/0.801`.
- Hard-frame eval: champion missed `96/144`; challenger fixed `13`, newly broke `2`, net `+11`.
- Regression set: `0/9` misses.
- Corrected post-cutoff eval: `5723/5799 = 98.689%` full-9 exact.

State: this confirms bad ground truth was a real limiter. The model improved after correcting it, but raw OCR still is not virtually perfect. The remaining work is to continue finding and correcting poisoned labels and separating physically ambiguous rolling digits from crisp visible truth; do not relax the production gate below `0.97` without a fresh confidence-band proof.

## 2026-06-29 - Expanded live HTTP eval and current hard-frame export

Context: The `loc2-v5` direct eval had only covered the earlier fixed-camera export. More post-cutoff archive rows had accumulated, and the live raw conflict report showed a repeated false-low class (`95035782` while committed/oracle was `95036782`). The next pass evaluated the live production CNN service over HTTP from the Acer, avoiding tower SSH.

Changes:
- Added `ocr-harness/eval_live_cnn_http.py`, a read-only evaluator that walks Acer archive rows, POSTs the actual JPEGs to `http://192.168.0.120:5201/cnn`, and reports exact-match, confidence bands, per-position accuracy, and sorted misses.
- Added a source filter so authoritative visual truth (`oracle`, `manual`, `reviewed_context`) can be scored separately from propagated/held committed rows.
- Added `ocr-harness/summarize_live_cnn_misses.py` to turn miss JSONL into review queues: repeated label/prediction pairs for training and high-confidence manual-label disagreements for visual review.
- Re-ran the archive training export on the Acer. It added 410 new post-cutoff authoritative image copies/manual-label rows to `~/meter-training`/`~/cnn-dataset-oracle`, without modifying live meter DBs.

Validation:
- Full committed archive HTTP eval: `9435/10343 = 91.221%` exact. This intentionally includes propagated committed rows and is not a pure visual-truth metric.
- Authoritative-only HTTP eval: `5884/6073 = 96.888%` exact.
- Authoritative confidence calibration remains safe at the production gate: `min_conf >= 0.97` scored `939/939 = 100%` exact. `>=0.90` is still unsafe (`83/85`).
- The top true high-confidence miss is real after visual inspection: `2026-06-28T15:46:23`, image reads `095030115`, live CNN predicts `095030175` at `min_conf=0.957`.
- Remaining authoritative misses are concentrated at digit position 5 (`100` misses) and low rolling digits. The dominant repeated pair is `095036782 -> 095035782` (`97` misses), now exported for the next retrain.
- Two high-confidence manual-label disagreements remain review candidates, not auto-corrections: `2026-06-28T20:26:06` (`095030800 -> 095030807`) and `2026-06-28T20:28:41` (`095031000 -> 095031007`). Temporal context is plausible enough that they were not rewritten from a glance.

State: raw OCR remains below the "virtually perfect" bar, but the next hard-frame batch is now in the training bank. The `0.97` production gate is still supported by expanded live evidence. Tower shell access as `jack` through the Acer was not available in this pass, so the next promotion requires restoring/using tower access or the retrain timer.

## 2026-06-29 - GPT-4o verified label repairs and loc2-v6 retrain in progress

Context: The expanded live HTTP eval found two high-confidence manual-label disagreements near `2026-06-28T20:26` and `20:28`, plus one true high-confidence CNN miss at `2026-06-28T15:46:23`. Because bad ground truth had already limited the CNN once, these candidates were checked with the authority model before being used as training truth.

Changes:
- Added `ocr-harness/oracle_check_candidates.py` to run non-mutating authority-model checks against specific archived JPEGs using the live service environment.
- Added `ocr-harness/repair_20260628_manual_labels.py` to apply only oracle-verified manual-label repairs, with backups and ledger recomputation.
- Used GPT-4o authority reads to verify five bad post-cutoff committed labels from `2026-06-28T20:25:56` through `20:28:41`.
- Corrected those five archive and ledger rows, preserving raw OCR, adding ledger correction rows, and appending training-label overrides for the old exported filenames.
- Exported the repaired archive again; it added 8 more post-cutoff training rows after the 5-row repair.

Validation:
- Backups created before writes: `meter_archive.db.bak.20260629-184949`, `meter_ledger.db.bak.20260629-184949`, and `manual_labels.jsonl.bak.20260629-184949`.
- Repaired values: `095030793`, `095030807`, `095030813`, `095030827`, and `095031007`.
- Local harness scripts compile cleanly.
- Post-repair committed-layer audit is still green: archive/ledger mismatches `0`, archive rows without ledger `0`, negative deltas `0`, unreviewed authoritative rows `0`, material unreviewed non-oracle deltas `0`, watering-window unreviewed positive deltas `0`.
- Raw OCR conflict count remains nonzero by design; bad raw reads are preserved as evidence instead of being smoothed away.
- A `loc2-v6` tower retrain started after the 410-row export and before the final 5-row repair export. At epoch 35 it was beating the live `loc2-v5` champion on hard-frame full-9 accuracy (`0.534` vs `0.518`), but it had not promoted yet.

State: The committed data layer remains clean after the verified repairs. Raw OCR is still not at the "virtually perfect" bar. Next action is to let `loc2-v6` finish, confirm promotion, then rerun the live HTTP authoritative eval; if the model did not include the final 8 repaired rows or fails the confidence-band proof, force a follow-up retrain from the repaired training bank.

## 2026-06-29 - loc2-v6 promoted, loc2-v7 rejected, production gate still exact

Context: After the GPT-4o verified label repairs and expanded hard-frame export, `loc2-v6` finished training and was evaluated against the fixed-camera post-cutoff archive. A follow-up `loc2-v7` retrain was forced after the final repair/export to make sure the newest corrections did not produce a better challenger.

Changes:
- Promoted `loc2-v6` on the tower. Gate: hard-frame full-9 `0.545 > 0.518` champion; ground-truth replay `0.946/0.823` vs `0.941/0.810`; hard-frame net `+5`; regression set `0/9`.
- Forced `loc2-v7` after exporting the final repair rows. It was rejected: hard-frame full-9 `0.549 <= 0.554` refreshed `loc2-v6` champion; ground-truth replay was worse; hard-frame net `-1`; regression set remained `0/9`.
- Paused `meter-cnn-retrain.timer` during the forced run to prevent concurrent trainers, killed duplicate scheduler-started processes, then restored the timer.

Validation:
- Live health after promotion: `version=loc2-v6`.
- Final authoritative live HTTP eval over `oracle`, `manual`, and `reviewed_context`: `5992/6120 = 97.909%` full-9 exact.
- Production gate remains empirically exact: `min_conf >= 0.97` scored `3557/3557 = 100%`; `>=0.90` remains unsafe (`352/356`).
- Remaining raw misses: `128`, concentrated in the last rolling digit (`117`) and dominated by `095029589 -> 095029583` (`55`) at low confidence.

State: `loc2-v6` is the best live CNN. Raw OCR is much better but still not virtually perfect, so production must keep the `0.97` commit gate and use oracle/manual/reviewed context below that. The current failure tail is low-confidence final-digit ambiguity, not a chart smoothing problem.

## 2026-06-30 - right-edge crop fix promoted as loc2-v7; threshold raised to 0.95

Context: The dominant remaining post-cutoff miss after `loc2-v6` was `095029589 -> 095029583` (`55` misses), concentrated on the final rolling digit. Crop-guide overlays showed the last digit was tight against the right edge/glare in the location-2 crop `(0.10, 0.45, 0.82, 0.73)`.

Changes:
- Added crop-guide and crop-variant harnesses under `ocr-harness/`.
- Tested live weights across crop variants. The targeted `095029589` cluster went from `24/79 = 30.38%` exact on the old crop to `79/79 = 100%` at right edge `0.84`; wider variants over-shot and degraded.
- Updated tower and local CNN crop to `(0.10, 0.45, 0.84, 0.73)` for `retrain.py` and `cnn_service.py`.
- Forced a gated retrain with the new crop. `loc2-v7` promoted: strict full-9 `0.549 > 0.538`; ground-truth replay roughly tied; hard-frame eval net `+2`.
- Raised the live `meter-cnn` threshold from `0.90` to `0.95` via systemd drop-in and code default after live eval showed `>=0.90` was not exact but `>=0.95` was exact.
- Exported 53 newest reviewed archive frames into the training bank and forced a follow-up `loc2-v8` retrain. It was rejected: strict `0.544 <= 0.549`, hard-frame net `-1`, so live stayed on `loc2-v7`.

Validation:
- Live health: `version=loc2-v7`, `threshold=0.95`, crop right edge `0.84`.
- Authoritative live HTTP eval after promotion (`oracle`, `manual`, `reviewed_context`): `6051/6151 = 98.374%` full-9 exact.
- Confidence calibration after promotion: `min_conf >= 0.95` scored `1834/1834 = 100%`; `>=0.97` scored `488/488 = 100%`; `>=0.90` remained unsafe (`2011/2019`).
- Remaining misses dropped to `100`; dominant prior cluster `095029589 -> 095029583` disappeared. Remaining misses are mostly final/rolling low-digit ambiguity, with top repeated pairs only `4` and `3` occurrences.
- `meter-cnn-retrain.timer` was restored after each forced run.

State: `loc2-v7` is the live champion and is safer than `loc2-v6` because the crop now includes the final digit correctly and the direct-commit threshold is calibrated to the exact band. Raw OCR is still not literally 100% across all frames, but accepted high-confidence direct CNN reads are gated at an empirically exact threshold; lower-confidence reads must continue to be oracle/manual/review/context, with raw guesses preserved.

## 2026-06-30 - Operational stop point: raw OCR not perfect, accepted band exact

Context: James asked whether the current result is good enough. The answer is yes for production operation and committed chart data, but no for mathematically complete raw OCR perfection.

Validation:
- Fresh live health: `version=loc2-v7`, `threshold=0.95`; `meter-cnn-retrain.timer` active.
- Fresh authoritative HTTP eval (`oracle`, `manual`, `reviewed_context`): `6094/6194 = 98.386%` full-9 exact.
- Confidence calibration: `min_conf >= 0.95` scored `1807/1807 = 100%`; `>=0.97` scored `489/489 = 100%`; `>=0.90` remains unsafe (`2033/2041`).
- Remaining misses are still exactly `100`, concentrated in the final rolling digits; top repeated pair is only `095034101 -> 095034100` (`4` examples).
- A read-only test-time-augmentation eval was started but stopped because it was too slow and had produced no results after ~30 minutes; no live service changes were made from that experiment.

Decision: Stop active expensive/aggressive OCR debugging for now. Keep the live direct-CNN threshold at `0.95`, preserve raw OCR failures, rely on oracle/manual/review/context below the accepted band, and let the gated retrain loop improve passively as new verified hard cases accumulate. Do not call the raw OCR "100%"; call the committed data path operationally safe and audited.

## 2026-06-30 - Final stabilization: loc2-v7 frozen, retrain timer stopped

Context: A forced `loc2-v8` retrain was launched after exporting 53 new authoritative post-cutoff labels. It did not need to finish because `loc2-v7` already satisfies the stable operating bar: no authoritative misses at the deployed `0.95` confidence threshold, and the committed data layer is clean.

Actions:
- Killed the active forced `loc2-v8` retrain before any promotion decision.
- Stopped `meter-cnn-retrain.timer` in both user and system scopes.
- Did not start any additional retrain cycles.

Validation:
- Tower health: `version=loc2-v7`, `threshold=0.95`, `ok=true`, model `/home/jack/meter-cnn/meter_cnn.pt`.
- `~/meter-cnn/VERSION` is `loc2-v7`.
- No `retrain.py` processes are running.
- `meter-cnn-retrain.timer` is inactive in both user and system scopes.

Decision: Leave `loc2-v7` as the stabilized live model. The retrain timer must not be re-enabled at the current cadence: it fires about every 10 minutes while a full retrain takes roughly an hour, which creates duplicate trainer pile-ups. Fix the timer/locking policy before re-enabling retraining.

## 2026-07-04 - loc2-v7 high/middle digit regression at current leading edge

Context: Water Usage spot checks showed the graph's committed reading and the clicked frame's raw CNN guess did not match. The graph/ledger sync bug was fixed separately; this pass investigated whether raw CNN accuracy had regressed.

Findings:
- Yes, it used to be more accurate in the accepted band. On 2026-06-30, `loc2-v7` scored `6094/6194 = 98.386%` authoritative exact, with `min_conf >= 0.95` exact.
- Current live oracle-graded samples are `0/18` for `loc2-v7`, and July 4 is `0/5`.
- The raw failure is systematic high/middle digit loss, not the previous low rolling digit tail: examples include `095028829 -> 095138820`, `095037792 -> 095137187`, and `095030982 -> 095150906`.
- Tower health is still `loc2-v7`, threshold `0.95`, so this is not an obvious service rollback.
- The current image is still framed and human-readable, but contrast/glare around the middle/high digits is weak.
- Constrained decoding on recent oracle frames is informative but not reliable enough to promote: in a 40-frame sample, about half were close and many were ~1000 counts off.

Action:
- Logged `BUG-meter-cnn-high-digit-regression-2026-07-04.md`.
- Fixed a latent server config hazard: live archive/constrained CNN acceptance was still overridden to `0.70`, despite the `loc2-v7` proof only supporting `0.95`. Updated `dashboard.py` defaults and `deploy.ps1`, deployed `dashboard.py`, and verified live env now sets all archive/reprocess/constrained CNN gates to `0.95`.

State: Raw CNN should be considered degraded on current `0951xx` leading-edge frames. Continue using committed oracle/manual/propagated readings for Water Usage; preserve raw guesses as evidence. Durable fix is retraining/fine-tuning with verified current `09513x-09515x` frames, followed by a new confidence-band proof before relaxing any gate.

Follow-up:
- Added 14 explicit `codex_visual_label` rows from rotated/enlarged current LCD crops (`095138871` through `095154201`) with no oracle calls.
- Exported the broader verified archive window from `2026-07-04T05:45:00`: 174 eligible rows, 160 new image copies/manual-label rows, all raw-CNN-wrong.
- Found and fixed a retrainer issue: synthetic rows were still generated around stale hardcoded `094...` prefixes. `cnn/retrain.py` now builds synthetic high-order prefixes from the newest trusted labels, so current examples synthesize around prefixes like `09514`/`09515`.
- First forced retrain with only the 14 visual labels did not promote: challenger `0.544 <= 0.549`, hard-frame net `-1`.
- Second forced retrain with 160 current labels promoted `loc2-v8`: refreshed gate `0.546 > 0.517`, ground-truth replay full-9 `0.822` vs champion `0.808`, hard-frame eval fixed 6 and broke 0.
- Post-promotion read-only current eval over 199 oracle frames since `2026-07-04T05:45:00`: positions 0-5 were `199/199` correct, pos6 `197/199`, pos7 `180/199`, pos8 `108/199`. This confirms the high/middle digit collapse is materially fixed, while final rolling digits remain weak.
- No current sample reached `min_conf >= 0.95`, so direct CNN acceptance remains effectively off for now. Fresh live raw guesses are now close and in-range (`095162721` vs committed `095162726`), but still `raw_conf=low`; committed Water Usage should keep using oracle/manual/propagated ledger values.

## 2026-07-08 - tower-first OCR/retrain operations

Context: OpenAI spend was exhausted/low, so the gaming tower should do as much meter work as possible and paid vision should only be a sparse authority check.

Actions:
- Verified tower services healthy: `meter-ocr` on `5200`, `meter-cnn` on `5201`, and `ollama` active.
- Live CNN is now `loc2-v8` at threshold `0.95`. The threshold remains strict because current raw reads are still low-confidence on the rolling/right digits.
- Tried local `moondream` on a recent archived frame; it did not produce a usable meter reading, so it is not a drop-in replacement for GPT-4o authority reads.
- Re-enabled `meter-cnn-retrain.timer` safely with a 2-hour cadence and a `flock`-guarded service:
  - old cadence: about every 10 minutes, which caused duplicate trainer pile-ups because a full retrain can take roughly 1-2 hours.
  - new cadence: `OnBootSec=10min`, `OnUnitActiveSec=2h`, `RandomizedDelaySec=5min`.
  - service command: `/usr/bin/flock -n /home/jack/meter-cnn/retrain.lock .../retrain.py`.
- Immediate timer run skipped correctly: `new frames since last retrain: 0 (threshold 25)`.

Decision: Keep the tower as the heavy local OCR/training box. Use OpenAI/Azure only for sparse anchor frames that unblock stale-lock repair or training labels. Do not lower the `0.95` commit gate without a fresh confidence-band proof.
