# Smart-Garden UX Audit — Findings Backlog

Maintained by Codex during UX audit runs (see `codex-ux-audit-prompt.md`).
Phase 1 = audit only (fill this table, no code changes). Phase 2 = fix high/med.

**Severity:** high (broken / wrong data shown) · med (usability hurts, still works) · low (polish — NOT fixed this pass)
**Status:** open · fixed · logged-only

## Findings

| Page | Severity | Status | Category | Expected vs Actual | Proposed fix |
|------|----------|--------|----------|--------------------|--------------|
| moisture-sim | high | fixed (superseded by `44bfd33`) | console/resource | Recurring `502` console errors were traced by the later instrumented capture to reset jsDelivr dependencies. | Dependencies are now pinned and same-origin; the captured root cause is closed. |
| moisture-sim | high | fixed | data-accuracy | Chart credited all-zone watering events to the selected zone because `/api/moisture-data` intentionally returns all events. | Filter display credits by `watering_event.zone_id` before authoritative daily normalization; live API facts and deployed source verified (commit `da63bc4`). |
| moisture-sim | med | fixed | correctness | A completed watering could be shown as the next expected run. | Final banner writer now uses `/api/schedule-7day`; live check found every same-day entry later than current time and completed Zone 1 moved to tomorrow. |
| moisture-sim | low | open | clarity | Zone dropdown shows "Zone 2 — Front Yard B [selected]" while URL is `#zone=1` (0-indexed URL vs 1-indexed label). Potentially confusing when sharing links. | Confirm intended; consider aligning URL param to the 1-indexed UI number or documenting the offset. |
| dashboard | med | fixed | dead-link | "Recent Activity → View All →" used a placeholder `href="#"`. | Link now has a real `#history` target while retaining the existing `showPanel('history')` action (commit `3509abd`). |
| dashboard | med | fixed | data-accuracy | Dashboard activity and Moisture Simulation next-watering banner disagreed. | Moisture banner's final writer uses the authoritative schedule API; current activity and future schedule API were cross-checked after deploy. |
| dashboard | low | open | clarity | Soil sensors show extreme test values (Sensor 0 = 1% raw 2649, Sensor 2 = 100%) labeled "test sensor". Real-looking % on the main dashboard may mislead. | Visually distinguish test-mode readings (badge/muted styling) so they aren't mistaken for calibrated soil moisture. |
| water-usage | med | fixed | dead/wrong-link | "← Back to dashboard" pointed to `/#cam`. | Changed the target to `/` and verified deployed template parity (commit `4ed9730`). |
| water-usage | high | fixed | data-accuracy | Event list showed "0 min" for completed orphan-cleanup spans with zeroed stored metadata. | Display API now derives elapsed seconds from start/end and configured estimated gallons without changing DB/control data; live events 691/692/702 verified. |
| water-usage | med | fixed | loading-state | On main API failure the subtitle changed, but the leak banner stayed indefinitely at "Checking…". | Main load catch now replaces both with an explicit retry/range error state (commit `5a25996`); normal live API returns populated data. |
| water-usage | low | open | usability | Event picker is a single flat dropdown with 100+ options across many days — hard to scan. | Group by day (optgroup) or add a date filter. |
| forecast | med | fixed | data-display | Same-day fractional predictions (`0.5d`, `0.8d`) displayed as `1d` beside today's date. | Values under one day now display as `Today`; API values `0.5` and `0.8` verified live (commit `30e42eb`). |
| forecast | med | fixed | clarity | The 24-hour window `00:00 – 14:00` was labeled `AM`, producing the invalid `14:00 AM`. | Now labeled `Watering window: 00:00 – 14:00` with no invalid suffix; verified live (commit `30e42eb`). |
| forecast | low | open | console/resource | Browser console reports a 404 for `/favicon.ico` on page load. | Add a site favicon or explicit favicon link. |
| forecast-vs-actual | high | fixed | data-accuracy | Accuracy Summary reported 98.1% (265/270 correct), counting manual-mode and non-comparable `no_event` rows as correct. | Only completed automatic decisions are scored; current manual zones and unscored rows are omitted from the comparison UI. Live API/UI, compile, smoke, and parity checks passed (commits `cf9dd8f`, `4962309`). |
| sensor-history | med | fixed | status-feedback | Desktop sidebar stayed at `Connecting...` indefinitely although the page loaded all four sensor APIs successfully and refreshes every 60 seconds. | Successful refresh now reports `Updated just now` (commit `cde26c9`). |
| sensor-history | low | open | console/resource | Browser console reports a 404 for `/favicon.ico` on page load. | Covered by the existing site-wide favicon finding; add a site favicon or explicit favicon link. |
| map | med | fixed (`3d3b7ec`) | responsive-navigation | At 320px, the desktop Map navigation clipped beyond the viewport. | Use the shared mobile navigation below 768px and suppress the desktop link row. |
| map | med | fixed (`3d3b7ec`) | tap-targets | Mobile navigation and zone Run controls were below the approximately 44px touch target minimum. | Give map controls a 44px minimum target and rely on the shared 64px mobile bar. |
| map | med | fixed (`3d3b7ec`) | map-identification | Mobile map markers depended on color and hover-only names, so zones were difficult to identify. | Show persistent numbered markers on mobile and add keyboard-accessible zone names. |
| sensor-history | high | fixed (`d4aba93`) | chart-alternative | Canvas chart had no accessible name or equivalent textual values. | Add an accessible chart description and synchronized latest/min/max/sample summaries. |
| sensor-history | high | fixed (`d4aba93`) | zoom-reflow | Auditor observed 1822px document width at 200% zoom on a 390px viewport. | Constrain the chart wrapper and allow controls to wrap; verify at narrow equivalent width. |
| sensor-history | med | fixed (`d4aba93`) | selection-semantics | Range, mode, and sensor selection state was visual/color-only. | Add radio semantics to exclusive choices and aria-pressed to sensor toggles. |
| sensor-history | med | fixed (`d4aba93`) | landmarks | No skip link or main-content landmark existed. | Add a first-focusable skip link and main landmark. |
| sensor-history | med | fixed (`d4aba93`) | dynamic-status | Loading and refresh completion had no live-region announcement. | Add a restrained polite status region for load/update state. |
| sensor-history | med | fixed (`d4aba93`) | calibration-status | Cards said Working while calibration API advice said Garden/Fruit Trees needed recalibration. | Display the API's explanatory calibration advice directly on each card. |

## Watering-behavior (DO NOT FIX — log for James)

Anything that is actually wrong irrigation/control behavior, not a display bug.

| Page/Area | What's wrong | Why it's control-logic, not display |
|-----------|--------------|-------------------------------------|
| moisture-sim | "Depth Per Cycle 0.06\"" vs target 0.5–0.75" — cycles apply ~10x too little (chronic under-watering). | Irrigation output (runtime × precip rate), not display. Under active tuning — do not change from a UX pass. |
| water-usage / schedule | Many watering events fire 10:15 AM–12:05 PM (Zone 1 running at 12:05 PM) despite the 00:00–10:00 turf window. | Watering-window enforcement / recovery behavior = irrigation engine, not display. Verify with James before touching. |

| dashboard / schedule / history | Grapes (zone 8) is currently reported `auto_mode:true`, appears in the automatic seven-day schedule, and has a completed engine-triggered `soil_dry` event despite the documented manual-only invariant. | Configuration/control/schedule behavior from `findings-4.json`; logged only. No watering code or configuration changed. |
| dashboard / schedule | Front-yard and backyard sync-group members are returned with independent sequential start times and runtimes instead of watering together. | Schedule/control behavior from `findings-4.json`; logged only. No watering code or configuration changed. |

## Resolved this run

- Forecast-vs-actual accuracy now excludes current manual zones and no-event rows from scoring and display (`cf9dd8f`, `4962309`).
- Water Usage zero-duration cleanup events now display their real elapsed span and a derived configured-volume estimate (commit `68b20f9`).
- Moisture chart irrigation credits are restricted to the selected zone (`da63bc4`).
- Recent Activity has a real history target (`3509abd`).
- Water Usage Back navigation and failed-load state are corrected (`4ed9730`, `5a25996`).

## 2026-07-10 parallel-auditor merge

The earlier open `moisture-sim` console/resource row is superseded by the captured CDN failure below. Site-wide favicon reports are deduplicated here.

