# Meter Data Layer — Journey Doc

**Status:** ✅ Canonical ledger built, backfilled, reconciled, kept current, **real-time (capture dual-writes to it)**, and the **entire `/water-usage` page reads it** (one source). ⏳ Retention flip + (optional) retiring the legacy writes remain.
**Arc dates:** 2026-06-27 → 2026-06-28
**Goal (James's words):** *"a really high quality, auditable, verifiable data layer, really clean and architected very well"* — so that **clicking any value on a chart shows its image, and the only way they can disagree is the OCR misreading that image.** Foundation for *lots* of future water charts with defensible numbers.

> **RESUME HERE:** The page is unified on `meter_ledger`. The ledger is kept current by `meter-ledger-sync.timer` (every 10 min). The two remaining steps change the live capture path + retention, so do them with James watching. Read "Current State" and "What's Next" below.

---

## TL;DR of the whole sequence

A click on the water-usage graph showed the graph value (`095029.589`) disagreeing with the photo's AI read (`095229.678`) — which surfaced, step by step, that the system had **no clean data foundation**: usage and photos came from two different stores that drifted apart, the raw OCR read was never persisted, and numbers weren't traceable to evidence. We diagnosed it, logged it, patched the symptoms, then **stopped patching and built the foundation**: a canonical, append-only, auditable ledger, and re-pointed the charts onto it.

---

## The sequence (chronological)

### Phase 0 — Chart usability polish (early session)
1. **Data labels + hover** on all three charts (selective numbers, index-mode hover). — commit `2fecd51`
2. **"18 gallons per minute?"** confusion → the bar title "Gallons used per 18 min" was misread as a rate. Retitled to **"Gallons per bar — each bar = 18 min."** — commit `68f3323`
3. **"Click a number → image."** Made the data-label numbers clickable to open the meter photos. — commit `fa58978`
4. **"How do I compare with what the graph showed?"** Added a banner in the photo modal: *"What the graph plotted here: 095029.589 ft³"* so you could compare graph value vs the photos. — commit `2110353`

### Phase 1 — The bug hunt ("why didn't you catch this bug?")
5. The banner exposed a mismatch (graph `095029.589` vs a frame's `095929.678`). Investigated: the camera OCR **misreads the 4th digit under glare** (`0`→`9` or `0`→`2`), but the guardrail **rejected** it — the misread never entered the stored data. Confirmed `0` of that day's frames committed a bad value.
6. **"Where is the evidence `95,029.6` is correct?"** Pulled the actual frame, rotated it 180°, **read the physical odometer by eye = `095029.675`.** That, plus the week's monotonic climb, proved the stored value was right and `95929` was the rejected misread. (Also conceded the earlier "bill" reference was *circular* — `billing.py` is derived from the camera, not external.)

### Phase 2 — The real problem ("the graph doesn't show what the OCR reads")
7. **"But it says the graph plotted `095029.589`."** Sharp catch: even the two *trusted* values disagreed — the **graph plots `flow_sample` (`.589`)** while the **photos come from `archive_frame` (`.675`)**. Two parallel streams, drifting `0.086 ft³` apart. This is the core architecture flaw.
8. **RCA written + bugs logged** (`do an rca and log the bugs thoroughly`): `RCA-ocr-historical-read-2026-06-27.md` + GitHub issues **#40** (no persisted raw read), **#41** (graph ≠ OCR frames, lossy transforms), **#42** (usage high-water-mark has no outlier guard). Related existing: #36/#37/#39.

### Phase 3 — Symptom fixes ("do all of them, keep working")
9. **P0** — relabel the meter chart **"Validated meter lock (not raw OCR)."**
10. **P1** — a **faithful OCR-audit chart**: one point per archived frame, no bucketing/HWM/gap-fill, colored by confidence, click → its photo (`/api/water-usage/ocr-audit`). — commit `bfab09f`
11. **P2** — **persist the raw per-frame OCR read** (`archive_frame.raw_reading`; captured free from the same CNN call, before bounding). Verified live: committed `95029.675` vs raw `95929.678` now a queryable series. — commit `bfab09f`
12. **P3** — flag-only **usage-outlier counter** (implausible single-step jumps). Immediately caught the **+1,709.8 gal** #39 freeze-dump. — commit `e960ec0`
13. Honesty correction: I had over-claimed "it's all working / contained" from one window; James pushed back; measured the real scope (misreads *do* reach the stored stream, the usage code has *zero* outlier guard) and retracted.

### Phase 4 — The foundation ("are you building foundations or the minimum for 3 charts?")
14. **The pivot.** James asked whether I was building foundations or patching 3 charts — and confirmed he wants a clean, auditable, verifiable data layer. **Stopped patching; built the foundation.**
15. **`meter_ledger.py`** — the canonical 3-layer ledger (see Architecture below). — commit `43909f6`
16. **Backfilled** 28,282 readings from the legacy stores; **reconciles** to the legacy meter net within **0.7 gal over 16 days**; **lineage** drill-down verified.
17. **Keep-current `meter-ledger-sync.timer`** (every 10 min, incremental). — commit `5e9f026`
18. **Re-pointed the OCR-audit chart** to the ledger. — commit `c667102`
19. **Re-pointed the MAIN charts** (bar/cumulative/meter + banner) to the ledger → the whole page is one source; meter line now shows `95029.675` matching photos; 7d usage `3,300.45 gal` verified unchanged. — commit `9b40f74`

---

## The canonical data layer (architecture reference)

**Module:** `server-prod/meter_ledger.py` → own DB `meter_ledger.db` on the Acer (`~/smart-garden-server/`). Only *reads* the legacy DBs; tiny rows → kept **forever** (images age out, numbers don't).

**Three cleanly separated layers:**

1. **Raw observation (immutable, write-once)** — `raw_reading`, `raw_conf`, `reader`. What the OCR actually read from *that* image, before any validation. The fact.
2. **Validated reading (the truth, correctable)** — `committed`, `committed_cf`, `method` (`read`/`corrected`/`propagated`/`held`/`anchored`/`interpolated` = **provenance**), `confidence`, `reviewed`, `image_file` (evidence), `state`, `delta_cf`.
3. **Derived metrics (recomputable)** — `usage_daily` (gallons, start/end cf, `n_readings`, `n_image_backed`, `n_fresh_reads`, versioned `method='high_water_mark_v1'`). Always rebuilt from layer 2, never the only copy.

Plus **`meter_correction`** — append-only audit log of every change to a committed value, so any number's history can be replayed.

**Defensibility chain:** `usage_daily → meter_reading → raw read + the photo → corrections`. Every number traces to evidence.

**CLI:** `./.venv/bin/python meter_ledger.py {init|backfill|recompute|stats|reconcile|sync|lineage <ts>}` (idempotent).

**Keep-current:** `meter-ledger-sync.timer` → `meter_ledger.py sync` every 10 min (incremental: since-bounded backfill + `compute_deltas(only_null=True)` + peak-seeded `recompute_daily`).

---

## Current state (what's live)

- **`/water-usage` is fully unified on the ledger.** Meter line + "graph plotted X" banner = `95029.675` = the photos. The `.589`/`.675` split is gone everywhere.
- **OCR-audit chart** is the verification surface: one ledger row per point, committed + raw + provenance + photo. A point and its image can only disagree via OCR.
- **Ledger stays current** automatically (10-min sync). Reconciles to legacy within 0.7 gal/16d.
- **Verified:** 7d usage `3,300.45 gal` (matches the daily rollup), endpoint 0.18s, usage numbers unchanged by the re-point.

**Key numbers backfilled:** 28,282 readings (12,752 image-backed = auditable + 15,512 flow-gap fills). by_method: held 15,512 / read 9,319 / propagated 3,428 / corrected 5.

---

## What's next (need James — riskier, change live behavior)

1. ✅ **DONE — capture dual-writes to the ledger** (commit `e737ac5`): a fully-guarded `meter_ledger.record_reading()` in `_archive_frame` lands new readings as `origin='live'` within seconds. The legacy writes stay (true dual-write); retiring them is an optional later step once it's proven over time.
2. **Flip retention** so the canonical numbers are permanent (today `flow_sample` is 30-day; the ledger already keeps everything, but the capture path should target it).
3. **Future charts** = defensible views on `meter_ledger`, never new patches on `flow_sample`/`archive_frame`.
4. **Root-cause OCR** (#36/#37/#39) — separate track; the glare misreads are contained but ongoing. Not unattended-safe (CNN is documented dead weight without the hardware encoder-wire fix).

---

## Commits (this arc, in order)

| Commit | What |
|--------|------|
| `2fecd51` | data labels on 3 charts |
| `68f3323` | retitle bar chart "Gallons per bar — each bar = N min" |
| `fa58978` | clickable numbers → photo |
| `2110353` | graph-vs-photo comparison banner |
| `bfab09f` | OCR audit chart + persist raw per-frame read (P0/P1/P2) |
| `e960ec0` | usage-outlier flag (P3) |
| `43909f6` | **meter_ledger.py — canonical data layer** |
| `5e9f026` | incremental sync + 10-min keep-current timer |
| `c667102` | re-point OCR audit chart → ledger |
| `9b40f74` | re-point MAIN charts → ledger (whole page one source) |

Issues: **#40** (no raw read — closed), **#41** (graph≠OCR — closed), **#42** (usage outlier guard — open, flag shipped). Repo: `jamesearlpace/smart-garden-server`. RCA: `RCA-ocr-historical-read-2026-06-27.md`.

---

## Key decisions & lessons

- **Confounds were symptoms, not bugs.** The `.589/.675` drift, bucketing, gap-fill, and false-precision were all downstream of *no single source of truth*. Patching them one by one was the wrong frame; the foundation was the fix.
- **Only the raw per-frame read can guarantee "value came from this image."** Committed values can be propagated/held/anchored (not read from that image), so verification must center on `raw_reading` + the photo.
- **Separate raw (immutable) from validated (correctable) from derived (recomputable),** with a correction log and provenance on every value — that's what makes numbers defensible.
- **Build additively, prove it reconciles.** The ledger took zero risk (own DB, read-only of legacy) and was proven against reality (0.7 gal/16d) before anything was re-pointed.
- **I over-claimed once** ("it's all working") and had to retract after measuring. Verify scope with data before reassuring; self-consistency ≠ correctness.
- **PS→ssh gotcha:** a `(` in a remote command makes PowerShell strip inner double-quotes → bash syntax error. Keep remote commands paren-free or scp a script.
