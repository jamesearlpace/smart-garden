# Smart Garden — Journey Doc

**Status:** ✅ **System operational + actively self-managing.** Sync-groups live (overlapping turf zones water together, deep+infrequent). ET₀ water-balance brain is the decision-maker. Soil sensors are observe-only supporting "eyes" (not the brain) with full server-side calibration UI. Dashboard de-cluttered.
**Last Updated:** 2026-06-28 (canonical meter data layer built + whole `/water-usage` page re-pointed to it — full chronological record in **`meter-data-layer-journey.md`**)

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
> **Deploy pattern (this service):** local edits in `C:\MyCode\smart-garden\server-prod\` → backup on server (`cp ...bak.<tag>-<ts>`) → `scp templates/cam_focus.html jamesearlpace@192.168.0.109:~/smart-garden-server/templates/` → `ssh ... "echo 'KeepingP@ce8!' | sudo -S systemctl restart smart-garden-server"` → authed smoke test via session-cookie python. Also mirror to `C:\MyCode\smart-garden-server-live\`. Port 5125.

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
SSH: `jamesearlpace@192.168.0.109` password `KeepingP@ce8!` (key auth configured, no prompt).

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