| Page | Severity | Status | Category | Expected vs Actual | Proposed fix |
|------|----------|--------|----------|--------------------|--------------|
| moisture-sim | high | fixed (`44bfd33`) | external CDN dependency failure | An instrumented cold load captured `net::ERR_CONNECTION_RESET` for all four required jsDelivr chart libraries while first-party requests stayed 200. | All dependencies are pinned and served same-origin; live requests return 200 with no CDN dependency. |
| moisture-sim | med | fixed (`a889fe3`) | missing dependency error state | Required chart-library failure had no visible error or recovery guidance. | A role=alert fallback now explains that the chart is unavailable and offers reload recovery while preserving schedule details. |
| dashboard / sensor-history / water-usage / costs / camera charts | med | fixed (`44bfd33`) | shared dependency blast radius | Checked chart pages imported Chart.js from jsDelivr, so one outage could blank several visualizations. | All affected pages now use pinned same-origin audited chart assets. |
| costs | med | fixed (`4d1b9b9`) | error state | A simulated water-cost API 500 rendered as valid-empty `No data yet`. | HTTP failures now show an announced retryable error. |
| costs | high | fixed (`4d1b9b9`) | mobile layout | At 390px Bill history made the document 448px wide. | The bill table is contained in a labeled keyboard-scrollable region; live document width is 390px. |
| costs | high | fixed (`4d1b9b9`) | chart accessibility | Three charts lacked accessible names and equivalent keyboard-readable values. | Charts are named and daily usage has a synchronized text series; bill values remain in the bill table. |
| costs | high | fixed (`4d1b9b9`) | mobile navigation accessibility | More lacked state semantics, exposed closed content, and ignored Escape. | Added expanded/controls state, inert hiding, Escape/toggle closure, and focus restoration. |
| costs | med | fixed (`4d1b9b9`) | navigation accessibility | Selected Water Cost links lacked `aria-current`. | Active navigation is now marked programmatically. |
| site-wide | low | open | console/resource | Favicon requests return 404 on multiple pages. | Serve a favicon or correct the reference. |
| flow | high | fixed (`10ca8de`) | stale current alert | Idle samples followed orphan event 1077, but UI still called its 3.26 gpm alert ongoing. | Fresh authoritative idle samples suppress stale open alerts; old rows are labeled stale unresolved records. |
| flow / water-usage | med | fixed (`10ca8de`) | connectivity inconsistency | Pages stayed at `Connecting...` while APIs/dashboard had a terminal state. | Shared navigation now resolves to online/offline/unavailable from `/api/dashboard`. |
| water-usage / flow | med | fixed (`10ca8de`) | estimate clarity | Usage used configured rates while Flow showed learned rates; `est` hid the basis. | Event labels now say configured estimate and show the derived configured GPM. |
| flow | med | fixed (`10ca8de`) | error/stale state | A simulated flow API 500 left urgent prior data looking current. | Refresh failure neutralizes alerts and explicitly hides prior alert content. |
| forecast | high | fixed (not reproduced) | time to usable / API latency | An earlier throttled run saw 7.7s API responses. | Superseded by the focused auditor: mobile forecast completed in 233ms, desktop TTFB 33-49ms, and health/forecast already run concurrently. Broader intermittent warm-up RCA only if recaptured. |
| forecast | med | fixed (not reproduced) | intermittent latency | An earlier cold request took 1.594s. | Ten focused reloads found only 83ms first versus 34-50ms warm; no actionable display defect remains. |
| forecast | low | open | responsiveness | Render produced 52ms and 135ms long tasks. | Batch DOM construction. |
| forecast | low | open | cache efficiency | Static CSS retransfers with cache BYPASS. | Add versioned static caching. |
| forecast-vs-actual | high | fixed (`a6ed348`) | stale/loading state | Refresh left old results looking current with no timeout. | Updating state is explicit and requests abort after 15 seconds. |
| forecast-vs-actual | med | fixed (`a6ed348`) | HTTP errors / 401 | Errors produced secondary failures or discarded the tab on 401. | Status is checked; 401 and other failures stay in-tab with an announced Retry path. |
| forecast-vs-actual | high | fixed (`a6ed348`) | malformed response | Partial/null/invalid records could break the whole view. | Payload and rows are normalized; invalid records are excluded. |
| forecast-vs-actual | high | fixed (`a6ed348`) | accuracy truthfulness | Trusted totals and percentages could be impossible or inconsistent. | Summary is recomputed from validated, displayed scored rows. |
| forecast-vs-actual | med | fixed (`a6ed348`) | empty semantics | All zero-row states claimed no forecast data and offered snapshot creation. | Filter no-match is distinguished and does not offer snapshot mutation. |
| forecast-vs-actual | med | fixed (`a6ed348`) | retry/recovery | Failures lacked Retry and loaded state blocked recovery. | Accessible Retry resets the failed state. |
| forecast-vs-actual | low | open | accessibility | Dynamic states and div tabs lack live/tab semantics. | Add live regions and proper tab behavior. |
| cam/convergence | high | fixed (`05c4ce4`) | DOM injection / unsafe URLs / inline handler injection | API text, image URLs, and timestamps crossed HTML/attribute/handler contexts unsafely. | Text is escaped, image URLs are restricted to the same-origin archive endpoint, and API timestamps are captured by listeners rather than inline handler source. |
| authenticated site | med | fixed (`8e9fc40`) | security headers | Pages/APIs previously lacked standard defense-in-depth headers. | Compatible headers and CSP Report-Only are live; strict CSP remains the separate broader campaign below. |
| camera charts / water-usage | low | open | script supply chain | CDN scripts lack SRI and CSP restriction. | Self-host or pin with SRI. |
| cam/archive | low | open | inline active content | Repeated inline onclick handlers expand CSP surface. | Replace with delegated listeners. |

## 2026-07-10 serial-fixer raw merge

Merged all 20 findings from `orchestrator/findings-1.json` through `findings-5.json`; existing page/category rows above were refined in place instead of duplicated. No new watering-behavior finding was reported. Additional low findings retained for a later polish pass: Forecast friendly Retry/stale-data recovery; Flow full date/age/timezone freshness labels; Costs empty Bill History message; Convergence explicit main-API error/Retry and empty verification state; and a restrictive CSP after remaining inline code is removed. The focused Forecast latency auditor superseded the earlier high/medium latency observations with 10 fast desktop reloads and a 233ms throttled-mobile API completion.

Two broader medium items remain open: the cross-camera-page unsafe-rendering pattern needs a dedicated page-by-page regression campaign, and compatible site-wide security headers/CSP need staged rollout after inline scripts are removed. The proven Convergence exploit paths are fixed.

## 2026-07-10 serial-fixer merge — camera, audit, and security

All 32 raw findings in `orchestrator/findings-0.json` through `findings-5.json` were reviewed. The site-wide favicon and missing-security-header reports were deduplicated against existing rows; 30 findings were newly folded into the backlog. None was watering behavior.

| Page | Severity | Status | Category | Expected vs Actual | Resolution / RCA |
|------|----------|--------|----------|--------------------|------------------|
| cam/labels | high | fixed (`d359536`) | DOM XSS / API status | API status crossed class and HTML contexts without validation. | Status is enum-normalized and job messages use `textContent`. |
| cam/archive | high | fixed (`d359536`) | DOM XSS / readings | API readings and totals entered HTML without numeric validation. | Readings/counts are finite-number normalized and escaped before markup. |
| cam/review, cam/test-audit, cam/regression | med | fixed (`d359536`, `6b3629f`, `aab11c3`) | API image URL validation | API URLs could load arbitrary origins or paths. | Each page now enforces same-origin, route-specific camera image paths. |
| authenticated site | med | fixed (`8e9fc40`) | security headers | Responses omitted browser defense-in-depth headers. | Added nosniff, DENY framing, referrer, permissions, HSTS, and CSP Report-Only headers; verified live with curl. |
| authenticated site | med | open — broader RCA | CSP readiness | Inline script/style and dynamic inline presentation prevent a strict enforced CSP. | Report-Only policy is staged (`8e9fc40`), but removing hundreds of inline sinks is a site-wide migration; director should schedule a CSP extraction campaign. |
| authentication | med | fixed (`8e9fc40`) | fail-open session secret | Missing environment configuration silently selected a known signing key. | Startup now rejects missing, default, or shorter-than-32-character secrets; live service restarted successfully with configured secret. |
| protected APIs | low | open | authentication response semantics | Unauthenticated JSON endpoints redirect to HTML login instead of returning JSON 401. | Later API-consistency pass. |
| cam / cam/focus mobile | med | fixed (`eebf053`) | More toggle blocked | Open sheet intercepted the More button. | Mobile navigation stays above the sheet so the same button can close it. |
| cam/focus | med | fixed (`eebf053`) | error-state interaction safety | Frame-dependent actions remained enabled after HTTP/fetch failure. | Controls start disabled and re-disable on failure; only a successful fresh frame enables them, while Refresh remains available. |
| cam/focus | med | open — broader RCA | intermittent network reliability | A deep link intermittently returned 502 for CSS and APIs. | UI recovery is safe, but simultaneous static/API 502s originate at service/tunnel availability, not display code; schedule infrastructure RCA if recaptured. |
| cam / cam/focus | low | open (deduped site-wide) | favicon | `/favicon.ico` returns 404. | Existing site-wide favicon row. |
| audit / history APIs | high | fixed (`8e9fc40`) | T-separated 24-hour cutoff | Space-separated `datetime()` cutoffs overstated 24-hour counts. | Display/report queries use T-separated `strftime`; authenticated curl now returns 57 watering events with oldest `2026-07-09T20:16:54`. |
| audit | med | fixed (`8e9fc40`) | health coverage | Only 13 of 25 application tables were audited. | All 25 are now specified and displayed. |
| audit | med | fixed (`8e9fc40`) | unused table semantics | Dead `billing_cycle` inflated actionable EMPTY. | It is `DISABLED` and excluded from EMPTY totals. |
| audit | med | fixed (`8e9fc40`) | sensor labeling | Active observe-only logging was called disabled. | Label now separates active logging from disabled control gates. |
| audit | med | fixed (`8e9fc40`) | loading/error/empty states | Fetch failures left Loading or stale/blank content. | Status/schema checks, accessible loading/error/empty states, and Retry are present. |
| audit mobile | med | fixed (`8e9fc40`) | horizontal overflow | The 541px table widened a 390px document. | Table is contained in a labeled keyboard-scroll region; live document overflow is zero. |
| audit | low | open | timezone labeling | Local timestamps omit Pacific timezone/offset. | Later polish pass. |
| cam/regression | high | fixed (`6b3629f`) | HTTP error semantics | HTTP errors rendered as valid-empty with enabled mutation UI. | Status checks render an announced Retry error and no cards/actions. |
| cam/regression | med | fixed (`6b3629f`) | malformed envelope | JSON null had an undifferentiated failure with no recovery. | Envelope validation gives a format error and Retry. |
| cam/regression | med | fixed (`6b3629f`) | malformed records | Bad rows collapsed into valid-empty. | Records validate independently; valid rows render and rejected count is announced. |
| cam/quality | high | fixed (`6b3629f`) | HTTP failure | A 500 removed useful quality content with no recovery. | Headings/tables remain, unavailable rows are explicit, and Retry is announced. |
| cam/quality | high | fixed (`6b3629f`) | loading robustness | Pending and failed states were indistinguishable blank shells. | Explicit live loading transitions to data, empty, or error. |
| cam regression / quality | med | fixed (`6b3629f`) | shared request-state cause | Neither page enforced status/schema/error states. | Both now implement the same success-gated request-state pattern. |
| cam/test-audit | high | fixed (`aab11c3`) | image alternatives | Decision-critical meter images had empty alt text. | Alt text identifies frame, stored label, and model prediction; live 27-image check found zero empty alternatives. |
| cam/test-audit | med | fixed (`aab11c3`) | async announcements | Long model work had no live status, timeout, or Retry. | Polite status, 30-second timeout, alert failure, and GET-only Retry added. |
| cam/test-audit | med | fixed (`aab11c3`) | repeated control names | Card actions did not identify their frame. | Every repeated action includes its frame identifier in `aria-label`. |
| cam/test-audit / cam/cnn-report | med | fixed (`aab11c3`) | landmarks | Pages lacked a main landmark and skip link. | Both now provide one main landmark and visible-on-focus skip link. |
| cam/cnn-report | high | fixed (`aab11c3`) | mobile reflow | Wide tables/tool links widened the 390px document. | Labeled scroll regions contain tables; live document overflow is zero. |
| cam/cnn-report | med | fixed (`aab11c3`) | blank table header | Decorative accuracy bar occupied an unnamed column. | Bar moved into Accuracy and is hidden from accessibility APIs. |
| cam/cnn-report | med | fixed (`aab11c3`) | contrast | Small green/blue text failed AA contrast. | Tokens changed to darker AA-compatible values. |
| cam/cnn-report | low | open | touch target size | Some tool/back links are under 44px. | Later polish pass. |

