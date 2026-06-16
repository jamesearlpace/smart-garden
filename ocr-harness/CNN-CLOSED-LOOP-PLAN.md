# Water-Meter OCR — CNN Closed-Loop Plan & State

**Status:** CLOSED LOOP LIVE. CNN v2 in production (gated retrain beat v1). Phases
1–4 done; Phase 5 (cost ramp-down) pending. Metrics layer persists improvement
data. This doc is the source of truth for the self-improving reader. Read first
when resuming.

**Last updated:** 2026-06-15

---

## 1. The goal

Read a 9-digit water-meter LCD from a cheap, glare-prone ESP32-CAM **reliably and
cheaply**, and have the system **improve itself over time** without James babysitting
labels. The end state: a small custom per-digit CNN reads ~95% of frames for free
and instantly; a vision-LLM (GPT-4o) oracle handles the hard ones and acts as an
independent verifier; corrections feed back into periodic retraining that only ships
if it beats the current model.

**Why a custom CNN at all:** general OCR (RapidOCR) and even GPT-4o are unreliable on
this specific blurry 7-segment LCD under moving glare. A model trained on THIS meter,
THIS camera, THESE lighting conditions generalizes across the failure modes that break
general readers. Hardware fixes (lens focus, exposure) were declined — software is the
path.

---

## 2. The closed loop (target architecture)

```
ESP32-CAM frame (every 5s)
      │
      ▼
┌──────────────────┐   all digits high-conf   ┌────────────────────────┐
│ CNN (per-digit)  │─────────────────────────▶│ accept read (free/fast)│
│ reads 9 digits   │                          └────────────────────────┘
└──────────────────┘
      │ ANY digit low-conf  OR  periodic spot-check heartbeat (~5 min)
      ▼
┌──────────────────┐
│ GPT-4o oracle    │  trusted, independent reader (+ slow-movement context hint)
│ (paid, ~$0.002)  │
└──────────────────┘
      │
      ├─ oracle AGREES with CNN ─▶ accept + bank as a NEW verified label
      └─ oracle DISAGREES ───────▶ accept oracle value + bank as a CORRECTION
                                    (this is the highest-value training data —
                                     exactly the case the CNN got wrong)
      │
      ▼  (nightly / when N new corrections accrue)
┌──────────────────┐
│ RETRAIN CNN      │  on (old verified set + new corrections)
│ eval vs golden   │  CHAMPION/CHALLENGER: promote the new model to prod
│ + harness        │  ONLY if it beats the current model on the golden set
└──────────────────┘
```

**The monotonic physics guard sits on top of everything** — CNN or oracle, the
meter-can't-go-backward rule vetoes impossible jumps. Cheap safety net independent of
any model being right.

---

## 3. The three guardrails (hard-won lessons — DO NOT violate)

1. **Never let a reader's own output become a training label.** A new label enters the
   training set ONLY when an INDEPENDENT verifier confirms it. CNN-confident +
   oracle-agrees → verified. CNN-wrong → oracle's value is the correction. CNN-alone →
   never banked. (This is the circular-poisoning trap that cost us days. The old
   `agree:true` was hardcoded/circular; fixed.)

2. **Retraining is GATED, not automatic.** After retrain, eval the challenger vs the
   golden set + harness. Promote to production ONLY if it beats the current champion.
   A bad batch of corrections must never auto-deploy a worse model.

3. **Physics (monotonicity) is the final veto.** Whatever reads the digits, the meter
   is a cumulative odometer. Impossible jumps are rejected regardless of model
   confidence. `audit_labels.py`'s LNDS backbone is the offline version; the live lock's
   forward-only + idle-aware ceiling is the online version.

