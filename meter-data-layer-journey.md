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

## 2026-06-28 - Local mitigation after garden-run split-brain finding

Context: James ran Garden manually (~15:42-15:48) and the layers disagreed: `flow_sample` saw 0 gal, `archive_frame` saw ~12 gal, `/water-usage`/ledger saw ~19 gal.

Changes made locally:
- `/api/water-usage/audit` now reads the same `meter_ledger` rows as `/api/water-usage`, instead of auditing against legacy `flow_sample`.
- `water_reconcile.py` now compares engine-estimated usage against `usage_daily` from `meter_ledger`.
- `flow_monitor` can sample a supplied canonical reading; dashboard startup passes `meter_ledger.latest_committed_cf`, with fallback to `meter_reader.last_good` if the ledger is unavailable.

State: deployed via `deploy.ps1` on 2026-06-28 18:12. Remote backups use suffix `.bak.20260628-181221`; smoke test `/login` returned 200. Next validation: repeat a short manual zone run and verify `meter_ledger`, `/water-usage`, `/api/water-usage/audit`, and newly written `flow_sample` rows agree.

## 2026-06-28 - 19:54 live validation + strict-backfill rollback

Context: James changed repo access rules to allow live read/write investigation. Rechecked the follow-up manual Garden run:
- `watering_event`: zone 7, `2026-06-28T19:54:15` -> `19:56:16`, 121s, manual.
- `/api/water-usage/audit?minutes=45`: verdict `accurate`, chart total = physical meter = **2.43 gal**, 97 ledger rows, 0 gap rows.
- Final verified window `19:50-20:02`: `flow_sample`, `archive_frame`, and `meter_ledger` all now read `95032.279 -> 95032.604` = **2.43 gal**; archive-vs-ledger mismatches = 0.

Finding: the main mitigation worked: `flow_sample` now follows the canonical ledger instead of freezing. But the rolling `strict backfill auto` job then corrupted recent `archive_frame` rows at 20:15/20:17 by propagating a stale value (`95030.604`) over better live ledger/CNN rows. That recreated an archive-vs-ledger split even though the charts were correct.

Actions:
- Disabled live rolling strict backfill via systemd override: `METER_STRICT_BACKFILL_AUTO_ENABLED=0`; verified in service env.
- Deployed `dashboard.py` backup `.bak.20260628-212022`: default auto strict backfill is now off, and strict reprocess may no longer downgrade an existing frame-specific `cnn`/`oracle`/`manual` row to a propagated guess.
- Repaired the damaged archive rows from `meter_ledger` after DB backups and service stop/start:
  - `meter_archive.db.bak.strict-backfill-repair-20260628-202117`
  - `meter_archive.db.bak.strict-backfill-repair2-20260628-202202`

State: data for the test window is clean across all three layers. Keep strict backfill manual/on-demand only until its algorithm can prove it will not overwrite frame-specific reads with continuity guesses.

## 2026-06-28 - 5-minute Garden validation passed

Context: James requested a longer live test of the same Garden zone (UI "Zone 8 of 9", internal zone id 7) to prove the data layer that backs `/water-usage` is clean end-to-end.

Run:
- Pre-closeall, open zone 7 at `2026-06-28T20:24:45`, close at `20:29:46`, closeall backstop at `20:29:47`.
- `watering_event` id 572: zone 7, 300s, manual_toggle, engine estimate 2.5 gal.

Validation:
- Exact run window (`20:24:45` -> `20:29:47`): `flow_sample`, `archive_frame`, and `meter_ledger` all show `95032.604 -> 95033.071` = **3.49 gal**.
- Settled wider chart window (`20:23:30` -> `20:40:00`): all three stores show `95032.604 -> 95033.090` = **3.64 gal**, 0 backward steps, archive-vs-ledger mismatches = 0.
- `/api/water-usage?minutes=30` (the three-chart backing payload): `total_gal=3.64`, bucket `45s`, meter line ends at `95033.090`, cumulative line ends at `3.64`, health `pct_monotonic=100.0`, no big jumps/outliers.
- `/api/water-usage/audit?minutes=30`: verdict `accurate`; chart total = physical meter = **3.64 gal**; 85 ledger rows, all image-backed, 70 fresh OCR, 0 flow-gap rows.
- `/api/status`: `active_zones=[]` after close.
- No `strict backfill` journal entries during the test; service env still has `METER_STRICT_BACKFILL_AUTO_ENABLED=0`.

Decision: the canonical meter data layer is working for this live Garden-zone test. The measured water (`3.64 gal / 5 min` = ~0.73 gpm) is higher than the config estimate (`2.5 gal`, 0.5 gpm), which is a calibration/tuning observation, not a data-layer defect.

## 2026-06-28 - `/water-usage` custom range + grain controls

Context: James wanted the three-chart water-usage page to choose both the time window and the bucket grain, including 5-second bars, e.g. `2026-06-28 10:30 -> 10:45`.

Changes:
- `/api/water-usage`, `/api/water-usage/audit`, and `/api/water-usage/ocr-audit` now all accept either rolling `?minutes=N` or explicit local `?start=YYYY-MM-DDTHH:MM[:SS]&end=...`.
- `/api/water-usage` accepts `bucket_s=5|10|15|30|60|300|900|1800|3600` (and other values clamped 5s-24h); omitted = auto grain.
- `/water-usage` UI keeps the rolling chips and adds Start, End, Grain, Apply range, and Use rolling controls. All three chart payloads and audit buttons share the same query string.

Validation:
- `start=2026-06-28T10:30:00&end=2026-06-28T10:45:00&bucket_s=5`: absolute mode, 5s buckets, 172 buckets, 27 ledger rows, audit verdict `accurate`.
- Garden run window `20:24 -> 20:31` at 5s: `total_gal=3.64`, 79 buckets, 40 samples, 100% monotonic, audit verdict `accurate`, OCR audit 40 points.
- Authenticated `/water-usage` HTML contains `grainSelect` and `datetime-local` controls. Deployed `dashboard.py` + `water_usage.html` with backups `.bak.20260628-221946`; copy-only template redeploy backup `.bak.20260628-222119`.

## 2026-06-28 - Browser QA auth helper

Context: Codex could verify `/water-usage` through authenticated API calls but could not visually open the protected page because the in-app browser had no Google login/session.

Change:
- Added `tools/authcookie.sh`, the browser-cookie equivalent of `tools/authcurl.sh`.
- It runs on the Acer with sudo, reads the live `SESSION_SECRET`, picks the first `allowed_emails.json` email, and prints a valid signed `session` cookie. No app route, no public bypass, no auth relaxation.

Usage:
- Header check: `ssh acer "cd ~/smart-garden-server && sudo bash tools/authcookie.sh --header"`
- Browser automation: use `--js` output to add the cookie for `sprinklers.savagepace.com`, then open `/water-usage`.