Live verification used the authenticated isolated Playwright state plus curl. Browser checks confirmed audit 25 rows/no mobile overflow, announced regression/quality HTTP 500 states, 27 test images with non-empty alternatives and frame-specific actions, CNN report no overflow/blank headers, and disabled Focus actions with Refresh available. The two remaining medium findings are broader campaigns rather than watering/control changes.

## 2026-07-10 serial-fixer merge — CSP, calibration, archive performance, authentication

Reviewed all 35 raw findings in `orchestrator/findings-0.json` through `findings-5.json`. The shared missing favicon, existing CSP-readiness campaign, and unauthenticated API-response finding were deduplicated/refined; 32 findings were newly folded into the backlog. None was watering behavior.

| Page | Severity | Status | Category | Expected vs Actual | Resolution / RCA |
|------|----------|--------|----------|--------------------|------------------|
| authenticated site | high | open — broader RCA | strict CSP migration | Report-Only still permits inline script/style, so telemetry cannot inventory the hundreds of inline dependencies that strict enforcement would break. | Director should schedule extraction by shared shell and page family, deploy a strict reporting candidate, then enforce after reports are clean. |
| shared shell / mobile navigation | high | open — broader RCA | CSP inline assets | Shared application and camera navigation partials depend on inline CSS/JS. | Extract versioned shared assets as part of the CSP campaign. |
| dashboard / forecast / map / moisture-sim / chart pages / camera family | high | open — broader RCA | page-family CSP blockers | Inline handlers, style attributes, inline controllers, and dynamic HTML prevent strict CSP; Focus additionally needs `blob:` images and Moisture Simulation needs an explicit same-origin weather strategy. | Migrate page families under the CSP campaign; avoid piecemeal policy enforcement that would disable display and manual UI. |
| calibrate | high | fixed (`9af367d`) | keyboard focus visibility | Interactive controls had no visible keyboard focus state. | Added a high-contrast 3px `:focus-visible` indicator. |
| calibrate | high | fixed (`9af367d`) | accessible labels | Battery and soil calibration inputs had placeholder-only names. | Added persistent programmatic labels, including sensor context. |
| calibrate | high | fixed (`9af367d`) | repeated controls | Repeated Set Dry, Set Wet, Save, and delete actions did not identify their target. | Added sensor/reading-specific accessible names. |
| calibrate | high | fixed (`9af367d`) | destructive action safety | Per-reading delete acted immediately and was ambiguously named. | Added exact-reading confirmation and unique names. |
| calibrate | med | fixed (`9af367d`) | dynamic status | Polling and operation feedback had no live-region semantics. | Status/toast output is now exposed through restrained live regions. |
| calibrate | med | fixed (`9af367d`) | chart alternative | Battery canvas had no accessible name or description. | Added a descriptive image role/name; the saved readings table remains the numeric alternative. |
| calibrate | med | fixed (`9af367d`) | contrast | Secondary, advice, drift, corrected-voltage, and active navigation text failed AA. | Darkened shared secondary/mobile text tokens and retained dark advice variants. |
| calibrate | med | fixed (`9af367d`) | zoom/reflow | At simulated 200% zoom the document and fixed mobile navigation widened to 718px. | Mobile navigation now uses five shrinkable grid tracks; main content remains fluid. |
| calibrate | med | fixed (`9af367d`) | loading/error states | Failed calibration APIs left indefinite Loading and enabled Live Mode. | HTTP failures now render announced Retry states; Live Mode is success-gated. |
| cam/archive | high | fixed (`b347cd2`) | image efficiency | Initial view loaded about 35 full 800×600 images at roughly 35-way concurrency though rendered around 211×158. | Initial cards are capped at 12 and image URLs are assigned only near the viewport; live initial viewport made zero image requests. |
| cam/archive | med | fixed (`b347cd2`) | main-thread responsiveness | Cold sample captured a 192ms task overlapping initial thumbnail loading. | Capped card construction and deferred image assignment remove the initial image burst. |
| cam/archive | med | fixed (`654d34d`) | request efficiency | Initial view additionally decoded about 693KB from full dashboard and usage APIs. | Shared navigation no longer fetches the full dashboard payload when no status consumer exists; archive usage remains visible, page-specific data. |
| cam/archive | med | fixed (`7694d82`) | caching | Warm reloads retransferred stable archive images because the global no-cache hook overwrote route headers. | Authenticated file-addressed images now use private one-day immutable caching; dynamic responses remain no-store. |
| cam/archive | med | fixed (`b347cd2`) | error-state usability | Archive HTTP failure showed only “failed” while mutation and load controls stayed enabled. | Failure now shows Retry, disables Smart Reprocess actions, and hides Load more; forced live 500 verification passed. |
| protected GET APIs | med | fixed (`b347cd2`) | authentication response semantics | Unauthenticated JSON clients receive a 302 HTML-login redirect rather than JSON 401. | Every `/api/*` request now returns JSON 401 when unauthenticated; curl verified status and content type. |
| protected pages | med | fixed (`b347cd2`) | return-to-page navigation | Login redirects discard the original safe same-origin deep link. | Safe relative paths and queries survive login through popup and redirect modes; unsafe targets are rejected. |
| cam-device | med | fixed (`34e6af3`) | telemetry schema mismatch | The page called `slice()` on the API's `{frames,pings}` series object and rendered `LOAD FAILED`. | The controller now explicitly selects `series.frames`, validates HTTP status, and leaves a recoverable table error on failure. Live browser verification rendered 13 telemetry rows with no load-failed card. |

| sensor-history API | med | fixed (`b347cd2`) | input validation / request bounding | Unsupported, malformed, duplicate, and unknown query values could return huge or misleading responses. | Type, sensor index, and the four UI-supported ranges are allowlisted; invalid and duplicate inputs return 400. |
| sensor-history | med | fixed (`b347cd2`) | range correctness | The 24h response used a midnight-floored cutoff and returned about 42.5 hours. | Read-only display query now compares T-separated timestamps against an exact rolling-hour cutoff. `dashboard.py` changed only for authentication and displayed history reporting. |
| sensor-history | high | fixed (`b347cd2`) | HTTP error recovery | HTTP failures left the page indefinitely loading while freshness claimed success. | HTTP status is checked, loading always settles, an announced error and Retry appear, and freshness updates only after success; forced live 500 verification passed. |
| sensor-history | med | fixed (`b347cd2`) | malformed payload / stale-data recovery | Invalid JSON/schema rendered as a successful empty window with stale cards. | Each response must contain valid timestamps and finite readings; malformed data enters the explicit recoverable error state. |
| sensor-history | med | fixed (`b347cd2`) | chart/text alternative synchronization | Hidden sensors and Moisture % mode were not reflected in the textual chart summary. | The summary derives from visible series and the active field; live None selection announces “No sensors are selected.” |
| sensor-history | med | fixed (`b347cd2`) | responsive reflow / zoom | Sensor cards widened the document to 478px at the audited narrow zoom equivalent. | Grid tracks and cards can shrink to 100% with zero minimum-content overflow. |

Low findings retained for later polish: camera capture latency variability; archive cache/performance baseline; route-specific authenticated CSP minimization; dashboard data-image removal; Calibration landmarks/table refinements; and Login loading/keyboard recovery.

## 2026-07-10 serial-fixer merge — reading provenance and label robustness

Reviewed all 23 raw findings in `orchestrator/findings-0.json` through `findings-5.json`. Thirteen page/issue findings were new; strict-CSP and restart-availability reports were deduplicated into the existing broader campaigns. None was watering behavior.

| Page | Severity | Status | Category | Expected vs Actual | Resolution / RCA |
|------|----------|--------|----------|--------------------|------------------|
| authenticated site | high | open — broader RCA | deployment availability | Planned service restarts caused brief origin-refused 502s across unrelated pages and APIs. | Display code cannot provide zero-downtime origin switching; director should schedule deployment/proxy RCA. |
| authenticated site | high | open — broader RCA | strict CSP / script and DOM sinks | Inline controllers/handlers and inconsistent API-to-HTML rendering block strict CSP across dashboard, Forecast, Map, Moisture Simulation, and camera pages. | Deduped into the staged CSP extraction campaign; page-family migration and regression coverage are required. |
| authenticated site | med | open — broader RCA | strict CSP / inline styles | Hundreds of inline/dynamic style attributes block `style-src 'self'`. | Deduped into the staged CSP extraction campaign. |
| dashboard camera | med | open — broader RCA | CSP image source | Authenticated camera blobs require `blob:` if CSP is enforced. | Add the scheme only as part of the strict policy rollout after controller migration. |
| cam/reading | high | open — broader RCA | reading provenance | Carried validated locks are labeled as the current frame's Reading even when the frame produced no fresh read. | Requires a common live/archive serializer contract separating frame model output, accepted lock, source, confidence, and disposition. Existing uncommitted camera-pipeline work overlaps this contract; do not patch the template alone. |
| cam/reading | high | open — broader RCA | cross-endpoint consistency | Oracle detail can expose a rolled-back model result as Reading while the accepted monotonic lock differs. | Same serializer/provenance RCA; label model output and accepted/rejected/constrained disposition separately. |
| cam/reading / archive | med | open — broader RCA | durable identity | Volatile live RIDs expire and archive rows have no compatible detail identity. | Persist a stable frame identity and archive fallback as part of the camera data-contract campaign. |
| cam/reading | med | open — broader RCA | timestamps | Detail/live timestamps omit date and timezone offset. | Return and display canonical ISO timestamps with offsets in the common serializer campaign. |
| cam/reading mobile | med | open — overlapping work | More sheet initial state | The reading page exposed the mobile dialog immediately. | Uncommitted user changes already modify this template and shared navigation; preserve them and verify/commit in the camera data-contract campaign. |
| cam/labels | high | fixed (`035a019`) | fail-safe controls | Mutations stayed enabled during loading, errors, empty, and uncertain data. | Controls now start disabled and enable only after a fully valid, non-empty response. |
| cam/labels | med | fixed (`035a019`) | error recovery / schema | HTTP, JSON, and envelope failures lacked safe Retry; malformed envelopes rendered undefined values. | Status/schema validation now fails closed into an announced GET-only Retry state. |
| cam/labels | med | fixed (`035a019`) | partial/duplicate records | One malformed record collapsed the list and duplicate records produced repeated actions. | Records validate and deduplicate independently; valid subsets render read-only with rejected/duplicate counts. |
| cam/labels | med | fixed (`035a019`) | large response | Hundreds of image-heavy cards rendered at once. | Initial captures are capped at 100 and rendering is paged in 100-card batches, bounding initial image/control construction while retaining access to all returned records. |

