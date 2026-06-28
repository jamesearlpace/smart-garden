# RCA — The meter system can't answer "what did the OCR read at time T?"

**Date:** 2026-06-27
**Severity:** High — a core capability is missing, and it quietly undermines trust in every historical insight the system produces.
**Found by:** James, via the `/water-usage` graph-vs-photo mismatch (graph plotted `95029.589`; a frame showed `095929.678`).
**Status:** Open — remediation not started.

---

## Executive summary

The smart-garden meter pipeline **cannot faithfully answer the most basic historical question** — *"what did the OCR read at a given time?"* — because **the raw per-frame OCR output is never stored.** Every persisted reading (`flow_sample.reading_cf`, `archive_frame.reading_cf`) holds the post-validation **lock** value, which is deliberately engineered to reject/suppress misreads. The graph then applies further lossy transforms (bucketing, gap-fill, high-water-mark). The net result is a graph that **looks clean by design**, is sourced from a **different stream than the photos**, and leaves **no recoverable record of what the reader actually saw**. For a project whose entire purpose is reading a meter from images, the raw reading is the one thing not kept.

This is not (primarily) an OCR-accuracy bug. It is an **observability / data-architecture** bug: the system measures and stores its *cleaned conclusion*, never its *raw observation*, so it cannot be audited against itself.

---

## The requirement that fails

> "What was the water meter reading, **according to the OCR**, at 3:00 PM on June 20?"

There is no data source that answers this. Every stored value is the lock (validated / held / anchored / propagated), not the OCR's actual per-frame output. The raw read is computed transiently and discarded.

---

## What actually happens (pipeline, layer by layer)

| # | Stage | Where | What it does to the value |
|---|-------|-------|---------------------------|
| 1 | Capture | ESP32-CAM | Pushes a frame ~every 5s |
| 2 | Read | CNN + GPT-4o oracle | Produces a **raw guess** for the frame |
| 3 | Validate → lock | `cam_ocr` / `_oracle_run` | Monotonic + forward-bound + anchor + corroboration → updates `meter_reader.last_good`. **Raw guess discarded here.** |
| 4 | `flow_sample` (smart-garden.db) | flow_monitor sampler | Stores `last_good` every 15s as `reading_cf` → **what the GRAPH plots** |
| 5 | `archive_frame` (meter_archive.db) | `_archive_frame` | Indexes each saved frame with `last_good` (or a CNN re-read **anchored to the lock**) → **what the PHOTOS show** |
| 6 | Graph display | `api_water_usage` | **Buckets** to the last reading per bucket; **carries forward** across gaps; **high-water-mark** for bar/cumulative |

Six transformation layers sit between the camera and the plotted point. The raw read is gone after step 3.

---

## Root causes

**RC1 — No raw-read persistence (the core).** Neither database stores the raw per-frame OCR guess. `archive_frame`'s schema has no column for it; the modal's "AI reads X" is computed at view time and thrown away. → Historical raw OCR is **unrecoverable**.

**RC2 — Two parallel streams that can diverge.** The graph plots `flow_sample`; the photos come from `archive_frame`. Both derive from the lock but via different throttles/anchoring, so the thing you audit *with* (the graph) is **not** the thing you audit (the frames).

**RC3 — Lossy display transforms.** Bucketing keeps only the *last* reading per bucket (hides ~80 individual 15s reads per point on a 12h view); gap-fill **carries values forward** (a flat line can mean "no data," not "steady"); high-water-mark **suppresses dips** (bar/cumulative). Each diverges from "what was read."

**RC4 — Most archive values are derived, not read.** Of accepted readings in the last 7 days, only **~74%** are high-confidence direct reads; **~26%** are `inferred`/`propagated`/`medium` (copies/holds). The newest row at the time of this RCA is `propagated`.

**RC5 — Usage high-water-mark has no outlier guard.** `api_water_usage` trusts `reading_cf` completely; a surviving misread that sets a false new high injects phantom gallons (≈7.48 gal/ft³), only partly self-cancelling.

---

## Evidence (verified 2026-06-27)

- **Graph source:** `api_water_usage` → `SELECT ... reading_cf FROM flow_sample` (dashboard.py ~L1786).
- **`flow_sample` = the lock:** flow_monitor sampler stores `meter_reader.last_good` every 15s (see memory note + flow_monitor.py).
- **`archive_frame` = the lock too:** `_archive_frame` indexes frames with `meter_reader.last_good` / lock-anchored re-read (dashboard.py ~L4011).
- **No raw-guess column:** `archive_frame(ts, filename, reading, reading_cf, confidence, source, reviewed, updated_ts)`. Newest row: `confidence=propagated, source=propagated`.
- **Confidence mix (7d, accepted frames):** high 8644 · inferred 1701 · propagated 861 · medium 532 · manual 5 → **~26% derived, not read**.
- **Stored-stream anomalies (14d, 85,548 samples):** 82 backward steps, 7 big jumps up (>50 ft³), 4 big drops — all during `state=gap`, in canceling pairs (transient misreads).
- **Usage HWM, no rejection:** dashboard.py ~L1836-1845 (`elif rc > peak_cf: dgal = (rc - peak_cf) * GAL`).
- **Physical ground truth:** the 15:11:07 frame, read by eye (rotated 180°), shows `095029.675` → the lock/graph are correct here; `95929` was a transient misread the guardrail rejected.

---

## Impact

- The graph **cannot be used to audit the OCR** — the explicit thing James wants it for.
- *"What did the OCR read at time T"* is **unanswerable** historically.
- A clean graph gives **false confidence** — it is engineered to look clean regardless of OCR health.
- After a long build, the basic insight (faithful historical reads) is the missing piece.

---

## Why it wasn't caught earlier

Every health check runs on the **cleaned lock stream** or the **watering engine** — both look correct precisely *because* the guardrails reject bad reads upstream. The error is contained but invisible; no check ever compared the plotted value to the raw frame read. A human eye caught it.

---

## Remediation (phased)

- **Phase 0 (now) — stop lying by omission.** Relabel the meter chart "validated lock (not raw OCR)"; surface confidence so `propagated`/`inferred` points are visibly flagged.
- **Phase 1 — faithful audit line from existing data.** Plot one point per `archive_frame` (same source as the photos), **no** high-water-mark, **no** carry-fill, **no** bucketing-collapse, colored by confidence. Click a point → its frame.
- **Phase 2 — persist the raw read.** Add `raw_reading` (+ reader, conf) written **at capture, before bounding/anchoring**. Overlay raw vs lock. This is what finally answers *"what did the OCR read at time T."*
- **Phase 3 — usage outlier guard.** Reject a high-water-mark advance that exceeds physical max flow × elapsed; flag instead of silently accruing.
- **Phase 4 — root-cause OCR** (#36 / #37 / #39): reduce the misread rate at the source.

---

## Tracked as

- **Existing:** #35 (lag during flow / record per-5s), #36 (`reading_cf` backward), #37 (archive garbles), #39 (freeze).
- **New (filed with this RCA):**
  - **#40** — [data-integrity] No persisted raw OCR read — cannot answer "what did the OCR read at time T?" (**the core bug; RCA Phase 2**)
  - **#41** — [audit] Graph plots the validated lock through lossy transforms, not the OCR frames — unusable for OCR audit (**RCA Phase 0 + 1**)
  - **#42** — [data-integrity] Usage high-water-mark has no outlier guard — a surviving misread injects phantom gallons (**RCA Phase 3**)
