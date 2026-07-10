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
| authenticated site | med | open | security headers | Pages/APIs lack standard defense-in-depth headers. | Add compatible headers; stage CSP around inline content. |
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