Low findings retained: Focus cold-load latency variance and Labels explicit empty-state polish (the latter now has a clear message and disabled actions as part of the safety fix).

## 2026-07-10 serial-fixer merge — regression traceability

Reviewed all 19 raw findings in `orchestrator/findings-0.json` through `findings-5.json`. Seventeen camera-contract, strict-CSP, deployment-availability, health-probe, and favicon findings were deduplicated into the existing broader campaigns or low backlog. Two medium regression/quality findings were new. None was watering behavior.

| Page | Severity | Status | Category | Expected vs Actual | Resolution / RCA |
|------|----------|--------|----------|--------------------|------------------|
| cam/regression | med | fixed (`143b21b`) | aggregate provenance | The page uses the evaluated `?flag=1` response, but the canonical unevaluated response omits `cnn`, `cnn_conf`, `pass`, and per-record error, so the displayed aggregate is not reproducible from the record set users are told about. | The live page identifies its evaluated endpoint, derives the aggregate from displayed `frames[].pass`, and warns on server/client total mismatch. Browser and authenticated API verification matched 0/9. |
<!-- serial-fixer-round-2026-07-10-b -->

## 2026-07-10 serial-fixer merge - camera resilience and review accessibility

Reviewed all 35 raw findings in `orchestrator/findings-0.json` through `findings-5.json`. Twenty-four page/issue findings were newly folded into the backlog; strict-CSP, deployment-gap, favicon, reading-provenance, archive-identity, and shared-mobile-navigation reports were deduplicated against existing campaigns. No finding was watering behavior.

| Page | Severity | Status | Category | Expected vs Actual | Resolution / RCA |
|------|----------|--------|----------|--------------------|------------------|
| cam/reading / latest / archive / quality | high | open - broader RCA | durable frame identity rollout | Live detail and latest-frame responses cannot be joined durably to archive/quality records; legacy quality evidence has no usable fallback. | Extend the existing camera data-contract campaign with immutable frame identity, RID/source mapping, and explicit null for irrecoverable legacy rows. Current overlapping camera-pipeline work makes a template-only patch unsafe. |
| cam/reading | med | open - broader RCA | secondary model-output attribution | An on-demand CNN guess can appear beside a carried/no-read frame without model version, evaluation time, or explicit not-accepted disposition. | Resolve with the common model-output versus accepted-state serializer campaign. |
| cam/archive | med | open - broader RCA | displayed attribution | Cards omit durable ID, filename, raw output, confidence, and disposition needed to attribute the shown accepted value. | Resolve with the same archive/detail provenance contract. |
| origin/service-wide | high | open - broader RCA | request saturation | Waitress queue depth reached 69, although the bounded sample completed without 5xx. | Infrastructure RCA: add per-route latency/queue telemetry and correlate the next failure with CF-Ray and handler activity. This is not a display fix. |
| health probes | med | open - broader RCA | unauthenticated liveness | Health routes require authentication, so external monitoring cannot distinguish a healthy auth boundary from application failure. | Add a deliberately minimal non-sensitive liveness contract in the infrastructure/auth campaign. |
| cam/cnn-report | med | open | error recovery | A failed report GET leaves empty tables and no Retry action. | Render an announced error with a GET-only Retry action. |
| cam/cnn-report | low | open | current navigation semantics | CNN Report lacks current-page state and reloads itself when activated. | Add current-page semantics; same-URL suppression is optional polish. |
| cam/test-audit | high | open | incomplete benchmark total | The page calls `n=300`, calls that subset the exact held-out set, and the API omits the full candidate count; `n=500` proved at least 500 valid frames. | Sort the complete candidate set before slicing, return total/subset metadata, and label the displayed result as a subset. |
| cam/test-audit | med | open | loading reliability | The 30-second client deadline can abort a normal request. | Raise the display deadline above observed normal latency and retain Retry; schedule cached/batched evaluation if saturation persists. |
| cam/test-audit | med | open | timestamp / provenance | Cards expose only encoded filenames, not explicit capture time, offset, frame ID, or source. | Return and display parsed ISO capture metadata and provenance without changing model/training behavior. |
| cam/quality | med | open | timestamp ambiguity | Recent rows discard the date and timezone by displaying only the time substring. | Display the complete labeled timestamp. |
| cam/quality | low | open | mobile table overflow | Recent reads is wider than a 390px content area. | Use an explicitly labeled horizontal scroll region or responsive cards. |
| cam/review | high | open | accessible mutation names | Forty correction fields are unnamed and every mutation button is simply Save; cards lack frame-specific grouping. | Add semantic card grouping, frame-specific headings/labels, and consequence text. |
| cam/review | high | open | failed GET shown as empty | A queue HTTP 500 becomes `Nothing to review`, falsely presenting failure as successful empty state. | Enforce HTTP/schema success, then show an alert and GET-only Retry on failure. |
| cam/review | med | open | bypass / main landmark | Keyboard users must traverse repeated navigation before 80 form controls. | Add a skip link and main landmark. |
| cam/review | med | open | image inspection equivalence | Review images are not keyboard-expandable and are weakly associated with their controls. | Add a keyboard-operable full-frame link and semantic card association. |
| cam/review | med | open | mobile targets / active nav | Tool links, Back, inputs, and buttons are below 44px; Review lacks current-page semantics. | Increase page control targets and mark Review current; shared tool-strip redesign belongs to the navigation campaign. |
| cam/review | med | open - shared RCA | closed mobile dialog semantics | Closed More content is exposed and lacks complete modal/focus behavior. | Deduped into the existing shared mobile-navigation campaign; verify overlapping partial changes first. |
| cam/review | med | open | status announcements | Loading and eventual queue state are not announced. | Keep a persistent polite status region and use an alert for failures. |
| cam/review | low | open | queue navigation efficiency | Forty cards create 80 consecutive mutation controls with no filtering/paging. | Add read-only paging/filtering in a later polish pass. |
| cam/review / test-audit | low | open | dynamic HTML maintenance risk | Escaping currently blocks observed injection, but extensive HTML sinks are fragile. | Migrate to DOM construction during the strict-CSP/page-family campaign. |
| authenticated camera pages | med | open - broader RCA | overbroad CSP sources | Google/data allowances are present on same-origin-only camera pages. | Tighten page-family directives only after inline controller/style extraction is complete. |
| cam/review / test-audit / cnn-report | med | open - broader RCA | inline presentation blocks CSP | Runtime style mutation and style attributes require unsafe-inline. | Fold into the staged strict-CSP extraction campaign rather than piecemeal changes. |
| cam/review / cnn-report | low | open | shared error-state consistency | Camera GET failures do not consistently expose alert and Retry behavior. | Covered by the high review and medium CNN Report fixes above. |

### Resolved by the serial fixer

| Page | Severity | Status | Category | Resolution |
|------|----------|--------|----------|------------|
| cam/review | high | fixed (`aca51e6`) | accessible mutation names | Cards are semantic articles with frame headings; correction inputs are labeled and Save names the target frame and consequence. |
| cam/review | high | fixed (`aca51e6`) | failed GET shown as empty | HTTP/schema failures now enter an announced error with GET-only Retry; only a successful empty array says nothing is pending. |
| cam/review | med | fixed (`aca51e6`) | bypass / main landmark | Added a first-focusable skip link and `main` queue landmark. |
| cam/review | med | fixed (`aca51e6`) | image inspection equivalence | Each image is a keyboard-operable full-size link associated with its frame article. |
| cam/review | med | fixed (`aca51e6`) | status announcements | Loading, per-card save feedback, results, and failures use persistent status/alert semantics. |
| cam/cnn-report | med | fixed (`c0e03f7`) | error recovery | HTTP, schema, and API errors now show an announced GET-only Retry action. |
| cam/quality | med | fixed (`e2d75d6`) | timestamp ambiguity | Recent rows display the complete API timestamp in a semantic `time` element rather than discarding date/offset context. |
| cam/test-audit | high | fixed (`304a254`) | incomplete benchmark total | The reporting API now sorts the complete valid candidate set before slicing and returns `total_count`, `limit`, and `has_more`; the page explicitly labels its deterministic subset. |
| cam/test-audit | med | fixed (`304a254`) | loading reliability | The recoverable client deadline is 60 seconds, above the observed 22-second successful response. Continued latency belongs to the saturation/caching RCA. |
| cam/test-audit | med | fixed (`304a254`) | timestamp / provenance | The display-only API returns frame ID, ISO timestamp with offset, and source parsed from the permanent filename; cards show all three. |