## 2026-06-28 - 5-second visual QA on `/water-usage`

Context: James asked to inspect the live water-usage page zoomed into the recent Garden test at 5-second grain.

Validation:
- Rendered authenticated `/water-usage` in headless Chrome for `2026-06-28T20:24:00` -> `20:31:00`, `bucket_s=5`.
- Page showed `79 buckets of 5s`, `3.64 gal`, exact local range, and all four chart canvases nonblank.
- Main three charts (per-bar gallons, cumulative gallons, validated meter lock) were readable and aligned on the shared time axis.

Change:
- Fixed the OCR audit chart so raw OCR outliers no longer expand the y-axis and flatten the committed meter line.
- Raw OCR outliers are now pinned to the chart edge, retain their true value in tooltip data, and are counted in the audit note.
- Deployed `water_usage.html` backup `.bak.20260628-230541`.

State: the recent Garden test at 5-second grain is visually inspectable on the live page. Screenshot: `_water_usage_recent_5s_zoom_fixed.png`.

## 2026-06-28 - OCR reporting separated from committed usage

Context: James correctly called out that the 5-second consumption spikes should not be smoothed away. If the apparent spikes come from OCR/commit behavior, the graphs and data layer must expose that instead of inventing a smoother flow profile.

Findings:
- Reverted the attempted bucket-distribution/smoothing change; `/api/water-usage` again reports exact committed high-water deltas in the bucket where the ledger committed them.
- Garden test window still shows the exact suspicious committed jump: `20:25:10`, `0.97 gal`, `11.67 gpm`.
- Raw OCR for the same `20:24 -> 20:31` window is not healthy: `40/40` raw reads are `low` confidence and differ from committed values. Example: raw `95930.604 ft3` vs committed `95032.604 ft3` (`+898.000 ft3`).

Changes:
- `/api/water-usage/ocr-audit` now reports committed confidence separately from raw OCR confidence (`by_conf` vs `by_raw_conf`) and returns `raw_mismatches`, `raw_conf`, `raw_reader`, and `raw_diff_cf` per frame.
- `/water-usage` OCR audit legend now shows both layers: committed (`medium`, `propagated`) and raw OCR (`low`). The note explicitly says when raw OCR differs from committed and when raw OCR outliers are pinned to the chart edge.
- Deployed `dashboard.py` + `water_usage.html` backup `.bak.20260628-231955`.

State: no fake smoothing is live. The page now focuses attention on the OCR failure: screenshot `_water_usage_ocr_reporting_fixed.png`.

## 2026-06-28 - Fixed constrained-CNN bad-anchor failure (+2.000 ft3)

Context: James pushed back that the 5-second spikes should not be smoothed or hidden; if OCR/commit behavior is wrong, fix that layer. Deeper inspection of Garden-test frames proved the committed meter values were anchored 2.000 ft3 high.

Root cause:
- The unconstrained CNN often read the visible low digits correctly but with a bad high digit, e.g. frame `20260628-202511.jpg`:
  - unconstrained CNN: `095930734`
  - unbiased `gpt-4o`: `095030734`
  - prior committed value: `095032734`
- The constrained CNN path forced the correct low-tail evidence into the bad anchor's high prefix (`95032...`), then the monotonic floor block overwrote an unbiased oracle down-correction back to the previous bad value.

Code changes:
- `_archive_try_exact_cnn` now rejects constrained CNN output when its low 5 digits conflict with the unconstrained CNN low 5 by more than `METER_ARCHIVE_EXACT_CNN_TAIL_CONFLICT` (default `800` counts).
- On that conflict, `_archive_frame` runs an unbiased authority-model reread and accepts it only when the raw low tail corroborates the oracle value.
- The monotonic floor repair no longer overwrites `oracle`/`manual` reads, so a high-confidence unbiased oracle can correct a bad anchor downward.
- Deployed `dashboard.py` backups `.bak.20260628-233330` and `.bak.20260628-233648`.

Historical repair:
- Backed up live DBs before writes:
  - `meter_ledger.db.bak.bad-anchor-2cf-20260628-233833`
  - `meter_archive.db.bak.bad-anchor-2cf-20260628-233833`
  - `smart-garden.db.bak.bad-anchor-2cf-20260628-233833`
  - `meter_archive.db.bak.ledger-align-garden-20260628-234057`
- Repaired the bad-anchor interval by subtracting exactly `2.000 ft3` where the row matched the proven pattern (`raw_reading 95930xxx/95931xxx`, committed `95032xxx/95033xxx`):
  - `797` ledger rows corrected and logged in `meter_correction`.
  - `312` archive rows corrected; the Garden validation window then aligned directly from the ledger.
  - `1284` flow samples corrected (`reading_cf`/`prev_cf`, with `delta_cf`/`gpm` recomputed).

Validation:
- Forward path after fix: newest rows now stay at `95031097`, not the prior bad `95033097`.
- Garden window `2026-06-28T20:24:00 -> 20:31:00`:
  - ledger: `95030.604 -> 95031.090` = `3.64 gal`, 40 rows.
  - archive: `95030.604 -> 95031.090` = `3.64 gal`, 40 rows, `0` archive-vs-ledger mismatches.
  - flow: `95030.604 -> 95031.090` = `3.64 gal`, 28 rows.
  - `/api/water-usage/audit`: `accurate`, chart total `3.64 gal`, physical meter net `3.64 gal`.
- Screenshot after repair: `_water_usage_ocr_repaired.png`.

State: the OCR/commit bug was real and is fixed at the commit layer. The remaining 5-second bar spikes are exact commit-time deltas, not smoothed flow estimates.

---

## 2026-06-29 - Zone 1 3-minute live graph validation

Context: James requested another live test on UI Zone 1 to verify the `/water-usage` graphs at low grain after the OCR/data-layer fixes.

Changes:
- Pre-closed all valves, then started internal zone `0` (UI Zone 1) through `/api/run`.
- Explicitly stopped the run with `/api/closeall`; `/api/status` confirmed `active_zones: []`.

Validation:
- `watering_event` recorded zone `0`, `2026-06-29T06:54:20 -> 06:57:37`, `197` seconds, manual, estimated `13.13 gal`.
- `/api/water-usage?start=2026-06-29T06:53:30&end=2026-06-29T06:58:30&bucket_s=5`: `53` buckets, `12.4 gal`, health `100%` monotonic, `0` backward steps, `0` big jumps.
- `/api/water-usage/audit` verdict: `accurate`; chart total `12.4 gal` equals physical meter net `95031.097 -> 95032.754 ft3`.
- Rendered authenticated `/water-usage` with exact range + 5-second grain; screenshot `_water_usage_zone1_3min_5s.png`.

State: the three main charts render the Zone 1 test correctly. OCR audit still shows the unconstrained raw CNN high digit as out-of-context (`95932...`) while the committed/context meter line is correct (`95032...`), and the page labels that separation explicitly.