4. **A confident reader can be confidently WRONG — never trust a big jump on confidence
   alone.** (Added 2026-06-15 after the CNN read a glary frame as `094180041` at 0.95
   conf and ratcheted the lock ~2000 too high, because high-conf reads skip the oracle.)
   A high-conf CNN read is trusted directly ONLY if it advances the lock ≤
   `CNN_MAX_TRUST_ADVANCE` (500 counts). A larger forward jump is NOT trusted on its own
   — it forces the independent oracle to corroborate before the lock can move. Real fast
   usage / stale-recovery still works (the oracle confirms it); only confident-wrong
   jumps are stopped. Corollary: do NOT lower the confidence threshold to "use the CNN
   more" — fix confidence via retraining, not by trusting more.

**Corollary — cost ramps DOWN over time:** early on the CNN is weak, so most frames go
to the oracle (lean on AI heavily, as James said). As retraining improves the CNN, raise
the confidence threshold so fewer frames need the oracle. The spot-check heartbeat stays
on forever (cheap insurance against confident drift).

---

## 4. What's already built & working (state as of 2026-06-15)

### Live reading pipeline (deployed on Acer `~/smart-garden-server/`)
- **ESP32-CAM** (192.168.0.160) pushes SVGA JPEG every 5s → Acer `/api/cam/upload`.
- **Tower OCR** (jackmint 192.168.0.120:5200, RapidOCR) — current digit reader, ~1-3s/frame.
- **MeterReader** (`cam_ocr.py`) — physics/odometer validator: cluster-lock, forward-only
  monotonic ceiling, corroborated advance, stale "≥" honesty, per-digit 7-seg scorer.
- **Vision oracle** (`vision_oracle.py`) — GPT-4o with the **slow-movement context hint**
  (last value + expected 6-digit prefix; "only last 2-3 digits change"). A/B proved the
  hint flips garbage→exact. Forward-only + idle-aware acceptance; corroboration for big moves.
- **Frame ring** (`/tmp/meter-frames`, newest ~720) — every processed frame saved by row id
  for the click-to-inspect detail page.
- **Live cam page** — readings table (clickable rows → `/cam/reading/<id>`), 🤖 AI rows,
  "reading pending" when a frame wasn't actually read, display-Δ fallback.

### Ground-truth / dataset pipeline (`MyCode/smart-garden/ocr-harness/`)
| File | Purpose |
|------|---------|
| `golden.json` | Trusted ground truth — frames verified by INDEPENDENT human/vision viewing (NOT the pipeline). The eval anchor. |
| `harness.py` | Scores the oracle (or later the CNN) against golden. Per-frame accuracy, exit-code pass/fail for automated iteration. |
| `audit_labels.py` | Quarantines physically-impossible labels via Longest Non-Decreasing Subsequence (meter monotonic). Robust to false-high AND false-low. |
| `build_cnn_dataset.py` | Export gate: monotonic backbone → cross-reader verify (`--verifier tower|oracle`, `--max-per-label N`). Emits manifest + needs_review. |
| `resolve_consensus.py` | Recovers disputed frames via 3-read GPT-4o majority vote + monotonic gate. Incremental/resumable/quota-aware. Corrects labels. |
| `finalize_dataset.py` | Bakes manual edits + manifest → `cnn_train.jsonl` (THE training file). Trust: manual > consensus > verified; excludes rejects/unresolved. |
| `rotate_upright.py` | 180° rotate helper (camera mounted upside-down) for human verification. |
| `README.md` | How to run the harness + audit + grow the golden set. |

### Label review + edit UI (deployed)
- **`/cam/labels`** (`templates/cam_labels.html` + `/api/cam/labels`) — gallery of every
  banked frame + label, color-coded: manual / verified / promoted / corrected / review /
  rejected. Filter chips + counts, sorted by reading value.
- **Inline editing** — each tile: **Fix** (type 9 digits), **OK** (confirm), **Reject**
  (exclude). Saved to `manual_labels.jsonl` via `POST /api/cam/labels/update`. Highest
  trust tier; overrides all automated verdicts on read.

### The finalized dataset (the payoff)
- **`~/cnn-dataset-oracle/cnn_train.jsonl`** — **373 frames, 336 distinct readings,
  0 unresolved, 0 missing.**