All four deployed page families returned authenticated HTTP 200 after restart. The test-set API returned 992 total held-out frames and a deterministic one-row sample with `captured_at`, `frame_id`, and `provenance`. Python compilation, live `/login`, and SHA-256 server/local parity passed. The requested in-app Playwright runtime was not exposed by tool discovery, so browser-DOM automation could not be rerun; authenticated live HTML/API smoke checks were used instead. `dashboard.py` was edited only in the read-only benchmark-report serializer and does not participate in irrigation balance, control, or schedule generation.
| cam/quality ↔ cam/regression | med | fixed (`ef8fa37`) | cross-page traceability | Quality recent rows expose only a timestamp and values, while regression uses durable bank filenames; shared-frame membership cannot be checked deterministically. | New evaluations persist and return the oracle-bank filename; the Quality table displays it and labels pre-migration rows `legacy — unavailable`. Live API returned `frame_file` on all 30 rows and the browser rendered the new Frame column. `cnn_metrics.py` and `dashboard.py` changes are reporting-only and do not affect irrigation. |

## 2026-07-10 serial-fixer merge — provenance, availability, calibration, and shared navigation

Reviewed all 36 raw findings in `orchestrator/findings-0.json` through `findings-5.json`. Thirty page/issue findings were newly folded into the backlog; six camera-identity, strict-CSP, availability, mobile-layout, and error-recovery reports were deduplicated into existing campaigns. No finding was watering behavior.

| Page / area | Severity | Status | Category | Resolution / RCA |
|---|---|---|---|---|
| camera reading / archive / quality APIs | high/med | open — broader RCA | durable identity, provenance, timestamps, serializer consistency | Extend the existing camera data-contract campaign. A template-only patch would misstate accepted-lock/model-output provenance and overlap current camera pipeline work. |
| origin / service / health | high/med | open — broader RCA | worker starvation, intermittent 5xx, monitoring and telemetry | The auditors reproduced queue saturation and watchdog restarts. This is infrastructure, not display code; schedule a bounded-query/worker/telemetry RCA. |
| authenticated pages | high/med | open — broader RCA | strict CSP, API-to-HTML sinks, inline styles, blob/weather origins | Staged Report-Only CSP cannot be enforced until page-family DOM construction and inline presentation are migrated. Forecast/Map stored-XSS sinks are high priority in that campaign. |
| shared mobile More sheet | med | fixed (`ca7076a`) | modal semantics / focus containment | Added `aria-modal`, background inerting, forward/reverse focus trapping, Escape closure, and focus restoration. |
| shared camera tool strip / Focus / Cam Device | med | open — overlapping work | target size, skip links, current page | `_meternav.html` and camera templates contain unrelated in-progress user changes; preserve them for the shared camera-navigation campaign. |
| calibrate | high | fixed (`febdd5e`) | partial history failure shown as empty | History now requires HTTP/schema success and shows a distinct unavailable state instead of `no history`. |
| calibrate | high | open — broader RCA | active calibration provenance divergence | Config/history disagreement and same-second test writes require a committed-revision/source contract; do not infer which calibration is authoritative in display code. |
| calibrate | med | fixed (`86ca12b`) | invalid drift interval | Captures less than 12 hours apart are labeled too close for drift analysis; zero is no longer rendered as missing or used for advice. |
| calibrate / sensor APIs | med | open — broader RCA | sample freshness and sensor identity | Add sensor-index timestamps/staleness to a common read-only serializer; `/api/sensors` must stop presenting irrigation-zone IDs as sensor IDs. |
| audit | high | fixed (`f408c64`) | parser/query failures reported OK | MAX/count and timestamp parse failures now return `ERROR` with the failed reason. |
| audit | med | open | timezone semantics | Reporting timestamps still need explicit offsets and date-only rows need calendar-date labeling. |
| water usage | high | fixed (`6c03322`) | unbounded reporting range | Rolling requests above seven days now fail quickly with JSON 400 before ledger synchronization. `dashboard.py` change is display/reporting-only. |
| water usage | med | fixed (`8871e04`) | mobile layout | Range controls collapse to one shrinkable column; live 390px document width is 390px. |
| water usage | med | fixed (`8871e04`) | error recovery | Failed GETs expose an explicit GET-only Retry action that repeats the selected query. |

Backend file edited: `server-prod/dashboard.py`, only for audit/calibration/water-usage reporting and client markup. No irrigation balance, schedule, runtime, precipitation, valve, MAD, or configuration logic changed.

## 2026-07-10 serial-fixer reconciliation - timestamp-normalized audit reporting

Re-read all 37 findings in the current `orchestrator/findings-*.json` files. Every item was already represented by the immediately preceding provenance/availability/calibration/navigation merge, so no duplicate rows were added. No finding was watering behavior.

| Page / area | Severity | Status | Category | Resolution / RCA |
|---|---|---|---|---|
| audit API / page | high | fixed (`48f541f`) | mixed timestamp formats hide newest records | Audit reporting now orders timestamp values by SQLite `julianday()`, filters rolling windows by normalized instants, and fails closed if any candidate timestamp is null or unparseable. This is a read-only display/report query change in `dashboard.py`; it cannot affect irrigation state or decisions. Live API returned all 25 audited tables with zero query errors. |
| audit API / page | med | open - broader RCA | timezone, date-grain, and DST semantics | Explicit-offset serialization and separate calendar-date metrics require a coordinated reporting-contract migration across the affected APIs; retain as one reporting/timezone campaign. |
| water usage and other reporting APIs | med | open - broader RCA | shared timestamp normalization | Migrate each read-only history query only after its stored timestamp semantics are inventoried; a blanket replacement could reinterpret naive local timestamps incorrectly around DST. |
| calibration / sensor APIs | high/med | open - broader RCA | authority, calibrated-value divergence, freshness, identity | Requires a shared, versioned calibration/sample serializer. Do not infer authority from same-second history rows or patch one page to conceal cross-endpoint disagreement. |
| camera identity / provenance | high/med | open - broader RCA | immutable identity and accepted-state attribution | Remains in the common camera data-contract campaign; template-only fixes would misstate accepted lock versus model output. |
| shared camera navigation | med | open - overlapping work | current-page semantics, mobile targets, dialog isolation, same-URL activation | `_meternav.html`, Focus, and Cam Device contain unrelated in-progress user changes. Preserve them for the shared-navigation campaign rather than overwriting the active worktree. |
| service / reporting availability | high/med | open - broader RCA | worker starvation, restart churn, telemetry, health boundary | Infrastructure and authentication-boundary campaign; not a display-only correction. |

Browser re-verification could not run because the required in-app browser runtime was not exposed and the repository fallback lacked its Playwright dependency. Compile, guarded pre/post server diff, timestamped remote backup, service restart, `/login` smoke, authenticated `/api/audit`, and SHA-256 parity all passed. One current high finding was fixed; 31 current high/medium raw findings remain logged in broader or overlapping campaigns.

## 2026-07-10 serial-fixer follow-up - rolling ranges and dashboard error sink

Re-read all 37 current raw findings; all were already merged, so no duplicate rows were added. No finding was watering behavior.

| Page / area | Severity | Status | Category | Resolution / RCA |
|---|---|---|---|---|
| weather/cycle history APIs | high | fixed (`f5ffe4d`) | one-hour range inclusion | The read-only report queries now compare T-separated stored timestamps with T-separated local cutoffs. Live one-hour results begin at 19:01 rather than midnight. `dashboard.py` changed only reporting queries and cannot affect balances, schedules, runtimes, valves, or watering decisions. |
| dashboard sensor test | high | fixed (`8e74df4`) | API-to-DOM HTML injection | API/fetch error text is rendered through `textContent` in a constructed span instead of `innerHTML`. |
| camera provenance, calibration authority, timezone/DST contract, strict CSP extraction, service saturation, shared camera navigation | high/med | open - broader RCA | coordinated contracts / infrastructure | These remain broader campaigns: piecemeal display changes would invent missing provenance, reinterpret naive timestamps, overlap active shared-template work, or cross into service/auth architecture. The service-saturation failure is broader infrastructure RCA evidence, not a display defect. |

Both deployments used timestamped backups, `/login` smoke tests, authenticated live API checks where applicable, and pre/post SHA-256 parity. The required in-app browser runtime was not exposed in this session, so browser interaction verification could not be performed.

## 2026-07-10 serial-fixer merge - forecast safety/accessibility, cost precision, and time contracts

Reviewed all 25 findings in `orchestrator/findings-0.json` through `findings-5.json`. Twenty-three page/issue findings were newly folded into the backlog; the service-availability burst and favicon 404 were deduplicated into existing campaigns. None was watering behavior.

| Page / area | Severity | Status | Category | Resolution / RCA |
|---|---|---|---|---|
| forecast panels | high | fixed (`ba8cdf5`) | API-controlled HTML, attribute, inline-handler, configuration, option, and outcome sinks | Zone names and errors are escaped; IDs and percentages are validated/clamped; stored times are allowlisted; data-controlled inline actions were replaced with listeners; filter options use DOM text; outcomes are allowlisted. |
| forecast comparison | high/med | fixed (`ba8cdf5`) | keyboard tabs, landmarks, labels, announcements, structure, equivalence, contrast, targets | Tabs are real named controls with exposed selection, the page has skip/main structure, filters are labeled and 44px tall, dates are headings, result announcements are concise, exclusions are explained, the impossible filter is gone, the client-derived metric is named `No-water predictions`, and foreground tokens are darker. |
| forecast error state | med | fixed (`ba8cdf5`) | unsafe error sink | Error text is escaped before entering the existing card renderer. |
| costs | med | fixed (`5dcd056`) | tier-rate precision | Per-gallon rates render five decimal places, preserving all distinctions in the live tariff. |
| costs | low | open | snapshot/display conversion drift | Render daily disclosure gallons directly from `snapshots[].used_gal` in a later low-priority pass. |
| origin/service-wide | med | open - broader RCA | navigation burst 502s | Deduped into the existing saturation/deployment-availability campaign; display code cannot repair tunnel/upstream failure. |
| water-usage instant ranges | high | open - broader RCA | DST-aware bounds and half-open range contract | Requires one ZoneInfo-aware reporting range resolver and a coordinated meter-ledger/report serializer migration. Do not patch isolated labels while bounds remain ambiguous. |
| watering/weather/cycle history reports | high | open - broader RCA | naive local instants and repeated-hour aggregation | Migrate stored/query instants and hourly buckets to an offset-aware common contract; read-only reporting issue, but broad enough for the existing timezone campaign. |
| daily summary / balance history | med | open - broader RCA | calendar-date range contract | Replace hour-floor conversion with explicit resolved calendar bounds in the reporting-contract campaign. |
| audit report | med | open - broader RCA | offset and elapsed/calendar semantics | Offset-aware serialization and distinct elapsed-24-hour versus calendar-day labels remain part of the shared reporting migration. |
| water usage | low | open | range-state explanation | After the range resolver exists, show resolved offset, timezone, duration, and safe API validation detail. |