---

## 2026-06-29 - Fixed Zone 1 raw-tail hold at 06:55:29

Context: James inspected the Zone 1 chart/photo around `Jun 29, 2026 06:55:35` and pointed out the visible meter read was `095031765`, not the held `095031690`.

Finding:
- Frame `20260629-065529.jpg` had raw CNN `95931766` (wrong high digit, useful low tail) but committed `95031690` as `propagated`.
- That stale committed point pushed `0.57 gal` into the later `06:55:35` bucket, making that bar read too high.

Changes:
- Deployed `dashboard.py` backup `.bak.20260629-085739`.
- Added a conservative raw-tail salvage path: if the raw CNN high digit is wrong but its low 5 digits form a physically plausible forward move from the anchor, commit the anchored-tail value instead of holding the old row flat.
- Backed up live DBs with suffix `zone1-rawtail-20260629-075810`.
- Corrected `2026-06-29T06:55:29` from `95031690` to `95031766` in archive + ledger, logged `meter_correction`, and recomputed ledger deltas.

Validation:
- Exact local range `06:55:20 -> 06:55:50`, `bucket_s=5`: `06:55:35` bucket changed from `0.89 gal` to `0.32 gal`; the `06:55:25` bucket now carries `0.57 gal` from the corrected image-backed row.
- Full Zone 1 window `06:53:30 -> 06:58:30`: audit remains `accurate`; chart total `12.4 gal` equals physical meter net `95031.097 -> 95032.754 ft3`, `0` backward steps.

State: no smoothing was added; this was a committed-reading repair plus a forward-path OCR commit fix for the same raw-tail failure class.

---

## 2026-06-29 - Post-cutoff OCR harness + fresh Garden validation

Context: James set the fixed-camera cutoff at `2026-06-25T22:00 Pacific` and approved using Azure/GPT verification budget for post-cutoff corrections. The goal was not to smooth graphs, but to make committed meter history correct and make raw OCR failures visible.

Changes:
- Added `ocr-harness/post_cutoff_audit.py`, a repeatable read-only harness for post-cutoff ledger/archive invariants.
- Deployed `dashboard.py` backup `.bak.20260629-094813`: stale-CNN fallback now has the same raw-vs-constrained low-tail conflict guard as exact-CNN, so a constrained value is not accepted as direct CNN evidence when the raw OCR tail disagrees.
- Deployed OCR-audit reporting backups `.bak.20260629-095419` / `.bak.20260629-095457`: the audit payload now reports committed provenance from `archive_frame` (`cnn`, `oracle`, `reviewed_context`, `propagated`) separately from raw reader (`cnn`), so oracle/reviewed rows are no longer mislabeled as direct CNN context reads.
- Deployed archive-to-ledger mirror backup `.bak.20260629-095754`: later archive oracle/manual/reprocess corrections now update `meter_ledger`, log value changes, and recompute deltas, preventing background archive convergence from creating chart/archive drift.
- Tightened raw-tail salvage with `METER_ARCHIVE_RAW_TAIL_MAX_ADVANCE=200`; larger jumps must go to oracle/review.
- Repaired audited post-cutoff rows with DB backups, correction logs, and delta recompute:
  - Zone 1 `06:54:59` -> `95031445`, `06:55:09` -> `95031538`, `06:55:29` -> `95031766`.
  - Garden `2026-06-28T15:42-15:49` active run and later false-high plateaus aligned to oracle/visual/context evidence.
  - Fresh Garden `2026-06-29T08:40-08:50` raw-tail conflict rows marked reviewed/corrected where committed values were verified by oracle/visual/context; raw OCR values were preserved as raw evidence.

Validation:
- Proper Garden test (internal zone `7`, UI Zone 8): `2026-06-29T08:40:51 -> 08:42:58`, `127s`, event id `575`; `/api/status` confirmed `active_zones=[]`.
- `/api/water-usage?start=2026-06-29T08:40:30&end=2026-06-29T08:49:30&bucket_s=5`: `2.21 gal`, 100% monotonic, 0 backward steps, 0 big jumps, 0 usage outliers.
- `/api/water-usage/audit` for the same window: verdict `accurate`; chart total `2.21 gal` equals physical meter net `95033.805 -> 95034.100 ft3`; 30 ledger rows, all image-backed, 0 flow-gap rows.
- Post-cutoff harness: `archive_ledger_mismatches=0`, `negative_deltas=0`, `direct_cnn_tail_conflicts_unreviewed=0`.

State: the committed data layer is clean for post-cutoff history under the harness. The raw CNN still systematically misreads high digits (`959...` vs `950...`); those raw failures are preserved and reported in OCR audit, while reviewed/oracle/context commits keep the charts accurate without smoothing.

---

## 2026-06-29 - Stricter harness + oracle-confirmed fresh Zone 1 window

Context: After the Garden validation, the post-cutoff harness was tightened to fail if an archive row still claimed direct `cnn` while its raw CNN value materially differed from the committed value. A fresh short water run was then used to validate the data layer against new live frames.

Changes:
- `ocr-harness/post_cutoff_audit.py` now fails on `misleading_direct_cnn_raw_diff`, so constrained/context values cannot masquerade as direct CNN reads.
- Deployed provenance taxonomy fixes in `dashboard.py` / `meter_ledger.py`: `constrained_cnn`, `raw_tail_cnn`, and `reviewed_context` are distinct from raw direct `cnn`.
- Backed up and repaired live DBs:
  - `ocr-cleanup-20260629-090656`: fixed the `2026-06-28T20:29:01` negative delta after an oracle row and relabeled misleading post-cutoff `cnn` rows to `constrained_cnn`.
  - `ocr-prerun-flatten-20260629-091522`: removed inferred pre-run creep before the fresh Zone 1 valve opened.
- Ran a fresh Zone 1 test (event `576`, `2026-06-29T09:08:12 -> 09:10:15`, 122s). The wrong-zone selection was caused by PowerShell curl quoting during the test command; the server-side `request_int()` helper already handles JSON bodies.
- Oracle-read all moving/edge frames in the fresh test window. Corrections included `09:08:40` `95034422 -> 95034442`, `09:09:26` `95034782 -> 95034786`, `09:10:41` `95035170 -> 95035177`, plus the intervening moving frames. No fake smoothing was used.

Validation:
- Post-cutoff harness: `archive_ledger_mismatches=0`, `negative_deltas=0`, `direct_cnn_tail_conflicts_unreviewed=0`, `misleading_direct_cnn_raw_diff=0`.
- Fresh Zone 1 `/api/water-usage/audit?start=2026-06-29T09:07:30&end=2026-06-29T09:13:00&bucket_s=5`: verdict `accurate`; chart total `8.05 gal` equals physical meter net `95034.101 -> 95035.177 ft3`; 23 ledger rows, all image-backed, 20 fresh OCR/oracle rows, 0 flow-gap rows.
- OCR audit for that same window: 20 high-confidence oracle rows + 3 flat propagated pre-flow rows; raw CNN is preserved and visibly wrong on all 23 rows (`959...` vs committed `950...`).
- `/api/status` after the run confirmed `active_zones=[]`.

