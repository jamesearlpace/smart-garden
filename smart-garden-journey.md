# Smart Garden — Journey Doc

**Status:** ✅ **System operational + actively self-managing.** Sync-groups live (overlapping turf zones water together, deep+infrequent). ET₀ water-balance brain is the decision-maker. Soil sensors are observe-only supporting "eyes" (not the brain) with full server-side calibration UI. Dashboard de-cluttered.
**Last Updated:** 2026-07-22 (Codex OCR batch runner records bounded no-output calls as blocked; water-meter history and OCR details remain in **`meter-data-layer-journey.md`** and **`meter-cnn-journey.md`**)

## 2026-07-22 - Codex OCR batch no-output handling

The NUC Codex supervisor found that the `*:50` direct OCR batch timer was reaching its intended idle slot, but the 2026-07-21 23:50 run failed the systemd service after processing event 0528 and timing out without a final Codex JSON output for event 0529. Evidence: `/home/john/.local/share/smart-garden-meter-ocr-batch/runs/20260721-235007/status` had `status=failed exit_code=1`; its `error.log` ended in `FileNotFoundError` for event 0529 `codex_output.json`; the preserved call manifest recorded `status=timeout_no_final_output`, `timeout_sec=180`, and `output_path=null`. The preceding `22:50` run completed successfully in about 90 seconds, so this was not a timer collision regression.

Changed only `ops/codex-meter-batch/run-direct-meter-ocr-batch.sh`: the direct worker now attempts one event per hourly idle slot by default, gives that event a 420-second compact Codex budget inside the existing 8-minute wrapper timeout, and records known missing `codex_output.json`/`pack_manifest.json` outcomes as `status=blocked` with the event IDs instead of leaving systemd failed. This is runner bookkeeping and cadence control only: no irrigation behavior, production services, databases, model weights, OCR guard policy, prompts, backlog promotion, or live smart-garden files changed.

Pre-change backups and evidence are under `/home/john/.local/share/codex-job-repair-backups/20260722-0050-smart-garden-ocr-no-output-block/`.

## 2026-07-21 - Codex OCR batch timer idle slot

The NUC Codex supervisor found that the direct OCR batch worker was healthy when it got a slot, but its timer was scheduled at `*:08,38`, which repeatedly collided with the shared Codex lock held by the top-of-hour home-net-watch telemetry audit and the `*:19` home-net-watch UI audit. Evidence captured before the change showed the 2026-07-21 direct OCR batch statuses as `5` success, `20` skipped for `other_codex_job_active`, `2` blocked for the verified holdout false-accept gate, and `2` failed during earlier manual/catch-up work. Recent successful runs completed in about 78-91 seconds and processed two backlog events without promotion; the runner's internal batch timeout remains 8 minutes.

Changed only `ops/codex-meter-batch/smart-garden-meter-ocr-batch.timer`: the timer now runs once per hour at `*:50`, with a comment documenting the home-net-watch audit windows and the 8-minute worker budget. This should turn predictable collision attempts into a bounded idle-window batch while preserving the global no-overlap lock. No irrigation behavior, production services, databases, model weights, OCR policy, backlog state, prompt content, or live smart-garden files changed.

Pre-change backups and evidence are under `/home/john/.local/share/codex-job-repair-backups/20260721-2158-smart-garden-ocr-idle-slot/`.

## 2026-07-21 - Codex OCR batch status bookkeeping

The NUC Codex supervisor found that `smart-garden-meter-ocr-batch.timer` and `smart-garden-meter-improvement.timer` had been stopped/disabled even though their installed units still matched source and the auth watchdog was healthy. It restored only timer state with `systemctl --user enable --now smart-garden-meter-improvement.timer smart-garden-meter-ocr-batch.timer`.

The supervisor also fixed `ops/codex-meter-batch/run-direct-meter-ocr-batch.sh` so every skipped, blocked, complete, failed, or successful direct OCR batch writes a `completed=` timestamp. Previously global-lock skips such as `20260721-125041` lacked completion time, and the same-job lock branch could leave the latest run without any status. Validation under the supervisor-held global lock wrote `/home/john/.local/share/smart-garden-meter-ocr-batch/runs/20260721-125301/status` with `status=skipped`, `reason=other_codex_job_active`, and `completed=2026-07-21T12:53:01-07:00`. This was runner bookkeeping only: no irrigation behavior, production files, databases, model weights, OCR policy, or backlog decisions changed.

## 2026-07-08 - Meter data repair + OCR next step pointer

Context: A long meter/fleet session repaired the July 6-8 water history and rechecked the tower-first OCR plan. Keep the detailed chronology in the meter-specific journey docs; this master doc only points to the current state.

Changes and validation:
- `meter-data-layer-journey.md` now holds the canonical July 6-8 evidence-based repair: 499 real archived meter frames re-read, Jul 8 total corrected to `823.76 gal`, Grapes 07:35 corrected to about `67 gal`, and unlogged whole-house movement kept unattributed instead of assigned to a zone.
- `meter_ledger.run_rate_stats()` now bridges clean read segments across sparse interpolated rows with `clean_max_gap_s=120`, so repaired windows still produce real per-event medians.
- `/api/water-usage` now returns `integrity{}` and `/water-usage` shows a Data integrity card. Live spot-check for `2026-07-08T00:00:00 -> 10:20:00` returned `missing_median_count=0`, one `median_outlier` warning for Zone 8 Garden at `09:21:50`, and total `823.76 gal`.
- `meter-cnn-journey.md` now documents the recurring CNN leading-edge loop and the 2026-07-08 OCR exploration: tower `jackmint` runs `meter-cnn` `loc2-v9` at threshold `0.95`, local large VLMs are impractical on the GTX 970, and Azure Read OCR is not reliable enough on the current camera stream even with loc2-style crops.
- Highest-leverage next step changed after testing: implement the guarded low-digit phase tracker in `ocr-harness/eval_temporal_constrained_cnn.py` as a feature-flagged event-total candidate. On the post-final-location holdout (`87` events since `2026-06-25T22:00:00`), conservative tuning auto-accepted `40/87` events with accepted-event max error `0.711 gal`; the other events should be marked `needs_anchor` and resolved with one sparse oracle/human end anchor.
- Follow-through: the tracker is now deployed read-only in Water Usage shadow mode via `server-prod/meter_phase_tracker.py` and `/api/water-usage phase_tracker{}`. Persisted raw-CNN evidence is weaker than the live HTTP harness, so a separate current-CNN phase cache was added (`meter_phase_tracker.db`, refreshed by `tools/refresh_phase_tracker_cache.py`) and guarded with a stricter hybrid rule. Long-window smoke test now auto-accepts `24/88` events with accepted-event max shadow error `0.554 gal`; July 8 repair-window events correctly stay `needs_anchor`.
- Strict high-quality retrain follow-up: exported `348` newly reviewed archive labels, disabled weak outside-tail labels, and promoted tower CNN `loc2-v9` (`loc2-v8` hard full-9 `0.498` -> `loc2-v9` `0.511`; replay full-9 `0.798` -> `0.806`). After refreshing all `5067` phase-cache frames with v9, the live shadow tracker remained `24 auto_accept / 55 needs_anchor / 9 reject`, so the model improved but did not justify broader automatic trust.
- Anchor-queue follow-through: `meter_phase_tracker.db` now persists every shadow event decision in `phase_event_decision`, `/api/water-usage/phase-tracker/queue` exposes the queue, and each `needs_anchor`/`reject` row carries two recommended real-photo anchors for the existing frame modal/correction flow. Full-window validation persisted `88` rows matching the live API exactly (`24/55/9`), and all `55` `needs_anchor` rows had two frame recommendations. Canonical meter/watering data is still untouched.
- End-to-end follow-through: added resolver/writer/pipeline tooling and enabled `smart-garden-phase-tracker.timer` on the Acer. Current guarded profile uses zone priors first, rejects high frame-spread (`p95_frame_error_counts > 100`), validates auto-accepts against ledger truth at `<=0.75 gal`, and applies only validated `auto_accept` rows to `watering_event.est_gallons/est_cf` with backups + phase audit rows. Full-window current validation: `34 auto_accept / 45 needs_anchor / 9 reject`, `0` auto failures, max accepted error `0.486 gal`; `43` validated event estimates have been applied. The timer runs every 30 minutes but blocks writes when Water Usage integrity is not OK; current Jul 8 two-day window blocks because of the known Zone 8 median outlier.
- Follow-up after James noticed the 720-minute page still showed blanks/zero: found a real post-10:27 ledger flatline at `095376.901 ft3` while photos advanced to `095432.150`. Applied `tools/repair_20260708_post1027_visual_anchors.py` with backup `/home/jamesearlpace/meter-history-backups/20260708-223058-post1027-visual-anchors-preapply`; last-12-hour total is now about `395.5 gal`, missing medians dropped `6 -> 0`, and the zone table shows physical meter totals/GPMs. Broadened tracker validation back to camera cutover: `35 auto_accept / 81 needs_anchor / 17 reject`, `0` auto failures, max accepted error `0.486 gal`.

Verification note: `smart-garden-server` live API and tower HTTP services were spot-checked from the LAN. The Azure TPM bump could not be independently rechecked from the live host because `az` was not available/logged in there during this documentation pass; keep the existing `meter-cnn-journey.md` note unless a later Azure CLI check contradicts it.