Live `/forecast`, `/api/forecast`, `/api/forecast-vs-actual?days=30`, `/costs`, and `/api/water-cost` returned authenticated HTTP 200. JavaScript syntax checks, timestamped remote backups, service restarts, `/login` smoke tests, and SHA-256 server/local parity passed for both deployments. No Python backend file was edited. The required in-app browser runtime was not exposed by tool discovery; the auditors' authenticated Playwright evidence was retained and live authenticated HTML/API verification was used after each fix.

## 2026-07-10 serial-fixer merge - reporting time, availability, and safe rendering

Reviewed all 29 findings in `orchestrator/findings-0.json` through `findings-5.json`. Three distinct display defects were newly folded into the queue; the remaining reports were deduplicated into the existing timezone/reporting-contract, strict-CSP, and service-saturation campaigns. The two watering-behavior reports (manual Grapes and sync-group execution) remain logged only in the dedicated DO NOT FIX section above.

| Page / area | Severity | Status | Category | Resolution / RCA |
|---|---|---|---|---|
| flow | med | fixed (`511efaf`) | HTTP failure shown as healthy | The GET now checks HTTP status. Failure clears stale zone/sample data, neutralizes alerts, and presents a GET-only Retry action. |
| flow | med | fixed (`511efaf`) | API-controlled class/HTML contexts | Text escaping now covers quotes and API state/severity values map through fixed CSS-class allowlists. A full DOM-construction migration remains part of strict CSP. |
| audit | high | fixed (`c3a8c91`) | API-controlled HTML injection | Summary pills, table rows, empty state, and error state are constructed with DOM nodes and `textContent`; status is allowlisted before class assignment. `dashboard.py` changed only the audit reporting page renderer. |
| water-usage / reconcile / cost | high/med | open - broader RCA | offset-aware half-open ranges and downstream reconciliation | Requires the existing common ZoneInfo-aware reporting resolver and meter-report contract. Isolated label/query edits could reinterpret naive historical instants. |
| weather / watering / cycle history / flow | high/med | open - broader RCA | timezone, repeated-hour, bucket and range semantics | Migrate these read-only reporting APIs under the existing timestamp-contract campaign; preserve repeated DST instants and publish resolved bounds/grain. |
| moisture-sim / daily-summary / balance-history | med | open - broader RCA | calendar dates, DST conversion, and history coverage | Use local calendar-date parsing and a common explicit coverage contract; do not change balance credit or schedule generation. |
| audit | high/med | open - broader RCA | offset, date-grain, elapsed-window, and accessible table semantics | Split instant and calendar-date reporting semantics and serialize explicit offsets as part of the coordinated reporting migration. |
| origin / health / request telemetry / restart | high/med | open - broader RCA | worker starvation and availability attribution | Infrastructure RCA remains required for bounded reporting, queue/in-flight telemetry, readiness, and serving overlap. It is not a display-only fix. |
| authenticated shell / water-usage / flow / audit | high/med | open - broader RCA | strict CSP extraction and remaining dynamic HTML | Deduplicated into the staged page-family CSP migration. Do not enforce the current policy until inline controllers/styles and remaining sinks are extracted and regression-tested. |

The in-app browser runtime required by the browser skill was not exposed by tool discovery. The raw auditors' authenticated Playwright reproduction was retained; fixes were verified with syntax/compile checks, timestamped remote backups, service restarts, live `/login` smoke checks, and SHA-256 server/local parity. The first restart briefly returned the already-known origin 502 before recovering; this was recorded under the existing restart-availability RCA.

## 2026-07-10 serial-fixer merge - benchmark completeness, CNN insights, and range contracts

Reviewed all 25 findings in `orchestrator/_work/round-01/findings-0.json` through `findings-5.json`. Seven distinct page/issue refinements were newly folded into the backlog; the other 18 findings were deduplicated into existing reporting-timezone, calibration-authority, shared-camera-navigation, favicon, and service-saturation campaigns. None was watering behavior.

| Page / area | Severity | Status | Category | Resolution / RCA |
|---|---|---|---|---|
| cam/review | med | fixed (`58f16db`) | frame-specific form naming | The correction label now includes the immutable frame ID, so multiple textboxes have distinct accessible names. |
| cam/review | med | fixed (`b888e0d`) | current-page state | Review exposes `aria-current="page"`; authenticated Playwright confirmed it live. |
| cam/review | med | fixed (`8609ed2`) | touch targets | Back, correction input, Save, skip link, and Meter tools links have at least 44px targets. |
| cam/review | med | fixed (`8609ed2`) | mobile Meter tools navigation | The existing horizontal tool strip centers the current Review link; live 390px Playwright measured Review visible at x=147 and no document overflow. |
| api/cam/test-set | high | fixed (`b011406`) | complete benchmark pagination | Added bounded `offset`, `next_offset`, stable file ordering, ordering version, and one-based candidate rank. Live pages 1 and 501 returned distinct frames/ranks from all 992 candidates. `dashboard.py` is a read-only camera-report serializer change only. |
| cam/test-audit | med | fixed (`3c093a6`) | timeout accuracy | The loading message now matches the actual 60-second abort deadline. |
| cam/test-audit | med | fixed (`8e2d83c`) | subset reproducibility | The page displays candidate rank, ordering key, ordering version, and complete-population total; authenticated Playwright reconciled 300 of 992. |
| cam/cnn-report | high | fixed (`8690126`) | missing insights integration | Added an independently loaded/validated Operational insights panel with generated timestamp, archive quality, trend, backfill state, reader, independent Retry, and stale clearing. |
| cam/cnn-report | med | fixed (`27227e0`) | loading announcement | The persistent report status node contains the initial loading message and remains the completion/error announcer. |
| cam/cnn-report | med | fixed (`4bbd84a`) | parse/schema errors | Invalid JSON and malformed envelopes now produce controlled, distinct messages. Playwright interception verified both paths and successful recovery. |
| water-usage | med | fixed (`829a0b9`) | desktop responsive regression | Shrinkable grid tracks contain exact-range controls. Live Playwright measured `scrollWidth=1440` at a 1440px viewport and retained 390px mobile containment. |
| water-usage / reconcile / cost | high/med | open - broader RCA | DST-aware bounds, half-open membership, bucket origin, error envelopes, reconciliation and billing provenance | Five raw findings deduplicate into the shared ZoneInfo reporting-contract campaign. Root cause is mixed naive-local, epoch, calendar-day, and closed/half-open primitives across meter ledger and reporting APIs. Implement one resolver/migration; isolated query or label patches could reinterpret historical readings. |
| calibration / sensor APIs and pages | high/med | open - broader RCA | active revision authority, drift provenance, sensor identity, sample freshness | Four raw findings deduplicate into the versioned calibration/sample serializer campaign. Root cause is independent dry/wet history rows plus config-held active values without a shared revision ID or observation timestamp. A page patch cannot truthfully choose authority. |
| health / schedule telemetry | med | open - broader RCA | public liveness attribution and route-local latency telemetry | Two findings deduplicate into the service-saturation campaign. `/api/schedule-7day` latency is route-local in this capture, but queue/lock/cache timing is absent; public liveness also cannot distinguish auth from process health. This is infrastructure/observability work, not display code. |

Low findings were retained without entering the fix queue: closed mobile-dialog tree isolation, benchmark-filter empty state, CNN/favicon console hygiene, calibration reproducibility/empty-state detail, and the site-wide favicon 404. Every deployment used a timestamped server backup, restart, public `/login` smoke test, and SHA-256 parity check.

## 2026-07-10 serial-fixer merge - round 02 Focus, Costs, and camera identity

Reviewed all 20 findings in `orchestrator/_work/round-02/findings-0.json` through `findings-5.json`. Seven page/issue findings were newly folded into the backlog; thirteen were deduplicated into the existing camera data-contract, shared-navigation, reporting-timezone, and low-priority Costs items. None was watering behavior.

| Page / area | Severity | Status | Category | Resolution / RCA |
|---|---|---|---|---|
| cam/focus | high | fixed (`0796e73`) | mobile clipping | The page, grid children, canvas, and long controls can shrink within the viewport. Live Playwright at 390px measured document width 390px and canvas right edge 384px. The horizontal Meter tools strip keeps Focus visible and now exposes a scrollbar cue. |
| cam/focus | med | fixed (`0796e73`, `56212e9`) | target size and current page | Back, buttons, selects, and Meter tools links are at least 44px despite the later shared stylesheet; Focus exposes `aria-current="page"`. Live Playwright found no short controls and centered the 83px Focus destination at x=153. |
| cam/focus | med | fixed (`0796e73`) | state announcements and canvas equivalence | Added a polite textual ROI/orientation/rotation/padding summary, a failure alert, canvas instructions, keyboard focus, and slider equivalence. Black rotation padding is explicitly distinguished from browser clipping. |
| costs | med | fixed (`8ff744b`) | snapshot provenance | Daily bars and accessible values identify auto, bill, interpolated, and carried sources; gaps anywhere between real rows are described as interpolation. The disclosure uses authoritative `used_gal` and an existing all-zero series renders as data instead of missing history. |
| costs | med | fixed (`8ff744b`) | cross-report reconciliation | The page names whole-house meter movement as bill-reconciliation authority and identifies `/api/billing` as a separate irrigation-planning estimate with the 150 ft³ indoor baseline. |
| costs | med | fixed (`8ff744b`) | historical provenance | Every history row now distinguishes paid paper bills, completed derived cycles with their start/end sources, and the open-cycle live-meter projection. |
| camera reading / archive / quality APIs | high/med | open - broader RCA | immutable identity, accepted-state provenance, durable detail, timestamps, model/confidence/correction attribution | Nine raw findings deduplicate into the camera data-contract campaign. The live RID is volatile, Archive and Quality use independent keys, and legacy quality rows have no frame attribution. A UI-only patch cannot truthfully create joins, accepted authority, capture times, model versions, or correction history. Existing uncommitted camera-pipeline work was preserved. |