- Sources: **86 manual** + **8 manual-ok** + **197 consensus** + **82 verified**.
- 36 frames manually rejected (excluded). 69+92 quarantined earlier as impossible.
- Every label is human-verified or passed 2-reader + monotonic + consensus gates.

### Collection switch
- **`METER_BANK_ENABLED=0`** (drop-in `collection.conf`) — auto-collection OFF so James
  isn't on a correction treadmill. Oracle still reads/re-anchors the live meter; just
  stops saving training jpgs. Re-enable: rm the drop-in + daemon-reload + restart.

### Key facts
- 9 digits, decimal 3 from the right: `094100762` = 94,100.762 ft³. 1 ft³ = 7.48052 gal.
- Frames stored UPSIDE-DOWN (camera mount) — rotate 180° to read.
- Acer: `jamesearlpace@192.168.0.109`, sudo `KeepingP@ce8!`, service `smart-garden-server`.
- ⚠️ Server `dashboard.py` + `config.yaml` DRIFT ahead of local — diff before deploying.
- OpenAI key at `/etc/smart-garden/cam-env`. 30K tokens/min cap; ~$0.002/read.

---

## 5. The build plan (what's NEXT)

### Phase 1 — Train CNN v1 ✅ DONE (2026-06-15)
**Result: per-digit 99.6%, full-9-correct 96.4%** on a 55-frame held-out val set
(318 train). Trained locally (Windows, torch 2.8 CPU), ~37 min, 80 epochs.

Key design choices that worked:
- **Camera DRIFT discovered** via crop-preview tooling: framing moved over the
  dataset, so a fixed pixel crop misses digits on newer frames. Solved with a
  **generous crop** (`config.CROP`) + **heavy augmentation** (random shift/scale/
  rotate, brightness/contrast, blur, glare-erase) so the model is position-tolerant.
- **No per-digit segmentation** (the digits are unevenly spaced + skewed + drift —
  brittle). Instead a single conv backbone over the whole digit band → AdaptiveAvgPool
  to (1×9) → **9 per-position heads**, each 10-way softmax. Each head's softmax-max is
  the per-digit confidence for oracle routing.
- CLAHE preprocessing (same as the tower) pulls digits out of glare.
- Tooling: `preview_crop.py`, `detect_lcd.py` (tried screen-detection, too flaky on
  this feed — abandoned for the generous crop), `coverage.py` (verify crop contains
  digits across drift).

**Files** (`MyCode/smart-garden/cnn/`): `config.py`, `dataset.py`, `model.py`,
`train.py`, `cnn_reader.py` (inference → 9 digits + per-digit conf), `eval_golden.py`,
`model/meter_cnn.pt` (weights). Training/inference libs installed on the **tower**
(meter-ocr venv: torch 2.12 CPU + onnx + cv2) so the retrain loop can live there.

**Caveat:** golden set is only 5 frames (1 local). The 96.4% val number is the
trustworthy baseline; expand the golden/test set for a sharper number. v1 doesn't
need to be perfect — it's the champion the closed loop improves on.

### Phase 1b — partly done
- ⚠️ ONNX export **BLOCKED**: `adaptive_avg_pool2d` to (1×9) isn't ONNX-exportable
  (16 not divisible by 9 → "output size not a factor of input size"). Would need a
  retrain with an export-friendly pool. **Decision: skip ONNX, run PyTorch directly** —
  torch 2.12 CPU is on the tower and inference is ~24-106ms, plenty fast. ONNX was only a
  nicety.
- TODO (low priority): held-out TEST split + grow the golden set for a sharper number.
- Deploy target decided: **tower** (always-on, has the libs; Acer is RAM-starved).

### Phase 2 — Wire CNN into live inference ✅ DONE (2026-06-15)
- **`cnn_service.py`** on the tower (systemd `meter-cnn`, port 5201, meter-ocr venv,
  self-contained: bundles the model + CLAHE preprocess). `POST /cnn` raw JPEG →
  `{digits, value, min_conf, per_digit_conf, confidence, readable, ms}`. Auto-starts on
  boot, restarts on crash. Verified: reads `094100762` correct @ 0.984 conf in 106ms.