> **RESUME HERE — RCA: the meter graph can't show what the OCR read (session 2026-06-27 eve):**
>
> **Trigger:** James used `/water-usage` to audit the reader and saw the graph plot `95029.6` while a frame's modal showed `095929.678`. He pushed hard on "is there a bug / what's working" → full RCA.
>
> **Verdict (honest):** the stored data + graph for that window are **correct** — the physical photo read by eye (rotated 180°) = `095029.675`, matching the week's monotonic climb (94,524 → 95,029). The `95929` was a **transient OCR misread the guardrail rejected**. BUT the real, bigger problem James surfaced: **the system never persists the raw per-frame OCR read.** Every stored series (`flow_sample.reading_cf`, `archive_frame.reading_cf`) is the post-validation **lock**; the graph then adds bucketing + gap-fill + high-water-mark. So you **cannot answer "what did the OCR read at time T,"** and the graph **cannot audit the OCR** (it is engineered to look clean regardless of reader health). I had initially over-claimed "it's all working / contained" — retracted; the OCR is genuinely buggy and the leaks reach the stored stream (82 backward steps + 11 big jumps in 14 days).
>
> **Logged:** RCA doc **`RCA-ocr-historical-read-2026-06-27.md`** (repo root). New issues **#40** (no raw-read persistence — THE core), **#41** (graph ≠ OCR frames, lossy transforms), **#42** (usage high-water-mark has no outlier guard). Related existing: #35/#36/#37/#39.
>
> **Remediation (phased, NOT started):** P0 relabel meter chart "validated lock (not raw OCR)" + flag `propagated`/`inferred` points; **P1** faithful audit line from `archive_frame` (one point/frame, no HWM/carry/bucketing-collapse, color by confidence, click→frame) — low-risk, uses existing data; **P2** persist `raw_reading` at capture **before** bounding/anchoring (THE fix for "what did OCR read at T"); P3 usage outlier guard; P4 root-cause OCR.
>
> **SHIPPED overnight 2026-06-27 (commits bfab09f, e960ec0):** P0 relabel + **P1 faithful OCR-audit chart** (new `/api/water-usage/ocr-audit` endpoint, one point per archive_frame, color = confidence, click → photo) + **P2 raw-read persistence** (`archive_frame.raw_reading`/`raw_conf`/`raw_source`; `_archive_frame` records the unconstrained CNN read per frame, free, write-once) + **P3 flag-only** usage-outlier counter in reading-health. VERIFIED live: committed `95029.675` vs raw `95929.678` now persisted + served + plotted; 30d health flags 5 implausible jumps (biggest **+1709.8 gal = the #39 freeze-dump**). Issues **#40, #41 CLOSED**; **#42 open** (flag shipped, accrual-guard deferred — catch-up jumps are often real water). Hard-refresh `/water-usage` to see the audit chart. **Remaining (need James, not unattended-safe):** P3's real accrual guard + P4 OCR root-cause.
>
> ---
>
> **RESUME HERE — loc2 CNN + meter rollover + Water Usage 3-chart, session of 2026-06-25:**
>
> **The arc:** Focus Assistant (2026-06-24) → operator refocused + **reseated the meter cam to a new fixed position "location-2"** (CUTOVER 2026-06-24 17:03) → collected a fresh **675-frame** oracle-labeled dataset (`~/cnn-locations/location-2/` on the Acer) → trained a new per-digit CNN **`loc2-v1`** for the new position.
>
> **loc2-v1 trained + deployed (overnight 2026-06-25 00:33–00:44):** held-out **full-9 0.962 / per-digit 0.996** (vs old location-1 ~0.65–0.81). Deployed to the tower CNN service (`~/meter-cnn/meter_cnn.pt`, `VERSION=loc2-v1`, port 5201) with the **location-2 serving crop `(0.10,0.45,0.82,0.73)`** (must match training) + backups (`meter_cnn_preloc2.bak`, `cnn_service.py.bak.preloc2`). Train script: tower `~/meter-cnn-loc2/train_loc2.py` (local `c:\MyCode\smart-garden\cnn\train_loc2.py`).
>
> **⚠️ Then the meter ROLLED OVER 094→095** (now **~095026224** = 95,026.224 ft³). loc2-v1 was trained only on `094920–094968`, so it **confidently misreads** the `095` frame as `094922` — a **leading-edge / out-of-distribution** failure (the synthetic generator hardcoded the `094` prefix). The live lock froze ~6h at the stale `094797660`, and the GPT-4o oracle (the only reader that can read `095`) hit **HTTP 429 rate-limit**. **Re-anchored** the lock to the true `095026224` (confirmed by eye + oracle): stop svc → write `/tmp/meter_state.json {"last_good":95026224}` → start. Display correct again; archive updating 1/min.
>
> **DURABLE FIX attempt (completed 2026-06-25 evening):** widened `train_loc2.py` `synth_rows()` to synthesize values across a **wide forward range (94,900,000–96,500,000)**, retrained **`loc2-v2`** (**best held-out full-9 0.975 / per-digit 0.997**), and deployed to live (`VERSION=loc2-v2`, with timestamped backup of served loc2-v1).
>
> **Post-deploy reality:** raw CNN argmax on current live frames is still unstable (`095922224`, min_conf ~0.40-0.59, `readable=false`). However, the production path uses anchor-constrained decode (`/cnn?anchor=<lock>&ceil=...`), and on the same frames `constrained_value` consistently resolves to **`095026224`**. Lock timestamp and `flow_sample` rows are still advancing every 15s, so continuous history/update behavior remains intact while oracle and physics guards stay on top.
>
> **Next model step:** improve raw confidence on true 095 frames (not just constrained rescue), then promote a new checkpoint.
>
> **Water Usage page got a 3rd chart:** `/water-usage` now shows **Actual meter reading (ft³)** below the gallons-bar + cumulative-line charts. The API (`/api/water-usage`) emits a new bucket-aligned `meter` series (`flow_sample.reading_cf`), and **all three charts share one x-axis** (identical bucket labels + fixed 82px y-axis width so plot areas align). Deployed + verified.
>
> **Image-view gotcha (fixed):** viewing a meter frame failed with a JPEG/PNG media-type mismatch — `System.Drawing` `RotateFlip` then `Save("...jpg")` writes **PNG bytes** (rawFormat→MemoryBmp). Fix: save rotated frames as **`.png`** (extension matches bytes). Verify header `89 50 4E 47`.
>
> ---
>
> **RESUME HERE — Focus Assistant (Meter Lens Focusing Tool), session of 2026-06-24:**
>
> **What it is:** A new page `/cam/focus` (`templates/cam_focus.html`, route in `dashboard.py`) that coaches manual lens focusing of the water-meter ESP32 camera. URL: `https://sprinklers.savagepace.com/cam/focus`. Nav tab "🎯 Focus" in `_meternav.html` + tile in `cam_hub.html`.
>
> **How it works:** Polls `/api/cam/latest`, draws the frame to a padded `<canvas>` (`displayCanvas`), computes a **client-side ROI sharpness score** (grayscale gradient-energy `dx²+dy²` mean over the ROI box). User pulls cam → twists lens → reinserts → waits for new capture time → clicks Log baseline / I twisted CW / I twisted CCW. The coach compares score deltas and tells you to keep going, reverse, or change step size.
>
> **Features shipped this session (all deployed + smoke-tested live):**
> 1. Iterative twist coach with history table (score, delta, capture time, best marker).
> 2. **Rotation:** fine rotation slider (±12°) + **base orientation toggle** (Upside down 180° / Normal 0°) — the meter cam mounts upside down. Render uses `totalRotationDeg()` = base + fine for BOTH display and scoring.
> 3. **No-crop rotation:** image drawn on a larger black-padded canvas so straightening doesn't clip corners; ROI may extend over the black border. Padding is sized to the **current** angle (not worst-case) so digits stay large.
> 4. **Locks:** "Lock ROI" + "Lock rotation" buttons freeze those controls.
> 5. **Persistence:** all settings (ROI, rotation, base orientation, locks, compact mode, step mode, learned step, twist ref, polling) persist across refresh via `localStorage` key `cam_focus_v2`.
> 6. **Turn-fraction guidance:** step selector is in TURNS not degrees — `Auto learn (start 1/4 turn)`, 1, 1/2, 1/4, 1/8, 1/16, 1/32. Auto mode adapts: improve→bigger step, worse→reverse+halve, flat→adjust.
> 7. **Compact mode** (default On): denser one-screen layout, viewport-fit canvas (`applyCanvasViewportFit()`).
> 8. **Direction reference** dropdown: "meter side (lens/front)" vs "camera back (wire side)" — just clarifies which viewpoint CW/CCW refers to; independent of image orientation.
>
> **KEY UNRESOLVED ISSUE (physical, not software) — "numbers cut off":** Fetched the raw frame (800×600). The outer digits run off the LEFT/RIGHT edges of the *camera capture itself* — the web page faithfully shows the full frame, it is NOT cropping. Root cause: focusing these lens modules = unscrewing the lens, which **magnifies** and **narrows field of view**, pushing outer digits off-frame. Focus vs. framing fight each other. **Fixes are physical:** (a) move cam farther from meter then refocus, (b) re-aim cam so the digits the OCR needs are centered, (c) accept centered digits if those are the ones the reading needs. NEXT STEP: check which digit positions the OCR pipeline actually requires (`water-meter-ocr.md` repo memory) so we know which must be in-frame.
>
> **Known limitation of the tool:** A single frame's sharpness score cannot distinguish "out of focus because too near" vs "too far" — it only knows better/worse per twist. Could add a one-time near/far calibration if desired.
>
> **Deploy pattern (this service):** local edits in `C:\MyCode\smart-garden\server-prod\` → backup on server (`cp ...bak.<tag>-<ts>`) → `scp templates/cam_focus.html jamesearlpace@192.168.0.109:~/smart-garden-server/templates/` → `ssh ... "sudo -n systemctl restart smart-garden-server"` → authed smoke test via session-cookie python. Also mirror to `C:\MyCode\smart-garden-server-live\`. Port 5125.

> **2026-06-12 (evening) — Water-meter cam is now a self-correcting, AI-verified reading pipeline + a new Flow/Leak monitor.** See the dated entry "Meter OCR overhaul + vision-LLM oracle + Flow/Leak monitor" below, and repo memory `/memories/repo/water-meter-ocr.md` for full implementation detail. Headline: per-digit 7-segment OCR + physical odometer model + GPT-4o vision oracle (auto-re-anchor, low-conf fallback, gold training labels) + new **/flow** page (per-zone GPM learned from the real meter, leak/overrun/high-flow detection via ntfy). Known limitation: cam WiFi ~30% packet loss → late/stale frames (hardware; relocate/antenna). No trainable model yet — oracle is collecting the gold dataset for a future per-digit CNN.

**Goal:** Solar-powered smart irrigation controlled remotely via Copilot through home server.

> **RESUME HERE — current state as of 2026-06-07 (read the dated entries at the bottom for details):**
> - **Rain source FIXED (2026-06-07)** — past-rain now comes from the Open-Meteo **Archive API** (observation-corrected ERA5), not the forecast endpoint. Root cause: the forecast endpoint keeps its old model guess for past hours, so it reported **0mm for the Jun 6 cats-and-dogs day that actually dropped 9.8mm/0.39"** — the garden never saw the rain, never skipped/credited. `get_rain_last_24h()` now prefers archive (fallback to forecast). Added `get_rain_for_date()` + `get_daily_rain_history()`. Nightly `reconcile_balances(days_back=3)` re-credits recent days so a forecast miss can't carry forward; `update_daily_balances` credits today's archive actual. One-time `backfill_actual_rain.py 7` corrected 31 balance rows (Jun 4–6 rain ≈0.7" that was never credited). Deployed + verified on Acer.
> - **Water Budget chart rebuilt (2026-06-07)** — now **whole-lawn (avg of turf zones 0–6) in INCHES** (`zone=all` on `/api/balance-history`). Blue Rain + green Irrigation both point up (stacked = total water in, directly comparable), red ET points down, orange = soil balance. A heavy-rain day now towers over a sprinkler cycle (Jun 6: 0.39" rain vs 0.01" irrigation) instead of the old stubby-blue/long-green mm view.
> - **Rain shows sooner (2026-06-07)** — archive cache 6h→2h (accurate rain settles within ~2h not 6h); added **mid-day (1 PM) + evening (6 PM) balance reruns** so rain banks into the visible soil-balance/moisture line hours before the 11 PM close. ET is **time-pro-rated** via `IrrigationEngine._et_fraction()` (cosine ramp over 06:00–20:00, mirrors the chart's `getEtFraction`) so mid-day reads aren't pessimistically dry; at/after 20:00 fraction=1.0 so the 11 PM authoritative close is byte-identical to before. Stored `etc_mm` stays the FULL day's demand (chart + reconciliation depend on it); only `balance_mm` reflects partial ET. **Does NOT touch any watering decision** (the 4–8 AM skip logic reads live ET/rain directly).
> - **Test suite (2026-06-07)** — `test_engine.py`, now **21 offline tests** (no network, temp DB): rain-source archive-vs-forecast, reconciliation, weather-scale, TAW/MAD, ET proration. Pre-deploy gate via `run_tests.sh`. Passing locally + on Acer.
> - **Audit (2026-06-07)** — `professional-audit-2026-06-07.md` in the smart-garden repo: framework-first review, graded B+/prosumer. Cycle-soak intentionally NOT implemented (James's call). Remaining: catch-can precip calibration (physical) + firmware valve-timeout/token (USB flash).
> - **Sync-groups SHIPPED + verified** (first live run watered all 7 turf zones together 4–5:45 AM, no errors). front_yard=[0,1], backyard_grass=[2,3,4,5,6]. Window widened 04:00→08:00.
> - **Soil balance credited immediately** after watering (not 11 PM) — predictor/banner/forecast reflect a completed watering in real time.
> - **Forecast-vs-Actual audit cleaned up** — group-aware snapshot, manual runs excluded, water/skip collision fixed (48.9%→99% on live data).
> - **Sensor strategy SETTLED** (evidence-backed): ET model = brain; cheap capacitive sensors = consumable supporting eyes (rain detection, dashboard cross-check, optional skip-gate). NOT a permanent/accurate lawn sensor. Pros use TDR/sealed-potted; passive auto-cal REJECTED as unscientific.
> - **Calibration system BUILT** — `/calibrate` page + nav tab: server-side per-sensor dry/wet (no reflash), invalid-reading guard, drift tracking, recalibration advice. Sensors still `soil_sensor: null` (observe-only).
> - **Battery voltage calibration LIVE (2026-06-05)** — `/calibrate` now has a 🔋 Battery section: read the true voltage off the Wanderer, type it in, tap Add. Server captures the ESP32's raw reading at that instant, least-squares fits a correction (pure-python, no numpy: 1pt=scale, 2–4=linear, 5+=quadratic), applied live via shared config (`battery_calibration`). Replaces the old hardcoded ×1.02884. **numpy is NOT in the server venv — never import it in deployed code.** Includes a scatter chart (X=ESP32 raw, Y=Wanderer actual) with best-fit line + live "right now" ◆ marker, per-point delete, clear-all.
> - **`/calibrate` restyled (2026-06-05)** — converted from standalone dark theme to the light theme + dark-green sidebar + mobile bottom nav matching the dashboard & forecast page. Nav mirrors index.html.
> - **Graceful sensor failure (2026-06-05)** — low-battery ntfy alert (<11.8V, 3-read hysteresis) + battery line in daily digest; sensor-fault check guarded against `soil_sensor: null`. Decisions already immune to dead soil sensors (ET brain; invalid reading → neutral 50).
> - **Dashboard charts cleaned up** — removed duplicate injected Analytics/Usage/Weather sections + dup battery from History, deleted orphaned p-analytics panel, fixed all 6 Chart.js console errors.
> - **Physical TODO (James, at the device):** seal sensor electronics (polyurethane + heat-shrink, blade exposed); reseat/replace Fruit Trees sensor (raw 4095 = open circuit); then use `/calibrate` to capture real dry/wet.
> - **Pending firmware flash (USB only, NEVER OTA):** crashLoop fix + 5-min sampling interval (committed, not flashed). Optional: strip pct math from firmware (server overrides it).
> - **Still open / future:** `precip_rate_iph` uncalibrated (catch-can test, physical); firmware valve-timeout 3600→1800s + reboot-token rotation (USB flash); cycle-soak **intentionally WON'T-DO** (James's call 2026-06-07 — see audit finding A5); journey doc needs archive-split.

**Goal:** Solar-powered smart irrigation controlled remotely via Copilot through home server.

> **Full history → [smart-garden-journey-archive.md](smart-garden-journey-archive.md)** (~234KB, all dated session logs through 2026-06-06, hardware build notes, deployment post-mortems). This doc keeps only active reference + the most-recent work. Newest archived batch is under the divider "Archived 2026-06-12 from main journey".

---

## 2026-06-27 — VS Code login fix (Google popup blocked)

**Context:** In the VS Code embedded browser, clicking **Sign in with Google** on `/login` did nothing. Browser console showed Google Identity popup errors (`Failed to open popup window`), so auth could not start from that environment.

**Root cause:** `login.html` relied on Google popup UX. Embedded browser context blocks/limits popups, so GIS could not open its auth window.

**Fix shipped:**
- `templates/login.html` now auto-detects embedded/VS Code browser context and switches GIS to **redirect mode** (`ux_mode=redirect`, `login_uri=/auth/google`) instead of popup.
- Follow-up fix: removed mixed auto-init (`g_id_onload`) + manual init pattern that could initialize GIS with an empty/undefined client ID and override redirect behavior. Login page now uses a single explicit `google.accounts.id.initialize(...)` + `renderButton(...)` path after `/auth/config` loads.
- Post-deploy adjustment: redirect-default triggered Google `redirect_uri_mismatch` (`https://sprinklers.savagepace.com/auth/google` not registered in OAuth client redirect URIs), so login was rolled back to **popup-default**. Redirect mode remains available only via `?mode=redirect` for environments where OAuth redirect URIs are explicitly configured.
- Added inline mode hint text and query-param error display (`invalid_token`, `not_authorized`, `csrf`) so failures are visible on the login page.
- `dashboard.py` `/auth/google` now supports BOTH flows:
   - existing JSON POST callback (popup mode)
   - form POST from GIS redirect mode (embedded-browser-safe)
- Added redirect-mode CSRF double-submit validation (`g_csrf_token` form + cookie) when present.

**Deploy:**
- Backed up server files on Acer:
   - `dashboard.py.bak.vscodeauth-<ts>`
   - `templates/login.html.bak.vscodeauth-<ts>`
- Deployed updated `dashboard.py` + `templates/login.html` to `~/smart-garden-server/`.
- Verified `python -m py_compile dashboard.py` and restarted `smart-garden-server` (`active`).
- Synced mirrors: `smart-garden-server-live` -> `smart-garden/server-prod`.

**Additional dashboard fix (same session):**
- Found a **false stale-warning** condition on the Home dashboard (`Data stale — last reading ~63m ago`) even while server telemetry rows were fresh every few minutes.
- Root cause: client-side freshness math used browser `Date.now()` against server timestamps (`health.ts`/`conn.ts`) without anchoring to server clock, so timezone/clock skew could inflate age by ~1 hour.
- Fix in `templates/index.html`: introduced server-referenced clock (`setServerNow`, `nowRefMs`) and switched `timeAgo`, stale-alert age, and card freshness age calculations to use that server reference.
- Result: stale banner/card freshness now reflect real pipeline age, not local clock skew.

**Cam panel follow-up fix (same session):**
- On `#/cam`, the image subtitle still showed `Captured ... (60m ago)` even while new frames were arriving every few seconds.
- Root cause: cam subtitle age used `Date.now() - new Date(o.cap)` (browser clock basis), bypassing the new server-clock anchor used elsewhere.
- Fix in `templates/index.html` (`camRefresh`): switched capture-age math to `parseTsMs(o.cap)` + `nowRefMs()`, with negative-age clamp and safe fallback when capture header is unparsable.
- Result: cam captured-age now matches real freshness instead of client/server timezone skew.

---

## 2026-06-25 — loc2 CNN deployed, meter 094→095 rollover caught + fixed, Water Usage 3rd chart

## 2026-06-25 — loc2 CNN deployed, meter 094→095 rollover caught + fixed, Water Usage 3rd chart

**Context:** Continued a chat that had overloaded mid-work on the location-2 CNN. Reconstructed state from memory + live checks, then carried it through deploy, a rollover incident, a retrain, and a UI feature.

**1. loc2-v1 trained + deployed.** The corrected 675-frame location-2 dataset (4 bad labels #87–90, `094928xxx`→`094929xxx`) was re-synced Acer→tower and trained clean: **full-9 0.962 / per-digit 0.996** (DONE 00:33). Deployed 00:44 to the tower CNN service: copied `meter_cnn_loc2.pt`→`~/meter-cnn/meter_cnn.pt`, set serving **CROP=(0.10,0.45,0.82,0.73)** (location-2 band, matches training), `VERSION=loc2-v1`, backed up the old location-1 model. `/health` ok, service active.

**2. Meter rolled over 094→095 — leading-edge blind spot.** Morning check found the live lock frozen ~6h at `094797660`. Root cause: the meter physically climbed past `094999` into **`095026224`** (95,026.224 ft³, confirmed by eye + GPT-4o oracle). loc2-v1's training data was entirely `094920–094968`, and `synth_rows()` hardcoded the `094` prefix, so the model **confidently misreads** the `095` frame as `094922` (it can't output digits it never trained on). The lock couldn't catch up because the oracle's correct `095026` read was a +228 ft³ jump the physics guard (correctly) blocks, and the oracle itself was **HTTP 429 rate-limited**.

**3. Re-anchored the lock.** Manual re-anchor to the confirmed `095026224` (stop service → write `/tmp/meter_state.json` → start). Verified: lock holds, oracle confirms it, the CNN's wrong `0949xx` reads are rejected as below-lock, archive saving 1/min. Display correct again.

**4. Durable fix (retrain, in progress).** Edited `train_loc2.py` `synth_rows()`: instead of hardcoding `[0,9,4,...]`, it now generates synthetic values across a **wide forward range (94,900,000–96,500,000)** by recombining real digit strips (all digits 0–9 exist in the strip library), teaching the model `095/096+` prefixes before the meter physically reaches them. Launched **loc2-v2 retrain** on the tower (current model preserved as `meter_cnn_loc2_v1.bak`). When done: verify it reads a live `095` frame, then redeploy.

**5. Water Usage page — 3rd chart + axis sync.** `/water-usage` now has a third chart, **Actual meter reading (ft³)** (`flow_sample.reading_cf`), below the gallons-per-bucket bar and cumulative-usage line. Backend (`api_water_usage` in `dashboard.py`): added `reading_cf` to the query and emits a new **bucket-aligned** `meter` series; also bucket-aligned the cumulative `line` so all three series share identical timestamps. Frontend (`water_usage.html`): added the chart + a shared `xAxis()`/`yAxis()` config with a **fixed 82px y-axis width** so all three plot areas line up exactly. Deployed + verified (`reading_cf` populated 74,432 rows, latest 95,026.224).

**Files touched:** tower `~/meter-cnn-loc2/train_loc2.py`, `~/meter-cnn/cnn_service.py`; Acer `~/smart-garden-server/dashboard.py` + `templates/water_usage.html`; local `c:\MyCode\smart-garden\cnn\train_loc2.py`, `c:\MyCode\smart-garden-server-live\` + `server-prod\` mirrors.

**Current live state:** lock correct at 95,026.224; archive + usage continuous; oracle carrying live reads (429s expected until loc2-v2 ships). Retrain running.

---

## 2026-06-24 — Focus Assistant: preview-size fix + "numbers cut off" diagnosis

**Preview-size fix (`templates/cam_focus.html`):** Padded rotation canvas was sized for worst-case ±12° rotation at all times, shrinking the live digits. Changed `computePaddedSize()` to size the border to the **current** `totalRotationDeg()` (with `Math.max(src, bbox)` floor), bumped compact preview height (`window.innerHeight * 0.38`, cap 360), and call `ensureCanvasSize()` on rotation/orientation change so the canvas recomputes. Deployed (`cam_focus.html.bak.previewsize-20260624-151008`), restarted, smoke-tested OK.

**"Numbers cut off" — ROOT CAUSE (physical, not software):** Pulled the raw frame via authed `GET /api/cam/latest` → **800×600**. The page renders the FULL frame; nothing is cropped in software. In the raw capture the outer digits already run off the LEFT/RIGHT edges. Cause: focusing these lens modules = unscrewing the lens → magnifies → narrows field of view → outer digits leave frame. Focus and framing trade off against each other. **Resolution is physical:** move cam farther + refocus, or re-aim so the needed digits are centered. **NEXT:** confirm which digit positions the OCR pipeline needs (see `/memories/repo/water-meter-ocr.md`) so we know the must-be-in-frame digits.

---

## 2026-06-24 — Focus Assistant orientation fix (upside-down image support)

**Context:** Operator reported the live frame appeared upside down during focusing.

**What changed in `templates/cam_focus.html`:**
- Added a base-orientation toggle button in the rotation controls:
   - `Base: Upside down (180 deg)`
   - toggles between 180 deg and 0 deg base orientation
- Fine rotation slider remains +/-12 deg and now applies around base orientation.
- Render path now rotates by `totalRotationDeg()` (base + fine) for both display and scoring.
- Base orientation now persists across refresh in local storage (`cam_focus_v2`).
- Rotation lock now disables the base-orientation button as well.
- Direction help text now clarifies CW/CCW reference is independent of image orientation.

**Deploy + verify:**
- Backed up production template: `cam_focus.html.bak.orientation-20260624-132710`.
- Deployed updated template and restarted `smart-garden-server` (`active`).
- Smoke check (`GET /cam/focus`) confirmed:
   - `orientationFlipBtn` present
   - base orientation state persisted (`baseOrientationDeg` save/load)
   - rendering uses combined `totalRotationDeg()`

**Operator note:**
- If frame is upside down, keep base at `Upside down (180 deg)`, then use fine rotation slider for straightening.

---

## 2026-06-24 — Focus Assistant usability pass: persistent locks + exact turn fractions

**Context:** Operator feedback identified three workflow blockers:
- "Direction reference" wording was ambiguous.
- ROI/rotation lock state did not persist after page refresh.
- Degree-based guidance was impractical; desired guidance is in turn fractions (full, 1/2, 1/4, 1/8, 1/16...) with learning.

**What changed in `templates/cam_focus.html`:**
- Direction clarity:
   - renamed options to explicit viewpoints:
      - `As viewed from meter side (lens/front)`
      - `As viewed from camera back (wire side)`
   - added inline helper text that updates with selected viewpoint.
- Lock persistence across refresh:
   - added localStorage persistence (`cam_focus_v2`) for:
      - ROI position/size
      - rotation degrees
      - ROI lock state
      - rotation lock state
      - compact mode
      - step mode and learned step size
      - twist reference and polling settings
   - state now rehydrates on page load.
- Turn-fraction workflow + adaptive learning:
   - replaced degree-centric step selector with turn fractions:
      - `1`, `1/2`, `1/4`, `1/8`, `1/16`, `1/32`
      - plus `Auto learn (start 1/4 turn)`
   - coaching text now recommends explicit turn fractions.
   - in auto mode, turn size adapts based on score deltas:
      - improve -> modestly increase step
      - worse -> reverse direction and reduce step
      - flat -> adjust step directionally and continue

**Deploy + verify:**
- Backed up production template: `cam_focus.html.bak.turns-20260624-132104`.
- Deployed updated template, restarted `smart-garden-server` (`active`).
- Smoke check (`GET /cam/focus`) confirmed presence of:
   - auto/fraction turn options
   - direction helper + step learning text
   - `saveState()` / `loadState()` and `cam_focus_v2` storage key

---

## 2026-06-24 — Focus Assistant compact mode (one-screen fit)

**Context:** Even with ROI/rotation lock controls in place, the page still felt too spread out to monitor frame + controls + guidance together.

**What changed:**
- Added a `Compact mode` toggle (default On).
- Compressed control layout into denser grids:
   - ROI sliders in one row (`controls-grid`)
   - rotation + polling controls in compact two-column panels (`panel-grid`)
   - utility actions merged into one 4-button row (`btn-row-4`)
- Added viewport-fit logic for the rotated padded canvas:
   - `applyCanvasViewportFit()` scales frame area to available height/width
   - keeps ROI overlay aligned by sizing `viewerWrap` with the canvas
   - recalculates on window resize and when compact mode toggles
- Reduced compact-mode vertical footprint:
   - tighter spacing/padding
   - shorter history viewport
   - step list hidden in compact mode to keep operational controls visible

**Deploy + verify:**
- Backed up production template: `cam_focus.html.bak.compact-20260624-131626`.
- Deployed updated `cam_focus.html`, restarted `smart-garden-server` (`active`).
- Smoke check (`GET /cam/focus`) confirmed presence of:
   - `compactToggleBtn`
   - `controls-grid` / `panel-grid` / `btn-row-4`
   - compact CSS block and `applyCanvasViewportFit()` JS function

**Operator note:**
- Leave `Compact mode: On` for tuning sessions where everything must stay visible on one screen.

---

## 2026-06-24 — Focus Assistant: straightening control added (few-degree image rotation)

**Context:** During manual focusing, the meter frame was slightly tilted, making ROI alignment and visual comparison harder.

**What changed (v2 enhancement same day):**
- Added rotation UI in `templates/cam_focus.html`:
   - `Image rotation (deg)` slider (`-12` to `+12`, step `0.1`)
   - live rotation readout
   - reset button
- Added lock controls:
   - `Lock ROI` / `Unlock ROI` (freezes ROI sliders + preset)
   - `Lock rotation` / `Unlock rotation` (freezes rotation slider + reset)
- Reworked rendering so rotated view keeps the full source image:
   - switched from rotating `<img>` to drawing into a larger black-padded canvas (`displayCanvas`)
   - no text loss from corner clipping during small-angle straighten operations
   - ROI can now be positioned over the black border area as requested
- Rotation is applied to both display and scoring, so guidance remains aligned with what the operator sees.

**Deploy + verify:**
- Backed up production template: `cam_focus.html.bak.rotate-20260624-130541`.
- Backed up enhanced template before lock/padded-canvas deploy: `cam_focus.html.bak.lockpad-20260624-131116`.
- Deployed updated `cam_focus.html` to `~/smart-garden-server/templates/`.
- Restarted `smart-garden-server`; status remained `active`.
- Smoke check (`GET /cam/focus`) confirmed:
   - `id="displayCanvas"` present
   - `id="roiLockBtn"` present
   - `id="rotationLockBtn"` present
   - larger-black-border rotation note present

**Operator guidance:**
- Use tiny rotation first (for example `+1.0` to `+3.0` deg) until number wheels look vertical.
- Then position ROI on number wheels and continue baseline/CW/CCW loop.

---

## 2026-06-24 — Focus Assistant page shipped for iterative manual lens tuning

**Context:** Manual ESP32 lens focus was taking hours because visual judgment was inconsistent and the meter letters (slightly different depth) could mislead decisions while the real goal is digit sharpness.

**What was built:**
- New page `GET /cam/focus` (`templates/cam_focus.html`) with a guided iterative focusing loop.
- Live ROI-only sharpness scoring on `/api/cam/latest` frames:
   - ROI sliders and a digits preset keep scoring anchored to the number wheels, not nearby letters.
   - Score uses grayscale gradient-energy over ROI (`dx^2 + dy^2` mean), updated each fresh capture.
- Step-by-step twist coach:
   - actions: baseline, twisted CW, twisted CCW, undo, reset.
   - guidance logic recommends continue/reverse/reduce/increase based on score delta with noise tolerance.
   - logs each step with capture time + delta and highlights best score.
   - waits for **new capture timestamp** to avoid stale-frame false conclusions.
- Navigation wired so the tool is easy to reach:
   - `_meternav.html` adds a `🎯 Focus` tab.
   - `cam_hub.html` adds a Focus Assistant tile.

**Backend wiring:**
- Added route in `dashboard.py`:
   - `@app.route("/cam/focus")` → `render_template("cam_focus.html")`.

**Deployment + verification (Acer `192.168.0.109`):**
- Backed up production files with timestamped `*.bak.focus-20260624-125827`.
- Deployed: `dashboard.py`, `templates/cam_focus.html`, `templates/cam_hub.html`, `templates/_meternav.html`.
- Restarted `smart-garden-server` and confirmed:
   - service `active`, new `ActiveEnterTimestamp=2026-06-24 12:58:37 PDT`.
   - authenticated smoke tests: `/cam/focus` 200, `/cam` 200 (contains focus link), `/api/cam/latest` 200.

**Outcome:** James now has a purpose-built page that can tell him, after each twist iteration, whether to keep direction, reverse, or change step size while prioritizing focus on meter digits only.

---

## 2026-06-23 — Archive evidence clarity: inferred rows hidden by default

**Context:** The archive view could show two cards that looked like duplicate independent evidence (for example one `cnn` and one `prop`/propagated row at nearly the same displayed time), which made confidence look higher than it really was.

**What changed:**
- Added API-level filtering in `/api/cam/archive` so propagated rows are excluded by default (`include_propagated=0`) and can be explicitly included when requested.
- Extended `meter_archive.list_range()` / `count_range()` with `include_propagated` support so filtering is done in SQL, not just in the browser.
- Updated `cam_archive.html` UX:
   - new toggle: **Show inferred (prop)**
   - propagated badge text changed from `prop` to `inferred`
   - list status now reports how many inferred rows are hidden
   - timestamp display now includes seconds (not minute-only)

**Why this matters:** primary measured evidence is now visually separated from inferred backfill rows, reducing false confidence during review while preserving access to inferred history when needed.

**Files modified:**
- `server-prod/dashboard.py`
- `server-prod/meter_archive.py`
- `server-prod/templates/cam_archive.html`

---

## 2026-06-23 — Truth-guard latch deployed (manual review mode + bank pause)

**Context:** Meter values could still be smooth/plausible while wrong, and we needed a hard runtime latch that pauses training-label banking until a human confirms truth.

**What changed in code (`server-prod/dashboard.py`):**
- Added persistent truth-guard state (`~/meter-truth-guard.json`) with flag/clear history, counters, and status snapshot.
- Added banking gate: when truth-guard is active, both local and oracle banking paths skip writing labels.
- Wired physics blockers to auto-flag truth-guard on impossible forward/down moves (so suspicious jumps immediately pause banking).
- Extended `/api/cam/status` with a `truth_guard` block for live observability.
- Added manual endpoints:
   - `GET /api/cam/truth-guard`
   - `POST /api/cam/truth-guard/flag`
   - `POST /api/cam/truth-guard/clear`
- Manual correction/reanchor flows now auto-clear truth-guard on successful re-anchor.

**Deployment + verification (Acer `192.168.0.109`):**
- Backed up live file: `~/smart-garden-server/dashboard.py.bak.truthguard-20260623-141940`.
- Deployed updated `dashboard.py`, restarted `smart-garden-server`, confirmed active start timestamp `2026-06-23 14:19:50 PDT`.
- Authenticated smoke tests passed:
   - `GET /api/cam/truth-guard` returned `ok=true` and full state object.
   - `GET /api/cam/status` includes `truth_guard` payload.
   - `POST /api/cam/truth-guard/flag` and `/clear` both operational.
- Runtime log confirmed a real protection event right after deploy:
   - physics guard blocked `094790541` as impossible (`+50457 > phys_max 11770`) and auto-flagged truth-guard.
   - final state left clean with `truth_guard.active=false`.

**Current state:** Truth-before-training guardrail is live in production and observable; suspicious meter jumps now pause label banking until manual review/clear.

---

## 2026-06-23 — Auto-heal hardening patch (no-manual objective guardrails)

**Context:** Follow-up audit found two subtle safety gaps in the first auto-heal release:
- authority confirmations could carry across unrelated disagreement episodes,
- successful auto-heal always cleared truth-guard, even if the latch came from a non-oracle/manual investigation reason.

**What changed (`server-prod/dashboard.py`):**
- **Episode-scoped confirmations:** added `auto_heal.confirm_signature` and reset confirm streak whenever the disagreement episode signature changes (direction + disagreement band + lock band). This prevents confirmation carry-over between unrelated incidents.
- **Reason-scoped guard clear:** auto-heal now clears truth-guard **only** when latch source is oracle-related (`oracle-physics` / `auto-heal`). If truth-guard source is manual/other, auto-heal preserves it and logs why.
- Added observability field in `/api/cam/status`:
   - `auto_heal.confirm_signature` for live debugging and audit traceability.

**Deployment + verification:**
- Backed up live file: `~/smart-garden-server/dashboard.py.bak.healpatch2-20260623-144805`.
- Restarted `smart-garden-server` successfully (`active`, new `ActiveEnterTimestamp`).
- Verified `/api/cam/status` includes the new field and runtime state:
   - `auto_heal.confirm_signature: null` (clean start),
   - truth-guard state available and readable post-patch.

**Outcome:** The auto-heal system remains fully automated, but now with stronger episode isolation and no accidental clearing of unrelated manual safety latches.

---

## 2026-06-23 — Archive-to-lock self-heal (drifted CNN/history auto-corrects)

**Problem:** The dashboard card showed `094841999` (`cnn`) while the physical glass + the oracle-trusted lock read `094791096` — about +51 ft³ too high. The lock auto-heal could NOT catch this: the wrong number lives on the **archive chain**, a separate surface that anchors each frame to its OWN previous value with a forward-only bound. So a one-time over-read became a permanent high floor it could never come back down from, even though the lock was correct. The lock never disagrees with itself → the lock heal never armed.

**Root cause (verified in code):**
- `_archive_frame` anchored the exact-frame CNN read to `prev_i` (previous archive value), not the trusted lock.
- A `cnn`-high archive row was treated as a `trusted_anchor` and propagated, reinforcing the drift.
- The existing repair helpers (`_auto_interpolate_to_anchor`, `propagate_delta`) **stop at trusted/reviewed rows**, so they halted right at the wrong number.

**Fix (all automatic, nothing hardcoded — `dashboard.py` + `meter_archive.py`):**
- **Anchor to truth:** when the lock is oracle-trusted (`_lock_trusted_value()` — oracle-confirmed within 15 min and the lock hasn't drifted off that confirmation), new archive frames anchor to the **lock**, not to a possibly-drifted previous value. A high garble frame is then rejected by the bound and the row defaults to the correct lock value — drift stops at the source.
- **Monotonic floor capped at truth:** the "lock lags" recovery floor (`prev_floor`) is capped at the trusted lock, so a drifted-high previous row can't re-pin a row upward.
- **Reconcile existing drift:** `meter_archive.reconcile_above()` rewrites every archive row reading ABOVE the trusted lock (the meter is monotonic, so the lock is the all-time high → anything higher is provably impossible) down to the lock. It deliberately **overrides wrongly-trusted `cnn`/`oracle`/`lock`/`propagated` rows** (the sharpening the old helpers couldn't) but NEVER touches `manual` human corrections.
- **Strong trust gate:** heal only acts when the lock is oracle-trusted recently AND within plausible real-flow lead of the confirmed value — so it can never force the archive onto a bad lock (fail-safe).
- **Observability:** new `archive_heal` block in `/api/cam/status` (`reconciles`, `rows`, `last_from/to`, `lock_trusted`).

**Verified live (2026-06-23 15:11):**
- Pre-heal archive max: `094844999` (drifted ~+54 ft³).
- On restart, once the oracle re-confirmed the lock, the heal fired automatically:
  `ARCHIVE-HEAL: reconciled 559 impossible-high archive row(s) (max 094844999 -> trusted lock 094791096) — NO manual step`.
- Post-heal archive max: `094791096` (matches the trusted lock). Status: `archive_heal.reconciles=1, rows=559, lock_trusted=true`.
- New frames written after the heal stay correct (`094791096`, source `lock`) — no re-drift.

**Net:** both meter surfaces now self-heal automatically — the **lock** (sustained multi-model consensus) and the **archive/display** (reconcile-to-trusted-lock). Fully programmatic, no manual re-anchor.

---

## 2026-06-23 — Exact archive convergence mode shipped (authoritative rows are now immutable)

**Context:** The previous archive heal stopped catastrophic drift, but history could still remain "mostly right" instead of converging fully to per-image truth. Goal was to finish Option B: exact convergence with no manual steps.

**What changed:**
- Added convergence-mode candidate APIs in `meter_archive.py`:
   - `reread_candidates(..., mode='converge')`
   - `count_reread_candidates(..., mode='converge')`
   - `retire_missing(ts)` to mark evicted-image rows as non-actionable (`source='evicted'`) so backlog can reach zero.
- Added runtime mode control in `dashboard.py`:
   - `METER_ARCHIVE_REREAD_MODE` (defaults to `converge`, accepts `suspect` for legacy behavior).
- Updated archive reread worker:
   - uses convergence candidate set,
   - retires missing-image rows automatically,
   - refreshes pending count at worker exit,
   - reports mode and retirement counters.
- Hardened immutability of truth anchors in strict backfill/reprocess:
   - reviewed rows, manual rows, and oracle rows are never rewritten,
   - one-off `/api/cam/archive/reread` oracle reads now persist as reviewed anchors.
- Extended `/api/cam/status` `archive_heal` payload with:
   - `mode`, `retired_missing`, `converged`.

**Deployment + verification:**
- Deployed `dashboard.py` and `meter_archive.py` to Acer, restarted `smart-garden-server`, verified `active`.
- Authenticated status confirms new fields are live:
   - `archive_heal.mode = "converge"`
   - `archive_heal.converged = false` (worker actively draining)
   - `archive_heal.running = true`
   - `archive_heal.pending` reported non-zero backlog (expected at start of convergence run).
- Recent 6h DB snapshot right after deploy showed large remaining uncertain backlog dominated by propagated rows (expected on first convergence pass): `pending_like_converge=647`, sources mostly `propagated`.

**Current state:** exact-convergence machinery is now in production. The system no longer depends on a near-truth plateau; it is configured to keep converting uncertain history into authoritative per-frame truth while retiring non-recoverable evicted-image rows.

---

## 2026-06-23 — Convergence Monitor + self-audit (the monitor can be checked)

**Context:** James's concern with any progress dashboard: "I'll look at it and think this isn't right." A monitor that self-grades is worthless if it can quietly mark wrong rows as perfect. So the design goal was an honest monitor whose every claim is checkable against the one thing that can't lie — the archived image.

**What was built (all behind existing auth):**
- **New page `/cam/convergence`** (`templates/convergence.html`, self-contained, light theme, Chart.js CDN):
  - KPI strip: Perfect %, Perfectable left, Rate/hr, ETA, **Blind agreement %**, **Your agreement %**, Unrecoverable, Heal running.
  - One trend line: **Perfectable Remaining** (down=good) + Perfect % on a second axis. The single most honest progress metric.
  - **Run blind audit** button → re-reads rows the system claims correct and shows match/MISMATCH per row.
  - **Verify with your own eyes** lane → image next to stored number, ✓ Correct / ✗ Wrong (type the right 9 digits → row corrected immediately as manual+reviewed).
- **Convergence trend logging** (`meter_archive.convergence_snapshot` table): the strict-backfill daemon records a snapshot each cycle (~2 min) → `perfectable_remaining`, `authoritative`, `perfect_pct`, etc.
- **Audit-the-monitor log** (`meter_archive.audit_result` table): every blind AI re-read and human spot-check is stored, so agreement % is computed from real independent checks, not self-assessment.
- **New helpers** in `meter_archive.py`: `convergence_stats`, `record_convergence_snapshot`, `convergence_history`, `random_perfect_rows`, `record_audit_result`, `audit_summary`.
- **New endpoints** in `dashboard.py`:
  - `GET /api/cam/convergence` (stats + trend + rate/ETA + audit summary + heal state)
  - `POST /api/cam/convergence/audit` (blind re-read of N claimed-correct rows; exact-match because it re-reads the SAME image)
  - `GET /api/cam/convergence/verify-batch` (N rows with image URL + stored value)
  - `POST /api/cam/convergence/verify` (record human verdict; correct on disagreement)

**Why exact-match is a strong audit:** the blind re-read uses the SAME archived JPEG with no hint/anchor. A correct system must reproduce the identical 9 digits, so any mismatch is a real contradiction — not model noise about a moving meter.

**Verified live (2026-06-23 16:41 deploy):**
- Service `active`; page renders; no TemplateNotFound/Traceback.
- `GET /api/cam/convergence`: `perfect_pct=11.7`, `perfectable_remaining=770`, `total=872`, history logging started.
- `POST /api/cam/convergence/audit {n:5}`: `checked=2 agreed=2 agreement_pct=100.0` (both claimed-correct rows reproduced exactly: `94796505`, `94793774`). Rows whose images were evicted are skipped.
- `verify-batch` returns rows with `img_available` flags.
- Note: when the heal worker and a blind audit run together they can hit oracle **HTTP 429** rate limits; both paths skip failed reads gracefully (audit just checks fewer rows), no crash.

**Net:** progress is now monitored by one honest line (perfectable-remaining → 0) plus two independent agreement checks (blind AI re-read, human eyes) that exist specifically to catch the monitor lying. URL: `https://sprinklers.savagepace.com/cam/convergence`.

---

## 2026-06-23 — Navigation: every meter/cam page is now reachable

**Context:** The cam/meter pages were standalone with no shared navigation — you had to know the URL. James wanted to be able to navigate to everything.

**What was built:**
- **`templates/_meternav.html`** — a shared, self-contained sticky top nav bar (scoped CSS + tiny JS, horizontal-scroll on mobile) linking every meter tool: Dashboard, All Tools, Convergence, Archive, Quality, Review, Labels, Regression, Test Audit, CNN Report. Highlights the current page.
- **`templates/cam_hub.html` + route `/cam`** — a directory page grouping all tools (Monitoring & truth / Training & ML / Back to the garden) with descriptions.
- **Injected `{% include '_meternav.html' %}`** right after `<body>` in all cam pages: cam_archive, cam_review, cam_quality, cam_regression, cam_testaudit, cam_labels, cnn_report, convergence, cam_reading.
- **Desktop sidebar** (`index.html`): added a "📷 Meter Tools" link (→ `/cam`) next to Meter Archive.
- **Shared mobile nav** (`_mobilenav.html` More sheet): added "📷 Meter Tools" → `/cam`, so all main pages (index/forecast/moisture/costs/sensor-history) can reach the hub on phones.

**Note:** `/cam-device` renders `cam_device.html` which does NOT exist on disk (pre-existing dead route) — deliberately left OUT of the nav so we don't link to a 500.

**Verified live (2026-06-23 16:47 deploy):** service active; all 9 meter pages render the nav bar (`mtn-bar` present); `/cam` hub loads; no TemplateNotFound/jinja2/Traceback in logs (only transient oracle 429s from the heal worker).

---

## 2026-06-23 — Permanent archive anti-drift guardrails (prevent recurrence)

**Context:** A wrong low value was accepted as an `oracle` reviewed anchor in archive history (`2026-06-23T20:41:49`), then propagated through surrounding rows. The issue was not a single bad card; it was missing invariants on trusted archive updates.

**Root cause:** `meter_archive.update_reading()` accepted reviewed `oracle/cnn` values without validating against adjacent archive history (monotonic + physical bounds), so one bad machine reread could become a trusted anchor and poison interpolation/propagation.

**Systemic fix (deployed to Acer):**
- Added machine-anchor guard in `server-prod/meter_archive.py`:
   - new env knob: `METER_ARCHIVE_AUTO_REVIEW_BACKSTEP_TOL` (default `2500` counts)
   - reviewed `oracle/cnn` updates are now rejected if they imply impossible backstep/forward jump versus neighboring rows using time-aware physical caps (`_max_forward_counts`) plus small tolerance.
   - blocked updates are logged (`archive update rejected ... reason=...`) for observability.
- Added optional `force` parameter to `meter_archive.update_reading(...)`:
   - internal repair pipelines that already enforce independent bounds can bypass neighbor guard safely.
- Updated `server-prod/dashboard.py` callsites:
   - strict reprocess writes use `force=True` with existing hard-ceiling/physics checks.
   - archive heal worker + convergence drainer use `force=True` (already bounded by monotonic floor + trusted-lock ceiling).
   - ad-hoc `/api/cam/archive/reread` now applies explicit floor/ceiling check (`anchor_value` .. `trusted_lock + ARCHIVE_HEAL_TOL_COUNTS`) before calling `update_reading`.

**Verification:**
- Local compile check passed (`python -m py_compile meter_archive.py dashboard.py`).
- Service restarted cleanly and is `active`.
- Direct regression test on production:
   - attempted impossible low oracle-reviewed update at `2026-06-23T20:41:49`
   - update rejected with log reason `below-previous ...`
   - row remained unchanged.

**Outcome:** this class of failure is now prevented at the write boundary. A single bad machine reread can no longer silently become a trusted anchor and cascade through archive history.

---

## 2026-06-23 — CNN retrain root-cause fix (live-range coverage + anti-false-confidence gate)

**Context:** CNN looked collapsed in production (v5 ~0% on live oracle eval), while retrain metrics still looked acceptable. Root-cause diagnostics showed a dataset mismatch: trusted retrain labels had almost no digit-4 `6/7` coverage, which is exactly the current meter range (`0946xxxx` / `0947xxxx`).

**Root-cause evidence (verified):**
- Live direct inference on latest meter-training frames: `full-9=0.0%`, avg `min_conf≈0.36`, no high-confidence rows.
- Failure localization on `0946/0947` set: digit-4 confusion dominated (`6→0`, `7→0`), causing 0% full-9.
- Retrain trusted set before fix had severe scarcity at digit-4: effectively no `6` coverage and sparse `7`, so held-out benchmark underrepresented live failure modes.

**Code changes (`cnn/retrain.py`):**
- Added **weak outside-tail inclusion** when propagation is active:
   - keeps anchor/confirmed/repaired as trusted core,
   - additionally includes a bounded tail of `outside` labels **above trusted max**,
   - assigns low trust weight (`OUTSIDE_TAIL_TRUST=0.35`) to avoid overpowering gold labels.
- Added **held-out coverage seeding** in `build_rows()` so the test set contains minimum critical live-range digits (`6/7` at digit index 3) when clean data has enough examples.
- Added **coverage gate** (`coverage_guard`) in `main()`:
   - aborts retrain before promotion if held-out test misses required live-range coverage,
   - writes coverage diagnostics into `retrain_status.json` / history for auditability.

**Deploy + smoke test:**
- Deployed updated `retrain.py` to tower (`jack@192.168.0.120`, `~/meter-cnn/retrain.py`).
- Compile check passed on tower.
- Dry-run retrain (`--force --dry-run --epochs 1`) confirmed new behavior:
   - propagation now included `1082` trusted + `185` weak outside-tail labels,
   - clean digit-4 mix now includes strong live-range counts (`6:122`, `7:67`),
   - held-out test coverage passed gate (`6:16`, `7:3`; required met),
   - no promotion (challenger stayed worse), so gate + strict keep still protect production.

**Outcome:** retrain now follows the live meter range and cannot report a misleading win from an under-covered benchmark.

---

## 2026-06-23 — Meter archive misread incident: deep-dive investigation + pre-mortem

**Context:** James reported an archive card pair that looked self-contradictory (`094790239` then `094798240`) and asked for a deep-dive on how the AI path still allowed an incorrect result despite the existing safety model.

**Incident evidence captured (live server):**
- Archive DB (`meter_archive.db`) rows in the window `17:30-17:40` included:
   - `2026-06-23T17:33:57 -> 094790239` (`source=oracle`, `confidence=high`, `reviewed=1`, `updated_ts=17:46:47`)
   - `2026-06-23T17:34:29 -> 094798240` (`source=oracle`, `confidence=high`, `reviewed=1`, `updated_ts=17:44:40`)
- Live validated stream (`flow_sample` in `smart-garden.db`) stayed flat at `094797601` with `0.0 gpm` across the same window.
- Consecutive archive deltas in the same window included physically impossible transitions (example: `+8001` counts in `32s` vs cap about `2339` counts).
- No request-log evidence of manual `/api/cam/archive/reread` calls in the window.
- Service log showed continuous background `ARCHIVE-HEAL[converge]` reread cycles in that interval.

**Root cause (code-path level):**
- The live lock path (`MeterReader._validate`) correctly enforces monotonic + time-aware physical bounds and did **not** move to the wrong values.
- A separate archive correction path (`_archive_reread_worker`) can write authority-model reads into archive rows as `source=oracle, reviewed=1` when value is inside floor/ceiling bounds relative to trusted lock.
- That archive path does not require the same neighbor-step continuity checks that protect the live lock stream.
- During heavy glare blur, authority-model high-digit errors passed floor/ceiling checks and were promoted to reviewed oracle anchors in archive history.

**Why this was surprising at the UI level:**
- The archive page language says usage is built from monotonic, physically-capped deltas (true for aggregation).
- The same page presents `AI` + `✓` badges on per-image cards.
- Combined, this can look like "card value is guaranteed true" when the guarantee actually applies to downstream delta filtering, not to every card label.

**Measured impact in this incident:**
- Live monitor truth remained correct (`094797601`, no flow).
- Archive cards in that window were wrong.
- Archive usage model still admitted small local forward deltas and reported about `2.768 gal` in that 10-minute window while live flow was `0.0 gal`.

**Runtime conditions that widened risk during this event:**
- `METER_ARCHIVE_REREAD_MODE=converge`
- `METER_ARCHIVE_HEAL_TOL_COUNTS=1500`
- Frequent archive-heal cycles were active while oracle provider was also returning many `429` responses.

**Pre-mortem on proposed fix (self-audit before implementation):**
1. Switching to `suspect` mode alone can leave bad below-lock rows untouched.
2. Tightening one tolerance constant alone can over-block real movement or still miss structured glare errors.
3. If a wrong oracle row remains marked reviewed, downstream strict/backfill logic treats it as immutable anchor and can preserve bad chains.
4. Repair jobs can race with active background writers unless mutators are paused during correction.
5. If trust badges remain unchanged, operators may still over-trust single-pass AI rows.

**Recommended remediation strategy (staged, safer than a one-shot tweak):**
1. **Containment first:** pause archive mutators during repair windows.
2. **Trust-promotion hardening:** single oracle reread should not auto-become reviewed authority; require corroboration before promotion.
3. **Continuity gate for archive writes:** enforce neighbor-step physics monotonic checks before accepting archive oracle writes.
4. **Deterministic repair pass:** run dry-run report first (row count + before/after deltas), then apply.
5. **Post-fix invariants:** verify no impossible deltas, no sustained lock-divergent authoritative plateaus, and no authoritative rows without corroboration metadata.

**Decision recorded:** no hot patch was applied during this investigation pass. This entry documents the evidence chain and the hardened implementation plan to avoid swapping one failure mode for another.

**Follow-up note (same day):** CNN retrain hardening was shipped later on 2026-06-23 (outside-tail inclusion + held-out coverage gate) and is documented in the separate dated entry above. The no-hot-patch decision here refers only to this archive-misread investigation pass.

---

## Plumbing Permit — Irrigation Water Tap

**Status:** Application submitted 2026-05-21 via Duvall permit portal. **Permit #26-175.** Currently in Administrative Review.

### What's being done
Tapping into the potable water supply right after the water meter (NW corner of property) to create a dedicated irrigation supply line. Bypasses house plumbing for better flow (expect ~7.5-8.5 GPM vs. current 6.0 GPM through hose bibb).

### Permit documents (all in `C:\MyCode\smart-garden\`)
| File | Purpose |
|------|---------|
| `permit-plumbing-schematic.svg` | Plumbing connection diagram: meter → tee → ball valve → DCVA → 1" poly → 2 valve boxes (4+5) |
| `permit-site-plan.svg` | Property layout showing meter, tee, DCVA, main line route, valve box locations |
| `permit-acting-as-own-contractor.pdf` | City form — print, sign, scan, upload |

### Backflow preventer decision
- **Proposed:** DCVA (Double Check Valve Assembly) — Watts 007M1-QT, 1" bronze
- **Why DCVA:** Can install underground in valve box (no freeze risk, no ugly riser), handles backpressure, single device for whole system
- **Alternative:** PVB (Pressure Vacuum Breaker) — cheaper (~$150 vs ~$200-500) but must be above ground 12" above highest head
- **Hazard classification:** Low hazard (no chemical injection) per WAC 246-290-490
- **Annual testing required:** By Sept 1 each year, certified BAT tester. City mails reminder in June.
- **Key contact:** Duvall Public Works backflow line: 425-788-3434 / CoDbackflow@duvallwa.gov
- **Permit tech:** 425-788-2779 / permit.technician@duvallwa.gov

### Connection layout
```
Water Meter (¾", NW corner) → existing pipe → NEW TEE
  ├→ Right: existing water to house (no change)
  └→ Down: Ball Valve → DCVA → 1" Poly (100 PSI) → VB1 (4 valves) → VB2 (5 valves)
```

### Next steps after permit approval
1. Call 425-788-3434 to confirm DCVA is accepted (or if they require PVB)
2. Buy the backflow device (Watts 007M1-QT 1" at Lowe's — bookmarked)
3. Do the plumbing work (shut off water, cut in tee, install ball valve + DCVA, run 1" poly)
4. Schedule inspection: permit.technician@duvallwa.gov or 425-788-1160 (24h advance, leave trench open)
5. After approval: hire certified BAT for initial field test (find at https://wcs.greenriver.edu/bat/hire-a-bat/)
6. Annual backflow test due by Sept 1 each year

---

## Water Rate Structure — City of Duvall (in-city residential)

**Source:** [2023–2026 Utility Rates History (PDF)](https://www.duvallwa.gov/DocumentCenter/View/14564/2023---2026--Utility-Rates-History) · [Utility Billing page](https://www.duvallwa.gov/132/Utility-Billing). Use this to convert metered consumption (the OCR ft³ reading) into dollars.

**Unit conversion:** the Sensus meter reads in **cubic feet (ft³)**. `1 cf = 7.48052 gallons`. Tiers below are billed **per 100 cubic feet** (1 "ccf" = 748 gal). Bills go out the last week of each month, due the 20th of the next. Typical residential total ≈ $150–190/mo.

**Water — tiered (inclining block). Base fee includes the first 200 cf:**

| Tier (cubic feet) | Billing | 2023 | 2024 | 2025 | 2026 |
|---|---|---|---|---|---|
| **Base fee** (incl. first 200 cf) | flat/mo | $31.90 | $34.26 | $34.26 | $34.26 |
| 201 – 400 cf | per 100 cf | $4.75 | $5.10 | $5.10 | $5.10 |
| 401 – 600 cf | per 100 cf | $6.11 | $6.56 | $6.56 | $6.56 |
| 601 – 800 cf | per 100 cf | $7.48 | $8.03 | $8.03 | $8.03 |
| 801 – 1,000 cf | per 100 cf | $8.82 | $9.48 | $9.48 | $9.48 |
| Over 1,001 cf | per 100 cf | $10.22 | $10.97 | $10.97 | $10.97 |

**Flat monthly add-ons (residential):**

| Charge | 2023 | 2024 | 2025 | 2026 |
|---|---|---|---|---|
| Sewer | $84.91 | $91.18 | $91.18 | $91.18 |
| Storm drain | $23.88 | $25.64 | $28.72 | $32.17 |

**Marginal water cost per gallon (2026, the rate that matters for "what did this watering cost"):**
- Tier 201–400 cf: $5.10 / 748 gal ≈ **$0.00682/gal**
- Tier 401–600 cf: $6.56 / 748 ≈ **$0.00877/gal**
- Tier 601–800 cf: $8.03 / 748 ≈ **$0.01074/gal**
- Tier 801–1,000 cf: $9.48 / 748 ≈ **$0.01268/gal**
- Over 1,001 cf: $10.97 / 748 ≈ **$0.01467/gal**

Irrigation pushes consumption into the **upper tiers**, so the *marginal* cost of garden watering in summer is realistically **~$0.011–0.015/gal** (≈ **$8–11 per 100 cf / 748 gal**). Sewer and storm are flat, so extra outdoor watering does **not** raise the sewer charge — only the water tiers.

> **Notes:** Sewer/storm rates rise each year; water tier rates were flat 2024→2026. Reduced-rate (10%/40% low-income) and out-of-city/agricultural schedules exist in the PDF if ever needed — the Pace home is **in-city residential** (the table above). A leak-adjustment process exists (Ord. 1130) if a high bill is from a leak.

### Getting 2027+ rates when they're published
The table above is the **2023–2026** schedule. When the city publishes a new cycle, refresh from these durable links (the DocumentCenter PDF URL changes each cycle, so start from the Utility Billing page):
1. **Utility Billing page (start here):** https://www.duvallwa.gov/132/Utility-Billing — always links to the *latest* "utility rate schedule" / "Utility Rates History" PDF under **Utility Billing Forms**.
2. **Current rates PDF (2023–2026, may be superseded):** https://www.duvallwa.gov/DocumentCenter/View/14564/2023---2026--Utility-Rates-History
3. **Duvall Municipal Code (authoritative ordinances):** https://library.municode.com/index.aspx?clientId=16325 — search "utility rates" if the PDF lags behind a rate ordinance.
4. **Billing clerk** (to confirm): utilitybilling@duvallwa.gov · 425-788-1185.

How to extract: download the PDF and run `pdfplumber` (`pdf.extract_text()` per page) — that's how the table above was pulled. Page 1 = residential + commercial; pages 2–3 = reduced-rate / out-of-city / agricultural (ignore for the Pace home).

### Actual bills — account 001-0006184-004 (Natalie Pace, 27201 NE 144th Pl)
Three real water bills (downloaded 2026-06-12, from OpenGov / duvallwa.pay.opengov.com). The meter register on the **bill** reads in **hundreds of cubic feet (CCF)**; the **OCR** reads the same register in **cubic feet (cf)**. These bills **confirm the documented 2026 tiers to the penny** (tier math reproduces each Water Service line exactly), and the meter reads line up with the OCR.

| Bill due | Service period | Meter (CCF) start→end | Used (cf) | Water $ | Sewer $ | Storm $ | **Total** |
|---|---|---|---|---|---|---|---|
| 2026-04-20 | 02/26 – 03/25 | 892 → 896 | 400 | $44.46 | $91.18 | $32.17 | **$167.81** |
| 2026-05-20 | 03/25 – 04/27 | 896 → 906 | 1,000 | $92.60 | $91.18 | $32.17 | **$215.95** |
| 2026-06-22 | 04/27 – 05/27 | 906 → 931 | 2,500 | $257.15 | $91.18 | $32.17 | **$380.50** |

- **Account on auto-pay** (ACH on the due date). Pay/view: https://duvallwa.pay.opengov.com
- **Tier math check (2,500 cf bill):** base $34.26 + (200cf×$5.10) + (200×$6.56) + (200×$8.03) + (200×$9.48) + (1,500cf @ over-1001 ×$10.97 = $164.55) = **$257.15** ✓. The "Water Service" line **includes** the base fee. All three bills reproduce exactly → rate table is validated.
- **Usage is climbing fast into summer:** 400 → 1,000 → 2,500 cf/mo as irrigation ramps. The Jun bill (2,500 cf) is dominated by the over-1,001 tier at **$10.97/100cf ≈ $0.0147/gal** — this is the marginal cost of summer watering.
- **Bill PDFs:** `email_bill_001-0006184-004*.pdf` (3 files) in `~/Downloads` as of 2026-06-12 (not yet filed to a permanent home). Bill fields parsed: account #, due date, total, name/address, service period (start/end), meter type `WT`, register start→end, units used, per-charge breakdown.

### ⭐ Meter ↔ Bill Conversion (READ THIS to turn a meter read into a bill)

**The single most important fact:** the physical Sensus LCD, the OCR, and the bill are all reading **the exact same odometer** — just displayed in different units. Nothing is estimated; it's pure unit conversion.

**1. Reading the 9-digit Sensus LCD.** The display shows **9 digits, and the rightmost 3 are decimals** (fractional cubic feet, like the tenths on a car odometer). The `Ft³` label on the glass confirms the unit.

```
   0 9 4 0 0 8 . 3 4 8   Ft³
   └───────┘   └───┘
   whole ft³   decimal ft³
   = 94,008    = .348
```
So `094008348` = **94,008.348 ft³**. (It is NOT 94 million cf — that would be ~700 million gallons, absurd for a house. The trailing 3 digits are always decimals on this meter.)

**2. The bill register is CCF (hundreds of cubic feet).** The City bills in units of 100 ft³ — `1 bill unit = 1 CCF = 100 ft³ = 748.052 gallons`. The bill register is just the meter's **whole cubic feet with the last two digits dropped**:

```
bill_CCF = floor( whole_ft³ / 100 ) = floor( (meter_9digit / 1000) / 100 )
```

**3. Worked examples (both directions):**

| Direction | Input | Math | Output |
|---|---|---|---|
| Meter → bill | meter `094008348` | 94,008.348 ft³ → floor(94,008 / 100) | bill reads **940 CCF** |
| Meter → bill | meter `093100000` | 93,100 ft³ → 93,100 / 100 | bill reads **931 CCF** |
| Bill → meter | bill `931 CCF` | 931 × 100 = 93,100 ft³ | meter ≈ `093100xxx` |
| Bill → gallons | `2,500 cf` used | 2,500 × 7.48052 | **18,701 gal** that month |

**4. Computing a month's usage (what the bill charges for):** usage = (end register − start register) in CCF, then ×100 for cf, ×7.48052 for gallons.
- Example (Jun bill): `931 − 906 = 25 CCF = 2,500 ft³ = 18,701 gal`.

**5. Live cross-check (verified 2026-06-12):**
- Last bill closing read **05/27 = 931 CCF = 93,100 ft³**.
- Physical meter / OCR on **06/12 = `094008348` = 94,008 ft³ = 940 CCF**.
- Delta = `94,008 − 93,100 = 908 ft³ in 16 days ≈ 57 ft³/day ≈ 425 gal/day` — matches summer irrigation. **The OCR is reading the true physical register.** ✓

**6. Estimating the in-progress bill from a live meter read.** Take the current meter, subtract the last bill's closing register, that's CCF used so far this cycle; project to the next read date at the recent ft³/day, convert CCF→$ through the 2026 tier table (remember the first 200 cf is in the base, and summer usage is mostly in the **over-1,001 tier @ $10.97/100cf**), then add flat **sewer $91.18 + storm $32.17**.
- *Worked (as of 06/12):* 940 − 931 = 9 CCF used so far; at ~0.57 CCF/day to a ~06/27 read → ~`949–950 CCF` close → ~18–19 CCF (1,800–1,900 cf) billed → water ≈ **$200–230** → total ≈ **$330–360**.

**Quick constants for code/dashboards:**
- `CF_PER_CCF = 100`, `GAL_PER_CF = 7.48052`, `GAL_PER_CCF = 748.052`
- `meter_whole_cf = meter_9digit // 1000` (drop 3 decimal digits)
- `bill_CCF = meter_whole_cf // 100`
- 2026 marginal $/gal by tier: 201–400 `$0.00682`, 401–600 `$0.00877`, 601–800 `$0.01074`, 801–1000 `$0.01268`, over-1001 `$0.01467`

---

## 2026-06-23 — Oracle budget controller shipped ($150/mo target, spend-to-improve)

**Context:** James asked for explicit budget usage policy: use the subscription budget intentionally to improve meter accuracy now, then drive toward a no-LLM steady state. He approved aggressive spend within a hard monthly cap.

**What shipped:**
- New module `server-prod/oracle_budget.py`:
   - tracks oracle spend per call in `smart-garden.db` (`oracle_spend` table)
   - estimates USD from tokens (or fallback per-call estimate)
   - computes cycle-to-date spend + remaining budget + suggested daily cap
   - adds cycle projection fields (`projected_cycle_spend_usd`, `projected_delta_vs_budget_usd`, utilization %, elapsed/total cycle days)
- `dashboard.py` oracle integration:
   - new env knobs: `METER_ORACLE_BUDGET_ENABLED`, `METER_ORACLE_MONTHLY_BUDGET_USD` (default 150), `METER_ORACLE_DAILY_MIN`, token/fallback pricing knobs
   - new env knob: `METER_ORACLE_BUDGET_CYCLE_START_DAY` (default 1) for non-calendar billing cycles
   - dynamic daily oracle cap (`effective_daily_cap`) refreshed from budget state
   - spend recording on **all** oracle call sites (heartbeat, authority confirms, archive reread/reprocess, manual reanchor)
   - visibility added to `/api/cam/status` and `/api/cam/quality` (`budget`, hard/effective cap, monthly target)

**Operational result on Acer after deploy:**
- `smart-garden-server` active
- status payload now includes live oracle budget summary (month spend, remaining, suggested cap)
- status + quality payload now include cycle start day and month-end projection values
- with current defaults, target is $150/month and pacing cap is computed automatically each day

**2026-06-23 accuracy ramp (applied in production):**
- Added systemd drop-in `oracle-accuracy.conf` with accuracy-first pacing while keeping monthly cap:
   - `METER_ORACLE_MONTHLY_BUDGET_USD=150`
   - `METER_ORACLE_DAILY_CAP=1200`
   - `METER_ORACLE_DAILY_MIN=800`
   - `METER_ORACLE_VERIFY_SECS=60`
   - `METER_ORACLE_MIN_INTERVAL=20`
   - `METER_ORACLE_LOWCONF_INTERVAL=25`
- Verified active service env includes the new oracle knobs.
- Oracle spend table confirmed sustained activity after rollout (`calls_last_10m: 17`).
- Archive UI now shows the 3 simple spend numbers directly:
   - **Spent** this cycle
   - **Remaining** this cycle
   - **Projected end-of-cycle spend**
   (implemented in `server-prod/templates/cam_archive.html`, refreshed every 30s from `/api/cam/quality`).

**2026-06-23 auto in-between inference (new):**
- Added automatic interpolation in `server-prod/meter_archive.py` for rows between trusted anchors.
- Trigger: when a trusted anchor arrives (`manual`, `oracle`, or `cnn` high), lock/propagated rows between the previous trusted anchor and the new anchor are auto-filled.
- Safeguards:
   - monotonic only (never decreases)
   - bounded by max physical flow (`METER_MAX_GPM`)
   - never rewrites reviewed/manual/oracle/cnn-strong rows
   - marks inferred rows as `source=propagated`, `confidence=inferred`
- Verified with isolated temp-DB smoke test:
   - left anchor `94780531`, right anchor `94780542`
   - middle rows auto-filled to `94780535`, `94780538`.

**2026-06-23 reconnect self-heal (automatic backfill):**
- Implemented disconnect-aware auto backfill so this no longer needs manual one-off scripts.
- New behavior in `dashboard.py`:
   - detects long cam upload gaps (`METER_RECONNECT_GAP_SECS`, default 45s)
   - marks reconnect backfill pending with a bounded lookback window
   - tags first post-gap OCR frames to force oracle confirmation quickly
   - repeatedly runs archive reconciliation while pending (bounded attempts)
- New helper in `meter_archive.py`:
   - `reconcile_window(start_ts, end_ts)` re-applies trusted-anchor interpolation for all anchors in the window
- Added visibility in `/api/cam/status` under `archive.reconnect_backfill`.
- Validation:
   - temp-db outage sequence test produced inferred middle rows automatically
   - live status API shows reconnect_backfill state fields.

**2026-06-23 strict inference mode (tower CPU-first between AI anchors):**
- Upgraded reconnect/anchor recovery to run strict smart-window backfill in a background worker instead of interpolation-only reconciliation.
- New behavior:
   - whenever a trusted anchor lands, queue a bounded strict window pass over recent archive rows
   - after reconnect gaps, queue strict passes over the reconnect window until applied/expired
   - strict pass uses constrained CNN on the real archived frames (`_smart_archive_reprocess`) and keeps oracle budget configurable (default 0 for this strict mode path)
- New config knobs:
   - `METER_STRICT_BACKFILL_ENABLED` (default 1)
   - `METER_STRICT_BACKFILL_LOOKBACK_MINUTES` (default 240)
   - `METER_STRICT_BACKFILL_MAX_ROWS` (default 480)
   - `METER_STRICT_BACKFILL_ORACLE_BUDGET` (default 0)
   - `METER_STRICT_BACKFILL_MIN_INTERVAL_S` (default 45)
- `/api/cam/status` now reports `archive.strict_backfill` runtime state (`enabled`, `running`, `last_reason`, `last_result`).

**Azure-side guardrail attempt:**
- Tried creating a subscription budget via CLI + REST for `f94c002c-2212-4bfb-b7a4-f8898b7ea4e5`.
- Blocked by RBAC (`RBACAccessDenied`) on Cost Management budget write at current account permissions.
- App-level budget controller is active regardless; cloud budget object still needs higher role permissions.

## 2026-06-23 — Smart archive window reprocess shipped (wider context, dry-run/apply)

**Context:** James asked for a smarter approach than one-row fixes: use wider temporal context, support dry-run before commit, and reprocess targeted windows when the archive looks suspicious (including the 08:08 case).

**What shipped (server + UI):**
- **Context-aware reprocessor** in `server-prod/dashboard.py`:
   - `_smart_archive_reprocess(start, end, max_rows, oracle_budget, commit)`
   - `POST /api/cam/archive/reprocess` with `minutes/start/end/max_rows/oracle_budget/dry_run`
   - Candidate scoring across existing value + constrained CNN + selective oracle
   - Monotonic + physics bounds + prefix progression guard
- **Config knobs** for safe tuning without code edits:
   - `METER_ARCHIVE_REPROCESS_MAX_ROWS`
   - `METER_ARCHIVE_REPROCESS_MAX_ORACLE`
   - `METER_ARCHIVE_REPROCESS_CNN_MIN_CONF`
   - `METER_ARCHIVE_REPROCESS_CONSENSUS_COUNTS`
- **UI controls** in `server-prod/templates/cam_archive.html`:
   - "Smart Reprocess (dry run)"
   - "Apply Smart Reprocess"
- Manual correction path continues to use delta propagation in `meter_archive.propagate_delta(...)` so nearby stale rows align immediately after a human correction.

**Important hardening fix after first dry-run:**
- Added a **strict right-anchor bound** for upcoming reviewed/manual anchors.
- Before this fix, a row immediately before a reviewed anchor could still overshoot by tolerance and create a dip at the anchor.
- Now reviewed/manual anchors are hard upper bounds; tolerant bounds remain only for softer anchors.

**Production validation (Acer, 100.84.106.20):**
- Compile clean locally and on server.
- Service restart successful (`smart-garden-server` active).
- 2-hour pass: dry-run then apply completed; updates committed.
- 6-hour pass with larger oracle budget: dry-run then apply completed.

**Observed around 08:08 after apply:**
- `08:07:16 -> 94779715`
- `08:08:18 -> 94779715` (reviewed anchor preserved)
- `08:09:18 -> 94779891`
- Sequence remains monotonic around the anchor with no pre-anchor overshoot.

**Current state:**
- Smart window reprocessing is now available from the archive page and via API.
- Users can run dry-run first, inspect `would_update/oracle_calls/changes`, then apply.

## 2026-06-23 — Fully automatic strict backfill cadence + CNN improvement insights

**Context:** James asked for two concrete outcomes: (1) strict archive repair should run automatically (not only on reconnect/anchor events), and (2) CNN progress should be visible in clear metrics instead of guesswork.

**What shipped (`server-prod/dashboard.py`):**
- Added periodic strict scheduler controls:
   - `METER_STRICT_BACKFILL_AUTO_ENABLED` (default `1`)
   - `METER_STRICT_BACKFILL_AUTO_EVERY_S` (default `180`)
   - `METER_STRICT_BACKFILL_AUTO_WINDOW_MINUTES` (default `360`)
- Added background daemon `_strict_backfill_daemon()`:
   - continuously queues strict passes while enabled
   - prioritizes reconnect windows when pending
   - otherwise runs rolling auto windows on cadence
- Expanded strict status state:
   - includes `runs`, `auto_enabled`, `auto_every_s`, `window_minutes` in `/api/cam/status`.
- Added CNN insight helpers and endpoints:
   - `_archive_quality_stats(hours)` for inferred/trusted percentages in rolling windows
   - `_cnn_trend_summary(daily_rows)` for recent-7d vs prior-7d CNN accuracy delta
   - `/api/cam/cnn-report` now includes `insights` block (trend, archive quality, strict state, oracle budget)
   - new compact `/api/cam/cnn-insights` endpoint for dashboards/automation clients.

**Stability fix (same deploy):**
- Fixed startup race where the daemon could run before `_smart_archive_reprocess` was bound in `create_app`.
- `_run_strict_backfill` now waits briefly for helper binding on boot instead of failing the first auto pass.

**Production deploy + validation (Acer):**
- Deployed `dashboard.py` to `~/smart-garden-server/` and restarted `smart-garden-server` (active).
- Updated systemd drop-in `oracle-accuracy.conf` to persist:
   - `METER_STRICT_BACKFILL_AUTO_ENABLED=1`
   - `METER_STRICT_BACKFILL_AUTO_EVERY_S=120`
   - `METER_STRICT_BACKFILL_AUTO_WINDOW_MINUTES=360`
- Verified service env includes `METER_STRICT_BACKFILL_AUTO_EVERY_S=120`.
- Verified journal startup line: `strict backfill daemon started (every 120s, window 360 min)`.
- Verified `cnn-insights` payload includes trend + 1h/6h/24h archive quality snapshots.

**Current state:**
- Strict backfill is now autonomous on a fixed cadence and still event-aware for reconnects.
- CNN improvement telemetry is exposed via API and can be graphed/alerted without manual SQL.

## 2026-06-23 — CNN retrain moved to near-real-time checks + full ground-truth replay metrics

**Context:** James asked to stop waiting for a daily 3:20 AM job and instead improve the CNN as soon as enough new data is available, while continuously tracking improvement quality.

**What changed (tower retrain system):**
- `meter-cnn-retrain.timer` changed from clock-based nightly run to frequent polling:
   - old: `OnCalendar=*-*-* 03:20:00`
   - new: `OnUnitActiveSec=10min`, `OnBootSec=2min`, `RandomizedDelaySec=60`
- Gate remains data-driven in `retrain.py`:
   - train only when `(new_frames + new_manual) >= MIN_NEW_FRAMES` (still 25)
   - otherwise skip quickly (cheap check cycle)

**Continuous improvement tracking (new):**
- `retrain.py` now evaluates champion and challenger on:
   - held-out benchmark (existing gate)
   - **all trusted ground truth** (`clean` label set after audit/manual/propagation overlay)
- Added new status fields in `~/meter-cnn/retrain_status.json`:
   - `champion_ground_truth_full9`
   - `challenger_ground_truth_full9`
   - `champion_ground_truth_perdigit`
   - `challenger_ground_truth_perdigit`
   - `trusted_ground_truth_n`
- Added append-only per-run history log:
   - `~/meter-cnn/retrain_history.jsonl`
   - includes both skipped and completed runs for trend analysis over time.

**Validation on tower (live):**
- Timer active with 10-minute cadence (`meter-cnn-retrain.timer` waiting, next trigger ~10 min).
- Forced smoke run (`--force --epochs 2`) completed and status included new ground-truth fields.
- Sample result from live run:
   - champion held-out full-9: `0.6552`
   - champion ground-truth full-9: `0.7741`
   - trusted ground truth size: `1111`
- History file appended both:
   - skipped run record (below threshold)
   - completed run record (full metric payload)

**Current state:**
- Retrain checks are now near-real-time and no longer tied to once-daily timing.
- Actual training still only starts when enough new data exists (25 threshold), preserving stability and cost.
- Improvement tracking now includes benchmark + full trusted-ground-truth replay each run.

## 2026-06-13 — Dedicated Sensor History page + unified compact mobile nav + cam-cutoff fix

**Context:** James couldn't see soil-sensor history anywhere (the existing charts are buried in the index History panel's drilldowns), and the mobile bottom nav was broken: 11 items jammed into a `justify-content:space-around` row wrapped onto 2–3 lines on a phone — so the bar was huge, items were cut off, and **the Water Meter Cam panel got hidden behind the over-tall nav** ("camera cut off"). Each page also hardcoded a *different* nav subset (forecast/calibrate showed fewer items than home) because the in-page SPA panels (Zones/History/Cam/Deer) only exist on index.html.

**Live sensor truth at the time (unchanged hardware):** Garden(p32)=754 stuck-low = dead oscillator; **Grapes(p33)=2492 = the one good sensor** (stable, tracks real moisture); Fruit Trees(p34)=0 floating; South Lawn(p35)=0 floating. Config logs only `soil_0`(Garden, 5294 rows) + `soil_1`(Grapes, 2661 rows); `soil_2/3` off (no point logging dead probes).

**What shipped:**
- **New `/sensor-history` page** (`templates/sensor_history.html` + route in `dashboard.py`). One Chart.js line chart with all 4 sensors, **Raw ⇄ Moisture%** toggle and **24h/7d/30d/90d** range. Per-sensor summary cards (live raw, %, status pill — Working/Stuck low/Check wiring/Disabled, window min–max, sample count, dry/wet cal). **Reuses the existing `/api/sensor-history?type=soil&index=N&hours=H` endpoint** (returns `[{ts,pct,raw}]`) + `/api/calibration` for names/cal/live raw — no new API needed. Dead sensors auto-populate once their probes are fixed and `soil_2/3` flipped to true.
- **Shared mobile nav partial `templates/_mobilenav.html`** (self-contained scoped CSS + JS), included via `{% include '_mobilenav.html' %}` in index, forecast_merged, moisture_sim, costs, sensor_history. **Fixes the per-page drift permanently** — one file, identical everywhere. Design = chosen "5 primary tabs + More sheet": Home / Zones / Schedule / Forecast / **More⋯**; the More slide-up sheet holds History, Sensor History, Cam, Deer, Settings, Water Cost, Flow, Calibrate, Zone Map. In-page panel links use `/#panel`; on `/` they're intercepted → `window.showPanel()` (no reload), from other pages they navigate to `/#panel` and index opens it from the hash on load (index already supported hash-deep-link).
- **Cam-cutoff fix:** root cause was the over-tall wrapped nav. New single-row nav is ~62px; also bumped index `.main` mobile bottom padding to `calc(84px + env(safe-area-inset-bottom))` so the cam panel always clears the fixed bar.

**Decisions:** kept dead-sensor logging OFF (no point recording flat zeros); did NOT touch any watering logic or the ESP32 firmware; desktop sidebars left as-is (added Sensor History link to the new page's sidebar + all mobile More sheets).

**Verify:** service `active`, no errors/TemplateNotFound in logs, all routes (`/sensor-history`, `/`, `/forecast`, `/moisture-sim`, `/costs`) return 302→login (render OK, auth-gated). James to confirm on phone. Deployed to Acer `~/smart-garden-server/` + restarted.

---

## 2026-06-12 (night) — Moisture forecast falsely predicted DAILY watering (chart-only bug, model is correct)

**Context:** James looked at the moisture/Schedule page and saw the forecast projecting watering **every single day** in the coming week, which contradicted the design intent (deep + infrequent, ~2–3×/week). He asked whether the model was wrong, whether it was getting extra hot, or whether he really should water daily.

**Diagnosis — pulled REAL data from the live DB (`~/smart-garden-server/smart-garden.db`), not theory:**
- **Actual watering (last 21d) is already 2–3×/week**, exactly as designed: Zone 0 = 9 days/21 (~every 2.3d), Z1=5, Z2=4, Z3=5, Z4=8, Z5=6, Z6=3. The engine is doing the right thing.
- Current soil state: TAW=**22.9mm (0.9")**, MAD=**11.4mm (50%)**, today's ETc≈**4.45mm/day**, ET₀ climbing (2.7mm Jun 6 → ~5.0mm Jun 11–12). Real refill 50%→100% over a ~50-pt band ÷ ~20%/day ET ≈ **water every ~2.6 days** — matches the actual data.

**Root cause = the forecast SIMULATION, not the decision engine.** In `templates/moisture_sim.html`, the projected morning watering refilled the soil only to **`madPct + 20` (≈70% full)** — a shallow top-off — instead of the **deep soak to field capacity (~100%)** the real engine applies (it runs `max_runtime_min` and the balance fills to TAW). With summer ET ≈ 20% of the bucket per day, a shallow 20-pt refill re-crossed MAD the very next morning → forecast falsely showed **daily** watering. The real engine refills the full ~50-pt band → every ~2.6 days.

**Fix (chart-only, ZERO change to any watering decision):** changed the projection's `waterTarget` from `Math.min(100, madPct + 20)` to **`100` (field capacity)**, matching the real engine. The `minutesWateredToday < maxRuntimeMin` cap remains the true limiter on a single morning cycle. `irrigation.py` (the actual decision engine) was **not touched**. Deployed `moisture_sim.html` to the Acer + restarted `smart-garden-server.service` (active, HTTP 200).

**Agronomy note for future-me:** frequency should always be an **output** of ET depletion, never a hardcoded calendar. In cool weather the engine stretches to 4–5d/skips; in a July heat wave it correctly tightens toward ~every 2d. That variability is the system being *right*. If James ever wants genuinely less-frequent summer watering, the correct lever is a **deeper root depth / bigger bucket** (config already ramps root depth to 8" Jul–Aug), NOT a frequency cap. Did not change MAD, root depth, or run times — they're internally consistent and agronomically sound.

---

## 2026-06-13 — Ground-truth defense-in-depth (stop bad labels mistraining the CNN)

**Context:** James saw the training grid still had wrong labels and asked the key question: *"how do we make sure it doesn't get stored like that and end up mistraining the CNN?"* Right question — a wrong label is worse than no label (it actively teaches the model the wrong thing).

**Two root holes found:**
1. **The monotonic audit can't catch systematic errors.** The wrong labels descended smoothly (`119983 → 119163 → 115559…`) — internally consistent, so they pass the LNDS monotonicity check. When the reader makes the *same* mistake across many frames, no single-signal/physics check catches it.
2. **The oracle's `agree:true` flag was circular/dishonest.** `_oracle_bank_label` hardcoded `agree:true` with `ocr_guess==label` — but the oracle IS the only reader, so it verifies nothing. **295 of 388 banked labels were oracle-only with this fake flag** → the majority of ground truth had zero independent verification.

**The principle: collected ≠ verified.** Banking COLLECTS candidate (frame, label) pairs cheaply. The CNN must train ONLY on labels that pass INDEPENDENT verification — never raw banked labels. A label is CNN-eligible only when **two independent readers agree**: RapidOCR (small scene-text model, on the tower) and GPT-4o (oracle) fail in *different* ways, so a systematic error fooling one rarely fools both.

**What shipped:**
- **`dashboard.py` banking honesty fix** — `_oracle_bank_label(... local_low=)`: `agree` is now true ONLY if the local RapidOCR's independent low-5 digits match the oracle's value; oracle-alone = `agree:false` + records `local_low`. Threaded the local read's low-5 from `_maybe_oracle` → `_oracle_run` → bank. No more circular `agree:true`.
- **`ocr-harness/build_cnn_dataset.py`** — the export gate. (1) LNDS monotonic backbone, then (2) re-reads every backbone frame with the tower's RapidOCR (free, independent architecture) and keeps a label only if the second reader agrees on all 9 digits (or low-5 with `--low-only`). Emits `manifest.jsonl` (CNN-ready) + `needs_review.jsonl` (disagreements, excluded until a human resolves). The CNN trains ONLY on the manifest.
- Confirmed the poison by **independent viewing** (rotated frames): `094119983` etc. are glare-garbled — the trailing/middle digits don't match the stored label.

**Lesson:** never let a pipeline's own output become ground truth without a *genuinely independent* check. Monotonicity (physics) catches impossible labels; cross-reader agreement (two architectures) catches systematic ones; a human spot-check montage catches the rest. Defense in depth, because each layer has a blind spot the others cover.

**First cross-reader run (the calibration surprise):** strict "all 9 digits must match" rejected 301/384 — but the disagreements showed RapidOCR mostly returned **∅ (nothing)**, **10 digits**, or **scrambled order** (e.g. label `094010324` vs tower `401010324`) on this glary feed. So the rejections were mostly **false-rejects** (a weak 2nd reader), NOT proof the labels were wrong. Takeaway: RapidOCR is too noisy on this camera to be a strict 9-digit second vote. The robust setting is `--low-only` (require just the low-5 digits to agree — the ones that change + that both readers can usually get; the high digits come from the monotonic backbone anyway). Also worth adding later: use the ORACLE re-read (GPT-4o with context hint) as the second vote instead of RapidOCR, since the harness showed it's far more reliable. The gate logic is right; the *choice of second reader* matters.

**2026-06-15 — oracle verifier + dedup + consensus resolver.** Two days of data → 627 frames; re-audit quarantined 92 new poison → 581 clean. Added to `build_cnn_dataset.py`: `--verifier oracle` (GPT-4o re-read with the slow-movement hint as the independent 2nd vote — the reliable reader) and `--max-per-label N` dedup. Also dropped live banking `GOLD_MAX_PER_LABEL` 3→1 (one clean image per number is enough for a per-digit CNN; cuts cost). Oracle-verified + dedup-to-1 = **104 verified / 305 review** of 409 deduped. The 305 disagreements were almost all **±1-5 on the fast-moving LAST digit** under glare (the high 8 digits matched). James confirmed the last digit DOES matter for a per-digit CNN, so we don't relax the rule. Instead: **`resolve_consensus.py`** — re-reads each disputed frame 3× with GPT-4o, promotes to the manifest only if a value wins a **strict majority** AND fits **monotonically between the trusted 104 anchors** (a meter can't go backward). Majority vote resolves stochastic glare disagreement without lowering the bar; corrected labels are written into the manifest (the CNN trains on manifest `(file,label)`, so no file rename needed). Result counts pending the run. **Key principle reaffirmed:** the manifest is the single source of truth for training; the filename's label is just a candidate.

**Consensus result (final):** **104 → 395 verified labels.** Of 305 disputed frames, **291 promoted** (majority vote + monotonic gate), **72 of those had their label CORRECTED** by the vote (almost all last-digit glare errors like `...589→...584`, at 3/4 or 4/4 votes — exactly the bad labels that would have mistrained the CNN), only **14 stayed unresolved**. Two operational fixes were needed mid-effort: (1) the first run **ran the $10 OpenAI credit dry** and then spun forever on "exceeded your current quota" (backoff can't fix an empty wallet) — made the resolver **incremental + resumable** (`consensus_results.jsonl`, one durable line per frame, skips done frames on re-run) and **quota-aware** (raises `QuotaExhausted` and stops cleanly vs. the per-minute 429 which it waits out). (2) Added client-side throttle (~27 reads/min) to respect the 30K-token/min cap. With fresh credit the resumable run finished clean, 0 quota stops.

**Label review gallery** (`/cam/labels`, `templates/cam_labels.html` + `/api/cam/labels`): merges manifest + needs_review into one color-coded gallery — Verified (green) / Promoted (blue) / Corrected (purple, shows "was X") / Review (amber) — with filter chips + counts, sorted by reading value. The Corrected filter is the spot-check view (did the vote's fix match the image?); Review is the small human-eyeball pile. Frames served via `/api/cam/training/img/<file>`.

**2026-06-15 — manual edit + collection-off + finalize (DATASET DONE, CNN-ready).** Added inline editing to the gallery: each tile has **Fix** (type correct 9 digits), **OK** (confirm), **Reject** (exclude). Saved to `manual_labels.jsonl` (highest trust tier, `POST /api/cam/labels/update`, last-write-per-file wins), overriding all automated verdicts on read. New statuses **manual** (cyan) + **rejected** (red). James reviewed the whole set: **86 corrected, 8 OK'd, 36 rejected** (130 edits). **Turned OFF auto-collection** — `METER_BANK_ENABLED=0` via `collection.conf` drop-in (gates both `_bank_sample` and `_oracle_bank_label`; the oracle STILL reads/re-anchors the live meter, it just stops saving training images) so James isn't stuck on a manual-correction treadmill. **`finalize_dataset.py`** bakes everything into the final training file `cnn_train.jsonl` with trust priority manual > consensus/verified, excluding rejects + unresolved review: **373 frames (336 distinct readings), 0 unresolved, 0 missing.** Sources: 86 manual + 8 manual-ok + 197 consensus + 82 verified. THIS is the only file the CNN trains on.

**➡️ NEXT: the closed-loop self-improving reader. Full plan + current-state doc: [`ocr-harness/CNN-CLOSED-LOOP-PLAN.md`](../smart-garden/ocr-harness/CNN-CLOSED-LOOP-PLAN.md).** Summary: CNN reads digits (free/fast) → low-conf or 5-min spot-check heartbeat falls through to GPT-4o oracle (independent verifier) → oracle agreements bank new verified labels, disagreements bank corrections → gated nightly retrain (champion/challenger: promote only if it beats the golden-set score). Three guardrails: (1) never let a reader's own output become a label without independent confirmation, (2) retraining is gated not auto, (3) monotonic physics is the final veto. Build order: train CNN v1 → wire inference path → verified-only correction banking → gated retraining → cost ramp-down.

---

## 2026-06-13 — OCR test harness + ground-truth audit (iterate without manual eyeballing)

**Context:** James was tired of the loop "I troubleshoot → screenshot → you fix → I check again." He asked for a **test harness so the reader can be iterated automatically**, and flagged that the **banked training labels looked wrong** and he was nervous about them becoming ground truth. Both concerns were dead-on.

**Ground-truth audit (his worry was justified).** I pulled banked frames, rotated them upright (camera is upside-down), and read them **independently** (a separate vision model from the pipeline — not circular). Found real poison: e.g. a frame whose true reading is `094100575` was banked as `094110575`; `094099518` banked as `094103951` (~4,400 too high). All from the ratcheting bug. The pipeline had been auto-labeling its own mistakes into the ground truth.

**Tools built (in `MyCode/smart-garden/ocr-harness/`, see its README):**
- **`golden.json`** — trusted ground truth, each frame's real reading verified by independent viewing (NOT the pipeline). `true` vs `stored_label` so poison is explicit.
- **`harness.py`** — runs each golden frame through `vision_oracle.read_meter` with the realistic context hint, scores **per-frame** accuracy vs `true`, exits non-zero below threshold so a loop can iterate on reader code. Runs on the Acer (has the key + tower).
- **`audit_labels.py`** — finds + quarantines poisoned labels via **Longest Non-Decreasing Subsequence** over (capture-time, label). The meter is monotonic, so the largest non-decreasing backbone is trustworthy; everything off it is an outlier. Robust to BOTH false-highs and false-lows (a naive running-min envelope flagged 215/396 because one false-low poisons the whole backward envelope — LNDS fixed that to a principled 69).
- **`rotate_upright.py`** — 180° rotate helper for human verification.

**Results:**
- **Quarantined 69 poisoned frames (138 files incl. JSON), leaving 328 clean, monotonic ground-truth frames.** Reversible (moved to `~/meter-training-quarantine/`, nothing deleted). Caught the entire documented ratchet cluster (`094103951`–`094110575`).
- **Improved the oracle hint** using the harness: the meter moves only a few hundred counts/read, so the first **six** digits barely change — told GPT-4o "the reading is very close to X, only the last 2-3 digits change." Oracle per-frame accuracy on the hardest-glare golden set went **20% → 60%** (typical frames read near 100%). The 2 remaining misses (`094099518`, `094100575`→`094100573`) are heavy-glare frames near the hardware ceiling.
- **Oracle reads now appear as table rows** (`record_oracle_reading`, kind=`oracle`, 🤖 AI label, blue tint). Previously the AI was successfully reading glared frames the local OCR couldn't, but those reads were invisible — the table showed all "reading pending" even though the meter was being read. Now those show as real fresh reads.

**Stable golden dir:** `~/ocr-golden/` on the Acer (the audit never touches it). Grow the golden set by viewing more upright frames and adding verified rows — makes the harness stronger over time.

**Lesson:** never let a pipeline auto-label its own outputs into the ground truth without an independent check — errors become "training truth." The monotonicity audit is the cheap independent check that needs no AI and can't be fooled.

---

## 2026-06-13 — Click-to-inspect reading detail (verify each row against its image)

**Context:** James noticed the live image showed ~094098675 while the table's "captured this minute" row read ~094083407 — far behind — and (rightly) didn't trust it. He wanted to click any row and see the exact frame the OCR saw for it, plus all that row's data.

**Problem:** per-reading frames weren't saved at all — only banked high-conf frames (training set) and the single latest `cam_state["image"]`. So a row couldn't be tied to its image.

**What shipped:**
- **`cam_ocr.py`** — every readings-table row now gets a unique `id` (`<epoch_ms>-<seq>`, module counter `_ENTRY_SEQ`, survives restarts, sortable). New `get_reading_by_id(rid)`.
- **`dashboard.py`** — frame ring buffer `FRAME_DIR=/tmp/meter-frames` (env `METER_FRAME_DIR`), keep newest `METER_FRAME_KEEP=720` (~1h, ~30MB); `_save_frame(rid, frame)` writes `<id>.jpg` in the OCR worker right after `process_text` and prunes the evicted oldest via an in-memory `_frame_ids` deque. Routes: `GET /api/cam/frame/<id>` (serves that frame or 404), `GET /api/cam/reading/<id>` (full field dump + `has_frame`), `GET /cam/reading/<id>` (detail page).
- **`templates/cam_reading.html`** (new) — shows the rotated frame + every field (processed/captured/gap/lag/reading/ft³/gal/ocr_guess/Δ/rate/kind/conf/stale/raw_low_match/note/raw OCR/id). Graceful message when the frame was pruned or the row is a derived back-fill (no frame).
- **`index.html`** — table rows are now clickable (`cursor:pointer`, navigate to `/cam/reading/<id>`).

**Verified:** frames saving every ~5s, ids assigned, endpoints registered (auth-gated like the rest of the dashboard). Compile-checked, deployed, service active.

**Oracle low-conf fix (same session, the real root cause):** the detail page immediately proved James right — a row showed `≥94,083.407` **stale 5649s (94 min!)** while the captured image clearly read ~094098.675. Investigation: the vision oracle was **rejecting every read** (173 floor-rejections that day, ~1000+ wasted GPT-4o calls). GPT-4o read the LOW (moving) digits reliably but garbled the leading `09`→`34`/`84` under evening glare, so the raw value fell below the anchor floor and was discarded → meter sat stale for 90+ min.
- **Fix 1 — high-digit garble repair (`_oracle_splice`):** keep the lock's stable high digits, overlay the oracle's trusted low 5–7 digits, accept the first physically-plausible **forward** step. Turns `34038780`→`094038780`.
- **⚠️ Fix 2 — FORWARD-ONLY (critical safety catch):** the first version of the splice allowed a small downward correction, and it *immediately bit* — at 20:38 the oracle pulled the lock **backward** 94083407→94038780 because in deep glare GPT-4o garbles the LOW digits too (`38780` vs true `98675`). A water meter is monotonic, so any oracle value **below the lock is a misread, not a real decrease**. Changed both the splice and the acceptance check to **reject anything below the lock** (`0 ≤ d ≤ ceiling`) and **hold + show stale** instead. Genuine high-drift correction is now only via the **manual "AI Re-anchor" button** (user-triggered override) — never automatic downward.
- **Re-anchored** the corrupted lock to James's eyeball read 94098675 (stop service → write `/tmp/meter_state.json` → start). **Verified live:** oracle misread `34038700` was rejected at the floor and the lock **held at 94098675** (forward-only working).
- **Lesson (again):** corroboration ≠ trust when the error is systematic; and an *independent verifier that can itself be systematically wrong* (GPT-4o in glare) must be constrained by domain physics (monotonicity) — never allowed to move the lock backward automatically.
- **Still open:** the stale anchor floor env is still `94009473` (loose); evening glare is the hardware ceiling (lens focus/exposure). The oracle now ratchets UP correctly but can't fix a static blurry meter — that needs the per-digit CNN or a hardware fix.

**Oracle CONTEXT HINT (same session, James's idea — big win):** James asked "can we send it context — acceptable ranges, starting point — to help it get the right number?" The oracle had been sending GPT-4o ZERO context ("read the 9 digits"), so glare on the high digits left it guessing pixels. Added `vision_oracle._build_hint(hint)`: injects the last value, the monotonic floor + physical ceiling, and the expected high-digit prefix (`0940`) into the prompt — framed so the bounds disambiguate **only** the glare-prone HIGH digits while the LOW digits are still read straight from the image. `read_meter(jpeg, rotate180, hint)` now takes the hint; `_oracle_run` builds it from `last_good` + the physical ceiling; the manual re-anchor passes a soft prefix-only hint (no hard floor, so the override stays free in both directions). **A/B tested on the live glared frame:** no-hint → `794038780` (garbage); with-hint → `094098709` (exact truth). Same image, same model — context alone fixed it. This makes the oracle far more useful on exactly the blurry evening frames that were failing.

---

## 2026-06-12 (night) — Cam readings table: capture-time alignment + display-Δ fallback + gold-set prune

Three small, surgical fixes to the Water Meter Cam page, all verified against the live server (no drift — `dashboard.py` and `index.html` both md5-matched the Acer before editing).

**1. Capture-time alignment (table vs. live image).** The live image's "Captured" (the `X-Capture-Time` header) used the **transfer-corrected** capture moment (`capture_dt = now − transfer_s`), but the frame enqueued for OCR was tagged with **plain arrival time** (`cam_queue.append((time.time(), data))`). So the readings table's "Captured" column ran a couple seconds *later* than the image's for the same frame on the lossy WiFi. Fixed `cam_upload` to enqueue the **same** corrected stamp: `cam_queue.append((capture_dt.timestamp(), data))`. Now both timestamps derive from the identical capture instant. (Residual: the table's top row can still look older than the live image — that's real FIFO *processing* lag, shown in the Lag column, not a timestamp bug.)

**2. Δ (change) columns now track the displayed reading.** Complaint: the reading climbs (e.g. ≥094012120 → 094012171) but **Δ ft³ / Δ gal stay blank**. Root cause: the engine (`cam_ocr._validate`) only emits a Δ on a **confirmed high-confidence advance** — "hold"/"stale"/"pending" rows return `delta=None`, so the Δ cells render `—` even though the shown value went up. Fix is **frontend-only** in `camLoadReadings()` (`index.html`): when the engine left Δ blank, derive a **display-Δ** from the change in the *shown* ft³ vs the previous (older) row (`parseShownFt3` strips the "≥" and commas; threshold 0.0004 ft³; gal = Δft³ × 7.48052; green when positive). Engine-provided Δ and the **rate (gal/min) column are untouched** — rate still needs real timing, so it stays engine-only. **Zero changes** to the OCR lock, validator, banking, or oracle. This is purely how the table presents change. Honest because the meter is monotonic — any rise in the displayed value is real water, including across a stale "≥" catch-up.

**3. Gold-set prune (one-time cleanup).** Training viewer showed 7–8 images of the same number (094010270 ×8, 094008998 ×7, 094010324 ×6) — over the `GOLD_MAX_PER_LABEL=3` cap. The cap was added during the OCR overhaul and only enforces on **new** writes (it can't retroactively prune); those duplicates were banked *before* the cap went live, while the meter sat static and the steady-meter rule saved one frame/~50s. Both banking paths (`_bank_sample`, `_oracle_bank_label`) verified correct (count all `.jpg` for the label, stop at 3). Pruned to the **3 newest per label** (kept lighting variety), removing 12 jpgs + their `.json` sidecars: **60 → 48 samples**, max 3 each. Post-restart banking confirmed capping correctly (new numbers at 1–2). Not a recurring leak.

**Deploy:** `dashboard.py` scp'd + `systemctl restart smart-garden-server` (active); `index.html` scp'd (templates auto-reload, hash-verified). Prune ran via a temp bash script (PS→ssh heredoc quoting forced a file, not inline), then cleaned up.

---

## 2026-06-12 (evening) — Meter OCR overhaul + vision-LLM oracle + Flow/Leak monitor

**Context:** Day-long deep session turning the water-meter cam from "numbers bounce randomly" into a self-correcting, AI-verified reading pipeline, then building per-zone flow estimation + leak detection on top. (Detailed implementation notes live in repo memory `/memories/repo/water-meter-ocr.md` — this is the narrative summary.)

### 1. Reading accuracy — from garbage to reliable
The Sensus iPERL shows **9 digits, decimal 3 from the right** → `094008.348 ft³` (verified against the city bill register + the physical meter). Fixes, in order of impact:
- **Box-ordering (biggest win):** RapidOCR returns the two LCD digit groups out of order (`1593 9400`); the tower now sorts detections by bounding-box X so they read left-to-right.
- **Leading-zero width bug:** `int("094…")` drops the zero → a good 9-digit read looked like 8. `_extract` now returns the true matched digit width.
- **Physical meter model** (`cam_ocr.py`): monotonic odometer + **time-aware flow ceiling** (`max_gpm=20`, even a burst pipe; a 5s frame allows ~290 counts, a 60s gap allows proportionally more). Rejects impossible jumps as `too-fast`.
- **Per-digit 7-segment context scorer:** enumerates every physically-possible reading in a tight window and scores each candidate digit-by-digit by segment similarity (so a blur-induced `7→1` still scores high), gated on the reliable low digits. Beats pass/fail on the whole string.
- **Corroborated advance:** the lock only moves when the same value appears in ≥2 consecutive frames — stops a *systematic* misread from "self-corroborating" into a false-high lock that then rejects every real (lower) read forever. (This false-high drift bit us twice; the heartbeat below is the real safety net.)
- **Known anchor + state persistence:** seeded `METER_ANCHOR_VALUE` (operator-confirmed reading) as a monotonic floor; lock persists to `/tmp/meter_state.json` across restarts so it never re-bootstraps into garbage.
- **CLAHE preprocessing (tower):** by mid-afternoon the glass washes out to near-zero global contrast and RapidOCR found *zero* text; CLAHE local-adaptive equalization recovers the digits where plain autocontrast got nothing.
- **Honesty:** when a frame can't be read it **holds** the last value, and after 20s marks it **stale** (shows `≥ value`) instead of pretending a stale number is current. Dashboard cam table gained columns: Processed | Captured | **Gap** | Lag | Q | Reading | **OCR Guess** | ft³ | Gallons | Δ | gal/min | Kind | Conf | Note | Raw OCR. Plus an image **size slider**, **180° flip**, and gap **back-fill** (derived rows evenly distribute usage across a blind gap).

### 2. Vision-LLM oracle (GPT-4o) — the trusted verifier + closed-loop data engine
- **`vision_oracle.py`** — sends the **original full-color frame** (tower `/raw.jpg`, rotated) to **GPT-4o vision** (key in `/etc/smart-garden/cam-env`, ~$0.002/call). Color frame is essential — the processed CLAHE/gray image gives the LLM garbage.
- **Three jobs, all async (background thread so it never stalls the 5s OCR worker):**
  1. **Auto-re-anchor** — when the lock is stale OR a **verify heartbeat** fires (every 5 min, *even on high-confidence reads* — the only thing that catches self-consistent drift), GPT-4o reads the true value and re-anchors. **Downward correction allowed** (the oracle outranks a drifted lock; only floor is the operator anchor).
  2. **Low-confidence fallback** — any frame the local pipeline can't read cleanly goes to the oracle.
  3. **Trusted training labels** — every trusted oracle read is banked as a **gold** sample for a future custom model.
- **Closed-loop data engine:** high-confidence local reads are free; only hard/changing frames cost an API call, and each becomes labeled training data. Spends ~nothing on a static, cleanly-read meter (skip-unchanged: won't re-send a number it already confirmed).
- **Training-data banking + 🧠 Training Data viewer** on the Cam page: auto-labeled frames (`<reading>_<ms>.jpg` + JSON sidecar with `raw_low_match` independent-agreement flag). **Dedup:** ≤3 images per distinct number (no flooding the set with copies of the same reading). Manual **🤖 AI Re-anchor** button too.
- **Honest status:** there is **no trainable model yet** — the reader is still RapidOCR + physics rules. The oracle is collecting the gold dataset; the per-digit CNN (Tier-3) is the next build, after which the retrain loop closes.

### 3. Timing diagnosis (the "X ago" was lying)
- **Two independent delays.** *Image age* = **network**: the ESP32-CAM WiFi has **~30% packet loss + high jitter**, so uploads crawl (TCP retransmits) and frames arrive late. *Processing lag* was the **synchronous oracle** blocking the worker — fixed by making it async.
- **Timestamp fix:** the capture time was stamped when the upload *finished arriving*, not when the frame was *taken*. The server now measures the body-transfer time and subtracts it (`timestamp = now − transfer_s`) — a no-reflash approximation. Fully accurate timing would need firmware NTP + a capture-epoch header (USB reflash, not done). The real cure for all timing symptoms is the cam's WiFi (relocate / repeater / external antenna).

### 4. Flow & Leak monitor (`flow_monitor.py` — new, isolated like `water_cost.py`)
Correlates the live meter register with which zone the controller has ON to do four things:
- **Per-zone GPM, learned from real flow** — recency-weighted **EWMA (α=0.30)** of each single-zone run-segment's **median** instantaneous GPM. Latest runs count more (tracks a drip line gaining emitters over time); the median is the stable cross-check. Falls back to config `est_gpm` until measured.
- **Leak / anomaly detection** — the core signal is *flow + a zone on = sprinkler (fine); flow + NO zone on = problem.* Small sustained unexplained flow (after 120s) → **"Possible leak"**; big unexplained flow (≥2 gpm) → **urgent "Water running — no zone on!"** (burst/hose/faucet).
- **Zone overrun** — a zone ON longer than `max_runtime_min × 1.25` → **"Sprinkler running too long, may be stuck."**
- **Full raw logging** — every ~15s sample (register, Δ, interval, gpm, active zones, classification) for audit/troubleshooting.
- Alerts push to **ntfy.sh/smart-garden-james**. Tables: `flow_sample` (30d retention), `zone_flow_est`, `flow_event`. API `GET /api/flow`; UI **/flow** page (`templates/flow.html`) + "💧 Flow & Leaks" nav links. Tunables in `config["flow_monitor"]`. Background sampler started in `create_app` after the OCR worker. Verified: idle samples recording cleanly, no false anomalies; per-zone GPM fills in as zones run (nightly).

**Files touched:** `cam_ocr.py`, `dashboard.py`, `vision_oracle.py` (new), `flow_monitor.py` (new), `templates/index.html`, `templates/flow.html` (new) on the Acer (`~/smart-garden-server/`); `meter_ocr_service.py` on the tower (jackmint). **Anchor/state:** `/etc/systemd/system/smart-garden-server.service.d/meter-anchor.conf` (write via base64 to dodge PS→ssh→bash quoting; **always `daemon-reload`** after editing it).

---

## 2026-06-12 — Water Cost page (real-meter billing from the cam)

**Context:** Wanted a dollar view of actual household water cost driven by the real meter the ESP32-CAM reads — separate from the existing `billing.py`, which only estimates the irrigation slice from sprinkler run-time. Built while the cam OCR was being improved in a parallel chat, so the whole feature is deliberately isolated from cam code.

**What shipped (new `/costs` page on sprinklers.savagepace.com):**
- **`water_cost.py`** (new module) — owns its own `meter_snapshot(date PK, reading_cf, source, ts)` table. Reads the live whole-house register from `MeterReader.last_good` (÷1000 → ft³), records one snapshot/day (lazy, on page hit), and seeds the 3 real paper bills as `source='bill'` anchors so history is correct from day one. Tier math reads the 2026 rates from `config["billing"]`.
- **`templates/costs.html`** (new page) — matches the app chrome (light theme, dark-green sidebar, mobile nav). Shows: live meter (ft³/CCF/gal) + projected bill hero, current-cycle detail (usage, gal/day, tier badge, marginal $/gal), projected tier breakdown bar, a stacked bill-history chart (water/sewer/storm) with the 3 real bills + live estimate, and a daily-usage bar chart from snapshots.
- **`dashboard.py`** — added `/costs` + `/api/water-cost` routes in an **isolated block right after `/api/billing`** (far from the cam section at ~1952+). They read `meter_reader` via closure; no cam routes touched.
- **Storm rate fix:** config `storm_flat` was the stale 2025 value `28.72`; bills confirm 2026 = **`32.17`**. Fixed.

**Verified live (server venv, real DB + meter lock):** meter `94011433` → 94,011.433 ft³ = 940 CCF; cycle since 93,100 cf @ 05/27 → 911 ft³ / 6,818 gal used, 426 gal/day, tier 5; cost so far **$207.55**, projected **$293.72** (water $170.37 + sewer $91.18 + storm $32.17). History shows the 3 real bills ($167.81 / $215.95 / $380.50) + the live estimate.

**Deploy gotcha (near-miss clobber):** the server's **`config.yaml` had drifted ahead of local** — it holds **live `battery_calibration` (9 points + fitted coeffs)** and sensor dry/wet cal values written by the app. Pushing local config would have wiped all of it. Fix was applied **in place on the server** with `sed` on just the `storm_flat` line, then local was resynced *from* the server. (Same drift rule as `dashboard.py`; now noted in repo memory.) `dashboard.py` itself was in sync (0 server-only lines), re-checked immediately before push.

**Nav link (follow-up):** the page was reachable at `/costs` but had no link from the main dashboard, so it looked "missing." `index.html` is the cam page being edited in the parallel chat, so instead of overwriting it I added the **💵 Water Cost** sidebar link + **Cost** mobile-nav link with an **idempotent insert script** (`_add_costs_nav.py`, regex-anchored after the Schedule link, makes a `.bak`, no-ops if `/costs` already present). Ran it **both on the server in place AND on local `index.html`** so the link survives a sync in either direction and never collides with cam work. `index.html` templates auto-reload, so no restart was needed for the link.

**Tier insights + "Tier journey" graph (same day, later):**
- **`water_cost.py`** — added `tier_progression(used_cf, daily_cf, cycle_days, start_date, rates)`: computes the day each tier boundary was/will-be crossed assuming cumulative usage climbs linearly at the current daily rate. Tier T (T≥2) is entered when cumulative use crosses the *previous* tier's `max_cf` (e.g. T6 at 1,000 cf). Returns per-tier `{entry_cf, entry_gal, rate, rate_per_gal, crossed, day, date, within_cycle}`. `build_report` now also emits `projected_end_tier`, `num_tiers`, and a plain-language **`insight`** string (e.g. *"You're in Tier 5. At the current pace you'll hit Tier 6 ($10.97/100 ft³) in ~2 days, and the cycle should close in Tier 6."*; turns into a top-tier message when already maxed).
- **`templates/costs.html`** — new **insight banner** (amber→red gradient, red when in the top tier) + a **Tier journey** card: a Chart.js line chart with X = day of billing cycle (0→cycle_days), Y = cumulative ft³ used. Each price tier is a **shaded horizontal band** labeled with its $/100 ft³ rate (custom `tierBands` inline plugin draws the bands + a dashed green "now" vertical marker). **Solid green line** = usage so far (built from real in-cycle snapshots, bracketed by start=0 and now), **dashed orange line** = projection to cycle close. Below it: a tier-color **legend** and a **progression table** (per tier: $/gal, gallons-to-enter, day/date crossed-or-projected, status ✓in-it / projected / not-this-cycle).
- **Verified live (server venv):** Day 16/30, Tier 5, 911 ft³/6,818 gal @ 426 gal/day → **projected to cross into Tier 6 ~day 17.6 (~2 days)**, cycle closes Tier 6, projected bill **$293.72**. Progression table cross-days: T2 day3.5, T3 day7, T4 day10.5, T5 day14, T6 day17.6.
- **Historical drill-in caveat:** last month's bills only give start/end meter reads (no per-day granularity), so the Tier-journey graph can't replay June retroactively. It builds true day-by-day shape **going forward** from the daily snapshots — a full cycle from now, any month can be drilled into with real daily resolution.

**Next ideas:** add a tiny APScheduler job in `server.py` to call `water_cost.record_daily_snapshot()` once/day so history has no gaps even if nobody opens the page (held off — `server.py` overlaps the cam chat's edits); wire `should_tighten_budget`-style conservation off the *real* meter (not just irrigation estimate); push a daily/cycle cost line into the ntfy digest.

---

## 2026-06-11 — Water meter OCR: lag buffer + offload to gaming tower (jackmint)

**Context:** The original water-meter ESP32-CAM (board #1) died (see esp32-cam-journey). Flashed the replacement (board #2, static IP 192.168.0.160), then re-enabled OCR — but running it on the gaming tower (jackmint), 100% on-prem, with a buffer so no frame is lost if OCR lags.
**Architecture:**
- Cam pushes SVGA JPEG every 5s → Acer `/api/cam/upload`.
- Acer `cam_upload` drops the frame into a bounded **in-memory FIFO `deque(maxlen=100)`** — the lag buffer. Non-blocking; a full queue drops the oldest (we only want the latest reading, never a backlog). No disk, no history.
- A background `_ocr_worker` thread drains oldest-first and POSTs each frame to the **tower OCR service** (`http://192.168.0.120:5200/ocr`).
- `MeterReader.process_text(raw_text)` (new, in `cam_ocr.py`) reuses the existing extract/validate/median logic — heavy OCR is off-box, the smarts stay on the Acer.
- `/api/cam/status` now exposes `ocr{queue_depth, processed, errors, dropped, last_ms}`.
**Tower OCR (jackmint, 192.168.0.120):** `meter-ocr` systemd service (enabled), `~/meter-ocr/.venv` + `meter_ocr_service.py` (in `water-meter-cam/tower-ocr/`). Engine = **RapidOCR** (PP-OCRv4 models via ONNXRuntime, CPU). Chose it over PaddlePaddle-GPU because the GTX 970 (Maxwell) + Python 3.12 makes GPU builds painful, and CPU OCR (~600–730ms/frame) is far faster than the 5s cadence anyway. moondream (Ollama VLM) was rejected — unreliable for digit reading.
**Verified end-to-end:** tower log shows frames arriving ~5s apart, each OCR'd in ~700ms (never falls behind). Text currently empty because the cam is on the desk, not mounted over the meter — expected.
**Deploy gotcha:** the Acer's `dashboard.py` was **73 lines ahead** of the local repo — pulled the server copy down and edited against it to avoid clobbering. Service is `smart-garden-server`, dir `~/smart-garden-server/`.
**Next:** mount cam over the meter (upside-down; OCR flips 180°), confirm 9-digit Sensus reads land on the dashboard. To swap OCR engine later, change `OCR_TOWER_URL` env or upgrade the tower service.

---

## Quick Reference

### Control chain
```
Copilot → SSH Acer (192.168.0.109) → curl ESP32 (192.168.0.150) → valve actuates
```
SSH: `jamesearlpace@192.168.0.109` uses key authentication; run privileged commands with `sudo -n`.

### Common commands
```powershell
# Status
ssh jamesearlpace@192.168.0.109 "curl -s http://192.168.0.150/api/status"

# Open / close valve (id=0..9, zero-indexed)
ssh jamesearlpace@192.168.0.109 "curl -s -X POST 'http://192.168.0.150/api/valve?id=0&action=open'"
ssh jamesearlpace@192.168.0.109 "curl -s -X POST 'http://192.168.0.150/api/valve?id=0&action=close'"

# Close all
ssh jamesearlpace@192.168.0.109 "curl -s -X POST 'http://192.168.0.150/api/closeall'"

# Server dashboard
http://192.168.0.109:5125
```

### Deploy server changes
```powershell
cd C:\MyCode\smart-garden\server-prod
scp database.py dashboard.py irrigation.py server.py jamesearlpace@192.168.0.109:~/smart-garden-server/
scp templates/*.html jamesearlpace@192.168.0.109:~/smart-garden-server/templates/
ssh jamesearlpace@192.168.0.109 "sudo systemctl restart smart-garden-server.service"
```
**Local working copies:** `C:\MyCode\smart-garden\server-prod\` (mirrors `~/smart-garden-server/` on Acer).
**NOT a git repo on the server** — deploy by scp, not pull.

### Flash firmware (USB only — OTA disabled)
```powershell
cd C:\MyCode\smart-garden
pio run -e esp32 --target upload --upload-port COM5
pio device monitor --baud 115200 --port COM5
```

---

## Architecture

### Hardware
| Component | Model | Notes |
|-----------|-------|-------|
| MCU | ESP32-WROOM-32U | External antenna, MAC `00:70:07:26:48:DC` (replacement board, old `68:FE:71:0C:BA:98` fried 2026-05-27), static IP 192.168.0.150 |
| I/O Expander | Waveshare MCP23017 | I2C addr 0x27, valves 1-8 on PA0-PB7 |
| Antenna | 2.4 GHz 5dBi external | U.FL/IPEX connector on 32U |
| Solar | ECO-WORTHY 10W 12V | ~1.6 Ah/day in Duvall WA |
| Charge ctrl | Renogy Wanderer Li 10A | Battery + load output. **Brownout source.** |
| Battery | ExpertPower 12V 7Ah SLA | |
| Buck | LM2596 | 12V → 5V to ESP32 VIN. 1000µF cap on output. |
| Power gate | IRF4905 P-FET + 2N3904 NPN | GPIO 2 controls 12V to L298N boards |
| H-bridge | L298N × 5 | 2 valves per board, 10 valves total |
| Valves | Orbit 57861 DC latching | Pulse open, reverse pulse close |
| Caps | 1000µF + 100nF on 3.3V rail | Brownout protection for WiFi TX spikes |
| Server | Acer Aspire A314-23P | Linux Mint 22.1, 192.168.0.109 |

### Network
```
Ziply Fiber → Netgear GS305E → TP-Link ER605 (.1) → Eero 6
  ├─ Acer (.109, wired)
  └─ ESP32 (.150, WiFi static)
```

### Server (Acer)
- Repo deploy path: `~/smart-garden-server/` (NOT git)
- Service: `smart-garden-server.service` (systemd)
- Port: 5125
- Stack: Flask + waitress + apscheduler + SQLite (WAL)
- Logs: `journalctl -u smart-garden-server.service -f`
- Secondary collector service writes to `~/smart-garden/server/smart-garden.db` every 60s — dashboard falls back to this DB if main DB is >10 min stale (see archive: 2026-04-17)

### Alerting
**ntfy.sh/smart-garden-james** (NOT Pushover — ignore any old refs to Pushover). Title header is stripped to ASCII before send (emoji bug fix #11).

**Active monitoring (since 2026-04-22, commit `e53417a`):**
The server's `AlertMonitor` runs every poll cycle (5 min) on the Acer. It fires ntfy alerts on:
- ESP32 unreachable >15 min (`_check_offline`)
- Crash loop: >5 reboots in 1h (`_check_crash_loop`)
- Safe mode active (`_check_safe_mode`)
- Free heap <15% (`_check_memory`)
- Sensor flatline/railed >48h (`_check_sensor_faults`)
- **NVS counter delta** — `bootCount`, `wifiReconnects`, `crashCount` increase between polls (steady state on wall power = 0 delta, any change is news) (`_check_counter_deltas`)
- Chip temp >85°C (`_check_chip_temp`)

**Daily 8 AM digest** — single ntfy with 24h summary: uptime, RSSI, reconnect count, crash count, boot count delta, free heap, dashboard online %.

**Startup ping** — one ntfy 10s after server start = "pipeline alive" confirmation.

Alert cooldown: 30 min per alert key (won't spam the same alert).

---

## Critical reliability rules

### Brownout = root cause of every recent failure
The Wanderer load output sags voltage during high-current bursts. **Affects every high-current op:**
- OTA upload → bricks chip (5–10% into upload)
- `ESP.restart()` via `/api/reboot` → bricks chip
- Suspected: simultaneous valve pulses, WiFi reconnect storms

**Mitigation in firmware** (deployed 2026-05-01):
- Low-boot TX: `WIFI_BOOT_TX_DBM = WIFI_POWER_8_5dBm` during connect, bumps to `WIFI_TX_DBM = WIFI_POWER_19_5dBm` after WiFi established
- ArduinoOTA wrapped in `#ifdef ENABLE_OTA` (default OFF)
- Close-all valves only on clean boot, not crash reboots
- Deep sleep 10 min after 10 consecutive crashes (battery protection)
- Decoupling caps: 1000µF + 100nF on 3.3V rail, 1000µF on buck output

**Real fix (not yet done):** 1000µF + 100nF decoupling cap on 3.3V rail. See GitHub issue #2.
**UPDATE 2026-05-01:** Caps installed ✅. Low-boot TX strategy also deployed — ESP32U boots clean on battery-only power now.

### Verification playbook — confirm "still healthy"

**A. Quick health probe (30s)**
```powershell
ssh jamesearlpace@192.168.0.109 "curl -s --max-time 8 http://192.168.0.150/api/status" | python -c "import sys,json; d=json.load(sys.stdin); s=d['system']; h=d.get('health',{}); print(f'boot={s[\"bootCount\"]} uptime={s[\"uptimeSec\"]}s rssi={s[\"wifiRSSI\"]} reconnects={s[\"wifiReconnects\"]} crashCount={h.get(\"crashCount\")} safeMode={h.get(\"safeMode\")} temp={s.get(\"chipTempC\")}')"
```
Good: rssi -29 to -50, reconnects 0, safeMode False, uptime > 600s, chipTempC < 90.
Red flags: rssi worse than -65, reconnects climbing, safeMode True.

**chipTempC interpretation** — the ESP32 internal temp sensor is famously uncalibrated and noisy. **Real die temp at this deployment is ~77–78°C steady** (verified 2026-04-22 with 10 rapid samples + 30 soak samples: min 77.2, max 86.7, avg 77.8). Single-sample readings of 100°C+ followed seconds later by 78°C are sensor glitches, not thermal events — physics says the die can't cool 30°C in 4 minutes. Trust a *sustained* high reading, not a spike. See open issue for alert hysteresis fix.

**B. Dashboard cadence test (5 min)**
```powershell
ssh jamesearlpace@192.168.0.109 'for i in $(seq 1 10); do printf "%s " "$(date +%H:%M:%S)"; curl -s http://localhost:5125/api/dashboard | python3 -c "import sys,json; d=json.load(sys.stdin); print(\"online_flag=\"+str(d.get(\"esp32_online\")))"; sleep 30; done'
```
Expected: 10/10 `online_flag=True`. Less means TIME_WAIT or signal regression.

**C. Network probe (only if B fails)** — see archive 2026-04-21 for `tcpdump` recipe.

### The "before saying it's fixed" gate
Before any "you can box it up" / "last flash" / "OTA will work" / "ship it" claim:
1. USB physically disconnected
2. Chip on real deployed power source
3. At deployed location
4. Health probe (A) clean
5. Dashboard cadence (B) 10/10 over 5 min
6. **Then** make the claim. Not before.

This rule exists because I broke it 4 times in one session on 2026-04-21. See `/memories/mistake-ledger.md` M2 and [smart-garden#4](https://github.com/jamesearlpace/smart-garden/issues/4).

---

## Open issues

| Repo | # | Sev | Summary |
|------|---|-----|---------|
| smart-garden | [#5](https://github.com/jamesearlpace/smart-garden/issues/5) | **HIGH** | **Web server wedge** — chip RSTs SYNs on port 80 in 3-5 min cycles. ESPAsyncWebServer ruled out 2026-04-27 (5/7 fail at production cadence, identical pcap signature). **Bug is in lwIP / WiFi driver layer, NOT the application web server.** Self-recovers eventually (n=2 confirmed today). Server retry pattern catches most instances. Next candidates: ESP-IDF v5.x upgrade, `WiFi.setCountry()`, sdkconfig `lwip_max_listening` bump, or smart-plug out-of-band recovery. |
| smart-garden | [#6](https://github.com/jamesearlpace/smart-garden/issues/6) | **Med-High** | WiFi TX power varies between boots (7.8 / 14.3 / 14.8 / 14.0 dBm across 4 boots) despite `WIFI_POWER_19_5dBm` config. `setTxPower()` returns true; ESP-IDF runtime regulatory cap silently lowers actual TX. Telemetry pipeline shipped (`tx_power_raw` column + dashboard column). Hypothesis "low-TX boots cause WiFi watchdog cascades" weakened by today's wedges occurring at 14.3 dBm too. Need ~1 week of data. |
| smart-garden | [#2](https://github.com/jamesearlpace/smart-garden/issues/2) | Low | **Decoupling cap on 3.3V rail** — user buying 1000µF + 100nF caps. Fixes brownout class (M3): OTA bricks, ESP.restart() bricks, multi-valve simultaneous brownout. **Does NOT fix wedge** — confirmed today (wedges happen on USB power too, no brownout reset reason). Unlocks re-enabling OTA. |
| smart-garden | — | ~~Med~~ | ~~WiFi watchdog too aggressive~~ ✅ **SHIPPED** commit `53a91d9` (2026-04-27 07:34): threshold 60s→5min, close-all valves before `ESP.restart()`. |
| smart-garden | — | ~~Med~~ | ~~TWDT not subscribed~~ ✅ **STALE** — TWDT IS subscribed (`esp_task_wdt_add(NULL)` at `main.cpp:791`). Confirmed in serial. |
| smart-garden | [#4](https://github.com/jamesearlpace/smart-garden/issues/4) | Meta | Recurrent AI mistake: premature "ship it" claims |
| smart-garden | [#1](https://github.com/jamesearlpace/smart-garden/issues/1) | Meta | (Earlier) contradictory OTA claims |
| smart-garden | — | ~~Low~~ | ~~Wire voltage divider from battery to GPIO 36~~ ✅ **SHIPPED** commit `a01b3f5` (2026-04-27 07:50): 6:1 ratio. Wired — needs multimeter+serial verification before closing. |
| smart-garden-server | (closed) | — | Chip-temp false positives — fixed 2026-04-22. |
| smart-garden-server | (closed) | — | #10 TIME_WAIT, #11 emoji, #12 reboot wiring — closed 2026-04-21. |
| smart-garden-server | ✅ closed | — | dashboard.py bypass routes — FIXED `624b6d9` (2026-04-26). |
| smart-garden-server | ✅ closed | — | #15 banner past-time, #16 mm-as-inches, #17 forecast dark theme, #18 missing templates, #19 orphan routes, #20 dead templates, #21 forecast no sidebar, #22 mobile nav drift, #23 server clutter, #24 redundant breadcrumb, #25 sidebar footer drift — all SHIPPED 2026-06-03. See session log below. |
| smart-garden-server | ✅ closed | — | #3 same-zone double-click leaked orphan `watering_event` rows — FIXED 2026-06-04: idempotent guard in `start_zone_watering()`. Orphan event 164 backfilled. See June 4 session log. |
| smart-garden-server | ✅ closed | — | #4 `daily_summary` table had no populator (empty since inception) — FIXED 2026-06-04: `BillingCalculator.update_daily_summary()` + 23:55 scheduler job + 59-day backfill. See June 4 session log. |
| smart-garden-server | ✅ closed | — | #5 `skip_event` table empty — `log_skip_event()` defined but never called. FIXED 2026-06-04: wired into `run_cycle()`'s skip branch with per-zone per-day de-dupe via `db.skip_event_exists_today()`. First cycle produced 7 rows (648 gal / $0.36 saved). See June 4 session log. |

---

## Key decisions

1. **Latching solenoids** — Orbit 57861, hold position with no power
2. **L298N H-bridge** — Cheap polarity-reversal driver
3. **Acer as bridge** — Copilot can't reach LAN IPs directly

---

## Hardware to-do (when parts arrive)

Per archive 2026-04-14: P-channel MOSFET power gate for L298N rail + ESP32 deep sleep between watering windows. Estimated battery draw 76-148 mA → 11-18 mA (battery life 2-3 days → ~20 days).

Parts ordered: 10kΩ + 1kΩ resistors. **TO ORDER:** ~~IRF4905 P-FET, 2N3904 NPN~~. Full circuit + wiring steps in archive.

**UPDATE 2026-04-26:** MOSFET gate **installed and verified** (see Recently shipped). Battery monitoring also shipped. Deep sleep (Phase 2) deferred — user wants to observe battery behavior with gate alone first.

---

## Physical Installation Plan & Parts Inventory

**Full purchase history, fitting analysis, and shopping list** → [purchase-history.md](purchase-history.md)

**Design:** 2 valve boxes, 9 valves total, 27 Rain Bird 42SA+ rotor heads, 2 drip zones. 1in poly trunk splits to two valve box manifolds. ¾in poly laterals to each zone. ½in swing pipe risers to rotors.

**Water source:** 60 PSI, ~6 GPM at top of hill. No reducers needed for sprinkler zones. Pressure regulators on drip zones only.

**Status (2026-05-01):** ~$106 of fittings/rotors/valves still needed before install. See shopping list at bottom of purchase-history.md.

---

## Pre-flight before auto-watering kicks in

Run this checklist any time you're about to flip the engine on for a new season or after a long pause. The goal is to confirm the engine, the hardware, and the calibration story all agree before grass health depends on it.

### Tier 1 — Must do before tomorrow's first run

1. **Confirm all sprinkler zones are `auto_mode: true` on the server.**
   ```powershell
   ssh jamesearlpace@192.168.0.109 "grep -E '  (auto_mode|name):' ~/smart-garden-server/config.yaml"
   ```
   Expected: zones 0-6 = true, zones 7-9 = false (drip + spare).

2. **Check the watering window in [config.yaml](server-prod/config.yaml).**
   Currently `04:00-07:00`. With 7 zones × 24 min runtime = 168 min = 2:48 → fits in the 3-hour window with no margin. If a zone soaks longer than expected or one starts late, the window can run out and the next zone won't fire. Consider widening to `04:00-08:00` for safety.

3. **Verify the engine actually has a current soil balance for each zone.**
   ```powershell
   ssh jamesearlpace@192.168.0.109 "curl -s http://localhost:5125/api/dashboard | python3 -c 'import sys,json; d=json.load(sys.stdin); [print(z[\"name\"], z.get(\"balance_mm\"), z.get(\"mad_mm\")) for z in d.get(\"zones\",[])]'"
   ```
   If balance is `null` or stale, the engine won't decide correctly on day 1.

4. **Open the dashboard ([http://192.168.0.109:5125](http://192.168.0.109:5125)) and verify each zone's "Next watering" prediction is reasonable.**
   No prediction = engine doesn't know what to do. Wildly soon (today) on a recently-wet zone = stale balance. Far-future = balance might be inflated.

### Tier 2 — Should do within first week

5. **Catch-can calibration test** (15 min, ~$5 worth of tuna cans). This is the highest-leverage thing on the whole list. Steps:
   - Distribute 6-8 empty straight-sided cans randomly across a single zone
   - From dashboard, run that zone for exactly 15 minutes (Manual mode → Run)
   - Measure water depth in each can with a ruler (mm). Average them.
   - Real precip rate (in/hr) = average mm × 4 ÷ 25.4
   - Compare to `precip_rate_iph` in config. If real is much lower (likely 0.5-0.8 vs config's 1.0-1.5), **update config** and redeploy. The audit predicted this; confirm it.
   - Repeat per zone — different head models and pressure give different rates.

6. **Walk the lawn at sunset every 2-3 days for the first 2 weeks.**
   First stress signals: dull blue-green color, yellow tips, footprints staying visible (lack of turgor). If you see any: switch the affected zone to Manual, run a long soak, and lower its `precip_rate_iph` to force more frequent automatic cycles.

7. **Confirm the daily 8 AM ntfy digest is firing** (the same one that reports ESP32 health). It should also show last 24h irrigation events. If watering decisions aren't showing up there, the engine's not actually triggering anything — check `journalctl -u smart-garden-server.service -f`.

### Tier 3 — Optional / nice to have

8. **Set a conservative `precip_rate_iph` floor temporarily.** Until catch-can numbers are in, override config to multiply current rates by ~0.6 (e.g. 1.5 → 0.9, 1.3 → 0.8, 1.0 → 0.6). This makes the engine assume *less* water is being deposited, so it will water *more* often — safer error direction while uncalibrated.

9. **File two GitHub issues from the audit:**
   - "Calibrate `precip_rate_iph` per zone via catch-can test" — captures the calibration TODO and links results back to config.yaml
   - "Engine should size runtime to soil deficit, not run fixed cycle_run_min × cycle_count" — currently the only lever to change watering depth is `cycle_run_min`; engine should compute runtime as `(TAW - balance) / precip_rate_iph` clamped to `max_runtime_min`

10. **Set a manual rollback plan in your head.** If grass starts browning fast: flip all auto-mode zones to Manual on the dashboard, run each one for 30-45 min once, then troubleshoot config rather than letting another auto cycle make it worse.

### Quick rollback if something looks wrong tomorrow morning

```powershell
# Flip ALL zones to manual immediately
ssh jamesearlpace@192.168.0.109 "sed -i 's/auto_mode: true/auto_mode: false/g' ~/smart-garden-server/config.yaml && sudo systemctl restart smart-garden-server.service"
```

This stops the engine from making any further automatic decisions until you've diagnosed. Re-enable per-zone via the dashboard.



---



---

## 2026-06-15 � CNN closed loop LIVE: v1?v2 gated retrain, confident-wrong guard, improvement metrics

**Context:** The water-meter reader gained a real trainable model and the self-improving loop went end-to-end. Full detail in `ocr-harness/CNN-CLOSED-LOOP-PLAN.md` and repo memory `/memories/repo/water-meter-ocr.md`. Headlines:

**CNN is now the live reader (Phases 1-3, earlier today):** custom per-digit CNN on the tower (`meter-cnn` service, port 5201) reads every frame free/fast; low-confidence frames fall back to the GPT-4o oracle, which also acts as an independent verifier and banks corrections. Physics/monotonic guard sits on top of everything.

**Improvement metrics layer:** persisted `cnn_eval` + `cnn_daily` tables (`cnn_metrics.py`) so improvement is measurable across restarts and tagged by model version. Report page at `/cam/cnn-report`. Every oracle check is a free ground-truth sample of the CNN. Reading-detail page got a resizable captured-image slider.

**Confident-wrong incident + systemic guard:** the CNN read a glary frame as `094180041` at **0.95 confidence** (wrong � true `094171953`) and ratcheted the lock ~2000 counts too high, because high-conf reads skip the oracle. Re-anchored to truth (James confirmed the value). Added a hard guard: a high-conf CNN read is trusted directly ONLY if it advances the lock <=500 counts (`CNN_MAX_TRUST_ADVANCE`); a bigger forward jump forces oracle corroboration first. This is now the 4th guardrail. Lesson: a confident reader can be confidently wrong � never trust a big jump on confidence alone, and do NOT lower the confidence threshold to "use the CNN more."

**First gated retrain � v2 PROMOTED:** re-audited 650 banked frames (monotonic LNDS) ? quarantined 16 physically-impossible labels (incl the poison reads). Built an expanded verified set (614 frames / 456 distinct, +243 new oracle-verified). Trained challenger v2 and judged it against champion v1 on **60 held-out frames neither model trained on**. Result: **v1 55.0% vs v2 58.3% full-9 (+3.3 pts) -> PROMOTE.** Deployed v2 to the tower, bumped VERSION to v2, metrics now track the version transition. The loop works: collect -> verify -> audit -> gated retrain -> promote-only-if-better. Re-run `train_v2_gated.py` for v3+ as corrections accumulate; the champion baseline rises each cycle.

**Honest state:** +3.3 pts is a modest first step; live oracle-checked accuracy is ~30% (live glare is the worst case). Value today = the loop is proven and measurable, not a one-shot win. James is fine waiting as long as it is improving � and now it is, with numbers.

---

## 2026-06-19 — TP-Link CPE210 deployed as WiFi repeater for the garden (cam packet-loss fix)

**Context:** The ESP32-CAM (water-meter reader) has chronically poor WiFi — ~30% packet loss + high jitter, late/stale frames — because the garden is far from the Eero. Earlier journey entries listed *"relocate / repeater / external antenna"* as the cure. Bought a TP-Link **Pharos CPE210** (outdoor 2.4 GHz AP/CPE) to act as a wireless repeater. Full setup guide: `cpe210-repeater-setup.md`. Credentials + live status in repo memory `/memories/repo/cpe210-repeater.md`.

**Goal:** Repeater that pulls internet **from the Eero over WiFi** (no Ethernet WAN) and rebroadcasts toward the garden, so the cam (and ESP32 `.150`) get a stronger signal.

**What we did:**
- Confirmed the device on the LAN at factory IP **192.168.0.254** (MAC `b0-be-76-af-01-7c`, TP-Link OUI). Reachable from a normal browser; no laptop re-IP needed since it was already bridged onto the network.
- Logged into Pharos OS (admin / `password` — weak, flagged for later hardening).
- **Operation Mode dropdown → `Repeater`** (NOT Access Point, which was the factory default and expects wired WAN). Chose Repeater over Bridge deliberately: Repeater clones the **same SSID**, so the ESP32 devices connect with **zero reconfiguration** (Bridge would force a new SSID → ESP32 reflash, which is brownout-brick risky).
- Quick Setup → **Survey** → picked the home mesh **`TellMyWifiLoveHer`** (appears on 3 BSSIDs = the Eero nodes). Selected the strongest node (`C0-36-53-02-BA-A6`, −42 dBm) but left **Lock-to-AP OFF** — device will be moved to the garden, so it should roam by SSID and latch onto whichever node is strongest at the final spot.
- Entered WiFi password, WPA-PSK/WPA2-PSK, channel 11, kept IP at **192.168.0.254** (free on LAN, no conflict — abandoned the earlier `.250` plan to avoid "losing" the device at a new address).
- **Finished → rebooted into Repeater mode.** STATUS confirmed live uplink: **Signal −38 dBm, SNR 66 dB, CCQ 99** at the config spot (next to a node) — rock solid.

**Verified the wireless bridge:**
- Unplugged the injector's LAN cable (the config cable to the laptop). The CPE210 stayed reachable at `192.168.0.254` via ping (5–19 ms) — proving connectivity is purely over WiFi through the Eero, no Ethernet uplink needed.
- PoE wiring rule documented: **CPE210 ↔ injector cable + injector wall power must stay connected** (that's the only power source); the injector's LAN port can be empty in Repeater mode.

**Still TODO:**
- ~~Power-cycle resilience test~~ ✅ PASSED 2026-06-19 — pulled power, it rebooted and re-associated with the Eero on its own (ping recovered, no intervention).
- Mount/aim at the garden (flat front face toward the cam), recheck STATUS signal at the final spot (want **≥ −65 dBm**).
- **Power-cycle the ESP32-CAM** after the repeater is in place — ESP32s don't roam mid-session, so it needs a reboot to latch onto the now-stronger repeater.
- Re-check cam RSSI vs the **−71 dBm baseline** (captured 2026-06-19 before deploy; target ~−55 to −60). 

**Baseline before repeater:** ESP32-CAM `.150` RSSI −71 dBm, reconnects 0, boot 124.

**✅ RESOLVED 2026-06-19 — packet loss fixed, external antenna NOT needed:** Correction — the cam is `.160` (the irrigation controller is `.150`). First garden test was 15% packet loss because the cam **hadn't roamed onto the repeater** (ESP32s don't roam mid-session). After **power-cycling the cam** in the garden it latched onto the repeater. Verified healthy on both hops: repeater→Eero **−41 dBm / SNR 60 / CCQ 100** (CPE210 STATUS), cam→repeater **−49 to −52 dBm** (phone WiFiman at the cam). Cam ping reliability went **15% loss → 0% loss** (60-ping test: avg 186 ms, max 1618 ms, only 1/60 >500 ms). The residual latency jitter is the **single-radio repeater tax** (one radio time-shared between cam-side and Eero-side) — harmless at a 5 s JPEG cadence. **Net: ~30% historical packet loss → 0%.** Also investigated an external U.FL antenna on the cam (unplug test proved it was inactive — board on PCB antenna, 0Ω jumper not moved) but it's **moot** now. Full detail + reusable diagnostic method in repo memory `/memories/repo/cpe210-repeater.md`.

**Key lesson:** an ESP32-CAM will NOT move onto a new/stronger AP by itself — always power-cycle the cam after placing a repeater, and verify (phone WiFiman) the repeater is the strongest `TellMyWifiLoveHer` (BSSID `B0:BE:76`) at the cam first. Diagnose the path in two hops: cam→repeater (WiFiman at cam) and repeater→Eero (CPE210 STATUS Signal Strength).

**Follow-up — external antenna mod for burial (2026-06-19):** the cam is being **buried in the underground meter pit**, where the PCB antenna would be dead. So the external U.FL antenna became required after all (supersedes the "not needed" note above — that only applied to the above-ground test). Board confirmed = Aideepen/AI-Thinker ESP32-CAM-MB; antenna select is a `0Ω` resistor next to the U.FL connector (`/` = PCB, `\` = external). James soldered the bridge to the U.FL side. **Result was dramatic:** yard ping went from avg **186 ms / max 1618 ms** (PCB) → avg **24.8 ms / max 181 ms / min 6 ms**, still 0% loss — a 7.5× latency improvement that confirms the external antenna is now the active path. Remaining step: bury the board with the **antenna routed up out of the pit into open air**, then re-test.

---

## 2026-06-24 — Convergence verify thumbnails rotated upright

**Context:** On the Convergence page (`/cam/convergence`), the "Verify with Your Own Eyes" cards were displaying archive images upside down. The Archive page already rotated thumbnails 180 degrees, but the Convergence template did not apply the same transform.

**Changes:**
- Updated `server-prod/templates/convergence.html` CSS for `.vcard img` to include `transform: rotate(180deg)`.
- Deployed only the updated template to production (`~/smart-garden-server/templates/convergence.html`).
- Restarted `smart-garden-server` and verified service health (`active`).
- Confirmed deployed file contains the rotation rule.

**Current state:** Convergence verification images now render with the same orientation as Archive images, so manual spot-checking/fixes are readable and consistent across pages.

**Risk:** Low. UI-only display adjustment for image orientation; no model, lock, or archive write logic changed.

---

## 2026-06-24 — Convergence verify now shows before/after frame context

**Context:** Single-image verification cards made it hard to judge whether a stored value was truly correct. Without adjacent frame context, manual reviewers had to guess if a reading was plausible.

**Changes:**
- Added archive helpers in `server-prod/meter_archive.py`:
   - `previous_row(ts)`
   - `next_row(ts)`
- Updated `GET /api/cam/convergence/verify-batch` in `server-prod/dashboard.py` to include contextual neighbors for each sampled row:
   - `before` (closest prior frame metadata + image URL)
   - `after` (closest next frame metadata + image URL)
- Updated `server-prod/templates/convergence.html` verification cards to render:
   - Main frame
   - Side-by-side **Before** and **After** mini-cards with timestamp and ft³ value
   - Same 180° rotation for context images so orientation matches archive conventions

**Deployment + verification:**
- Deployed updated `dashboard.py`, `meter_archive.py`, and `templates/convergence.html`.
- Restarted `smart-garden-server`.
- Verified API payload now returns keys: `before`, `after` alongside main row fields.

**Current state:** Human verification now has immediate temporal context, making Correct/Wrong decisions much more reliable and reducing accidental bad manual anchors.

---

## 2026-06-24 — Convergence context cards now avoid duplicate neighbors and show deltas

**Context:** Even with before/after images, many cards still looked unhelpful because neighboring rows often carried the same reading (flat/inferred stretches). Reviewers still lacked decision signal.

**Changes:**
- Enhanced neighbor lookup in `server-prod/meter_archive.py`:
   - `previous_row(ts, distinct_from=...)`
   - `next_row(ts, distinct_from=...)`
   - when requested, these prefer the nearest row whose reading differs from the center reading.
- Updated `GET /api/cam/convergence/verify-batch` in `server-prod/dashboard.py` to:
   - request distinct before/after neighbors first
   - fall back to immediate neighbors only if no distinct reading exists
   - include metadata per context card: `delta_counts`, `delta_s`, `same_reading_as_ref`.
- Updated `server-prod/templates/convergence.html` context rendering to show:
   - full 9-digit reading (not only rounded ft³)
   - signed delta in counts (`Δ ±N ct`)
   - time offset from the center frame (seconds/minutes/hours)
   - explicit “same reading” note when fallback yields identical values.

**Deployment + verification:**
- Deployed updated `dashboard.py`, `meter_archive.py`, and `templates/convergence.html`.
- Restarted `smart-garden-server`.
- Verified `verify-batch` returns the new metadata and that sampled cards were no longer returning identical neighbors in the test batch.

**Current state:** Before/after cards now provide materially better signal for human review decisions, even in noisy windows.

---

## 2026-06-24 — Increased watering aggressiveness for non-grape auto zones

**Context:** Needed more water across the lawn/sprinkler zones while keeping Grapes unchanged.

**Changes (deployed):**
- Updated `server-prod/config.yaml` for zones `0-6` (all installed auto sprinkler zones):
   - `mad_pct: 60` (was default/implicit 50)
   - `max_runtime_min: 30` (was 24)
- Left Grapes (`zone 8`) unchanged (`max_runtime_min: 60`, no explicit `mad_pct` override).
- Garden (`zone 7`) remains manual (`auto_mode: false`) and was not changed.

**Operational effect:**
- Zones 0-6 now trigger watering sooner (higher MAD) and allow longer runs when they water.
- Grapes scheduling/volume behavior remains as before.

**Deployment + verification:**
- Deployed updated `config.yaml` to `~/smart-garden-server/config.yaml`.
- Restarted `smart-garden-server` (`active`).
- Verified deployed values on host:
   - Zones 0-6: `mad=60`, `max=30`
   - Zone 8 (Grapes): unchanged.

---
---

## 2026-06-30 - website zone-label and water-navigation cleanup

Context: The website was displaying mixed internal zone ids (`0-8`) and official zone numbers (`1-9`) in different places, especially around water-usage events. The water tooling was also split across Usage, Cost, and Flow pages with weak cross-navigation.

Changes:
- Added canonical API fields for displayed zone identity: `zone_number` and `zone_label`.
- Updated water-usage, dashboard activity/analytics, telemetry, and flow reports to consume `zone_label` instead of inventing zone labels locally.
- Added `server-prod/tools/check_zone_labels.py` and wired it into `deploy.ps1` so future deploys fail if obvious raw zone-id labels reappear.
- Made Water a primary mobile nav item, moved Forecast to More, added Water subnav links across Usage/Cost/Flow, and added Home-page Water Tools shortcuts.
- Hardened dashboard panel navigation so only real panel nav items call `showPanel()`, and panel changes update the URL hash.

Validation:
- Deployed through guarded `deploy.ps1`; smoke `/login` returned `200`.
- Live API checks confirmed `zone_id:4` returns `zone_number:5`, `zone_label:"Zone 5 - Southeast"` and `zone_id:0` returns `Zone 1 - Front Yard A`.
- Live page sweep returned `200` for the main dashboard, water pages, forecast, schedule, sensors, map, calibration, cam pages, and audit.
- Live API sweep returned JSON/`200` for dashboard, status, forecast, schedule, water usage, water events, OCR audit, flow, water cost, analytics, server health, audit, and cam endpoints.

State: Internal ids remain zero-based for controller/database safety. User-facing website labels now have a backend source of truth and a deploy-time regression guard.

---

## 2026-06-30 - website navigation and water-analysis stabilization pass

Context: After the zone-label fix, the website still had copied sidebars with different route sets and several water-analysis pages were easier to reach from some pages than others. The water-usage page also needed better scientific context for selected ranges.

Changes:
- Normalized the main desktop sidebars into Core / Water / Tools groups across dashboard, schedule, forecast, water-cost, sensor-history, and calibration pages.
- Added Water Usage, Water Cost, Flow & Leaks, and Forecast consistently to the Water group so those related pages are not hidden depending on entry point.
- Added the shared mobile bottom nav to the lightweight Water Usage and Flow pages.
- Fixed dashboard SPA active-state handling for the shared mobile nav classes.
- Added `/api/water-usage` coverage metadata and expanded the top water-usage summary to show total gallons, whole-window average GPM, active-bucket median GPM/GPH, and ledger/bucket coverage.

Validation:
- `python -m py_compile server-prod/dashboard.py server-prod/flow_monitor.py server-prod/tools/check_zone_labels.py`
- `python server-prod/tools/check_zone_labels.py`
- Inline JavaScript syntax check passed for changed plain-JS templates and `_mobilenav.html`.
- Offline Jinja render pass succeeded for changed templates with expected context keys.
- Deployed through `deploy.ps1`; smoke `/login` returned `200`.

State: The site now has a more consistent information architecture around the Water pages, and selected water-usage ranges expose enough rate/coverage context to reason about zone usage without treating interpolated bars as committed readings.

---

## 2026-06-30 - manual zone run duration selector

Context: The Zones/Forecast website had a Run button, but it presented the configured zone runtime and did not let the operator choose a short manual duration from the page.

Changes:
- Added a compact manual-run duration selector beside each installed zone's Run button on `/moisture-sim` / Forecast all-zones view.
- Added the same duration selector to the main dashboard Zones panel and irrigation map side panel.
- Supported durations are exactly `1, 5, 10, 15, 20, 25, 30` minutes.
- Hardened `/api/run` to reject other durations and pass the selected runtime into the irrigation engine.
- Added engine-side selected-runtime tracking plus a timer-based manual close, with the existing scheduler and safety timeout still acting as backstops.

Validation:
- `python -m py_compile server-prod/dashboard.py server-prod/irrigation.py`
- `python server-prod/tools/check_zone_labels.py`
- Inline JavaScript syntax check passed after substituting Jinja placeholders.
- Deployed `dashboard.py`, `irrigation.py`, `templates/moisture_sim.html`, and later `templates/index.html` through `deploy.ps1`; smoke `/login` returned `200`.
- Live file checks confirmed the duration selectors, allowed-minute guard, and engine `manual_runtime_min` hook are present; `smart-garden-server` is active.

State: Manual zone runs can now be started from Forecast, the main Zones panel, and the irrigation map for one of the approved durations, and selected manual runs auto-close at the chosen duration instead of waiting for the zone's configured runtime.

---

## 2026-06-30 - water-usage sprinkler-zone median report

Context: The Water Usage page needed bottom-of-page reporting for median water usage per sprinkler zone.

Changes:
- Added `zone_report` to `/api/water-usage`, grouped by installed sprinkler zones.
- The report includes selected-window run count, median gallons/run, median GPM, and total gallons, plus a 90-day baseline run count, median gallons/run, median GPM, and last run.
- Added a bottom card to `templates/water_usage.html` that renders the zone report whenever the selected range reloads.

Validation:
- `python -m py_compile server-prod/dashboard.py server-prod/irrigation.py`
- `python server-prod/tools/check_zone_labels.py`
- `node --check` on the extracted Water Usage inline JavaScript.
- Deployed `dashboard.py` and `templates/water_usage.html` through `deploy.ps1`; smoke `/login` returned `200`.
- Authenticated live API check for `/api/water-usage?minutes=60&rate_mode=actual` returned 7 sprinkler-zone report rows with selected-window and 90-day baseline medians.

State: `/water-usage` now has a bottom report showing median per-run water usage by sprinkler zone.

---

## 2026-06-30 - Cam training panel de-duplicated

Context: The dashboard Cam panel's Training Data section showed the newest 60 banked frames verbatim. During idle periods that could render dozens of identical meter labels (for example `095038.155 ft3`) and `0/60 OCR-agreed shown`, which looked like a broken page even though the bank itself was functioning.

Changes:
- `/api/cam/training` now defaults to `distinct=1`, returning the newest sample per distinct meter reading while still scanning the full bank for totals.
- Added full-bank counts: unique readings, corroborated/uncorroborated/unknown totals, source counts, and duplicate-label skip count.
- Updated the Cam panel to request distinct samples and show a clearer representative-sample summary plus per-tile corroboration/source text.

Validation:
- Python compile passed.
- Zone-label guard passed.
- `index.html` inline JavaScript syntax check passed.
- Offline Jinja render passed.
- Deployed through `deploy.ps1`; smoke `/login` returned `200`.

State: `/#cam` still opens the dashboard Cam panel, but the Training Data grid now behaves as a review surface instead of a raw newest-frame dump.

---

## 2026-06-30 - Cam panel icon mojibake cleanup

Context: The dashboard Cam page rendered with corrupted emoji/icon text in the sidebar and Cam controls, producing orphan glyphs such as variation marks in copied page text.

Changes:
- Replaced the main dashboard sidebar icons with ASCII-safe short labels.
- Replaced the shared mobile nav icons with ASCII-safe labels.
- Removed emoji/status glyphs from the Cam panel header, buttons, image alt text, and live-view dynamic status strings.

Validation:
- `index.html` and `_mobilenav.html` inline JavaScript syntax checks passed.
- Offline Jinja render confirmed the updated Cam strings and sidebar labels.
- Deployed through `deploy.ps1`; smoke `/login` returned `200`.

State: `/#cam` should no longer show broken icon glyphs in the nav or Cam controls. Other deeper dashboard sections still contain old emoji text, but the visible Cam path and navigation shell are cleaned.

---

## 2026-07-01 - full website data/UI audit pass

Context: Deep audit request for every page and the data quality behind the public sprinkler site, with specific suspicion around the Cam page and Water Usage over-time data.

Changes:
- Fixed `/api/schedule-7day` so zero-minute weather-scaled runs are not emitted or treated as soil refills. Manual/off drip zones remain out of the auto schedule.
- Added canonical `meter_ledger.latest_committed_reading()` and `meter_ledger.usage_for_window()` helpers.
- Updated the Cam APIs and dashboard Cam panel to show the accepted ledger meter reading separately from stale raw OCR lower-bound rows.
- Updated Water Usage zone medians to use physical meter ledger gallons when the run window is covered and plausible, with explicit fallback counts for configured estimates.
- Added the missing `cam_device.html` template so `/cam-device` no longer 500s and now shows cam upload/WiFi/OCR/archive telemetry.

Validation:
- `python -m py_compile server-prod/dashboard.py server-prod/meter_ledger.py server-prod/irrigation.py server-prod/flow_monitor.py`
- `python server-prod/tools/check_zone_labels.py`
- Inline JS syntax checks passed for `index.html`, `water_usage.html`, and `cam_device.html`.
- Deployed through `deploy.ps1` in three guarded steps; smoke `/login` returned `200` each time.
- Live checks: schedule has no zero-minute rows and no manual drip schedule rows; `/api/water-usage/audit?minutes=60` verdict `accurate`, source `meter_ledger`; `/api/cam/readings` returns accepted ledger reading `95045.723 ft3` separately from stale raw OCR `095029589`; crawled primary pages and cam tool pages all returned `200`, with `/forecast-vs-actual` redirecting successfully to `/forecast`.

State: The main site pages are serving, the worst misleading numbers are corrected or explicitly labeled, and Cam/Water Usage now separate accepted data from stale/raw evidence.

---

## 2026-07-01 - Water Usage bug audit and trust boundary

Context: Follow-up audit asked whether Water Usage data was bug-free. Live event-window checks found two real bugs.

Findings:
- Event windows before the stabilized meter-ledger cutoff could show huge impossible usage totals from old OCR/re-anchor history, while the audit still said `accurate` because chart total matched the same high-water math.
- Exact event windows could undercount the first boundary interval because `/api/water-usage` started from the first ledger row inside the selected window and ignored the immediately prior row.

Changes:
- Added a Water Usage trust boundary at `2026-06-25T22:00:00`.
- `/api/water-usage/events` now excludes untrusted pre-cutoff events by default and returns the trust cutoff metadata.
- `/api/water-usage` and `/api/water-usage/audit` return `trust` metadata and mark pre-cutoff windows as review/untrusted.
- Added `meter_ledger.reading_before()` and seeded Water Usage chart/audit calculations with the close prior ledger row without plotting an out-of-window point.
- Added UI warnings so pre-cutoff custom windows are not visually presented as trustworthy precise totals.

Validation:
- `python -m py_compile server-prod/dashboard.py server-prod/meter_ledger.py`
- `python server-prod/tools/check_zone_labels.py`
- Inline JS syntax check passed for `water_usage.html`.
- Deployed through `deploy.ps1`; smoke `/login` returned `200` with backups `.bak.20260701-065423`.
- Bad 2026-06-24 windows now return `trust.trusted=false` and audit verdict `review`.
- Event quick-select default returned no untrusted events; oldest returned event was `2026-06-27T07:57:35`.
- Boundary cases now match the ledger helper: Grapes `22.31 gal`, Zone 4 `7.65 gal`, Zone 6 `37.83 gal`.
- Rolling windows 5/15/60/180/720/1440/4320 min reconcile total vs line vs summed bars; first 20 trusted recent event windows all audited `accurate`.

State: Trusted Water Usage windows now reconcile end-to-end. Pre-cutoff custom history remains visible for investigation but is explicitly marked review/untrusted.

---

## 2026-06-30 - Cam stale readings collapsed at API layer

Context: The Cam readings table still showed long runs of repeated stale lower-bound rows such as `>=095029589`. The first UI collapse compared the full note text, but the note includes a changing stale-age counter, so rows like `stale 245256s` and `stale 245250s` did not group reliably. Browser caching could also keep older JS alive.

Changes:
- Updated the Cam table collapse rule to ignore the changing stale-age note.
- Added the same stale-run collapse inside `MeterReader.get_readings()`, so `/api/cam/readings` returns one newest representative row with `_collapsed`, `_collapsed_oldest_ts`, and `_collapsed_oldest_captured` metadata for repeated stale lower-bound runs.
- Kept raw readings in memory unchanged; this is only the display/API view returned by `get_readings()`.

Validation:
- `python -m py_compile server-prod/cam_ocr.py`
- Direct harness confirmed three stale rows with the same lower-bound reading but different stale-age notes collapse to one returned row with `_collapsed: 3`.
- Deployed only `cam_ocr.py` through `deploy.ps1`; smoke `/login` returned `200`.

State: Repeated stale Cam rows should now collapse even if the browser is running older table-rendering JavaScript. Authenticated JSON could not be checked through `Invoke-WebRequest` because the public API path served the login page without a session.

---

## 2026-07-02 - meter archive retention and OCR root-cause fix

Context: User found a recent meter image missing and current meter OCR wrong. Requirement clarified: archive every cam frame possible at ~5s cadence for 12 months, and fix OCR root cause without hardcoded meter values.

Findings:
- Live archive was configured for idle `METER_ARCHIVE_INTERVAL=60` seconds, flow `5` seconds, and a 30 GiB FIFO cap. It had 23,919 images/1.2 GiB from 2026-06-23 onward, not 5-second all-day retention.
- Current disk has ~302 GiB free; current average JPEG is ~48 KiB. A 365-day, 5-second archive needs ~284 GiB. With a 50 GiB safety reserve, safe archive capacity is ~253 GiB, so this disk cannot safely guarantee 12 months at 5-second cadence without more storage or a smaller frame size.
- OCR drift was circular trust: constrained CNN and hinted oracle/archive reads could use a bad lock as context, then mark bad values as trusted/reviewed. The oracle prompt was too strong ("almost certainly within a few counts"), and a no-hint oracle can also garble high digits while seeing the low digits correctly.

Changes:
- Changed archive defaults to 5-second target, 365-day target retention, 280 GiB cap, and 50 GiB free-space guard. `/api/cam/status` now reports retention feasibility/forecast.
- Added constrained-CNN raw-tail conflict detection: conflicting constrained values are not admitted to the median window and force oracle review.
- Softened the oracle prompt so prior readings are advisory and the image wins.
- Added physical splice/bounds guards to live oracle re-anchor, manual oracle re-anchor, and archive reread so high-digit garbles like `895...` cannot be applied directly.
- Re-anchored the live meter to `095074.203` using the latest image's oracle-read low digits spliced onto the stable physical prefix; fixed the transient impossible maintenance row and recomputed ledger deltas/daily rollups.
- Cleared the stale truth guard after correction.

Validation:
- `python -m py_compile server-prod/dashboard.py server-prod/vision_oracle.py`
- `git diff --check -- server-prod/dashboard.py server-prod/vision_oracle.py`
- Backed up live `meter_archive.db`, `meter_ledger.db`, and `/tmp/meter_state.json` under `~/smart-garden-server/backups/*.pre-ocr-retention-20260702-064213`.
- Deployed `dashboard.py` and `vision_oracle.py`; `smart-garden-server` restarted active.
- DB check: latest archive/ledger rows show `095074.203`; no `committed > 200000000` or `abs(delta_cf) > 1000` rows remain.
- Archive forecast: 23,947 files, 1.08 GiB, avg ~48,308 bytes, 365d@5s estimate ~283.76 GiB, safe capacity ~252.75 GiB, feasible=false with current safety reserve.

State: Live meter display is corrected and future OCR paths have non-circular trust guards. Archive now targets 5-second capture, but full 12-month retention is not safely feasible on the current disk with the 50 GiB reserve.

---

## 2026-07-02 - Water Usage zone median GPM split

Context: User wanted the most accurate median GPM, not a bucket-size-dependent chart rate.

Changes:
- Confirmed the top Water Usage median is bucket-derived and expected to change with chart grain.
- Changed the bottom sprinkler-zone report so primary median GPM uses only clean single-zone physical meter runs.
- Stopped mixing configured estimates into the primary median.
- Added separate estimate/reference GPM columns for uncovered or overlapping runs.
- Updated UI copy to say physical zone medians do not use chart grain.

Validation:
- `python -m py_compile server-prod/dashboard.py`
- Extracted `water_usage.html` inline scripts and ran `node --check`.
- `git diff --check -- server-prod/dashboard.py server-prod/templates/water_usage.html`
- Deployed `dashboard.py` and `templates/water_usage.html`; `smart-garden-server` restarted active.

State: The most accurate median GPM is now the physical-meter median per completed clean run. Estimate GPM remains visible separately as a fallback/reference.

Follow-up:
- Added the same clean physical run median to the top Water Usage summary as `Physical Run Median GPM`.
- It uses selected-window clean physical runs when present, otherwise falls back to the 90-day clean baseline and shows the run count/scope.
- Validated with `python -m py_compile server-prod/dashboard.py`, extracted inline JS `node --check`, deployed, and restarted service active.

Follow-up audit:
- Rechecked high GPM examples and found the previous "clean physical" baseline still admitted pre-`2026-06-25T22:00:00` OCR/re-anchor history plus short boundary runs.
- Tightened clean-run eligibility: run must start after the trusted cutoff, be single-zone/non-overlap, at least 120 seconds, have >=2 ledger samples, positive meter gallons, and not exceed the existing plausible configured-gallons ceiling.
- UI excluded count now includes pre-cutoff, short, thin, overlapping, and implausible runs.
- Validated with `python -m py_compile server-prod/dashboard.py`, extracted inline JS `node --check`, `git diff --check`, deployed, and restarted service active.

Second follow-up audit:
- Audited the 2026-07-02 07:26:59 to 07:36:14 Zone 5 window. The 29.87 gal total and 3.55 GPM run math were internally consistent with high-water ledger usage, but the committed meter went backward twice during the run, with a largest drop of 5.949 ft3 / 44.5 gal.
- Changed `meter_ledger.usage_for_window()` to return backward-step metadata and changed clean physical zone medians to exclude any run window with backward committed-meter steps.
- Live API verification for the exact window now reports `health.backward_steps=2`, Zone 5 selected `physical_runs=0`, `backward_runs=1`, and estimate-only selected GPM until the meter reads are reviewed/corrected.
- Validated with `python -m py_compile server-prod/dashboard.py server-prod/meter_ledger.py`, extracted inline JS `node --check`, `git diff --check`, deployed `dashboard.py`, `meter_ledger.py`, and `templates/water_usage.html`, restarted `smart-garden-server`, and smoke-tested `/login` 200.

Display cleanup:
- The top `Physical Run Median GPM` card had been falling back to the all-sprinkler 90-day clean baseline when the selected Zone 5 run was excluded, while the bottom table correctly showed Zone 5's own baseline. Updated the top card to scope to the single selected zone when exactly one sprinkler zone has a selected run.
- For the 2026-07-02 Zone 5 window, the top card should now describe `Zone 5 - Southeast 90d clean baseline` instead of an all-zone baseline.
- Added a separate `Selected Run Median GPM` card for the exact event chosen from the Watering event dropdown. It computes the median from the plotted bucket GPM values whose bucket centers fall inside the event's real start/end, so it answers "what was the median GPM for this selected run" without mixing in the padded chart window or the historical baseline.
- Added compact per-zone clean GPM history to the bottom zone report: API returns up to the last 30 clean physical run points per zone; UI shows a tiny sparkline plus median/range/latest stats. This keeps leak/blockage baseline review on the same Water Usage page instead of a separate report.
- Fixed selected-run median blank state: the page no longer depends on dropdown load state to compute the top card. `/api/water-usage` now returns `selected_run_stats` when the window contains exactly one watering event, and the UI uses that first. Verified live for `2026-06-24T20:41:29` Zone 7: selected-run median `3.39 GPM`, 8 one-minute buckets, with the existing pre-trust/backward-step warning still shown.
- Replaced selected-run median source with bucket-independent raw ledger segment math. `meter_ledger.run_rate_stats()` computes GPM between consecutive committed meter readings inside the actual event, trims 30s startup/shutdown for longer runs, excludes backward steps and >25 GPM spikes, then reports the median plus quality counts. Verified live Zone 5 runs: `2026-07-02T08:08:07` -> `3.50 GPM` from 38 segments, and `2026-07-02T07:27:29` -> `3.50 GPM` from 50 segments.
- Aligned bottom zone report with the same official raw-segment GPM method. Backward meter steps are now warning counts, not whole-run exclusions, because the official median already ignores bad negative segments. Verified live Zone 5: selected-window official median `3.50 GPM`; history now includes 4 official measured runs (`3.59`, `3.50`, `3.50`, `3.50`) with overall official median `3.50 GPM`.
- Expanded the bottom official GPM report from sprinkler-only to all installed water zones, including drip zones. Renamed section to `Zone water usage medians`. Live check includes Zone 8 Garden with 5 official history points and median `0.58 GPM`; Zone 9 Grapes is present with no clean official history yet and estimate `0.5 GPM`.
- Adjusted report filtering after user clarified Grapes also feeds ~300 ft of tree drippers, so configured `0.5 GPM` was too low for plausibility. High meter total vs configured estimate is now a warning count, not an automatic exclusion, because the official raw-segment median should establish the real baseline. Live Grapes now shows 3 official measured history points (`4.41`, `4.31`, `4.31`) with median `4.31 GPM`; estimate column still shows old `0.5 GPM` for reference.

Retention follow-up:
- User clarified the priority is preserving raw historical data so future bugs/calculation changes can be reprocessed from raw rows rather than only aggregates.
- Disabled DB pruning by default: `database.prune_old_data()` returns unless `SMART_GARDEN_ENABLE_DB_PRUNE=1`, `prune_cam_telemetry()` returns unless `SMART_GARDEN_ENABLE_CAM_TELEMETRY_PRUNE=1`, and flow samples are no longer deleted unless `SMART_GARDEN_ENABLE_FLOW_PRUNE=1`.
- Deployed `database.py`, `flow_monitor.py`, `server.py`, and `dashboard.py`; service restarted active and `/login` returned 200.
- Live row ranges after deploy: raw sensor/weather/system rows date back to 2026-04-01, watering events to 2026-05-24, flow samples/events to 2026-06-12, meter ledger to 2026-06-12, archive-frame metadata/images to 2026-06-23. Image files remain storage-limited by archive cap/free-space guard, unlike DB rows.

All-valves max-flow test:
- Added a Zones page control to open every installed valve together for 5, 10, 15, 20, 25, or 30 minutes.
- The aggregate test is recorded as a virtual `All Valves` watering event (`zone_id=-100`, `trigger_reason=manual_all`) so Water Usage can keep max-flow history like a zone.
- Individual member valve events use `manual_all_member` and are hidden from Water Usage event pickers and per-zone median history so the max-flow test does not pollute normal zone baselines.
- The Water Usage zone report now includes an `All Valves` row using the same raw meter-segment official median GPM method as the normal zone history.
- Bugfix after live click returned `Could not start`: `IrrigationEngine.self.zones` is a dict keyed by zone id, not a list of zone dicts. Changed `start_all_valves_watering()` to iterate `self.zones.items()` when selecting installed zones, deployed `irrigation.py`, compiled on server, restarted service active, and smoke-tested `/login` 200.

Zone head-count update:
- User clarified current physical sprinkler counts after removing some heads/valves: Zone 1=4, Zone 2=4, Zone 3=3, Zone 4=3, Zone 5=4, Zone 6=3, Zone 7=4.
- `server-prod/config.yaml` already matched all except Zones 3 and 4; updated their `heads` fields from `4` to `3`.
- Deployed live `config.yaml`, verified parsed counts `[(1,4),(2,4),(3,3),(4,3),(5,4),(6,3),(7,4)]`, restarted service active, and smoke-tested `/login` 200.

UI consistency audit:
- Added shared `server-prod/static/site.css` and included it across rendered pages so cards, buttons, forms, table hover states, focus rings, tool nav, mobile spacing, and border radii have a common baseline.
- Rebuilt `_mobilenav.html` with clean stable text badges, consistent active states, and safer null checks. Added the mobile nav to pages that were missing it, including camera tools and the standalone map.
- Rebuilt `_meternav.html` with clean text badges instead of fragile emoji glyphs, consistent active state, horizontal scrolling, and guarded `scrollIntoView`.
- Aligned the standalone `/map` zone controls with the main Zones page by adding the manual duration selector before `Run`; fixed mobile `/map` from a squeezed side-by-side layout to stacked map-over-zones.
- Validation: Python compile passed, Jinja parse passed on the server with temp templates, inline script `node --check` passed, live templates backed up to `~/smart-garden-server/templates.bak.ui-20260702`, deployed templates/static CSS, restarted service active, `/login` 200, `/static/site.css` 200.
- Browser verification used authenticated Playwright against live pages at desktop and mobile widths for `/`, `/water-usage`, `/flow`, `/costs`, `/moisture-sim`, `/map`, `/cam`, and `/cam/archive`; all returned 200 with no login redirects. Mobile `/map` was corrected after screenshot review and rechecked.
- Follow-up after user clarified the issue was the high-level navigation shell: added shared `_appsidebar.html`, replaced duplicated sidebars in Home/Schedule/Forecast/Cost/Sensor History, and put Water Usage + Flow into the same desktop app frame with shared sidebar CSS. Verified live screenshots/metrics for `/`, `/moisture-sim`, `/water-usage`, and `/flow`: all have the same 220px fixed sidebar and correct active nav item.

---

## 2026-07-03 - Cost page monthly cycle split

Context: `/costs` showed June and July usage together. July needed to start its own billing month/cycle instead of continuing from the last paper-bill anchor.

Changes:
- Fixed `water_cost.py` so the open cost cycle uses `config.billing.cycle_start_day` instead of permanently anchoring to the latest real bill close-read.
- Current cycle now starts `2026-07-01` and closes `2026-08-01`; June is emitted as a separate estimated completed cycle (`2026-06-01` to `2026-07-01`).
- Added cycle-start meter lookup from canonical `meter_ledger` with snapshot/interpolation fallback, so future months roll forward without needing a manual bill anchor first.
- Changed sparse daily meter snapshots to interpolate missing days between real readings instead of assigning a multi-day jump to one fake spike day.

Validation:
- `python -m py_compile server-prod/water_cost.py server-prod/dashboard.py`
- Extracted `costs.html` inline script and ran `node --check`.
- Candidate `water_cost.py` executed against live DB before deploy: cycle window `2026-07-01` -> `2026-08-01`, history tail includes separate `Jun 2026 (est)` and `Jul 2026 (est)`.
- Deployed only `water_cost.py`, compiled on Acer, restarted `smart-garden-server`, `/login` returned 200, and live module verification matched the candidate output.

State: Cost page should show July as its own current month. During deploy verification a manual Zone 6 run appeared; sent authenticated `/api/closeall`, all valves reported closed, and event 625 finalized at 52 seconds.

---

## 2026-07-04 - Water Usage stale-lock RCA and warning fix

Context: `/water-usage` was not picking up the 2026-07-04 early-morning manual watering correctly. The page initially showed the meter flat at `095119.577 ft3` through Zone 2 and Zone 1 manual runs even though the latest meter image read about `095131.151 ft3`.

Root cause:
- The CNN was reading the current `095131.xxx` frame as `095031.xxx`, dropping the `1` in the high digits.
- The physics guard correctly refused the bad raw CNN value, but the oracle path was exhausted/rate-limited, so the live lock stayed stale during watering.
- `/api/water-usage/audit` only compared chart total to the same stale ledger source, so it could call the window accurate while physically missing active watering.

Changes:
- Wrote RCA doc `RCA-water-usage-stale-lock-2026-07-04.md`.
- Manually re-anchored the live meter lock to `095131151`.
- Added stale-lock detection to `/api/water-usage` and `/api/water-usage/audit`: overlapping watering events with material estimated gallons but little/no measured meter movement now flag `health.stale_lock=true` and force audit verdict `review`.
- Updated `/water-usage` to show a visible stale/incomplete meter warning instead of a clean health line.

Validation:
- `python -m py_compile server-prod/dashboard.py`
- Extracted inline JS from `water_usage.html` and ran `node --check`.
- Deployed `dashboard.py` and `templates/water_usage.html` via `deploy.ps1`; `/login` returned 200.
- Live `/api/cam/status` shows accepted meter `095131.151 ft3` and truth guard cleared.
- Live `/api/water-usage?minutes=120&bucket_s=60` reports `total_gal=86.58` with `health.stale_lock=true`.
- Live `/api/water-usage/audit?minutes=120` returns `verdict:"review"` and fails the new `Active watering is visible in the meter ledger` check.

Backfill follow-up:
- User correctly pointed out that fixing the live lock was not enough; the old data also had to be repaired.
- Added `server-prod/tools/repair_20260704_stale_lock.py` and used it on the live host with the service stopped and backups first.
- Backup stamps: `20260704-stalelock-repair-055757` and cleanup backup `20260704-stalelock-repair-cleanup-060058`.
- Repaired the contaminated interval from `2026-07-04T04:13:39` through `2026-07-04T05:56:00`.
- Held idle rows flat at `095119.577 ft3` until watering began, then interpolated the real movement to `095133.040 ft3` across the three known watering events by estimated-gallon weight.
- Updated `meter_ledger.db`, `meter_archive.db`, and affected `smart-garden.db.flow_sample` rows; raw OCR/oracle readings were preserved, and committed repaired rows were marked `interpolated`, `inferred`, `reviewed=1`, `origin='repair:20260704_stale_lock'`.
- Recomputed ledger deltas and `usage_daily` for `2026-07-04`.
- Cleanup fixed the remaining negative deltas caused by the false `04:13:39` archive climb and the stray high `05:28:05` oracle frame.

Backfill validation:
- `python -m py_compile server-prod/tools/repair_20260704_stale_lock.py`
- Live service restarted active and `/login` returned `200`.
- Ledger now has zero negative deltas from `2026-07-04T03:30:00` through `2026-07-04T05:56:00`.
- `usage_daily` for `2026-07-04` recomputed to `100.71 gal`, `95119.577 -> 95133.040 ft3`, with `849` image-backed readings.
- Exact event-window audits now return `verdict=accurate`: Zone 2 `50.58 gal`, Zone 1 `33.90 gal`, Zone 3 `16.23 gal`.

State: The site no longer silently reports a stale-lock window as accurate, and the known stale-lock historical rows have been repaired. Remaining durable fix: automate recovery when oracle budget/rate limits block authority reads and CNN drops the `09513x` high digit.

Accuracy spot-check follow-up:
- User noticed clicked meter photos can appear slightly different from the Water Usage graph reading.
- Found two separate issues:
  - UX wording was wrong: a clicked bucket shows an endpoint meter value, while photos inside that bucket may be earlier in the minute as the meter is moving.
  - `meter_archive.db` had newer propagated rows around `2026-07-04T06:35` than `meter_ledger.db`, so Water Usage still had artificial register-down corrections until archive-to-ledger sync ran.
- Stopped the live service, backed up DBs under `20260704-ledger-archive-sync-063839`, ran `meter_ledger.sync()`, restarted active, then found the sync re-exposed two stale-lock repair rows.
- Stopped the service again, backed up under `20260704-post-sync-stalelock-cleanup-063935`, reran `tools/repair_20260704_stale_lock.py --apply`, restarted active.
- Added canonical archive overlay to `/api/water-usage/frames` so the photo modal prioritizes the committed archive/ledger reading and shows the raw CNN value only as supporting evidence.
- Changed the modal copy to say photos inside a bucket can be slightly before the endpoint, and to fix a frame only when its own caption disagrees with the visible meter.

Accuracy validation:
- `python -m py_compile server-prod/dashboard.py server-prod/tools/repair_20260704_stale_lock.py`
- Water Usage inline JavaScript `node --check`
- `git diff --check`
- Deployed `dashboard.py` and `templates/water_usage.html`; `/login` returned `200`.
- Live ledger now has zero negative deltas from `2026-07-04T03:30:00` through `2026-07-04T06:40:00`.
- Live 120-minute Water Usage audit returns `verdict=accurate`, `chart_total_gal=154.87`, `reanchor_count=0`, and no stale-lock event.
- `/api/water-usage/frames` now returns committed `reading` plus raw CNN `guess`; spot check at `06:35` shows raw CNN still misreads high digits (`09503x.xxx`) while committed oracle/propagated values are `095139.xxx`.

State: Water Usage totals are based on the canonical committed meter ledger, not the raw CNN guess. The raw CNN remains visibly unreliable on current `09513x/09514x` frames, so durable follow-up is still to improve guarded recovery/training for that high-digit failure mode.

Live Zone 5 bug log:
- User started Zone 5 and reported Water Usage still showed wrong numbers; clicking the validated meter lock line showed images with different numbers than the graph.
- Logged `BUG-water-usage-ledger-archive-sync-2026-07-04.md`.
- Reproduced live: `meter_archive.db.archive_frame` had smooth propagated/oracle values for the current Zone 5 run, while `meter_ledger.db.meter_reading` stayed flat at `095140.280` until a jump to `095142.724`.
- Root cause: `meter_ledger.record_reading()` used `INSERT OR IGNORE`, so late archive propagation could not update an existing stale live row with the same timestamp until a separate sync ran.
- Fixed `meter_ledger.record_reading()` to upsert archive-derived committed values into existing live/stale rows, insert a `meter_correction`, and clear `delta_cf` for recompute.
- Added `_sync_water_usage_ledger()` and call it before `/api/water-usage`, `/api/water-usage/audit`, `/api/water-usage/ocr-audit`, and `/api/water-usage/frames`.
- Deployed `dashboard.py` and `meter_ledger.py`; deploy smoke `/login` returned `200`.
- Validation: Python compile passed, `git diff --check` passed, temp-DB regression proved stale live row update works, live recent archive/ledger mismatch count is `0`, live recent negative deltas are `0`.
- Verified Zone 5 run `2026-07-04T06:43:42 -> 06:51:09`: audit for `06:43:30 -> 06:51:30` returned `accurate`, `22.91 gal`, `reanchor_count=0`; meter line now climbs smoothly `095142.000 -> 095144.904 ft3`.

Raw CNN follow-up:
- Investigated whether the meter reader used to be more accurate. Answer: yes, `loc2-v7` was validated on 2026-06-30 at `6094/6194 = 98.386%` authoritative exact, with the accepted `min_conf >= 0.95` band exact. Current 2026-07-04 live oracle-graded samples are `0/18` for `loc2-v7`.
- Logged `BUG-meter-cnn-high-digit-regression-2026-07-04.md`.
- Root cause is most likely leading-edge drift: the meter advanced into `09509x/09513x/09515x`, and raw CNN now collapses high/middle digits back toward `09503x` while often preserving some low digits. Example: current frame `20260704-071155.jpg` raw CNN `095030982` vs committed/oracle `095150906`.
- Checked the physical frame: camera framing is still usable, but LCD contrast/glare is weak around the high/middle digits. This looks like model/data generalization, not a lost camera or reverted crop.
- Tested constrained CNN on 40 recent oracle rows. It is informative but not safe as truth: about half the values were close, but many were ~1000 counts off, so low-confidence constrained output must not be promoted.
- Found and fixed a latent live config bug: an older systemd drop-in left archive CNN acceptance at `0.70`, while `loc2-v7` was calibrated only at `0.95`. Updated `dashboard.py` defaults and `deploy.ps1`, deployed `dashboard.py`, and verified live env has `METER_ARCHIVE_STALE_CNN_MIN_CONF`, `METER_ARCHIVE_EXACT_CNN_MIN_CONF`, `METER_ARCHIVE_REPROCESS_CNN_MIN_CONF`, and `METER_CONSTRAINED_MIN_CONF` all set to `0.95`. `/login` returned `200`.
- User approved visual labeling. Added 14 explicit no-oracle `codex_visual_label` rows from enlarged LCD crops, then exported the broader verified current window from `2026-07-04T05:45:00` (160 more current manual-label rows).
- Fixed retrainer synthetic rows so they use the newest trusted high-order prefixes instead of stale hardcoded `094...` examples.
- Forced gated tower retrains. The small visual-only run did not promote. The larger current-label run promoted `loc2-v8`: gate `0.546 > 0.517`, ground-truth replay full-9 `0.822` vs `0.808`, hard-frame eval fixed 6 and broke 0.
- Post-promotion eval: high/middle digits are fixed on the current oracle window (`positions 0-5 = 199/199`), but final rolling digits remain weak and no sample reaches the direct `0.95` accept band. Fresh live raw reads are now close/in-range (`095162721` vs committed `095162726`) but still `raw_conf=low`, so the canonical ledger remains the right source for Water Usage.

## 2026-07-06 — Meter ledger FROZE 2 days; reconstructed history from camera by eye (no oracle $)

**Context:** User reported the meter camera "not working right" and is out of LLM/oracle budget. Diagnosed: camera hardware fine (355 frames/hr), but `meter_ledger.meter_reading.committed` **froze at `095163972` (95163.972 ft³) from 2026-07-04 17:32** — 100% `propagated`, 0 fresh reads for ~37h. Raw CNN `loc2-v8` = 0/1252 exact on the current `09521x` edge (leading-edge drift again); oracle budget exhausted, so nothing could re-anchor. Split-brain confirmed: OCR lock `/tmp/meter_state.json`=`95138820`, ledger committed=`95163972`, glass≈`95219836` — all disagreed. `flow_sample.reading_cf` also frozen (derived from same lock); `watering_event.est_cf` unreliable (75 cf vs 56 cf glass; July 5 had 0 logged runs).

**Reconstruction (free, human eye instead of oracle):** Built `_sample_meter.py` (kept on acer) — samples archive frames across a window, rotates 180°, crops+enlarges the LCD strip, montages with timestamps. Read a monotonic anchor series directly off the glass: `07-04 17:32=95163972 → 19:09=95167250 → 23:24=95174158 (pre-midnight) → flat all July 5 → 95174453 → 07-06 05:25=95194666 → 06:43=95219836` (stable). Both midnights land on flat segments, so daily splits are exact.

**Repair (`_repair_freeze.py`, dry-run then --apply, DBs backed up to `~/meter-freeze-backup-20260706/`):**
- `meter_reading`: 4747 rows linearly interpolated between verified anchors (monotonic), `method='interpolated'`, `origin='repair:freeze-2026-07-04'`; 4747 `meter_correction` rows logged.
- `archive_frame`: 4747 rows corrected.
- `recompute_daily(start='2026-07-04')` (high-water-mark). **usage_daily fixed: Jul 4 332.1→408.3 gal, Jul 5 0.0→2.2 gal, Jul 6 0.0→339.5 gal.**
- Reanchored `/tmp/meter_state.json`→`95219836`, restarted `smart-garden-server`. New rows now `method=held @ 95219836` (no re-freeze). `/login` path resumed.

**Durable-fix progress:** Banked 10 verified current-range (`09517x–09521x`) gold labels to `manual_labels.jsonl` (`source=codex_visual_label_freeze_repair`). **Still needed:** the CNN remains 0% on the current edge and the lock WILL re-freeze at the next watering until retrained. Per the July 4 experience (~14 labels insufficient, ~160 worked), generate ~100+ current labels (fast via `_sample_meter.py` montages) then run a gated tower retrain. This repair was bailing water; the retrain is the leak fix.

## 2026-07-08 - Historical meter cleanup + current re-anchor

Context: James wanted missing/stale historical meter data fixed and wanted the gaming tower to carry as much OCR/training work as possible because OpenAI budget is limited.

Changes:
- Closed stale Zone 6 state with `/api/closeall`; all valves reported closed.
- Capped paid oracle use to local-first settings: `$10/month`, `40/day`, no daily minimum, sparse intervals; kept all direct-CNN commit gates at `0.95`.
- Fixed tower retrain operations: `meter-cnn-retrain.timer` now checks every ~2h and `meter-cnn-retrain.service` is guarded with `flock`; no duplicate trainer pile-ups.
- Full archive-to-ledger sync removed archive/ledger drift (`mismatches=0`).
- Reapplied the July 4-6 freeze repair and then applied a post-cutoff physics repair: committed readings after `2026-06-25T22:00:00` are monotonic and capped to a conservative `25 GPM`; raw OCR evidence was preserved.
- Found the live/current lock had frozen at `095219836`; one authority read on latest frame returned `095376901` high confidence. Repaired the July 6-8 flatline by distributing `1174.93 gal` across the logged July 8 watering events, then manually reanchored the live reader to `095376901`.

Validation:
- `smart-garden-server` active; `/login` 200; active zones `[]`.
- Archive/ledger mismatches `0`; post-cutoff negative deltas `0`; post-cutoff impossible jumps above the repair cap `0`.
- `/water-usage` backing API for `2026-07-08T00:00:00` to `10:20:00`: `1174.93 gal`, trusted, monotonic, no stale-lock warning.
- Backups live under `~/meter-history-backups/` with stamps from the repair run. Details are in `meter-data-layer-journey.md` and `meter-cnn-journey.md`.

State: Post-cutoff committed/chart history is physically plausible and internally consistent. Some rows still carry inferred/propagated provenance because the image was unreadable or below the accepted OCR confidence band; that uncertainty is preserved instead of pretending every frame was directly OCR-read.

Follow-up documentation:
- The initial July 8 current-anchor repair was improved after James questioned the excluded/repaired data. Blind authority reads from archived JPEGs found the July 7/July 8 boundary was `095266.471`, not stale lock `095219.836`.
- Repaired July 6-8 history from real archived-photo anchors. New daily totals: Jul 6 `298.78 gal`, Jul 7 `348.85 gal` unattributed, Jul 8 `826.07 gal`.
- Added conservative GPM provenance filtering so repaired/inferred rows do not pollute clean zone medians.
- Added Water Usage event overlays so zone executions are visible directly on the charts.
- Full handoff: `WATER-USAGE-REPAIR-SESSION-2026-07-08.md`. Event visibility RCA: `RCA-water-usage-event-visibility-2026-07-08.md`.

---

## 2026-07-10 - Moisture schedule page review

Context: James asked to continue reviewing `/moisture-sim`; screenshot showed the single-zone banner reporting `Fri Jul 10 at 1:20 AM` as the next expected watering even though it was already after 7 AM.

Changes:
- Fixed `/api/schedule-7day` so `next_water` only records slots whose scheduled start is still in the future. The all-zones grid still shows today's earlier slots, but marks them as `past` or `started` so they do not look like future runs.
- Updated `/moisture-sim` all-zones view to render past/started schedule cells muted.
- Clarified the summary and mode pills: automatic sprinkler dryness and automatic drip dryness are counted separately, and drip rows now show `Manual drip` vs `Auto drip` from live config instead of generic `Drip`.

Validation:
- `python -m py_compile server-prod/dashboard.py`
- `git diff --check -- server-prod/dashboard.py server-prod/templates/moisture_sim.html`
- Deployed only `dashboard.py` and `templates/moisture_sim.html` with timestamped server backups, restarted `smart-garden-server`, and `/login` returned `200`.
- Live `/api/schedule-7day` at `2026-07-10T07:15` returned past flags for `00:00` through `06:40`; `next_water` moved early zones to `Mon Jul 13` while keeping future `08:00` and `09:20` slots for today.
- Playwright visual QA at `526x600` and `1280x900` loaded `/moisture-sim` with no console errors; screenshots saved as `_moisture_narrow_after.png` and `_moisture_desktop_after.png`.

State: The page no longer presents already-started watering slots as "next expected" runs. Open product question: repo notes still say Grapes should be manual drip, but live config has Grapes `auto_mode: true`; this pass did not change config or watering behavior.

Follow-up after live-engine reconciliation:
- Found the grid was still an ideal simulation during a real delayed/restarted run: Zone 5 was physically active at `07:19` while the grid treated its original slot as elapsed.
- `/api/schedule-7day` now reconciles today's row with real `watering_event` history and `active_zones`: completed runs render as actual/past, the active run renders as running, zones past the engine's 50%-runtime already-watered guard are removed from today's future plan, and remaining starts are deferred behind the active run.
- Enforced the engine's watering-window semantics in the forecast. A run may finish after the `10:00` window if it started inside it, but no later zone is promised a start after `10:00`; overflow remains dry for reconsideration in the next allowed window.
- Live verification after restart matched the event log: Zones 1-4 were completed, Zone 5 was the next/restarted run, South was forecast inside today's window, and Southwest/Grapes moved to Saturday instead of the invalid `10:07`/`11:27` starts.
- Recompiled, ran `git diff --check`, backed up and deployed `dashboard.py`, mirrored it to `C:\MyCode\smart-garden-server-live`, restarted the service, and verified `/api/schedule-7day` and `/login` returned `200`.

Accuracy RCA follow-up:
- James questioned the underlying promise of the automation: if MAD is the moisture floor, why does the page show nearly every turf zone below MAD even after scheduled watering?
- Found two independent forecast math errors. The all-zones client predictor divided ET/rain/irrigation depth by physical root depth instead of the engine's plant-available-water bucket (`root_depth * 0.15 AWC`), understating percentage movement by about 6.7x. The authoritative server schedule did the opposite kind of damage: after every predicted run it set balance directly to TAW/100%, regardless of runtime and `precip_rate_iph`.
- Corrected both predictors to use the engine's actual checkbook units. Server schedule refills now use `runtime / 60 * precip_rate_iph * 25.4`; client ET/rain/refill percentages now divide by the TAW-equivalent bucket. Client rain skip now matches the engine's `5.0 mm` threshold instead of `0.25 mm`.
- Removed the reconciler's false `balance = TAW` assignment for zones that passed the same-day runtime guard; the live balance row already contains completed irrigation credit.
- Added projected post-run percentage to schedule cells and a visible capacity warning/status explanation (`full run +N%` versus `today ET -N%`). This exposes the current physical/control shortfall instead of implying that an 80-minute slot guarantees recovery.
- Current live math at ET0 `5.32 mm`, turf Kc `0.95`, 6-inch roots, AWC `0.15`, and precipitation rate `0.11 in/hr`: daily ET consumes about `22%` of the bucket while an 80-minute run restores about `16%` (roughly `-6%/day`). Seven zones would need about `108 min/day` each merely to match today's ET, exceeding the current 10-hour serial window.
- Files were backed up, copied to the Acer and live mirror, and syntax/diff checks passed. Because Zone 5 was actively watering, deployment restart was deliberately scheduled for `2026-07-10 10:25` via `smart-garden-moisture-accuracy-restart.timer` rather than fragmenting another live watering event.

Live follow-through (same session):
- James explicitly said future deployments do not need to avoid interrupting active watering. Cancelled the delayed restart timer and restarted immediately; retain this preference for future work.
- Fixed automatic same-day runtime accounting. The old engine stopped further attempts after an arbitrary 50% of `max_runtime_min`, yet a restart below that threshold launched a fresh full cycle. It now computes the weather-adjusted daily target, skips only when the full target is complete, and resumes only the remaining minutes after interruptions. Live proof: Southeast had about 40 minutes accumulated and resumed for `40 min`, matching both the engine log and `/api/schedule-7day`.
- Corrected forecast event order: morning watering is credited before that day's daylight ET. Today's balance subtracts only ET remaining after `now`; it no longer double-counts a full day already partly present in the live balance. Projected post-run cells changed from the impossible `8%` result to coherent values such as Southeast `24%`, South `38%`, and Southwest `45%`.
- Renamed the page to `Modeled Soil Water Balance`, explicitly states it is not a direct sensor reading, renamed columns to `Model balance` and `Trigger floor`, and converted the zone table into readable mobile cards.
- Capacity messages now show each full-run gain, today's forecast ET loss, and the approximate runtime needed merely to replace today's ET. Live summary: `7` turf zones under-capacity, up to `5%` modeled net loss/day, about `102 min/zone` needed today versus `80` configured.
- Removed unnecessary direct Open-Meteo archive/forecast calls from the all-zones operational view; it now uses the server-cached forecast already returned with moisture data. Added response-status checking plus one retry for server JSON requests. Three consecutive browser loads then returned 9 zone rows, the capacity warning, and no HTTP/console failures.
- Final checks: Python compile, inline-JS parse, `git diff --check`, `/login` `200`, service active, authenticated schedule API `200`, narrow `526x600` and desktop `1280x900` Playwright renders with no layout overflow.

State: The page is now honest about the model and its capacity shortfall. The remaining product/control decision is physical: raising the configured daily runtime/window enough to maintain MAD would materially increase water use; do not silently make that consumption change without James choosing the intended recovery/maintenance policy.

Single-zone accuracy audit:
- Removed the live chart's remaining independent watering assumptions: hardcoded `04:00-07:00`, seasonal root depth, and the false claim that a run refills to 100%. Forecast bars and moisture credit now come from the exact `/api/schedule-7day` cell start/runtime and use the latest engine TAW.
- Forced the single-zone banner's final writer to be the authoritative server schedule and the header badge's final writer to be the latest `soil_balance` row. This fixed the observed Zone 1 disagreement (`~4 AM` vs server midnight; chart-derived `36.1%` vs DB `26.4%`).
- Forecast days now carry the latest authoritative MAD/TAW forward instead of reverting from turf MAD `60%` to a hardcoded `50%`.
- Historical event timing is preserved, but daily chart irrigation credits are normalized to that day's authoritative `soil_balance.irrigation_mm`. This accounts for historical precipitation-rate config changes that are not stored per watering event and eliminated 25 chart-engine drift warnings on Zone 1.
- Cross-zone browser audit passed with zero warnings/errors: Front Yard A `26.4%` / MAD `60%` / next midnight; Southeast `15.9%` / MAD `60%` / next `05:20`; Garden `85.9%` with Manual-mode banner; Grapes `35.0%` / MAD `50%` / next `09:20`. Every badge exactly matched the latest API balance.

## 2026-07-10 - Demand-based recovery policy (MAD 50%)

Context: James confirmed turf MAD can be 50% but the automation must water enough to meet it. The corrected page proved the old fixed 80-minute policy lost about 5% modeled balance per day under current ET.

Changes:
- Turf zones 0-6 now use `mad_pct: 50`, a `120 min` daily recovery safety cap, and a `00:00-14:00` morning/start window. Config was edited textually with timestamped backups so YAML comments were preserved.
- Engine trigger is preemptive: it waters when the current balance minus remaining forecast ET would reach/breach MAD, instead of waiting for the next midnight after the floor is already crossed.
- Runtime is demand-based. It computes water needed to reach the larger of the configured wet target (75% for most turf, 72% for enclosed backyard) or `MAD + remaining ET`, converts the deficit through the real precipitation rate, and caps only severe recovery runs at 120 minutes.
- Interrupted/completed runtime reduces only the daily safety cap. Completed irrigation is already in the balance and is not subtracted twice from the newly calculated deficit.
- Sync-group triggering now uses the same projected-after-remaining-ET condition.
- `/api/schedule-7day` mirrors this exact policy, includes the engine's five-minute decision cadence between serial zones, and shifts Grapes to its restored `20:00-22:00` evening eligibility (`evening_zones: [8]`) when turf fills the daytime window.
- Recalculated current balances through `POST /api/balance/update`, immediately updating stored/displayed turf MAD from 60% to 50%.
- UI now states recovery behavior explicitly and uses authoritative `days_away` for status labels (`Scheduled today` vs stale client-derived `Soon`).

Verification:
- Live engine first decision matched the schedule: Front Yard A resumed for `19 min` toward its new demand target, not a fixed 120-minute run.
- Seven-day post-run projections rise rather than decline: Front Yard A reaches `68%`; Southeast `39 -> 44 -> 52 -> 58 -> 62%`; South `45 -> 50 -> 58 -> 68%`; Southwest `52 -> 57 -> 64 -> 75%`. Enclosed zones settle around their configured 72% target.
- Schedule includes five-minute serial gaps and Grapes at `20:00`; all turf starts remain inside the 14:00 start window.
- Live all-zones summary shows 50% MAD and recovery mode (`up to 120 min/day toward 75%`). Desktop browser QA returned no warnings/errors; service active, `/login` 200, and no server errors/tracebacks after deployment.

State: Demand-based recovery is live. The 120-minute cap limits severely dry-zone recovery over several days; after recovery, calculated runtimes shrink to the amount needed to preserve the 50% floor rather than blindly running the cap.

Target refinement after Zone 2 review:
- James clarified the desired behavior is to stay only slightly above MAD, not refill healthy zones to 72-75% retained balance.
- Replaced the legacy wet-target control objective with `MAD + remaining forecast ET + 2% of TAW`. The morning post-run percentage may still be around 69-75% on high-ET days because that water is budgeted for same-day evapotranspiration; the end-of-day target is approximately 52%.
- Schedule cells now display both values explicitly: `post-run` and `EOD`, preventing a necessary morning ET reserve from looking like retained overwatering.
- Live Zone 2 steady-state audit: EOD projections `52.0%, 53.7%, 52.0%, 51.9%, 52.1%, 52.1%`. Enclosed zones similarly settle around 52% EOD. Dry recovery zones remain capped at 120 minutes and climb gradually until they can meet the 52% EOD target.
- Browser QA showed the recovery explanation and post-run/EOD values with no warnings or errors; service active and `/login` 200.

Chart-floor correction after cross-zone review:
- James correctly identified that the single-zone chart still appeared to bottom near 70% even though the control schedule targeted about 52% EOD. The scheduler was correct; the display was not.
- Fixed DST-unsafe day arithmetic, today-to-tomorrow carry-forward, and live-day projection anchoring. Future points now start from the latest authoritative DB balance and include only remaining ET plus active/pending scheduled water.
- Reconciled each projected day's final chart value to `/api/schedule-7day.end_of_day_pct`; the 15-minute curve remains illustrative, while its daily endpoint can no longer drift from the control engine.
- Live browser spot-check across zones 1, 2, 4, 5, and 6 found no console errors. Healthy zones settle at roughly 52% EOD; recovering zones follow the schedule exactly and climb gradually (for example zone 6: 33.0, 40.4, 46.3, 47.5, 48.4, 51.0, 52.0%).

State: The apparent Zone 2 70% floor was a chart bug, not the watering target. Live chart and schedule endpoints now agree; 50% is the trigger floor and approximately 52% is the intentional safety-margin target.

## 2026-07-10 - Observe-only zone field notes

Context: After several weeks of operation, James wants timestamped visual assessments that can later support MAD/model calibration, but must not affect watering yet. The older Forecast-page `Looks dry` action is unsuitable because it immediately applies a decaying control bias and retains no immutable observation history.

Changes:
- Added append-only `zone_observation` records with observed and recorded timestamps, zone, objective condition, independent watering judgment, optional visible indicators, and notes.
- Added validated read/write `/api/zone-observations`; no irrigation/model code reads this table.
- Added a responsive Field observation form and recent-observation log to Schedule. Objective condition and personal management judgment are deliberately separate.

Verification: Temporary-DB round trip passed without touching `zone_feedback`; live DB backed up before migration; Python/JS/diff checks passed; desktop and mobile browser QA found all 9 zones, 6 condition choices, 6 judgment choices, 11 optional indicators, correct local timestamp, no overflow, and zero stored test records.

State: Live and data-collection-only. Future calibration should analyze repeated observations against modeled balance, recent ET/rain/irrigation, and season before changing MAD or runtimes.

Shadow calibration prototype:
- Added read-only `tools/prototype_zone_calibration.py`; it joins field observations to water balance, prior 72h watering, and physical meter-camera volume. It never writes config/DB or controls valves.
- Guardrails require at least 3 stable-policy days, observations on 3 distinct days, and 2 observations in a 24-72h response window before a zone can become a review candidate. Same-time notes across zones count as one survey context, not repeated evidence.
- Diagnosis order is delivery/flow and distribution, then ET/Kc and root-zone bucket, with MAD last. Meter gallons alone do not establish application depth without independent area or catch-can data.
- First live run correctly held every zone: James's Jul 10 survey occurred during/immediately after newly increased recovery watering. The model records it as baseline and recommends repeat observations over the next 1-3 days, with no control changes.

Independent verification (2026-07-10, Copilot quadruple-check):
- Safety confirmed: grep of the tool found zero write/control ops (no INSERT/UPDATE/DELETE/commit/write/valve/systemctl/HTTP). The only DB helper it calls, `meter_ledger.usage_for_window()`, is SELECT-only and closes its connection in a finally. No file in `server-prod/**/*.py` imports the tool — it is standalone and cannot affect the control loop even accidentally.
- Deploy parity confirmed: SHA256 of the server copy == local copy (`2e1a9bc2…4905f0`). Reviewed code == running code.
- Correction to the summary above: there are FOUR blockers, not three. The fourth — `area_sqft` required — is a permanent structural gate. Live `config.yaml` has ZERO `area_sqft` entries, so NO zone can ever reach `review_candidate` until zone areas are added, regardless of how many observations are logged.

Known limitations / future risks (why this could stall or frustrate):
1. Stability clock vs. active tuning — `days_since_control_change` is derived from `config.yaml` file mtime. Any config edit resets the 72h clock. While actively remediating brown grass (frequent precip/runtime/MAD edits), the "3 stable-policy days" gate may never be satisfied. Fixing grass and collecting calibration data are in direct tension.
2. Permanent area gate — no `area_sqft` in config → every zone HOLDs forever. Feeding observations produces nothing actionable until areas are measured. High risk the tool gets abandoned as "homework nobody grades."
3. Observation-window friction — needs obs in a 24-72h post-watering window on 3 distinct days; same-time surveys count once. Real-life ad-hoc yard walks cluster and miss the window, so valid observations get rejected on a technicality.
4. Whole-house meter contamination — per-zone gallons come from watering_event windows, but household water during a window inflates the meter/configured ratio → spurious `configured_flow` hypotheses, especially on early-morning zones.
5. Subjective input — "somewhat dry" conflates dormancy, fungus, dog urine, shade, heat stress with actual dryness. Tool may nudge toward watering fixes for non-water causes; only a catch-can audit disambiguates.
6. No back half — there is no defined path from `review_candidate` → decision → config change → verification. Without it, accumulated shadow data has nowhere to go.
7. Bit-rot — standalone script nothing calls on a schedule; depends on DB + config schema. Already failed on the local DB (missing `zone_observation` table). Silent breakage risk when schemas change.

De-risk plan (do #1 and #2 before logging much more data; rest can wait until candidates appear):
- [x] #1 DONE (2026-07-10) — stability clock decoupled from `config.yaml` mtime. Now derived from a SHA256 fingerprint of watering-relevant settings only (per-zone precip_rate_iph, max_runtime_min, mad_pct, dry_trigger, wet_target, est_gpm, heads, kc, cycle params, plus watering/weather_adjustment/schedule blocks). Anchored in a tool-owned `calibration_state.json` next to config. Unrelated edits (camera, oracle budget, battery cal) no longer reset the 72h window; only watering-param changes do. First live fingerprint `2b18e78a1b25988e`, anchored 2026-07-10T11:20:08.
- [ ] #2 Measure the 9 zone areas once (rough Google-Earth polygons are fine) and add `area_sqft` to config so it stops being a permanent gate. James chose: Copilot estimates from his lot — BLOCKED pending address/lot to measure independently (won't fabricate areas that feed calibration).
- [x] #3 DONE (2026-07-10) — back half defined and wired. James chose "just alert me". When a zone reaches `review_candidate`, `record_review_candidates()` appends a line to tool-owned `calibration-alerts.log` (ts, zone, name, hypotheses). No config/control change; James reviews and decides. Won't fire until #2 + the day/window gates clear.
- [x] #4 DONE (2026-07-10) — weekly cron installed (`crontab`: Mon 06:15) via `tools/install_calibration_cron.sh`; appends full report to `calibration-weekly.log`. Bit-rot canary: schema drift will show as an error in that log instead of silent death. State/log files gitignored (local + server).
- [ ] #5 (later) Flag meter/configured ratios as low-confidence when non-zero household baseline flow overlaps the watering window.
- Near-term action unchanged: log another survey tomorrow and again 48-72h after watering; do NOT tune watering from today's appearance.

Safety re-verified after #1/#3/#4 (2026-07-10): tool still writes only its own bookkeeping files (`calibration_state.json`, `calibration-alerts.log`, `calibration-weekly.log`); grep confirms no INSERT/UPDATE/DELETE/commit against the control DB, no config writes, no valve/HTTP control. Live run after deploy left `config.yaml` unmodified. Deployed tool committed to git (was previously untracked).

Adversarial hardening supersedes the initial #1/#3/#4 implementation (2026-07-10):
- Removed the inferred `calibration_state.json` stability clock. New near-real-time observations atomically capture immutable model/weather/watering context plus a semantic policy fingerprint. The fingerprint covers actual engine config inputs and the `irrigation.py` algorithm hash; equivalent numeric YAML values normalize. Legacy/backdated notes remain baseline-only and cannot unlock review.
- Report construction is pure and opens snapshot databases SQLite `mode=ro`. Evidence is partitioned by exact policy fingerprint, must cover 3 days/72h, requires 2 non-uncertain material 24-72h responses, and must show directionally coherent condition + management judgment.
- Added explicit stages: `collecting`, `enough_data`, `anomaly_detected`, `diagnosis_supported`. Only the last becomes `review_candidate`; independent area provenance plus catch-can rate/uniformity are required. Area alone does nothing.
- Whole-house meter evidence uses only isolated >=10-minute runs with clean meter segments and is advisory; it cannot support a delivery diagnosis because household co-flow remains unattributed.
- Alert-state emission is explicit and transition-deduplicated; normal/JSON reports have no alert side effect.
- Replaced append-only cron/log files with `smart-garden-calibration-shadow.timer` (Monday 06:15 Pacific). The oneshot takes SQLite-consistent private snapshots, runs read-only against them, and logs through bounded journald. Legacy cron entry removed.
- Added six adversarial tests: policy coverage/normalization/code hash, missing DB no-create, pure report, area-alone gate, coherent physical-evidence candidate, conflicting observations hold, and alert deduplication. Local temporary and live suites pass.

State: Live shadow report is `collecting / HOLD` for every observed turf zone; existing observations predate immutable context capture. `config.yaml` and irrigation behavior were unchanged. Future observations begin the valid evidence series.

## 2026-07-10 - Forecast accuracy display denominator corrected

Context: The Forecast vs Actual page reported 265/270 correct because its display summary treated manual-mode snapshots and days without a completed engine decision as correct predictions.

Changes: Forecast comparison rows now expose `scored`; the display summary, zone filter, and timeline include only completed automatic-engine decisions. Manual-mode and `no_event` rows remain in API history as `scored:false` for auditability.

Verification: Commit `cf9dd8f` compiled and deployed with a server backup. The authenticated live 30-day API reports 241 scored decisions, 236 correct, and 97.9% accuracy; manual-mode and `no_event` rows are unscored. Server/local hashes match for `database.py` and `templates/forecast_merged.html`, and `/login` returns 200.

State: All actionable HIGH and MEDIUM UX audit findings are fixed. The intermittent moisture-sim 502 remains open because logs and first-party endpoints are clean and the failing browser resource cannot be identified without Network/console evidence. No watering-behavior code or configuration was changed for this fix.

## 2026-07-10 - Triaged website high/medium fixes

Context: Worked the existing `UX-AUDIT.md` queue without browser access, using live authenticated APIs, service logs, source inspection, and server/local diffs. Scope was display/usability only.

Changes:
- Fixed single-zone chart drift: `/api/moisture-data` returns all-zone events, so the chart now filters irrigation credits by selected `zone_id` before reconciling to authoritative daily balance.
- Fixed Water Usage orphan-cleanup rows that stored zero duration/volume: the display API derives elapsed time from immutable timestamps and a configured-volume estimate, without changing DB records.
- Corrected Water Usage Back navigation and added an explicit main-load/leak-banner error state.
- Gave Recent Activity's View All control a real history target. Confirmed the Moisture banner's final writer is `/api/schedule-7day`, whose live same-day entries were all future-facing.

Validation: Python compile, inline JavaScript parse, diff checks, guarded backups/deploys, `/login` smoke tests, authenticated API checks, and post-deploy SHA256 parity passed. The intermittent browser-observed 502 remains open because service logs and all first-party endpoints were clean and no browser Network/console runtime was available to identify the third-party resource.

State: Every actionable high/medium audit item is fixed; the unidentifiable intermittent 502 is explicitly skipped/open. No irrigation engine, valve, MAD, runtime, precipitation, schedule-generation, or watering-parameter code was changed.

## 2026-07-10 - Codex given its own browser + an outer-loop orchestrator

Context: The UX audit worked (Copilot supplied browser "eyes" -> UX-AUDIT.md -> Codex fixed 7 high/med, deployed). But it ran short: Codex CLI has NO browser, so it couldn't self-generate the visual backlog, and the bounded prompt told it to stop. Goal: let Codex SEE the site itself and run for hours, maximizing the Codex subscription.

Changes:
- **Codex browser via Playwright MCP.** `codex mcp add playwright -- cmd /c npx -y @playwright/mcp@latest --headless --isolated --storage-state <path>`. `--isolated` is REQUIRED or `--storage-state` is ignored (lands on Login). Chromium installed via `npx playwright install chromium`. Verified: Codex loads the authenticated Dashboard itself.
- **Auth.** Site is Google-OAuth gated (no LAN bypass; dashboard.py check_auth). Minted a valid 30-day `session` cookie (`email|ts|HMAC(SESSION_SECRET)`) with `server-prod/tools/mint_session_state.py` (runs on server, reads SESSION_SECRET from the service /proc environ). Stored as a Playwright storage-state at `.mcp-auth/storage-state.json` (GITIGNORED - it's a real login credential; expires ~2026-08-09). Validated via curl (200 with cookie, 302 without).
- **Outer-loop orchestrator** in `orchestrator/`: `run-codex-loop.ps1` calls `codex exec` repeatedly (FRESH session each iteration = no compaction rot), each iteration re-reads UX-AUDIT.md, audits+fixes a bounded chunk via its own browser, and returns a JSON verdict (`--output-schema verdict-schema.json`). Loop stops on `work_remaining=false` or MaxIterations/MaxMinutes caps. Per-iteration verdicts + `loop-log.md` are gitignored. Full docs: `orchestrator/README.md`.

Decisions:
- Fresh `codex exec` per iteration (not `resume`) specifically to dodge the 83M-token compaction rot seen in the long interactive session.
- Success is measured by INDEPENDENT verification, not Codex's self-report: verdicts valid, `git log` commits match claimed fixes, one sampled fix confirmed live, `git diff` touches zero watering-logic (else abort), honest done-signal. (Guards against the false-done mistake-ledger pattern.)

State: Wiring proven end-to-end (Codex drove the browser, returned a title). Orchestrator built + parse-validated + dry-run OK. Repo memory: `smart-garden-codex-browser.md`. Next: 3-iteration proving run, verify against the success checklist, then scale the cap for a long unattended run.

## 2026-07-10 - Serial UX fixer: forecast accuracy scoring

Context: Forecast-vs-actual scored manual-zone snapshots and uneventful days as correct predictions, inflating the displayed 30-day accuracy to 98.1% across 270 rows.

Changes: Added an explicit `scored` reporting flag, limited the denominator to completed automatic decisions, excluded currently manual zones from the API comparison, and hid unscored rows from the timeline and zone filter. Commits: `cf9dd8f`, `4962309`.

Decisions: Historical rows remain in the database; this changes reporting only. No forecast generation, schedule, irrigation, runtime, MAD, precipitation, valve, or watering configuration behavior changed.

State: Deployed and live-verified. The API reports 236 scored automatic decisions, no no-event row is scored, the manual Garden zone is absent, compilation and `/login` smoke pass, and server/local hashes match. The intermittent moisture-page 502 remains open as a broader dependency RCA: 12 instrumented reloads captured no failures and every first-party/API/jsDelivr request returned 200.

Next: Capture the exact failing URL if the intermittent 502 recurs; do not change first-party display code without that evidence.

## 2026-07-10 - Serial UX round: map and sensor-history accessibility

Context: Parallel auditors submitted nine unique high/medium display findings: three for the mobile zone map and six for Sensor History. No watering-behavior finding was submitted.

Changes: Sensor History now has a named chart with synchronized textual statistics, responsive chart containment, programmatic selection state, a skip link/main landmark, polite refresh status, and visible calibration advice (`d4aba93`). The Map now switches to shared mobile navigation, provides 44px run controls, and exposes persistent numbered, keyboard-navigable markers (`3d3b7ec`).

Decisions: Templates only; no Python backend, irrigation balance, schedule, valve, runtime, MAD, precipitation, or watering configuration code changed.

State: Both templates were backed up before deployment, deployed, and verified live against their read-only APIs. At 390px Sensor History has no horizontal overflow and matches calibration advice; at 320px Map has no horizontal overflow, uses mobile navigation, and its Run targets are 44px. The intermittent Moisture Simulation 502 remains the sole open high/medium item because repeated instrumentation still has not captured a failing resource URL.

Next: Capture the exact resource URL and response evidence if the intermittent Moisture Simulation failure recurs.

## 2026-07-10 - Chart dependency outage captured and removed

Context: A parallel auditor finally captured the intermittent Moisture Simulation failure: all four jsDelivr chart dependencies reset together while the first-party page and moisture API remained healthy.

Changes: Pinned and self-hosted Chart.js 4.4.1, the date-fns adapter, Hammer, zoom, and datalabels for every affected chart page. Moisture Simulation now exposes an accessible chart-unavailable recovery message if its chart runtime cannot initialize. Commits: `44bfd33`, `a889fe3`.

Verification: Each deployment used timestamped server backups and pre/post SHA256 parity. Live Playwright loaded all four Moisture Simulation assets from `/static/vendor` with 200 responses, made no jsDelivr request, initialized Chart, kept the fallback hidden, and reported no console error. `/login` remained 200 and the service active.

State: The prior intermittent 502/connection-reset RCA is closed as a shared external-dependency failure. Sixteen newly merged high/medium display findings remain queued; no watering/control code or Python backend file changed.

## 2026-07-10 - Serial UX fixer: costs, forecast comparison, flow, convergence

Context: Merged 20 parallel-auditor findings and fixed the actionable high/medium display defects without touching watering behavior, schedule generation, balances, configuration, or Python backend code.

Changes: Costs now contains its bill table at 390px, names its charts, exposes daily values, announces loading/errors, and has an accessible More sheet. Forecast vs Actual now validates payloads, recomputes summary values from displayed scored rows, bounds requests, distinguishes empty states, and keeps 401/errors recoverable in the current tab. Flow suppresses stale orphan alerts when fresh idle samples supersede them, neutralizes retained alerts on refresh failure, and Water Usage labels configured-rate estimates explicitly. Convergence escapes API text, restricts archive image URLs, and removes timestamp interpolation from inline handlers.

Decisions: The focused Forecast performance audit superseded the earlier latency report because 10 desktop reloads and the throttled-mobile run were fast. Two broader medium campaigns remain: page-by-page camera renderer hardening and staged site-wide CSP/security headers.

State: Commits `4d1b9b9`, `a6ed348`, `05c4ce4`, and `10ca8de` deployed with timestamped remote backups. `/login` returned 200; local/server SHA-256 parity passed for all six deployed templates. Live Costs at 390px had no document overflow and all three canvases had accessible names; Forecast comparison rendered 236 validated predictions at 97.9%; Flow showed no active anomaly instead of the stale orphan alert. No backend `.py` file was edited.

Next: Run dedicated camera-page injection regression and CSP/header rollout campaigns; low-only polish remains in `UX-AUDIT.md`.

## 2026-07-10 - Serial UX fixer: camera, audit, and response hardening

Context: Six parallel auditor files supplied 32 raw display/usability/security findings across camera tools, DB Audit, and shared response policy.

Changes: Corrected T-separated 24-hour reporting and expanded Audit to all 25 tables with disabled/error/mobile semantics (`8e9fc40`); added browser security headers and fail-closed session-secret startup (`8e9fc40`); hardened camera label/archive/review rendering (`d359536`); added success-gated loading/error/schema states to Regression and Quality (`6b3629f`); added test-audit/CNN report alternatives, landmarks, names, reflow, semantics, and contrast (`aab11c3`); and disabled Focus actions until a fresh frame succeeds while keeping mobile More closable (`eebf053`).

Decisions: CSP remains Report-Only because strict enforcement requires a site-wide inline-code extraction campaign. Intermittent simultaneous static/API 502s remain an infrastructure RCA item; display controls now fail safe. `dashboard.py` changes are reporting/auth-response-only and do not touch balance, schedule, runtime, precipitation, valve, or irrigation decisions.

State: Five guarded deployments used timestamped remote backups, service restarts, `/login` smoke checks, and post-deploy SHA256 parity. Authenticated Playwright verified mobile Audit/CNN reflow, camera error states, 27 meaningful test-frame alternatives, named actions, and Focus failure gating. Curl verified 25 audited tables, 57 true last-24h watering rows, and live security headers. Two medium broader campaigns remain open: strict CSP migration and intermittent tunnel/service 502 RCA.

Next: Director should schedule the CSP extraction campaign and only open the infrastructure RCA when the simultaneous CSS/API 502 can be recaptured with proxy/service telemetry.

## 2026-07-10 - Serial UX fixer: Calibration accessibility and recovery

Context: The new parallel round identified missing keyboard focus, labels, contextual control names, destructive-action protection, chart/status alternatives, mobile reflow, contrast, and API-failure recovery on `/calibrate`.

Changes: Commit `9af367d` adds visible focus, sensor/reading-specific accessible names, confirmation for deleting a saved battery point, live status semantics, a named battery chart, darker secondary text, shrinkable mobile navigation, semantic sensor headings, and explicit Retry/error states that keep Live Mode disabled until calibration data loads.

Decisions: `dashboard.py` was edited only because Calibration is an embedded HTML response in that file. The change is display/usability-only: no irrigation balance, schedule generation, runtime, precipitation, MAD, configuration, or valve decision code changed.

State: Deployed after a timestamped remote backup. Python compilation and authenticated curl checks for all three Calibration APIs passed; `/login` returned 200; server/local SHA-256 matched. Live browser verification found zero unlabeled inputs or repeated accessible button names, four sensor headings, two live regions, a named canvas, visible focus CSS, and no 390px overflow.

Next: The remaining high/medium backlog is the broader strict-CSP migration, Camera Archive performance work, authentication-boundary semantics, and the intermittent tunnel/service 502 RCA.

## 2026-07-10 - Cam Device telemetry display repaired

Context: `/cam-device` failed with `rows.slice is not a function` because `/api/cam-telemetry` returns `series` as an object containing `frames` and `pings`, while the page treated it as an array.

Changes: Commit `34e6af3` explicitly renders `series.frames`, checks both HTTP responses, replaces stale table content with a retryable error, and binds Refresh without an inline handler.

State: Deployed after a timestamped server backup. `/login` returned 200, server/local SHA-256 matched, and authenticated live browser verification rendered 13 telemetry rows without a load-failed state. Template-only display change; no Python backend or watering/control code changed.

## 2026-07-10 - Serial UX fixer: auth, sensor history, archive loading

Context: Parallel UX findings identified unsafe login return handling, ambiguous unauthenticated API redirects, sensor-history boundary/recovery failures, and an eager archive image burst.

Changes: Commits `b347cd2` and `654d34d` add safe deep-link restoration, JSON 401 API responses, bounded exact-window sensor reporting, synchronized sensor error/summary states, viewport-driven archive images, a 12-card batch, and suppression of unused full-dashboard navigation requests.

Decisions: `dashboard.py` changes are display/authentication-only; no irrigation balance, credit, schedule, valve, runtime, or configuration logic changed. Grapes manual-mode and sync-group findings were logged as watering behavior and intentionally left untouched.

State: Deployed with backups. Python compile, live `/login`, authenticated browser checks, unauthenticated curl, forced HTTP-500 recovery, initial archive request count, and server/local parity passed.

Next: The strict-CSP extraction findings remain a broader staged campaign; investigate intermittent tunnel 502 only if recaptured.

## 2026-07-10 - Serial UX fixer: label fail-safe loading

Context: The latest robustness audit found `/cam/labels` left mutation controls enabled while label data was loading, invalid, duplicated, empty, or unavailable, and could construct hundreds of image-heavy cards at once.

Changes: The labels controller now starts fail-safe, checks HTTP and envelope shape, validates and deduplicates individual records, renders degraded subsets read-only, supplies an announced GET-only Retry, explains empty results, caps initial captures at 100, and renders records in explicit 100-card batches.

Decisions: Reading-detail provenance, durable IDs, timestamps, and the overlapping mobile-template edit require a common live/archive camera data contract, so those findings are logged for a broader RCA rather than receiving a misleading template-only patch. CSP extraction and restart availability remain broader campaigns. No Python backend or watering/control code changed.

State: Commit `035a019` was deployed after a timestamped remote backup. Inline JavaScript parsing, zone-label checks, live authenticated API shape, `/login` smoke, and server/local SHA-256 parity passed. The requested in-app browser runtime was not exposed in this session; command-line Playwright fallback lacked an importable test package, so browser-state interception could not be repeated after deploy.
## 2026-07-10 - Serial UX fixer: regression provenance

Context: Parallel auditors found two medium traceability gaps between the regression and live-quality displays.

Changes: Regression now identifies the evaluated `?flag=1` record set and derives its score from displayed frame verdicts (`143b21b`). New CNN/oracle evaluations persist their durable oracle-bank filename; the Quality API and table expose it while legacy rows are labeled unavailable (`ef8fa37`). Added a reusable deployment script that hashes local/remote files before and after, backs up deploy targets, optionally stops the service and backs up the live database, smoke-tests public `/login`, and enforces parity.

Decisions: `cnn_metrics.py` and `dashboard.py` were changed only in the camera reporting path. No irrigation, water-balance, valve, runtime, schedule, or watering configuration code changed. Historical quality rows remain honestly marked as legacy rather than guessed by timestamp.

State: Compiles passed. Both checkpoints were deployed with backups. Browser and authenticated API checks passed live; server/local hashes match.

Next: The existing camera identity contract, strict-CSP migration, and zero-downtime deployment findings remain director-level RCA campaigns.

## 2026-07-10 — Serial UX pass: calibration truth states and bounded usage reporting

Context: Six parallel auditors supplied 36 display/usability findings covering camera provenance, service availability, CSP readiness, shared navigation, calibration/audit reporting, and water usage.

Changes: Fixed Water Usage mobile overflow and GET Retry (`8871e04`), audit fail-closed reporting (`f408c64`), calibration history failure handling (`febdd5e`), invalid short-interval drift advice (`86ca12b`), seven-day reporting bounds (`6c03322`), and shared mobile-sheet focus containment (`ca7076a`).

Decisions: Camera identity/provenance, strict CSP, origin saturation, calibration revision provenance, and sensor identity/freshness need broader coordinated RCAs. `dashboard.py` edits are read-only display/reporting paths only; watering balance, schedule, runtime, valves, and configuration were untouched.

State: Six checkpoints deployed with timestamped remote backups and post-deploy SHA-256 parity. Authenticated Playwright confirmed Water Usage reflows to 390px and includes Retry. Public `/login` recovered to 200 after restart handoffs.

Next: Director campaigns should prioritize Forecast/Map XSS-safe DOM construction, camera serializer identity/provenance, and service saturation telemetry; then finish sensor/calibration provenance and shared camera navigation.

## 2026-07-10 - Serial UX fixer: camera review resilience

Context: Six parallel audits produced 35 findings. Twenty-four new page/issue items were merged after deduplication; none concerned watering behavior.

Changes: Review queue controls are frame-labeled, grouped, keyboard-inspectable, announced, and recover from failed GETs (`aca51e6`). CNN Report has Retry (`c0e03f7`). Quality shows complete timestamps (`e2d75d6`). The benchmark API reports a deterministic subset and full total plus display-only timestamp/source provenance; its UI deadline is 60 seconds (`304a254`).

Decisions: `dashboard.py` changed only in the read-only benchmark serializer. Camera identity, accepted-state semantics, CSP extraction, saturation/liveness, and shared navigation remain broader RCA items. No irrigation control, balance, runtime, valve, schedule generation, or watering configuration changed.

State: All checkpoints were backed up and deployed. Compile, public login smoke, authenticated live HTML/API checks, and SHA-256 parity passed. The live held-out total is 992. Browser MCP was not exposed by tool discovery, so authenticated HTTP verification substituted for the requested DOM rerun.

Next: Run the director-level camera data-contract, service saturation/liveness, strict-CSP, and shared-navigation campaigns.

## 2026-07-10 - Serial UX fixer: normalized audit timestamps

Context: Reconciled the current 37 raw auditor findings against the existing backlog. The remaining actionable high audit defect was mixed timestamp text causing lexicographic MAX/range errors.

Changes: Audit reporting orders and filters timestamps through SQLite `julianday()` and fails closed when any candidate timestamp is null or invalid (`48f541f`). The deployment helper now verifies the authenticated 25-table audit response in addition to parity and `/login`.

Decisions: `dashboard.py` changed only in the read-only audit serializer/query. No irrigation balance, schedule generation, runtime, precipitation, valves, MAD, or watering configuration changed. Calibration/sensor authority, camera provenance, shared navigation, timestamp-contract migration, and service availability remain coordinated campaigns; overlapping uncommitted user work was preserved.

State: Compiled, backed up remotely, deployed, restarted, and verified with zero audit query errors plus SHA-256 parity. Browser verification was unavailable because the in-app runtime was not exposed and the fallback Playwright dependency was absent.

Next: Director should schedule the remaining reporting-timezone, calibration/sensor serializer, camera identity, shared-navigation, and infrastructure campaigns.

## 2026-07-10 - Serial UX round 05

Context: Forty-eight raw findings covered health windows, camera identity/navigation, calibration authority, reporting ranges, and forecast resilience. The Grapes auto-mode discrepancy was quarantined as watering behavior.

Changes: Fixed T-separated health/connectivity/server-history cutoffs (`f05a1b3`), added main landmarks to four camera pages (`08fc3e9`), and made Forecast use the authoritative schedule with validated bounded loading and Retry (`ef47987`).

Decisions: `database.py` changed only read-only reporting queries. No irrigation balance, credit, schedule generation, runtime, valve, MAD, precipitation, or watering configuration code changed. Shared camera navigation was left open because `_meternav.html` contains unrelated uncommitted work.

State: The committed snapshot was deployed with timestamped backups. Compile, restart, `/login`, authenticated API/page checks, and remote/HEAD SHA-256 parity passed. One-hour live histories now return 20 health, 126 connectivity, and 7 server samples.

Next: Coordinate shared camera navigation, moisture batching/failure states, camera identity, calibration/sample provenance, reporting-timezone, and availability telemetry as broader campaigns.

## 2026-07-10 - Serial UX follow-up: rolling history and safe dashboard errors

Context: The latest 37 raw findings were already merged. The actionable one-hour reporting bug and dashboard sensor-test HTML sink were isolated from the broader camera, calibration, timezone, CSP, navigation, and saturation campaigns.

Changes: Commit `f5ffe4d` makes weather/cycle history use T-separated rolling cutoffs; commit `8e74df4` renders sensor-test errors as text rather than HTML.

Decisions: `dashboard.py` changed only read-only reporting queries. No balance, schedule, irrigation, runtime, precipitation, valve, MAD, or configuration behavior changed. Missing provenance, DST semantics, strict CSP extraction, service saturation, and overlapping shared navigation remain coordinated RCAs.

State: Both checkpoints were backed up, deployed, `/login`-smoked, and hash-verified. Live one-hour weather/cycle responses now contain only the preceding hour. Browser automation was unavailable because the required in-app runtime was not exposed.

Next: Run the coordinated camera/calibration/timezone/CSP/infrastructure campaigns; re-run browser interaction verification when the in-app runtime is available.

## 2026-07-10 - Serial UX fixer: forecast hardening and tariff precision

Context: Merged 25 current auditor findings. The actionable display defects were forecast API-to-HTML safety, comparison accessibility/equivalence, and cost-tier precision. DST/range-contract and service-availability findings remain coordinated reporting/infrastructure RCAs.

Changes: `ba8cdf5` validates or escapes forecast API fields, replaces data-controlled inline actions and option HTML, allowlists outcomes, adds semantic keyboard tabs/skip/main/filter labels/headings/concise status, explains scored exclusions, corrects the client metric label, and improves contrast/target size. `5dcd056` renders per-gallon tariff rates to five decimals.

Decisions: No backend Python, irrigation balance, schedule, runtime, valve, MAD, precipitation, or watering configuration code changed. Offset-aware reporting requires one shared range/serialization contract rather than isolated display patches.

State: Both commits were backed up and deployed independently. JavaScript syntax, public login, authenticated live pages/APIs, service state, and SHA-256 parity passed. Browser automation was unavailable because the required in-app Node REPL runtime was not exposed.

Next: Run the reporting-timezone/range-contract and service-saturation campaigns; address the low daily-cost snapshot drift later.

## 2026-07-10 - Serial UX fixer: Flow fail-closed and Audit safe DOM

Context: Reconciled all 29 current auditor findings. Two reports described real watering behavior (manual Grapes and sync-group execution) and remain logged only. Most reporting-time, CSP, and availability findings deduplicated into existing coordinated campaigns.

Changes: `511efaf` makes Flow reject HTTP failures, clear stale data, neutralize alerts, expose Retry, escape attribute-sensitive characters, and allowlist API-controlled state/severity classes. `c3a8c91` replaces Audit's API-controlled `innerHTML` construction with DOM nodes, `textContent`, numeric normalization, and status allowlisting.

Decisions: `dashboard.py` changed only the self-contained Audit reporting page renderer; no irrigation balance, credit, schedule, runtime, precipitation, valve, MAD, or configuration logic changed. Offset-aware ranges, strict CSP extraction, and worker saturation remain broader campaigns.

State: Both fixes were committed and deployed independently after timestamped remote backups. JavaScript/Python checks, service state, live `/login`, and SHA-256 server/local parity passed. The Flow restart briefly produced the known origin 502 before recovery. The required in-app browser runtime was unavailable, so the auditors' authenticated Playwright reproduction plus live HTTP/parity verification were used.

Next: Run the coordinated reporting-timezone contract, strict-CSP extraction, and origin-saturation RCAs. Do not change the two logged watering behaviors in a UX pass.

## 2026-07-10 - Serial UX fixer: round 03 safe rendering and mobile containment

Context: Reconciled all 41 round-03 auditor findings. Camera/calibration provenance, reporting-timezone, strict-CSP, and service-liveness reports deduplicated into existing coordinated campaigns. Manual Grapes and sync-group execution remain watering behavior and were not changed.

Changes: Dashboard yard-map names now render through DOM text nodes (`58ff0e8`); Map zone-list names escape at the HTML sink (`dc26f35`); Forecast comparison allows a normal 60-second display window (`b3bc749`); Camera Quality tables reflow inside labeled keyboard-scroll regions (`ed137b7`).

Decisions: All code changes are template-only display/usability fixes. No backend `.py`, irrigation balance, schedule generation, runtime, precipitation, valve, MAD, database, or configuration path changed. Broader data-contract, timezone, CSP, and infrastructure work remains open as coordinated RCA campaigns rather than individual raw findings.

State: Four guarded deployments used timestamped remote backups, `/login` smoke checks, and SHA-256 parity. Authenticated Playwright interception verified zero dashboard/Map injected nodes, a delayed 16.1-second comparison completed, and Camera Quality document width fell from 750px to 390px at a 390px viewport.

Next: Director campaigns remain camera/calibration provenance, ZoneInfo-aware reporting, strict CSP extraction, and service saturation/liveness. Do not change the logged Grapes or sync-group watering behavior in a UX pass.

## 2026-07-10 - Serial UX fixer: benchmark pagination and CNN insights

Context: Round 01 supplied 25 findings. Seven distinct refinements were newly merged; none concerned watering behavior.

Changes: Review fields now have frame-specific names, current-page state, 44px targets, and a visible current mobile destination (`58f16db`, `b888e0d`, `8609ed2`). The benchmark API paginates all 992 candidates with stable rank/order metadata, and the audit page exposes that provenance and the true 60-second deadline (`b011406`, `3c093a6`, `8e2d83c`). CNN Report independently renders `/api/cam/cnn-insights`, persistently announces loading, and controls parse/schema failures (`8690126`, `27227e0`, `4bbd84a`). Water Usage desktop controls no longer overflow (`829a0b9`).

Decisions: `dashboard.py` changed only in the read-only camera benchmark serializer. No irrigation balance, credit, scheduling, runtime, precipitation, valve, MAD, or watering configuration code changed. DST/reconciliation, calibration authority, and health/schedule telemetry remain coordinated RCAs because isolated UI edits would invent missing authority or range semantics.

State: Eleven high/medium findings were fixed through timestamped-backup deployments. Public login smoke, Python compilation, authenticated API checks, Playwright desktop/mobile geometry, invalid-response interception, and server/local SHA-256 parity passed. Eleven high/medium findings remain open across the three coordinated campaigns.

Next: Run the shared ZoneInfo reporting-contract migration, then the versioned calibration/sample serializer and service-observability campaigns.

## 2026-07-10 - Serial UX fixer: round 02 Focus and Costs provenance

Context: Round 02 supplied 20 findings across camera identity, Focus accessibility/responsiveness, and Costs provenance. None concerned watering behavior.

Changes: Focus now contains its canvas/workflow at 390px, keeps the current tool visible, exposes 44px targets and current-page semantics, and provides canvas instructions plus live ROI/orientation/padding and failure text (`0796e73`, `56212e9`). Costs now uses API `used_gal`, labels daily and bill-history provenance, renders zero-use series, and explains why its whole-house projected bill does not reconcile with the separate irrigation-planning estimate (`8ff744b`).

Decisions: Nine camera identity/provenance findings remain one coordinated data-contract RCA. Volatile RIDs, independent archive/quality keys, absent accepted-authority fields, and irrecoverable legacy attribution cannot be repaired honestly in display code. Existing uncommitted camera-pipeline and shared-navigation work was preserved. No Python backend or watering/control code changed.

State: Three checkpoints deployed with timestamped backups. Public `/login`, authenticated Costs and Focus APIs/pages, 390px browser geometry, target sizes, semantics, and local/server SHA-256 parity passed.

Next: Implement the durable camera frame/provenance entity and common serializers as a dedicated RCA campaign.

## 2026-07-10 - Serial UX fixer: round 04 camera tools and health

Context: Read and merged all 35 round-04 auditor findings. The actionable display work covered Regression interaction, Convergence recovery/accessibility, Cam Device polling/failure isolation, and ambiguous Health uptime/verdict labels.

Changes: `574c892` makes the active Regression link non-navigating, adds frame-specific action/image names, and adds filter/sort/paging. `df0db34` adds bounded Convergence loading with Retry, fail-closed output, chart/table equivalence, reflow containment, textual disagreement status, table semantics, current navigation, and 44px targets. `da1872b` independently classifies Cam Device panels, validates schema, reduces telemetry polling to one hour, prevents overlap, and pauses hidden tabs. `4a6c8f5` distinguishes application-process from ESP32 uptime and scopes the healthy banner to ESP32 reboot state.

Decisions: The immutable camera identity/provenance findings remain the existing data-contract RCA. Listener/auth/worker/layer telemetry and incident accounting remain the health/infrastructure RCA. The three T-separated health-history cutoff fixes are display/report queries, but `database.py` contains unrelated uncommitted work; deploying the whole file would absorb that work, so the query fix remains explicitly blocked for a clean coordinated patch. No watering behavior was reported or changed.

State: All four template checkpoints were deployed after timestamped remote backups. JavaScript parsing, authenticated live page/API checks, public `/login`, and local/server SHA-256 parity passed. The required in-app browser runtime was not exposed, so no new browser-DOM automation is claimed. No backend `.py`, irrigation balance, schedule, runtime, precipitation, valve, MAD, or watering configuration code changed.

Next: Implement the durable camera entity and the bounded health/availability reporting contract, then land the three history cutoff query changes without absorbing unrelated `database.py` work.

## 2026-07-10 - Serial UX fixer: round 06 failure states

Context: Round 06 supplied 27 findings. Ten distinct page/issue refinements were merged; the Grapes report deduplicated into the existing watering-behavior quarantine.

Changes: Dashboard activity detail is escaped at both HTML sinks (`984e26c`); Cam Device rejects semantically invalid telemetry rows (`219c8a7`); Forecast comparison announces busy/empty states, rejects partial schemas, and implements complete keyboard tab behavior (`4b4ac58`).

Decisions: No backend Python or watering/control code was committed. The T-separated Cam Device cutoff remains blocked by unrelated active `database.py` work. Moisture atomic batching, shared camera navigation, Map stale/schema handling, and Forecast high-zoom geometry remain open. Real Grapes automatic watering was not disguised with a display patch.

State: Three template checkpoints were backed up and deployed. Public `/login` and SHA-256 parity passed. The required in-app browser runtime was unavailable, so the authenticated raw-auditor browser evidence was retained and no browser rerun is claimed.

Next: Land the clean read-only Cam Device cutoff, then run the Moisture snapshot, shared camera-navigation, and Map failure-contract campaigns.

## 2026-07-10 - Serial UX fixer: round 07 stale-state safety

Context: Read and merged all 31 round-07 findings; none was watering behavior.

Changes: Map validates the full dashboard response and fails closed with retained last-update provenance, disabled controls/markers, and Retry (`184aebd`). The camera hub reflows at 195px, exposes focus, and links Device (`4344d01`). Shared camera navigation now has 44px targets, Device discovery, one `aria-current` destination, reading-detail ownership, and suppressed same-URL reloads (`cf20110`).

Decisions: Calibration authority, strict CSP, timestamp contracts, dashboard generation state, page-local reading detail, and telemetry bounds remain coordinated campaigns. Dirty backend/camera files were not absorbed. No Python or watering/control code changed.

State: Three checkpoints deployed after backups. Live authenticated Playwright, `/login`, restart recovery, and SHA-256 parity passed.

Next: Land the isolated read-only telemetry cutoff and finish the page-local camera reading recovery/landmark work.

## 2026-07-10 - Serial UX fixer: round 09 forecast extreme zoom

Context: Read all 40 round-09 findings. None was a new page/issue after deduplication; two watering-control reports remain quarantined. The only clean standalone open defect was Forecast comparison reflow at 200% and 400% zoom.

Changes: Forecast tabs stack at narrow effective widths, controls and comparison content shrink/wrap, summary cards lose their intrinsic minimum, forecast rows stack, and shared mobile navigation uses zero-minimum grid tracks (`4034c11`, `21bfa08`, `49a495d`).

Decisions: Moisture atomic snapshots, Dashboard generation/command authority, Cam Device time ranges, camera-reading detail, and calibration/sensor authority remain coordinated RCA campaigns. Dirty `database.py` and `cam_reading.html` were not absorbed. No backend Python or watering/control code changed.

State: Three guarded template deployments used timestamped backups, `/login` smoke checks, and server/local SHA-256 parity. Authenticated live Playwright measured exact document containment at 195px and 98px effective viewports. Thirty-two non-watering high/medium raw findings remain grouped into five broader/overlapping campaigns.

Next: Land the isolated read-only telemetry cutoff from a clean database patch, then run the atomic snapshot, Dashboard authority, camera-detail, and calibration-authority campaigns.
## 2026-07-10 - Round-10 UX serial fixer

Context: Merged all 36 round-10 auditor findings under the display-only safety boundary.

Changes: Audit page now server-renders its complete read-only table and uses same-origin external CSS/JS (`493f762`), so it has a truthful no-script baseline and is compatible with nonce-free strict CSP. Deployed with backups, authenticated live verification, `/login` smoke, and SHA-256 parity.

Decisions/State/Next: Manual-zone schedule contradictions remain watering-behavior DO NOT FIX items. Remaining high/medium reports deduplicate into the existing coordinated moisture snapshot, dashboard authority, reporting-time, camera detail/provenance, calibration authority, and site-wide CSP campaigns. Active unrelated changes in `database.py` and camera templates were preserved.

## 2026-07-10 - Round-11 convergence reporting

Context: Read and merged all 28 round-11 findings; none concerned watering behavior.

Changes: Convergence query validation rejects unsupported requests before database work, its displayed coverage aggregation avoids the correlated scan, and incomplete/null trend payloads fail closed.

Decisions/State/Next: `dashboard.py` and `meter_archive.py` are read-only reporting changes; no watering/control logic changed. Commit `d1a4f05` was deployed with backups; authenticated convergence completed in 76 ms, invalid input returned 400 in 1.4 ms, `/login` returned 200, and SHA-256 parity passed. Costs CSP, regression inference pagination, CNN metric provenance, and sensor identity/revision remain coordinated campaigns.

## 2026-07-10 - Round-12 forecast request ownership

Context: Read and merged all 32 round-12 findings; none concerned watering behavior. Twenty-one high/medium reports refine the existing atomic moisture, dashboard authority, telemetry-time, reading-detail, CSP, and calibration-provenance campaigns.

Changes: Forecast loads now have one page-level abort owner and a render sequence, so an older overlapping response cannot overwrite newer display state (`065491d`).

Decisions/State/Next: This was template-only; no backend or watering/control code changed. Deployed after a timestamped backup with authenticated forecast/API checks, `/login` smoke, service-active verification, and server/local SHA-256 parity. Continue the six coordinated campaigns recorded in `UX-AUDIT.md`.

## 2026-07-10 - Round-13 audit convergence

Context: Read and merged all 41 round-13 auditor findings; 38 were high/medium and one repeated the Grapes automatic-schedule contradiction.

Changes: Added the round-13 deduplication and RCA campaign mapping to `UX-AUDIT.md`; no product code changed.

Decisions: All non-watering high/medium reports refine existing coordinated atomic-snapshot, reporting-time, camera-detail, strict-CSP, regression-inference, or CNN-provenance campaigns. The Grapes schedule output remains Watering-behavior DO NOT FIX. Dirty `database.py` and camera/CSP files were preserved.

State: Zero new distinct findings, zero fixes, no deployment, and 38 raw high/medium findings remain represented by six open coordinated campaigns.

Next: Land those campaigns as coordinated changes with their required data contracts; do not patch schedule/control output from a UX pass.

## 2026-07-10 - Round-14 water labels, login alert, and Focus persistence

Context: Read and merged all 28 round-14 findings. One Grapes automatic-schedule contradiction remains quarantined as watering behavior.

Changes: Water Usage derives bucket labels from `bucket_s` (`1133e27`) and explains visible audit reconciliation arithmetic (`7a03956`). Login errors are announced (`1974763`). Focus reapplies stored locks, immediately persists the precise transformed ROI, and starts its tool strip at the leading edge (`0886c94`, `13226da`, `fe198ca`).

Decisions: The login deep-link report was invalidated by live curl and existing same-origin validation. Moisture atomic snapshots and camera benchmark/metric provenance remain coordinated campaigns. No backend Python or watering/control code changed.

State: Six display fixes were committed and deployed serially with timestamped backups, `/login` smoke checks, and SHA-256 parity. Thirteen non-watering high/medium raw findings remain represented by coordinated campaigns.

Next: Implement the atomic moisture envelope and the persisted, versioned camera metric/provenance contracts without changing schedule generation or watering behavior.
## 2026-07-10 - Round-15 benchmark failure truth

Context: Read and merged all 44 round-15 findings. Two Test Audit display/request issues were distinct and actionable; two Grapes/manual-zone reports remain quarantined as watering behavior.

Changes: Test Audit clears prior cards, counts, controls, and state before loads and on every failure (`0e5b5de`), and no longer issues a redundant per-card warm image GET (`31fef84`).

Decisions: The remaining 38 non-watering high/medium reports refine the existing atomic moisture, dashboard authority, reporting-time, durable camera-detail, persisted benchmark, and typed CNN-metric campaigns. No backend Python or watering/control code changed.

State: Both template checkpoints were deployed independently after timestamped backups. Authenticated live Playwright verified a forced HTTP 500 leaves zero stale cards/count and that the normal 83-card result still renders. Public `/login` returned 200 and remote/local SHA-256 parity passed.

Next: Land the six coordinated contracts without changing schedule generation, irrigation balance, valves, runtimes, MAD, precipitation rates, or watering configuration.

## 2026-07-11 - Round-16 audit convergence

Context: Read and merged all 45 round-16 auditor findings; 35 were non-watering high/medium and seven high findings were explicitly marked as watering behavior.

Changes: Added the round-16 deduplication and campaign mapping to `UX-AUDIT.md`; no product code changed.

Decisions: All non-watering high/medium reports refine the existing atomic moisture, dashboard provenance, reporting-time, persisted benchmark, typed CNN-metric, or durable camera-detail campaigns. The Grapes automatic-mode contradiction and dashboard/Map command-authority and stale-command risks remain Watering-behavior DO NOT FIX. Dirty backend and camera work was preserved.

State: Zero distinct new findings, zero fixes, and no deployment. Thirty-five non-watering high/medium raw findings remain represented by six coordinated RCA campaigns. No backend Python or watering/control code changed.

Next: Schedule the six coordinated contracts under their broader RCA campaigns; handle command-authority and Grapes behavior only through the watering-control change process.

## 2026-07-11 - Round-17 audit convergence

Context: Read and merged all 46 round-17 auditor findings; 38 were non-watering high/medium and three high findings were explicitly marked as watering behavior.

Changes: Added the round-17 deduplication and campaign mapping to `UX-AUDIT.md`; no product code changed.

Decisions: All non-watering high/medium reports refine the existing atomic moisture, dashboard provenance, reporting-time, persisted benchmark, typed CNN-metric, or durable camera-detail campaigns. The Grapes automatic-mode contradiction and dashboard/Map command-authority failures remain Watering-behavior DO NOT FIX. Dirty backend and camera work was preserved.

State: Zero distinct new findings, zero fixes, and no deployment. Thirty-eight non-watering high/medium raw findings remain represented by six coordinated RCA campaigns. No backend Python or watering/control code changed.

Next: Schedule the six coordinated contracts under their broader RCA campaigns; handle command-authority and Grapes behavior only through the watering-control change process.

## 2026-07-11 - Round-18 audit convergence

Context: Read and merged all 31 round-18 auditor findings; 26 were non-watering high/medium and one high finding was explicitly marked watering behavior.

Changes: Added the round-18 deduplication and RCA mapping to `UX-AUDIT.md`; no product code changed.

Decisions: Calibration/sensor authority, durable camera archive/detail, staged Costs/authenticated-shell CSP fallback, canonical flow reporting, and typed convergence metrics remain coordinated campaigns. The Grapes manual-only `soil_dry` attribution remains Watering-behavior DO NOT FIX. Dirty backend, watering, meter, cost, and camera files were preserved.

State: Zero distinct new findings, zero fixes, and no deployment. Twenty-six non-watering high/medium raw findings remain represented by five coordinated RCA campaigns. No backend Python or watering/control code changed.

Next: Schedule the five coordinated contracts; handle Grapes attribution only through the watering-control change process.

## 2026-07-11 - Round-19 Camera Quality accessibility and audit convergence

Context: Read and merged all 44 round-19 auditor findings. Thirty-eight were non-watering high/medium; one high finding was explicitly watering behavior.

Changes: Added a first-focusable Camera Quality skip link (`80c74f4`) and a semantic recent-read match heading plus screen-reader Match/Mismatch text (`337427e`). Both template checkpoints were deployed independently with backups, `/login` smoke checks, and SHA-256 parity.

Decisions: The other 36 non-watering high/medium reports refine the existing atomic moisture, dashboard authority, reporting-time, durable camera-detail, persisted benchmark, and typed CNN-metric campaigns. The manual-zone configuration finding remains Watering-behavior DO NOT FIX. No backend Python or watering/control code changed. The authenticated browser runtime was unavailable, so no fresh browser-DOM verification is claimed.

State: Camera Quality keyboard bypass and match-result semantics are live. All remaining round-19 high/medium items are recorded under coordinated RCA campaigns.

Next: Schedule the six coordinated contracts; handle manual-zone behavior only through the watering-control change process.
## 2026-07-11 - Round-20 camera label safety and Flow truth

Context: Read and merged all 32 round-20 findings. One Grapes automatic-mode/schedule/scoring finding is watering behavior and remains quarantined. Seven standalone display issues were added; the rest refine existing coordinated authority/reporting campaigns.

Changes: Camera Labels validates all count fields (`6dd0e8d`), escapes the nine-character formatter (`5095abf`), rejects stale load generations (`a63adee`), and treats file as the unique mutation identity (`71565bb`). Flow keeps every unresolved event in its banner (`85fd488`) and rejects error-bearing 200 payloads (`9d19f8c`). Forecast comparison labels crop-adjusted `etc_mm` as ETc (`021bd67`).

Decisions: Calibration identity/revisions, forecast lineage, audit query/performance contracts, and canonical water reconciliation remain coordinated RCAs. The API half of Flow's failure contract remains open because deploying the heavily dirty `dashboard.py` would absorb unrelated backend work. No Python backend or watering/control code changed.

State: Six findings are fully fixed and live; Flow error-envelope display hardening is live but the combined API finding remains open. Each checkpoint used a timestamped backup, restart, `/login` smoke, authenticated API/page verification, and SHA-256 parity.

Next: Land the clean Flow API status change with the coordinated backend work, then implement the versioned calibration/sample and canonical reporting contracts. Do not change Grapes behavior in a UX pass.

## 2026-07-11 - Round-21 typed Flow failure contract

Context: Read and reconciled all 21 current raw findings. Three status/error-contract refinements were new; the remainder deduplicated into existing CNN, calibration, audit, canonical reporting, and infrastructure campaigns. No finding was watering behavior.

Changes: Flow reporting failures now return HTTP 503 with a typed `FLOW_UNAVAILABLE` envelope (`1a08bbc`). The already-hardened page rejects the response, clears stale operational claims, and offers Retry. Added the OCR-audit and camera job-status failure contracts to the backlog as broader authority campaigns.

Decisions: `dashboard.py` changed only the read-only Flow display API error response. No irrigation balance, credit, schedule generation, runtime, valve, MAD, precipitation, or watering configuration changed. Calibration provenance, bounded Audit aggregation, public liveness/schedule telemetry, canonical meter reporting, and camera job authority remain coordinated RCAs.

State: Python compile passed. The live file was backed up, deployed, restarted, authenticated-curl checked, `/login` smoked, and SHA-256 matched local. An initial PowerShell text-pipe diff mangled UTF-8 in the staged deployment; the timestamped backup was immediately restored before a binary-safe SCP deployment, and the service recovered with parity verified. The in-app browser runtime was unavailable.

Next: Implement the three typed failure contracts with their meter/job authority campaigns, then the versioned calibration and bounded Audit snapshot contracts.