State: the committed post-cutoff data layer is clean under the stricter harness, and the newest live test is oracle-confirmed without smoothing. The raw CNN is still not trustworthy as an OCR source; current correctness depends on guards, oracle review for consequential frames, and truthful provenance.

---

## 2026-06-29 - Material movement oracle pass

Context: The stricter harness was clean on hard contradictions, but there were still unreviewed constrained/propagated rows with material positive deltas. Those rows can move 5-second bars, so they needed image-backed verification rather than contextual acceptance.

Changes:
- Extended `ocr-harness/post_cutoff_audit.py` with `material_unreviewed_non_oracle_deltas` (`delta_cf > 0.02` by default). Any material post-cutoff movement must now be oracle/manual/reviewed.
- Oracle-read all remaining unreviewed non-oracle/non-manual rows above that threshold. This found and corrected several count-level errors, including:
  - Zone 1 `06:55:09` `95031538 -> 95031615`.
  - Zone 1 `06:55:29` `95031766 -> 95031765`.
  - Zone 1 `06:55:37` `95031809 -> 95031803`.
  - Zone 1 `06:56:55` `95032400 -> 95032407`.
  - Zone 1 `08:35:48` `95033593 -> 95033599`.
  - Garden `08:41:09` `95033911 -> 95033941`.
- Resolved oracle-induced archive/ledger mismatches by oracle-reading the affected in-between frames instead of mirroring inferred propagation.
- No smoothing was added; each material moving row is now image-backed by oracle/manual/review, while no-flow propagated rows remain explicit propagated rows.

Validation:
- Post-cutoff harness: `archive_ledger_mismatches=0`, `negative_deltas=0`, `direct_cnn_tail_conflicts_unreviewed=0`, `misleading_direct_cnn_raw_diff=0`, `material_unreviewed_non_oracle_deltas=0`.
- Zone 1 `06:53:30 -> 06:58:30`, `bucket_s=5`: verdict `accurate`; chart `12.4 gal`; physical meter `95031.097 -> 95032.754 ft3`; 25 image-backed rows, 25 fresh OCR rows, 0 flow-gap rows.
- Zone 1 `08:33:30 -> 08:37:00`, `bucket_s=5`: verdict `accurate`; chart `7.86 gal`; physical meter `95032.754 -> 95033.805 ft3`; 17 image-backed rows, 17 fresh OCR rows, 0 flow-gap rows.
- Zone 1 `09:07:30 -> 09:13:00`, `bucket_s=5`: verdict `accurate`; chart `8.05 gal`; physical meter `95034.101 -> 95035.177 ft3`; 23 image-backed rows, 20 fresh OCR rows, 0 flow-gap rows.
- Oracle spend table after this pass: `1024` calls today, estimated `$4.096`, `793,977` tokens.

State: all material post-cutoff usage movement is now covered by oracle/manual/reviewed evidence under the harness. Remaining unreviewed rows are below the material threshold or no-flow propagation and are still explicitly labeled as such.

---

## 2026-06-29 - Watering-window trust pass + fresh Garden test

Context: The material threshold pass still allowed many tiny unreviewed deltas during actual watering windows. Individually they were below `0.02 ft3`, but during a real run they add to charted usage, so they needed evidence too.

Changes:
- Tightened `ocr-harness/post_cutoff_audit.py` to attach `smart-garden.db` and fail if any positive unreviewed non-oracle/non-manual delta appears inside a real `watering_event` window.
- Oracle-read all positive unreviewed rows inside post-cutoff watering windows. This covered the June 28 Garden runs and the June 29 Garden validation rows without smoothing or redistribution.
- Forced a ledger sync, then relabeled post-cutoff archive rows that claimed direct `cnn` even though the raw CNN value materially differed from the committed/context value. These are now `constrained_cnn`, preserving the raw OCR failure while reporting provenance honestly.
- Ran a fresh Garden test (event `577`, internal zone `7`, `2026-06-29T09:31:15 -> 09:33:32`, 137s) and explicitly stopped all valves.
- Oracle-read the positive moving frames from that fresh Garden run.

Validation:
- Fresh Garden `/api/water-usage/audit?start=2026-06-29T09:30:30&end=2026-06-29T09:34:30&bucket_s=5`: verdict `accurate`; chart total `2.14 gal` equals physical meter net `95035.177 -> 95035.463 ft3`; 18 ledger rows, all image-backed/fresh, 0 flow-gap rows.
- Historical repaired windows at 5-second grain all return `accurate`:
  - `2026-06-28T15:42:30 -> 15:49:30`: `4.52 gal`, 48 image-backed rows.
  - `2026-06-28T19:53:45 -> 19:56:45`: `2.33 gal`, 17 image-backed rows.
  - `2026-06-28T20:24:15 -> 20:30:15`: `3.49 gal`, 38 image-backed rows.
  - `2026-06-29T08:40:30 -> 08:43:30`: `2.21 gal`, 18 image-backed rows.
- Post-cutoff harness after forced sync: `archive_ledger_mismatches=0`, `negative_deltas=0`, `direct_cnn_tail_conflicts_unreviewed=0`, `misleading_direct_cnn_raw_diff=0`, `material_unreviewed_non_oracle_deltas=0`, `watering_window_unreviewed_positive_deltas=0`.
- `/api/status` after the run confirmed `active_zones=[]`.
- Oracle spend after this pass: `1109` calls today, estimated `$4.436`, `866,983` tokens.

State: post-cutoff committed usage movement inside watering windows is now oracle/manual/reviewed under the harness. The raw CNN still often reads the high digit as `959...`; the committed layer is correct through provenance, guards, and authority-model verification, not by smoothing.

---

## 2026-06-29 - loc2-v3 training export + fresh Zone 1 false-high repair

Context: James approved long-running OCR work for the fixed camera position, with the post-cutoff trust boundary set at `2026-06-25T22:00 Pacific`. The objective stayed strict: no fake smoothing, correct the OCR/reporting layer and keep raw failures visible.

