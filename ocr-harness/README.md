# OCR Test Harness + Ground-Truth Audit

Tools to **iterate on the water-meter reader without manual eyeballing**, and to
**keep the training/ground-truth data trustworthy**. Built 2026-06-13 after the
ratcheting bug poisoned a batch of banked labels.

> **📋 The big picture lives in [CNN-CLOSED-LOOP-PLAN.md](CNN-CLOSED-LOOP-PLAN.md)** —
> the self-improving reader architecture, current state, guardrails, and build phases.
> Read that first. This README is the how-to for the individual tools.

## The pieces

| File | What it does |
|------|--------------|
| `golden.json` | **Trusted ground truth.** Each frame's real 9-digit reading, verified by a human / independent vision model viewing the frame UPRIGHT — NOT by the pipeline (that would be circular). `true` = real reading; `stored_label` = what the pipeline banked (may be wrong). |
| `harness.py` | Runs each golden frame through `vision_oracle.read_meter` (with the realistic context hint) and scores the result against `true`. **Per-frame** accuracy; exit code 0 if ≥ threshold, 1 if not — so a loop can iterate on reader code until it passes. |
| `audit_labels.py` | Finds + quarantines **poisoned labels** in the banked training set using meter monotonicity (Longest Non-Decreasing Subsequence). Robust to false-highs AND false-lows. Reversible (moves to `*-quarantine/`, deletes nothing). |
| `build_cnn_dataset.py` | Export gate: monotonic backbone → cross-reader verify (`--verifier tower\|oracle`, `--max-per-label N`). Emits `manifest.jsonl` (CNN-ready) + `needs_review.jsonl`. |
| `resolve_consensus.py` | Recovers disputed frames: re-reads each 3× with GPT-4o, promotes on majority vote + monotonic gate. Incremental/resumable/quota-aware. Corrects labels. |
| `finalize_dataset.py` | Bakes manual edits (`manual_labels.jsonl`) + manifest → `cnn_train.jsonl` (THE training file). Trust: manual > consensus > verified; excludes rejects/unresolved. |
| `rotate_upright.py` | Rotates stored frames 180° (camera is mounted upside-down) so they can be read right-side-up for verifying ground truth. |

## Run the harness (on the Acer — has the OpenAI key + tower access)

```bash
# from local: push the harness + golden, run against the stable golden frames
scp harness.py golden.json jamesearlpace@192.168.0.109:/tmp/
ssh jamesearlpace@192.168.0.109 \
  "cd ~/smart-garden-server && ./.venv/bin/python /tmp/harness.py \
     --frames ~/ocr-golden --golden /tmp/golden.json --reps 3"
```

- `~/ocr-golden/` = stable copy of the verified frames (the audit never touches it).
- `--reps N` = re-read each frame N times (glare is stochastic; a frame passes if any rep is correct, matching how the live system reads the same meter repeatedly).
- Pass threshold is set in `harness.py` (`PASS_THRESHOLD`). The golden set is deliberately weighted with the HARDEST/most-glared frames, so 60% there ≈ near-100% on typical frames.

## Audit the training labels

```bash
scp audit_labels.py jamesearlpace@192.168.0.109:/tmp/
# dry-run (just prints what it would flag)
ssh jamesearlpace@192.168.0.109 "python3 /tmp/audit_labels.py --dir ~/meter-training"
# apply (move flagged jpg+json into ~/meter-training-quarantine/)
ssh jamesearlpace@192.168.0.109 "python3 /tmp/audit_labels.py --dir ~/meter-training --apply"
```

To **restore** a quarantined frame: `mv ~/meter-training-quarantine/<file> ~/meter-training/`.

## Growing the golden set (makes the harness stronger)

1. Pull a sample of frames + rotate upright (`_bundle.sh` on server → scp → `rotate_upright.py`).
2. View `frames_upright/*.jpg` and record the TRUE reading for clearly-readable ones.
3. Add `{file, true, stored_label, label_ok, note}` rows to `golden.json` (use the **actual filename**, which carries the stored-label prefix).
4. Copy those frames into `~/ocr-golden/` on the server so the harness can reach them.

## Iteration loop (the point of all this)

1. Change reader code (`vision_oracle.py` hint, `dashboard.py` acceptance logic, tower OCR).
2. Deploy to the Acer.
3. Run `harness.py`. Read the per-frame failures.
4. Repeat until PASS. No manual screenshot-and-report needed.

## Key facts baked in

- Frames are stored **upside-down** (camera mount); harness/oracle rotate 180°.
- Reading is 9 digits, decimal 3 from the right: `094100762` = 94,100.762 ft³.
- The meter is **monotonic** — that's what makes the audit principled.
- Ground truth is **independent of the pipeline** — never auto-label from the reader being tested.