- **Acer `dashboard.py` `_ocr_worker`**: calls the CNN FIRST (`_read_via_cnn`). If
  `confidence==high` → use the CNN digits (free path, `cnn_used++`). Else → fall back to
  RapidOCR (`cnn_fellback++`) + the paid oracle via `_maybe_oracle`. CNN digits are fed
  through `meter_reader.process_text` so the **physics validator stays on top** (guardrail
  #3). Config: `METER_CNN_URL`, `METER_CNN_ENABLED`. Stats: `reader`, `cnn_used`,
  `cnn_fellback` in `cam_ocr_stats`.
- **Verified live:** Acer calls the CNN every ~5s (11 calls/90s, all 200). A glary frame
  read `094168082` @ min_conf 0.875 on the uncertain 4th digit → correctly fell BELOW the
  0.90 threshold → routed to oracle instead of trusting the bad digit. Threshold working.
- TODO: surface the reader/conf on the readings table UI (cosmetic).

### Phase 3 — Correction banking ✅ DONE (2026-06-15)
- Re-enabled banking (`METER_BANK_ENABLED=1`) but **verified-only**: added a SEPARATE
  `METER_LOCAL_BANK_ENABLED` (default **0**) gating `_bank_sample`. The CNN read is keyed
  by its own digits, so local banking would be CIRCULAR (model labels itself) — and
  RapidOCR is too noisy to trust — so **the oracle is the ONLY banker** (independent verifier).
- **Correction tagging:** the CNN's reading is threaded worker → `_maybe_oracle` →
  `_oracle_run` → `_oracle_bank_label`, which records `cnn_said` + `cnn_correct` in the
  sidecar. `cnn_correct=false` = a genuine CNN failure the oracle caught = the highest-value
  training example. Stat `cnn_corrections`; logs "CNN correction banked".
- **Nearly free:** the oracle was ALREADY reading the hard (low-conf) frames to keep the
  lock current — Phase 3 just saves those (frame, oracle-label) pairs again. Dedup 1/label.
- **Verified live:** CNN read a glary frame `094168082` (wrong) → low-conf → oracle read
  `094158092` (correct) → banked with `cnn_correct:false`. The loop is closing: CNN
  failures become labeled corrections automatically, no manual work.

### Phase 4 — Gated retraining (champion/challenger) ✅ DONE (2026-06-15)
- **First retrain executed; v2 beat v1 and was promoted.** This proves the loop.
- **Data refresh:** re-audited all 650 banked frames (`audit_labels.py` monotonic
  LNDS) → 16 physically-impossible labels quarantined (incl the false-high oracle
  reads `094158092`/`094179953` from the confident-wrong poison incident).
  `build_expanded.py` merged v1's 373 verified + 243 NEW oracle-verified survivors
  (dedup max 3/label) → `cnn_train_v2.jsonl` = **614 frames / 456 distinct** (was
  373/336). New frames cover the `09415x`–`09417x` range v1 never saw.
- **Fair eval** (`train_v2_gated.py`): the held-out TEST set = 60 frames drawn ONLY
  from `source="oracle-new"` (frames v1 never trained on); v2 also excludes them
  from training. Both models are scored on the SAME unseen frames — no home-field
  advantage. Promote rule: ship v2 ONLY if its full-9 > v1's (ties keep champion).
- **Result:** champion v1 = **55.0%** full-9 / 93.1% per-digit; challenger v2 =
  **58.3%** full-9 / 94.3% per-digit → **VERDICT PROMOTE (+3.3 pts)**. 80 epochs,
  ~52 min, Python 3.11 torch 2.8 CPU, local.
- **Promotion:** backed up `meter_cnn_v1_backup.pt`; copied v2 → `meter_cnn.pt`; scp
  to tower `~/meter-cnn/`; `echo 'v2' > ~/meter-cnn/VERSION`; restart `meter-cnn`.
  Verified health `version:v2`, reads live frames, version tag flows into the
  `cnn_eval` metrics. Guardrails intact (low-conf → oracle; big-jump guard on).
- ⚠️ **Launch gotcha:** a long CPU train MUST run detached (`Start-Process powershell
  -WindowStyle Hidden -Command "python -u train.py > out.log 2> err.log"`). Running
  it `-NoNewWindow` or piped to `Tee-Object` ties it to the chat terminal; when VS
  Code cleans that terminal up the child gets a Windows console-CLOSE event and
  aborts mid-run (`forrtl: error (200) ... window-CLOSE`). Also use `python -u` +
  file redirect (NOT a pipe) so progress is monitorable — pipes buffer stdout.
- **To run v3+:** on Acer re-run `audit_labels.py --apply` + `build_expanded.py`,
  bundle + pull frames, locally run `train_v2_gated.py` (rename outputs v3), promote
  only if it beats the *current* champion's held-out score. Baseline rises each time.

### Metrics / improvement reporting ✅ DONE (2026-06-15)
- **Why:** in-memory `cam_ocr_stats` reset on restart, no version tag, no time-series
  — couldn't answer "is it improving?" Built persistence.
- **`cnn_metrics.py`** (`server-prod` + deployed): tables `cnn_eval` (one row per
  oracle verification = a free CNN ground-truth check: cnn_value, oracle_value,
  cnn_correct, model_version, min_conf) and `cnn_daily` (frames, cnn_used,
  cnn_fellback, oracle_calls, evals, cnn_correct per day + version). DB =
  `smart-garden.db` via `database.get_conn()`. `report(days)` → {daily, by_version,
  recent}.
- **Report UI:** `/cam/cnn-report` (`templates/cnn_report.html`) + `/api/cam/cnn-report`
  — live CNN accuracy by model version, daily reader split (free vs fell-back vs
  oracle), recent oracle checks. Auth-gated.
- **`cnn_service.py` versioning:** reads `~/meter-cnn/VERSION` (fallback v1), returns
  `version` in `/cnn` + `/health`. Acer stashes it so each eval row is tagged. Bump
  the VERSION file on every champion promotion.
- **Captured-image resize:** reading-detail page (`cam_reading.html`) has a Size
  slider (30–100%, persisted in localStorage) for inspecting frames.

### Phase 5 — Cost ramp-down (PENDING)
- As CNN accuracy climbs, raise the confidence threshold so fewer frames hit the oracle.
- Track oracle calls/day; it should trend toward near-zero (heartbeat only).
- ⚠️ **DO NOT lower `CONF_THRESHOLD`** despite v1 looking under-confident — the
  2026-06-15 incident proved the CNN can be CONFIDENTLY WRONG. Keep it conservative;
  let retraining improve confidence calibration first. The cost ramp comes from a
  *better* model passing the existing bar more often, not from lowering the bar.

---

## 6. Open decisions (resolve when building each phase)

- **Where does the CNN run?** Acer CPU (simple, co-located with the pipeline) vs tower GPU
  (faster, already runs RapidOCR). Lean Acer for v1 — the model is tiny; avoid a second
  network hop.
- **Framework:** ONNX (matches the tower's runtime, portable) vs PyTorch (easier to train).
  Likely train in PyTorch, export to ONNX for inference.
- **Digit segmentation robustness:** fixed slicing vs a tiny detector. Start fixed; only add
  detection if alignment drifts.
- **"Unreadable" class:** give the per-digit model an 11th class so it can say "I can't read
  this digit" → routes to oracle, rather than guessing. Recommended.
- **Confidence threshold:** start conservative (route lots to oracle), raise as accuracy
  proves out.

---

## 7. Pointers
- Main narrative: `smart-garden-journey.md` (this is the slim plan; journey has the day-by-day).
- Repo memory: `/memories/repo/water-meter-ocr.md` (dense facts + gotchas).
- Tooling + how-to: `ocr-harness/README.md`.
- Dataset: `~/cnn-dataset-oracle/cnn_train.jsonl` on the Acer.