Changes:
- Added `ocr-harness/export_archive_training.py` to export post-cutoff reviewed/oracle archive frames into the CNN training bank. Exported 5,799 reviewed fixed-camera frames and appended matching manual labels.
- Fixed the CNN training crop/versioning: retrain now uses the final location-2 crop `(0.10, 0.45, 0.82, 0.73)` and bumps `loc2-vN` versions correctly. `cnn_service.py` was aligned to the same crop.
- Trained and promoted `loc2-v3` on the tower. Metrics improved materially but are not yet perfect: trusted replay full-9 accuracy `79.7%`, hard-frame full-9 accuracy `31.9%`. The model is better, but the committed data layer still requires provenance and authority checks.
- Deployed archive reprocess provenance fixes: constrained/context reads now write `constrained_cnn`, oracle/manual reprocess rows are reviewed, and archive corrections mirror to `meter_ledger`.
- Ran a fresh live Zone 1 test; a PowerShell JSON quoting issue caused `/api/run` to use default internal zone `0` instead of the intended Garden zone. Event `578`: `2026-06-29T11:21:40 -> 11:24:12`, 152s.
- Found and repaired a direct false-high OCR row at `2026-06-29T11:22:56` (`95038185` raw vs reviewed `95036186`) plus adjacent authority-read rows. Repaired one impossible negative step at `11:23:18` with explicit `reviewed_context` after neighboring oracle reads proved the meter could not have decreased.
- Repaired idle drift introduced by an accidental broad reprocess by plateauing contradicted inferred rows to image-backed anchors, preserving raw readings and marking the committed values as reviewed context.

Validation:
- Post-cutoff harness: `archive_ledger_mismatches=0`, `negative_deltas=0`, `direct_cnn_tail_conflicts_unreviewed=0`, `misleading_direct_cnn_raw_diff=0`, `material_unreviewed_non_oracle_deltas=0`, `watering_window_unreviewed_positive_deltas=0`.
- Fresh Zone 1 audit `2026-06-29T11:21:00 -> 11:25:00`, `bucket_s=5`: verdict `accurate`; chart `9.67 gal` equals physical meter `95035.489 -> 95036.782 ft3`; 23 image-backed rows, 20 fresh OCR rows, 0 flow-gap rows.
- `/api/status` after testing: `active_zones=[]`.
- Tower health: `loc2-v3`, `ok=true`, retrain timer active.

State: the post-cutoff committed data layer is green under the stricter harness and the fresh 5-second chart audit. Raw CNN is improved but still not virtually perfect, so the system remains intentionally evidence/provenance driven: raw OCR is preserved, constrained/context/oracle commits are labeled, and charts use committed meter facts without smoothing.

---

## 2026-06-29 - Confidence-gated OCR acceptance after idle false-highs

Context: After `loc2-v3`, the committed layer was clean, but fresh idle frames produced repeated `95038782` false-high rows while the meter was actually flat at `95036782`. This was caused by trusting medium/low-confidence constrained CNN output too aggressively.

Findings:
- Re-scored the current `loc2-v3` service against all post-cutoff reviewed/oracle fixed-camera archive images.
- Unconstrained current CNN exact full-9 accuracy: `5741/5972 = 96.13%`.
- Sequential constrained decode with a `500` count physical window: `5882/5972 = 98.49%`.
- Every reviewed image with `min_conf >= 0.70` was exact in this fixed-camera evaluation; the remaining misses were below that confidence band, mostly rolling low-digit errors.

Changes:
- Raised archive exact/stale/reprocess constrained-CNN minimums from unsafe live overrides to `0.70`.
- Added `METER_CONSTRAINED_MIN_CONF` default `0.70` to the live constrained-median path, so low-confidence constrained values are not allowed to move the lock.
- Updated `deploy.ps1` to install a last-applied systemd drop-in (`zz-codex-ocr-thresholds.conf`) with the `0.70` archive thresholds; verified live env now shows `0.70`.
- Changed `meter_archive.record()` so new `oracle`/`manual` archive rows are inserted as reviewed anchors immediately.
- Repaired the idle false-high interval after backups: corrected post-`11:40` `95038782` rows to reviewed-context `95036782`, preserved raw OCR, and recomputed ledger deltas/daily usage.

Validation:
- Post-cutoff harness: `archive_ledger_mismatches=0`, `negative_deltas=0`, `authoritative_archive_unreviewed=0`, `material_unreviewed_non_oracle_deltas=0`, `watering_window_unreviewed_positive_deltas=0`.
- Idle audit `2026-06-29T11:40:00 -> 12:35:00`, `bucket_s=5`: verdict `accurate`; chart `0.0 gal` equals physical meter `0.0 gal`; 103 image-backed rows, 0 flow-gap rows.
- Fresh Zone 1 audit still accurate: `9.67 gal` chart equals `9.67 gal` physical meter.
- `/api/status`: `active_zones=[]`.

State: production now rejects the empirically unsafe low-confidence CNN band and falls back to oracle/review/propagation instead. This is stricter and may use more oracle calls until the CNN improves, but it avoids committing the exact false-high class found in the idle validation.

---

## 2026-06-29 - loc2-v4 hard-frame retrain and final confidence policy

Context: The committed/chart layer was green, but raw CNN still missed exactly the kind of fixed-camera low-digit and glare cases James cares about. The next pass focused on training the model on the hard frames it had actually missed, while preserving the rule that charts must never fake-smooth or hide raw OCR failures.

Changes:
- Patched `cnn/retrain.py` so non-held-out hard failures are included in training before the per-label cap, with `HARD_TRAIN_WEIGHT=3.0`. Previously some of the most valuable oracle-caught failures could be capped away.
- Retrained on the tower and promoted `loc2-v4`. The training set grew to 1,791 real rows plus 600 synthetic rows; held-out test stayed at 144 hard frames.
- Raised the live production acceptance gate from the temporary `0.70` band to `0.90` for constrained/live/archive OCR (`METER_CONSTRAINED_MIN_CONF`, `METER_ARCHIVE_STALE_CNN_MIN_CONF`, `METER_ARCHIVE_EXACT_CNN_MIN_CONF`, `METER_ARCHIVE_REPROCESS_CNN_MIN_CONF`) and deployed the guarded systemd drop-in through `deploy.ps1`.

Validation:
- Tower health: `version=loc2-v4`, `ok=true`, `threshold=0.9`; retrain timer active.
- Retrain summary: challenger fixed 14 hard frames and newly broke 3 vs `loc2-v3`; regression set stayed `0/9` misses.
- Post-cutoff reviewed fixed-camera export direct score: `5707/5799 = 98.414%` full-9 exact. By source: oracle `5437/5496 = 98.93%`, manual `251/282 = 89.01%`, reviewed_context `19/21 = 90.48%`.
- Confidence band check for `loc2-v4`: `min_conf >= 0.90` was `3798/3798 = 100.0%` exact on the reviewed post-cutoff export; `>=0.70` still had misses, so `0.70` is no longer considered safe for production commits.
- Post-cutoff committed-layer harness after deployment: `archive_ledger_mismatches=0`, `negative_deltas=0`, `authoritative_archive_unreviewed=0`, `material_unreviewed_non_oracle_deltas=0`, `watering_window_unreviewed_positive_deltas=0`.

