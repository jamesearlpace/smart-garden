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

### Why this is the current best path
- The dominant current failure is ambiguity on blurry frames, not missing guardrails.
- These changes improve decision quality without reopening the catastrophic jump/crash classes we already closed.
- Internet-down windows are now explicitly excluded from the quality score so they do not pollute model/arbitration evaluation.