The incidental low Costs drift and zero-state defects were corrected by `8ff744b`; the low Focus padding/clipping explanation was corrected by `0796e73`. Deployments used timestamped remote backups, live `/login` smoke tests, authenticated API/browser checks, and post-deploy SHA-256 parity. No Python backend file was edited.

## 2026-07-10 serial-fixer merge - round 03 security, comparison availability, and camera reflow

Reviewed all 41 findings in `orchestrator/_work/round-03/findings-0.json` through `findings-5.json`. Four page/issue findings were newly folded into the backlog; the remaining 37 deduplicate into the existing camera identity/provenance, calibration authority, timezone/reporting contract, strict-CSP, service saturation/liveness, and watering-behavior campaigns. The two manual-Grapes reports deduplicate into the Watering-behavior (DO NOT FIX) section above; the sync-group display report describes the already-logged control/schedule mismatch and remains there as well.

| Page / area | Severity | Status | Category | Resolution / RCA |
|---|---|---|---|---|
| dashboard | high | fixed (`58ff0e8`) | API-controlled zone-name DOM injection | The embedded yard-map tooltip now builds child spans and assigns the API name with `textContent`. Live interception changed four injected elements into four literal tooltip strings. |
| map | high | fixed (`dc26f35`) | API-controlled zone-name DOM injection | The zone-list renderer escapes `z.name` at its HTML sink. Live interception changed the injected element into literal text. |
| forecast-vs-actual | high | fixed (`b3bc749`) | normal response exceeds client deadline | The display deadline is now 60 seconds while retaining abort and Retry. A live intercepted 16.1-second response rendered all comparison content without timing out. |
| cam/quality | med | fixed (`ed137b7`) | mobile table overflow | Both tables are contained in named, keyboard-focusable horizontal scroll regions. Live 390px verification measured document width 390px; table overflow remains inside 358px regions. |
| camera identity / provenance | high/med | open - broader RCA | immutable identity, authority, accepted-state and migration contract | Eight reports refine the existing camera data-contract campaign. A template patch cannot create durable joins, model/version authority, correction revision, or recover irrecoverable legacy frame identity. |
| calibration / sensor APIs | high/med | open - broader RCA | active revision authority, sensor identity and observation freshness | Five reports deduplicate into the versioned calibration/sample serializer campaign; current config, append-only history, and samples lack one common revision/identity contract. |
| water usage / reconcile / costs / weather and history APIs | high/med | open - broader RCA | offset-aware instants, DST folds, half-open bounds, calendar buckets and coverage | Fifteen reports deduplicate into the common ZoneInfo-aware reporting-contract campaign. Isolated query/label changes could reinterpret naive historical timestamps. |
| origin / health / schedule telemetry | high/med | open - broader RCA | public liveness and route/worker saturation attribution | Three reports deduplicate into the infrastructure campaign for minimal public liveness plus bounded queue/route telemetry. This is not a display-only correction. |
| authenticated shell and page families | high/med | open - broader RCA | strict CSP extraction, reporting, and remaining dynamic HTML | Six CSP reports and the blocked-QA report deduplicate into the staged script/style extraction campaign. The confirmed dashboard and Map name sinks are separately queued above. |
| forecast / moisture-sim / flow / audit | med | open - broader RCA | shared date, timezone, coverage, and schedule presentation contracts | Cross-page date and coverage reports remain coordinated reporting work. The sync-group mismatch is already logged as watering behavior because the authoritative schedule itself reports independent execution. |

Low-only loading-state polish remains outside this pass.

All four display-only checkpoints were deployed separately after timestamped remote backups. JavaScript parsing, live authenticated Playwright reproduction/regression checks, `/login` smoke tests, and local/server SHA-256 parity passed. No backend `.py`, watering engine, schedule generator, configuration, database, or valve path was edited.

## 2026-07-10 serial-fixer merge - round 04 camera tools and health

Read all 35 findings in `orchestrator/_work/round-04/findings-0.json` through `findings-5.json`. Eighteen page/issue findings were newly folded into the backlog; seventeen deduplicate into the existing camera identity/provenance, shared camera navigation, site favicon, and service saturation/liveness campaigns. No finding was watering behavior.

| Page / area | Severity | Status | Category | Resolution / RCA |
|---|---|---|---|---|
| camera reading / archive / quality APIs | high/med | open - broader RCA | immutable frame identity, carried/accepted provenance, quality joins, versioned rollups | Six findings refine the existing camera data-contract campaign. Capture, OCR, archive, and evaluation use independent identifiers; a display patch cannot truthfully invent durable joins or accepted-state lineage. |
| cam/regression | high | fixed (`574c892`) | rapid active-link navigation | The current Regression tool link is `aria-current` and non-navigating, preventing duplicate same-URL requests. |
| cam/regression | med | fixed (`574c892`) | accessible row actions and image inspection | Remove controls name their frame and each image has a named keyboard-operable full-size link. |
| cam/regression | med | fixed (`574c892`) | filter, sort, pagination | Read-only filter/result/sort controls, clear action, announced counts, and bounded paging are live. |
| cam/convergence | high/med | fixed (`df0db34`) | bounded loading, chart equivalence, reflow, status/table semantics, target size | The GET has a 15-second timeout and Retry, failures clear stale output, the chart is named with a synchronized semantic table, the canvas is contained, disagreements are textual, audit semantics are complete, and controls meet 44px. |
| shared camera tool strip | med | open - overlapping work | current-item visibility and target size | `_meternav.html` contains unrelated in-progress user changes. Preserve it for the existing shared-navigation campaign; page-local current semantics may be added without replacing that work. |
| cam-device | med | fixed (`da1872b`) | failure/schema isolation | Status and telemetry settle independently; HTTP classes, malformed JSON, invalid schema, and legitimate empty arrays have distinct states. |
| cam-device | med | fixed (`da1872b`) | polling bandwidth and overlap | The page fetches one displayed hour, uses a single self-scheduled poll, and pauses while hidden or unloaded. |
| health history reports | high | open - overlapping reporting fix | T-separated rolling cutoff | Three read-only history queries compare T-separated stored values with space-separated cutoffs. The required query fix overlaps uncommitted `database.py` work and must be staged/deployed without absorbing unrelated changes. |
| origin / application health | high/med | open - broader RCA | authenticated liveness, worker saturation, layer attribution | The monitor accepts redirects/rejections as healthy and lacks queue/worker/probe telemetry. This is the existing infrastructure/observability campaign, not a UI-only correction. |
| Health dashboard | med | partially fixed (`4a6c8f5`); broader RCA remains | verdict, freshness, uptime, loading, incidents | Application-process and ESP32 uptime are named separately with young-process precision, and the healthy banner is scoped to ESP32 reboot state. Freshness, layer attribution, chart failure states, and incident grouping require the common health/availability contract. |

Low-only malformed-response wording, loading skeleton, convergence empty-state polish, corrupted Regression glyph, and favicon reports remain outside this pass.

## 2026-07-10 serial-fixer merge - round 05 health windows, forecast truth, and camera landmarks

Read all 48 findings in `orchestrator/_work/round-05/findings-0.json` through `findings-5.json`. Ten distinct page/issue refinements were added after deduplication; the camera identity, calibration/sensor authority, reporting-timezone, and availability findings refine existing broader campaigns. The Grapes automatic-watering report deduplicates into Watering-behavior (DO NOT FIX) and was not changed.

| Page / area | Severity | Status | Category | Resolution / RCA |
|---|---|---|---|---|
| health history APIs | high/med | fixed (`f05a1b3`) | T-separated rolling cutoffs | Connectivity, system health, server health, and sensor-flatline reporting now use canonical T-separated cutoffs in every raw/downsample branch. Live one-hour results fell from the reported all-day sets to 20, 126, and 7 rows. `database.py` changed only read-only reporting queries. |
| forecast | med | fixed (`ef47987`) | authoritative dates and fail-safe loading | Forecast now resolves dates from `/api/schedule-7day`, validates both GETs, has a 15-second deadline, announced loading, unknown rather than invented balance values, and an alert with GET-only Retry. |
| camera Regression / Quality / Labels / Archive | med | fixed (`08fc3e9`) | missing main landmark | Each page now exposes one stable `main` landmark. |
| shared camera tool strip | high/med | open - overlapping work | completeness, current item, same-URL activation, target size | `_meternav.html` contains pre-existing uncommitted user work. The complete shared correction was not committed or deployed because doing so would absorb unrelated changes; schedule this with the existing shared-navigation campaign. |
| moisture-sim | med | open - broader RCA | schedule failure and all-zone payload fan-out | Failure truthfulness and batching span the large shared controller and a new compact read-only endpoint. Coordinate them without changing the schedule generator or client prediction model. |
| Health dashboard / availability | high/med | open - broader RCA | layer attribution, probe history, stale/error chart states | Requires bounded edge/origin/worker telemetry plus a common availability envelope; generic process success cannot establish tunnel or worker health. |
| camera identity / provenance | high/med | open - broader RCA | immutable frame and accepted-state contract | Still requires durable frame/inference IDs and append-only acceptance history; a display patch cannot invent the missing joins. |
| calibration / sensor reporting | high/med | open - broader RCA | active revision, physical identity, sample freshness | Still requires a common revision and observation envelope across config, calibration history, and sensor samples. |
| usage/history/cost reporting | high/med | open - broader RCA | offset-aware instants and calendar coverage | Remains the common ZoneInfo-aware half-open reporting contract; isolated changes could reinterpret naive historical values. |

All deployed files were copied from committed HEAD after timestamped remote backups. Python compilation, service restart, public `/login`, authenticated live page/API checks, and post-deploy SHA-256 parity passed. The required in-app browser runtime was not exposed by tool discovery, so the auditors' authenticated browser evidence was retained and live authenticated HTTP checks were used. The failed first deploy attempt copied no files because its staging paths were wrong; the service restart succeeded, the helper was corrected in `57b95db`, and the verified deployment then completed.