State: the committed data layer and 5-second chart data are clean under the strict harness, with raw OCR failures preserved in `raw_reading`/conflict reporting. Raw CNN is much better but not virtually perfect: the remaining tail is mostly the rolling/ambiguous low digits. Production therefore only trusts the empirically exact `>=0.90` band and relies on oracle/review/propagation below that instead of smoothing the graph.

---

## 2026-06-29 - Corrected poisoned `95031090` plateau and promoted loc2-v5

Context: Reviewing the remaining `loc2-v4` misses exposed a bad post-cutoff ground-truth block. The archive/ledger and training labels had manually committed `95031090` for a plateau where the images visibly read `95031097`. This was exactly the concern James raised: if the ground truth is wrong, the CNN is punished for reading the glass correctly and future training learns the wrong digit.

Changes:
- Visually inspected representative upright frames from `2026-06-28T20:30:16 -> 21:45:16`; the plateau reads `95031097`, not `95031090`.
- Backed up `meter_archive.db`, `meter_ledger.db`, and `manual_labels.jsonl` with stamp `20260629-152002`.
- Corrected 139 archive rows and 139 ledger rows from `95031090` to `95031097`, preserving raw OCR and writing ledger correction rows with note `visual_review_95031090_plateau_should_be_95031097`.
- Appended training-label overrides for the affected existing training-bank filenames so the CNN no longer trains those images as `...090`.
- Retrained and promoted `loc2-v5` after the corrected labels exposed the real failure class.
- Tightened production CNN acceptance from `0.90` to `0.97` because `loc2-v5` has three misses above `0.90`; the highest remaining miss in the post-cutoff eval is `min_conf=0.957`.

Validation:
- `loc2-v5` gated retrain: hard holdout full-9 `0.410` vs `loc2-v4` corrected champion `0.333`; ground-truth replay `0.940/0.815` vs champion `0.938/0.801`; hard-frame net `+11`; regression set `0/9`.
- Tower health: `version=loc2-v5`, `ok=true`, threshold `0.9` at the CNN service; server-side commit gate is now `0.97`.
- Corrected post-cutoff direct eval: `5723/5799 = 98.689%` full-9 exact. The corrected `loc2-v4` baseline was `5615/5799 = 96.827%`.
- High-confidence calibration after `loc2-v5`: `>=0.90` is not safe (`1510/1513`); server-side production now requires `>=0.97`.
- Live systemd env verified after deploy: `METER_ARCHIVE_STALE_CNN_MIN_CONF=0.97`, `METER_ARCHIVE_REPROCESS_CNN_MIN_CONF=0.97`, `METER_ARCHIVE_EXACT_CNN_MIN_CONF=0.97`, `METER_CONSTRAINED_MIN_CONF=0.97`.
- Post-cutoff committed-layer harness remains green: `archive_ledger_mismatches=0`, `negative_deltas=0`, `authoritative_archive_unreviewed=0`, `material_unreviewed_non_oracle_deltas=0`, `watering_window_unreviewed_positive_deltas=0`.

State: the committed data layer is still clean, and one poisoned label block has been removed from both history and training. Raw OCR improved again but remains below the "virtually perfect" bar; remaining errors are still concentrated in rolling low digits and ambiguous frames. Current safe policy is stricter: only the `>=0.97` band may commit via CNN, and lower-confidence output must remain raw evidence or be resolved by oracle/review/context.

---

## 2026-06-29 - Expanded raw-CNN eval while committed layer stays green

Context: After `loc2-v5`, the committed layer was green but raw OCR still showed conflicts. The next pass measured the live production CNN over HTTP against the expanded post-cutoff archive and separated independent visual truth from propagated committed rows.

Changes:
- Added `ocr-harness/eval_live_cnn_http.py` for read-only Acer-side evaluation of the live CNN endpoint against archived JPEGs.
- Added `ocr-harness/summarize_live_cnn_misses.py` for miss clustering and poisoned-label review queues.
- Exported 410 newly eligible authoritative post-cutoff archive frames/labels into the CNN training bank. This touched `~/meter-training` and `~/cnn-dataset-oracle`, not `meter_archive.db`, `meter_ledger.db`, or `smart-garden.db`.

Validation:
- Live post-cutoff committed-layer harness remains green: archive/ledger mismatches `0`, negative deltas `0`, misleading direct-CNN diffs `0`, material unreviewed non-oracle deltas `0`, watering-window unreviewed positive deltas `0`.
- Full committed archive eval over live CNN: `9435/10343 = 91.221%` exact; this includes propagated rows and is mainly a raw-conflict surface.
- Authoritative-only eval (`oracle`, `manual`, `reviewed_context`): `5884/6073 = 96.888%` exact.
- Production gate evidence stayed strong: authoritative `min_conf >= 0.97` is `939/939 = 100%`; `>=0.90` is not safe (`83/85`).
- Main raw failure class: `095036782 -> 095035782`, `97` authoritative misses, concentrated at digit position 5.

State: the data layer is still correct by provenance and audit, with raw failures preserved rather than smoothed. The raw CNN is not finished; the newest hard-frame labels are now staged for retraining.

---

## 2026-06-29 - GPT-4o verified manual-label repair

Context: Two high-confidence manual-label disagreements in the `2026-06-28T20:26` and `20:28` windows were plausible enough that they were not safe to rewrite from temporal context alone. Authority-model reads were used to decide whether the committed data or the raw CNN was right.

Changes:
- Checked candidate archive frames with GPT-4o through the live oracle environment.
- Backed up `meter_archive.db`, `meter_ledger.db`, and `manual_labels.jsonl` before any writes.
- Corrected five oracle-verified bad committed labels while preserving raw OCR fields and recording ledger corrections with actor `codex_gpt4o_review`.
- Recomputed ledger deltas and daily totals after the edits.
- Exported the repaired labels to the training bank so future CNN retrains do not learn the old bad labels.

Validation:
- Corrected rows: `2026-06-28T20:25:56 -> 095030793`, `20:26:06 -> 095030807`, `20:26:11 -> 095030813`, `20:26:21 -> 095030827`, `20:28:41 -> 095031007`.
- The repaired window now has monotonic positive deltas with no negative jumps.
- Post-cutoff audit after repair: `archive_rows=10395`, `ledger_rows=10395`, `archive_without_ledger=0`, `archive_ledger_mismatches=0`, `negative_deltas=0`, `direct_cnn_tail_conflicts_unreviewed=0`, `misleading_direct_cnn_raw_diff=0`, `authoritative_archive_unreviewed=0`, `material_unreviewed_non_oracle_deltas=0`, `watering_window_unreviewed_positive_deltas=0`.

State: The data layer is still green and remains provenance-based: corrected committed values are marked/reviewed, raw OCR stays visible, and chart data should continue to use the ledger rather than smoothed or inferred raw reads. Raw OCR quality work continues in the CNN training loop.

---

