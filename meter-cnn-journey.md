# Meter CNN — Model Quality & Path to ~100%

> Journey doc for the water-meter digit CNN: the data audit, the model-quality
> upgrades, the benchmark audit, and the (negative) fusion experiment that
> reframed what "~100% accuracy" even means here. Captured 2026-06-20.
>
> Companion to `smart-garden-journey.md`. The OCR/CNN system reads a Sensus 9-digit
> LCD water meter from a fixed camera; a small CNN runs on the tower (jackmint
> 192.168.0.120, `~/meter-cnn/`), the Flask app + lock run on the Acer
> (192.168.0.109, `~/smart-garden-server/`).

## TL;DR
- **The system reading (running total / cost) is already ~100% correct** — the
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

**Failed experiments (do NOT re-propose without new evidence):**
1. **Naive multi-frame fusion** — glare is systematic (constant over seconds); fusing correlated-wrong reads = confidently wrong. Offline-proven.
2. **Naive context-decoder** — overwrote fast low digits from a stale prior, 93%→66%; position-aware recovered to ~92% but never beat raw. Shelved.
3. **Aggressive augmentation stacking** — glare 0.55 + perspective + noise + jpeg cratered an 8-ep smoke to 0.142. Aug must stay harder-but-READABLE.
4. **Glare augmentation (softened)** — full retrain 0.664 vs 0.673, hard-frame net −1. Kept v5.
5. **Synthetic recombination + trust weighting** — full retrain EXACT TIE 0.6726. Kept v5.

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