## 2026-07-10 serial-fixer merge - round 06 failure truth and camera navigation

Read all 27 findings in `orchestrator/_work/round-06/findings-0.json` through `findings-4.json`. Ten distinct page/issue refinements were added after deduplication. Shared camera navigation and Moisture Simulation batching refine existing campaigns. The Grapes auto-watering/scoring report is the already-logged real watering-behavior defect and was not changed.

| Page / area | Severity | Status | Category | Resolution / RCA |
|---|---|---|---|---|
| dashboard | high | fixed (`984e26c`) | API-controlled activity detail injection | Both recent-activity HTML sinks escape `recent[].detail`; injected markup renders literally. Template-only display fix. |
| cam-device | med | fixed (`219c8a7`) | invalid telemetry measurements | Rows now require valid timestamps, plausible RSSI, and finite non-negative gap/transfer/uptime/reconnect values; invalid payloads fail the panel closed. |
| forecast comparison | med | fixed (`4b4ac58`) | loading/empty announcements and busy state | Loading and empty states are polite status messages and the comparison container exposes its busy state. |
| forecast comparison | med | fixed (`4b4ac58`) | incomplete schema shown as empty | Any rejected comparison row now produces an explicit data error with the rejected-row count instead of a valid-empty claim. |
| forecast | med | fixed (`4b4ac58`) | keyboard tab semantics | Tabs use roving tabindex and support Left/Right, Home, and End with focus, selection, and activation synchronized. |
| forecast comparison | med | open | 200% zoom reflow | The auditor measured 428px content at a 390px viewport only at 200% zoom. Requires isolated browser geometry to identify the remaining 38px source; do not add speculative global clipping. |
| cam-device API | med | open - overlapping reporting fix | one-hour telemetry cutoff | `cam_telemetry.ts` is T-separated while the read-only query generates a space-separated cutoff, returning ~22 hours. The four-query correction is isolated, but `database.py` contains substantial unrelated in-progress work; deploy it from a clean coordinated patch. |
| moisture-sim | high/med | open - broader RCA | stale/invented schedule, duplicate waves, mixed generations, validation | Deduplicates into the existing atomic all-zone snapshot campaign. One compact read-only snapshot plus generation metadata, schema validation, bounded failure, and one initialization owner are required; do not alter the schedule generator or client watering model. |
| shared camera navigation / reading detail | med | open - overlapping work | completeness, current state, landmarks, responsive discovery, targets | Deduplicates into the existing shared-navigation campaign. `_meternav.html`, `cam_hub.html`, and `cam_reading.html` contain active unrelated changes, so this pass did not absorb or deploy them. |
| cam hub | med | open - overlapping work | card focus visibility | The one-line focus treatment belongs in dirty `cam_hub.html`; land it with the shared-navigation work rather than committing unrelated edits. |
| map | med | open | polling failure retains interactive stale state | On refresh failure, disable or clearly label old markers/list as last-known data with timestamp and Retry. |
| map | med | open | partial schema becomes authoritative false state | Validate required dashboard fields and render Unknown rather than inferring offline/planned from missing values. |

No backend `.py` file was committed or deployed. Three template-only display checkpoints used timestamped live backups, service restarts, `/login` smoke tests, and local/server SHA-256 parity. The in-app browser runtime was not exposed; authenticated auditor Playwright reproductions were retained and no unavailable browser rerun is claimed.

## 2026-07-10 serial-fixer merge - round 07 stale-state safety and camera reflow

Read all 31 findings in `orchestrator/_work/round-07/findings-0.json` through `findings-5.json` (including the zero-finding responsive RCA file). Five distinct page/issue refinements were added after deduplication; the remaining reports refine the existing telemetry-window, calibration authority, reporting-timezone, dashboard polling, shared camera navigation, and strict-CSP campaigns. None was watering behavior.

| Page / area | Severity | Status | Category | Resolution / RCA |
|---|---|---|---|---|
| map | high | fixed (`184aebd`) | stale operational state and schema validation | The GET now requires HTTP success and a complete typed dashboard envelope before an atomic render. Failure retains the last valid generation, labels it unavailable with the last-update time, disables valve controls and map markers, and exposes GET-only Retry. Live interception of HTTP 500 produced the unavailable state and successful recovery restored 10 rows and nine Run controls. |
| cam hub | high | fixed (`4344d01`) | 200% zoom reflow | The grid track can shrink below 260px. Live Playwright at a 195px viewport measured both document and viewport at 195px. |
| cam hub | med | fixed (`4344d01`) | tile focus visibility and Device discovery | Tiles have an explicit focus-visible outline and the hub now links to Camera Device. |
| shared camera tool strip | med | fixed (`cf20110`) | current semantics, same-URL activation, discovery, and target size | Device is discoverable; links are at least 44px; exactly one current destination exposes `aria-current`; same-URL activation is suppressed; reading-detail routes map to Usage. Live 390px Playwright verified all contracts and zero navigation requests on current-link activation. |
| camera reading detail | med | open - overlapping work | landmark, return path, detail controls, and async recovery | `cam_reading.html` still contains unrelated in-progress work. The shared strip portion is fixed, but the page-local `<main>`, listing return path, 44px controls, busy/live state, 404-vs-500 distinction, and GET-only Retry remain for the coordinated camera-detail change. |
| cam-device telemetry API/UI | high/med | open - overlapping reporting fix | T-separated half-open cutoff, parameter validation, bounds/freshness metadata | The all-day one-hour defect is confirmed in four read-only `database.py` predicates. That file contains thousands of unrelated in-progress changes, so this pass did not absorb or deploy it. Coordinate a clean read-only reporting patch, then label and validate the authoritative one-hour America/Los_Angeles window in the UI. |
| map and dashboard | med | open - broader RCA | shared generation/provenance state machine | Map now fails closed. The dashboard still needs the common validated generation adapter, retained last-success provenance, stale labeling, disabled operational controls, bounded polling, and Retry. |
| calibration / sensor reporting | high/med | open - broader RCA | active revision authority, identity, sample freshness, timezone and drift provenance | Seven reports deduplicate into the versioned calibration/sample serializer campaign. A UI patch cannot truthfully select an active revision or invent missing physical identity and observation provenance. |
| authenticated shell / costs / water-usage | high/med | open - broader RCA | strict CSP extraction and chart fallback | Five reports deduplicate into the staged page-family CSP campaign: externalize shared/page controllers and styles, replace dynamic inline styles, then add semantic table fallbacks before enforcing the policy. |
| history/reporting GET APIs | med | open - broader RCA | shared T-separated cutoff and timezone contract | Additional moisture, rain, weather, and sensor history predicates remain part of the coordinated ZoneInfo-aware half-open reporting migration; isolated edits could reinterpret naive historical timestamps. |

All three display-only checkpoints were committed and deployed separately from committed HEAD after timestamped remote backups. Public `/login`, authenticated live API/browser checks, service restarts, and SHA-256 local/server parity passed. No backend `.py`, irrigation engine, balance, schedule generator, watering parameter, database, or valve behavior was changed.

## 2026-07-10 serial-fixer merge - round 08 atomic snapshots and sensor bounds

Read all 35 findings in `orchestrator/_work/round-08/findings-0.json` through `findings-5.json`, including the zero-finding authentication file. Two distinct sensor performance/bounds issues were newly folded into the backlog. The moisture snapshot, camera-reading detail, dashboard/Map generation safety, calibration authority, sensor identity/provenance, and reporting-timezone findings refine existing open campaigns. The Grapes automatic-watering report deduplicates into the Watering-behavior (DO NOT FIX) section and was not changed.

| Page / area | Severity | Status | Category | Resolution / RCA |
|---|---|---|---|---|
| sensor-history | med | fixed (`4a6dfc6`) | bounded history rendering | Long display series are capped at 2,000 evenly sampled points while preserving both endpoints. Live 90-day sensor 0 fell from 10,747 rows / 542,521 bytes to 2,000 rows / 100,968 bytes, and the browser rendered four 2,000-sample summaries. |
| sensor-gaps API | med | fixed (`15f697b`) | strict query bounds | The route now requires exactly one integer `zone` and `hours`, rejects unknown parameters, bounds hours to 1-2,160, and validates the configured zone range. Live billion-hour and duplicate-hour requests return 400. |
| moisture-sim | high/med | open - broader RCA | atomic all-zone snapshot and bounded failure | Existing campaign: one read-only generation-bearing snapshot must replace per-zone fan-out, duplicate initialization/schedule requests, mixed caches, and stale fallback. Do not change the schedule generator or watering predictor. |
| camera reading detail | high/med | open - overlapping work | held-reading truth, distinct failures, recovery, labels, announcements, reflow and targets | Existing coordinated detail-page change in dirty `cam_reading.html`; suppress or explicitly qualify held values when `fresh_read=false`, distinguish 404/5xx/invalid/timeout/session states, and complete accessible recovery/inspection controls. |
| dashboard and Map | high/med | open - broader RCA | validated generation, command authority and last-success provenance | Map already fails closed on transport/schema failure, but both pages need one non-overlapping generation-aware snapshot adapter. Dashboard controls must disable on uncertainty; Map controls must remain disabled when ESP32 command authority is absent. |
| calibration / sensor reporting | high/med | open - broader RCA | active revision, durable physical identity, observation provenance, timezone and valid drift | Existing campaign: mutable endpoint config and independent history cannot identify an atomic active revision, and legacy samples lack durable identity/revision provenance. Do not invent those joins in the UI. |

Low-only coordination, structure, optional-field, image-alt, and mobile-overflow polish remains outside this pass.

The two fixes changed only `dashboard.py`: both are read-only reporting/API presentation paths and cannot alter water balance, credits, scheduling, valve commands, runtimes, precipitation rates, MAD, or configuration. Deployment used backup `dashboard.py.bak.round08-20260710-224122`; compile, public `/login`, authenticated live API checks, authenticated 90-day browser rendering, and SHA-256 server/local parity passed. The remaining 26 round-08 high/medium raw findings are broader or overlap dirty coordinated files; their RCA campaign groupings are recorded above rather than patched with invented provenance or changes to watering logic.