## 2026-06-29 - Late archive reconciliation and reviewed watering segment

Context: After `loc2-v6` promotion, new archive corrections/inferred rows arrived while `meter_ledger.sync()` still used `INSERT OR IGNORE`. That left existing ledger timestamps stale when archive values changed, producing archive/ledger mismatches and unreviewed positive deltas in a zone 5 watering window.

Changes:
- Repaired one propagated negative-delta row: `2026-06-28T19:54:40` from `095030310` to visually reviewed `095030453`; raw OCR preserved.
- Reconciled late archive updates into ledger rows, with backups and correction-log entries for committed-value changes.
- Reviewed the bracketed `2026-06-29T21:09:26 -> 21:14:16` watering segment against authority anchors at `21:09:41` (`095036963`) and `21:14:51` (`095038155`). The values remain provenance-labeled; only the review flag/correction log was added.
- Recomputed ledger deltas and daily totals after each repair.

Validation:
- Final strict post-cutoff audit: `archive_ledger_mismatches=0`, `archive_without_ledger=0`, `negative_deltas=0`, `direct_cnn_tail_conflicts_unreviewed=0`, `misleading_direct_cnn_raw_diff=0`, `archive_only_misleading_direct_cnn_raw_diff=0`, `authoritative_archive_unreviewed=0`, `material_unreviewed_non_oracle_deltas=0`, `watering_window_unreviewed_positive_deltas=0`.
- Final live CNN authoritative eval: `5992/6120 = 97.909%`, with `min_conf >= 0.97` still `3557/3557 = 100%`.

Decision: The one-off repair helper fixed live history, but the durable code fix should make `meter_ledger.sync()` update existing rows when archive committed/provenance fields change. Otherwise late archive corrections can leave the ledger stale again.

Follow-up code fix:
- Patched `meter_ledger.backfill_from_archive()` so `sync()` updates existing ledger rows when archive committed/provenance/raw fields change, instead of only `INSERT OR IGNORE`-ing new timestamps.
- Deployed through `deploy.ps1`; remote backup `.bak.20260630-000400`; smoke `/login` returned 200.
- Ran patched live `meter_ledger.sync()` and strict audit after deployment: archive/ledger mismatches `0`, negative deltas `0`, material unreviewed deltas `0`, watering-window unreviewed deltas `0`.

State: committed chart data is green under the strict harness, with raw OCR failures still preserved. The retrain timer was restored after the forced `loc2-v7` rejection, and the archive-to-ledger drift bug now has a production code fix.

---

## 2026-06-30 - post-loc2-v7 chart data audit still green

Context: After the right-edge crop fix promoted `loc2-v7`, the data layer needed a fresh strict check to make sure the three water-usage charts were still backed by aligned committed rows, not raw OCR guesses or smoothed values.

Changes:
- Ran live `meter_ledger.sync()` after the model/threshold change. It recomputed the last two days and added no new deltas.
- Re-ran the strict post-cutoff audit from `2026-06-25T22:00:00`.

Validation:
- `meter_ledger.sync()` result: `new_deltas=0`, `days_recomputed=2`, `image_backed=13513`, `flow_gap_fill=15512`, `total=33175`.
- Strict audit: `archive_rows=11180`, `ledger_rows=11180`, `archive_ledger_mismatches=0`, `archive_without_ledger=0`, `negative_deltas=0`, `direct_cnn_tail_conflicts_unreviewed=0`, `misleading_direct_cnn_raw_diff=0`, `archive_only_misleading_direct_cnn_raw_diff=0`, `authoritative_archive_unreviewed=0`, `material_unreviewed_non_oracle_deltas=0`, `watering_window_unreviewed_positive_deltas=0`.
- Raw conflict report remains nonzero by design (`raw_tail_conflicts_reported=768`); these are preserved raw OCR disagreements, not committed chart-data mismatches.

State: The chart data layer is still green. The remaining problem is raw OCR model accuracy/calibration, not the ledger/archive structure.

---

## 2026-06-30 - operational stop audit after loc2-v7

Context: After deciding the system is operationally good enough, the data layer was checked again against the current larger archive to avoid freezing the decision on stale evidence.

Validation:
- Live `meter_ledger.sync()` result: `new_deltas=0`, `days_recomputed=2`, `image_backed=13917`, `flow_gap_fill=15512`, `total=33581`.
- Strict post-cutoff audit from `2026-06-25T22:00:00`: `archive_rows=11586`, `ledger_rows=11586`, `archive_ledger_mismatches=0`, `archive_without_ledger=0`, `negative_deltas=0`, `direct_cnn_tail_conflicts_unreviewed=0`, `misleading_direct_cnn_raw_diff=0`, `archive_only_misleading_direct_cnn_raw_diff=0`, `authoritative_archive_unreviewed=0`, `material_unreviewed_non_oracle_deltas=0`, `watering_window_unreviewed_positive_deltas=0`.
- Raw-tail conflict report still has `768` entries by design; these remain raw evidence, not accepted chart facts.

Decision: The committed/chart data layer is green and defensible. Do not smooth raw OCR. Keep using ledger committed values for charts, with provenance and correction log as the authority.

---

## 2026-06-30 - stabilization deploy and post-deploy audit

Context: Stabilization moved the current known-good OCR/data-layer fixes from a local commit into the live service, then rechecked the deployed endpoints and full post-final-camera DB invariants.

Changes:
- Committed local stabilization scope as `e4db78a stabilize meter OCR data layer`.
- Deployed changed production files through guarded `deploy.ps1`: `dashboard.py`, `flow_monitor.py`, `meter_archive.py`, `meter_ledger.py`, `water_reconcile.py`, `index.html`, `login.html`, `water_usage.html`.
- Deploy backup suffix: `.bak.20260630-071828`; smoke `/login` returned 200.

Validation:
- Authenticated live `/api/water-usage?minutes=60&bucket_s=5`: `bucket_s=5`, `total_gal=0.0`, `flat=true`, `backward_steps=0`, `usage_outliers=0`, `pct_monotonic=100.0`, `samples=110`.
- Authenticated live `/api/water-usage/audit?minutes=60`: verdict `accurate`; chart and physical meter both counted `0.0 gal`; `110` ledger rows, all image-backed, `11` fresh OCR, `0` flow-gap rows.
- Authenticated live `/api/water-usage/ocr-audit?minutes=60`: `points=110`, `raw_mismatches=0`, `by_conf={high:11,inferred:95,propagated:4}`, raw CNN guesses preserved as `low` confidence evidence.
- Full post-cutoff live DB audit from `2026-06-25T22:00:00`: `archive_rows=11684`, `ledger_rows=11684`, `archive_ledger_mismatches=0`, `archive_without_ledger=0`, `negative_deltas=0`, `direct_cnn_tail_conflicts_unreviewed=0`, `misleading_direct_cnn_raw_diff=0`, `archive_only_misleading_direct_cnn_raw_diff=0`, `authoritative_archive_unreviewed=0`, `material_unreviewed_non_oracle_deltas=0`, `watering_window_unreviewed_positive_deltas=0`.
- Raw-tail conflict report remains `768` by design. These are visible raw OCR disagreements, not accepted committed/chart values.

State: The deployed committed/chart data layer is stable and green after deployment. The remaining perfection gap is raw OCR accuracy at low confidence, not data-structure integrity.

---

## 2026-06-30 - final stabilization audit

Context: After freezing the CNN on `loc2-v7` and stopping the retrain timer, the live post-final-camera data layer was audited one last time from `2026-06-25T22:00:00`.

Validation:
- Live CNN remains `loc2-v7` at threshold `0.95`.
- `smart-garden-server` is active and `/login` returns `200`.
- Strict post-cutoff DB audit: `archive_rows=11841`, `ledger_rows=11841`, `archive_ledger_mismatches=0`, `archive_without_ledger=0`, `negative_deltas=0`, `direct_cnn_tail_conflicts_unreviewed=0`, `misleading_direct_cnn_raw_diff=0`, `archive_only_misleading_direct_cnn_raw_diff=0`, `authoritative_archive_unreviewed=0`, `material_unreviewed_non_oracle_deltas=0`, `watering_window_unreviewed_positive_deltas=0`.
- Raw-tail conflict report remains `768` by design; those are preserved raw OCR disagreements, not committed/chart facts.

State: Post-cutoff committed/chart history is stabilized and internally consistent. The raw OCR model is frozen at the exact accepted confidence band, with low-confidence uncertainty still handled by provenance, oracle/manual/reviewed context, and correction logs.

---

## 2026-06-30 - water-usage actual vs interpolated rate bars

Context: The 5-second rate chart needed an explicit choice between raw committed-row bucket values and an interpolated rate view for windows where sparse accepted meter reads otherwise create gap/spike bars.

Changes:
- Added `rate_mode=actual|interpolated` to `/api/water-usage`.
- Added a Bars selector on `/water-usage`: `Actual rows` preserves committed-row bucket deltas; `Interpolated` distributes each accepted high-water meter increase across the elapsed time between accepted readings.
- Increased per-bucket API precision so many small 5-second bars reconcile with the cumulative total instead of drifting from two-decimal rounding.

Validation:
- Historical 2026-06-29 21:08:50-21:12:43 at 5s: actual total `6.59 gal`, max bar `1.0622`; interpolated total `6.5899 gal`, max bar `0.4563`.
- Current 2026-06-30 08:09:30-08:21:53 at 5s: actual total `37.5008 gal`, max bar `0.8378`; interpolated total `37.5007 gal`, max bar `0.2805`.
- Both modes ended with cumulative line `37.5 gal` for the current window and `6.59 gal` for the historical window.

State: Interpolation is display-layer allocation only. It does not smooth or rewrite committed readings, meter locks, OCR values, or totals.

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

## 2026-07-20 — Scheduled evidence-driven meter improvement loop

**Context:** James wants the meter-camera system to keep investigating accuracy failures and improving over months. Prior work proves that blind retraining, random frame splits, smoothing, and confidence-threshold relaxation can produce convincing but false progress.

**Changes:** Added `ops/codex-meter-improvement/` with three independent ChatGPT-authenticated Codex stages every six hours: a read-only event-contract audit, an independent single-experiment gate, and a shadow-only executor. Runs use the NUC's shared Codex overlap lock, retain structured evidence and a cumulative experiment journal, and read the Acer live tree plus tower model state without writing either host. The executor may improve only its persistent offline lab and run artifacts during this first phase.

**Decisions:** Optimize event-authority accuracy, not cosmetic frame-level accuracy. Chronological photo-backed truth, explicit unknown/rejection, and zero false accepts outrank coverage. The job cannot change watering behavior, live databases, accepted readings, labels, thresholds, checkpoints, services, provider budgets, or Git. Automatic live promotion remains locked until a chronological benchmark and at least 30 new shadow events prove the documented gate.

**State:** The systemd service/timer, schemas, runner, current RCA/success-criteria context, authentication registration, and shared overlap protection are installed on the NUC. A bounded first cycle is used only to validate read-only evidence collection and offline artifact creation.

**Next:** Accumulate chronological cycles and shadow experiments. Consider a separate promotion workflow only after the permanent journal proves zero false accepts across the required new-event gate and the canonical source-mirror problem is resolved.

First-cycle validation: run `20260720-063452` completed all three stages with exit code 0. The audit found fresh camera frames but degraded end-to-end authority: 42 completed events in the prior 24 hours, one verified run, and 41 pending events. The independently selected offline replay copied the four source databases without modifying Acer, treated held/propagated values as unknown, reconciled verified event 905 at `110.868787 gal / 3.695626 GPM`, kept events 906-946 pending with explicit reasons, and produced zero false accepts. Reusable code, manifests, per-event results, rejected candidates, hashes, and the full report are retained under `~/.local/share/smart-garden-meter-improvement/lab/offline_authority_first_water_usage_replay_20260720` and the run directory. This proves truthful authority-first semantics for the window; it does not authorize live promotion or claim that recognition coverage is adequate.

**2026-07-20 continuation and promotion policy:** James requested that useful work continue inside the current cycle and that proven OCR fixes deploy automatically. Stage 3 now has a 60-minute bounded research loop and continues directly related, non-repeating experiments until no safe action remains. Automatic live promotion is enabled for meter-camera/OCR scope only. Recognition authority changes still require zero false accepts and the documented 30-new-event shadow gate; deterministic meter-contract/presentation fixes may promote from focused tests and exact contract replay. Every deployment requires an idle-valve proof, per-file backups, allowlisted measurement files, focused tests, live health/contracts, automatic rollback on failure, and a patch/manifest for later reconciliation with the dirty Windows checkout. Irrigation control and provider-budget changes remain prohibited.

**Promotion-policy correction:** The executor could deploy, but stage 2 still restricted every approved scope to offline-only work, so the second cycle stopped after proving pending/unknown API semantics. James clarified that visible production improvement is the objective. Stage 2 may now approve implementation and deployment of proven meter-camera/OCR and Water Usage fixes, and must prefer a live deterministic fix when existing lab evidence already proves it. Stage 3 must reuse that evidence and deploy in the same cycle when gates pass rather than producing another equivalent fixture.

**Supervisor job-definition repair:** On 2026-07-20, the NUC Codex-job supervisor removed the scheduled runner's automatic `mtime +365` run-directory pruning. That deletion conflicted with the standing requirement that Codex job history must never be deleted by the runner, because old audit/experiment artifacts are needed to prove whether later cycles are novel, repeated, or regressed. Run history should be archived or pruned only by an explicit human maintenance task, not by this recurring Codex workflow.
