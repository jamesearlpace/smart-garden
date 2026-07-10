# Smart-Garden UX Audit — Findings Backlog

Maintained by Codex during UX audit runs (see `codex-ux-audit-prompt.md`).
Phase 1 = audit only (fill this table, no code changes). Phase 2 = fix high/med.

**Severity:** high (broken / wrong data shown) · med (usability hurts, still works) · low (polish — NOT fixed this pass)
**Status:** open · fixed · logged-only

## Findings

| Page | Severity | Status | Category | Expected vs Actual | Proposed fix |
|------|----------|--------|----------|--------------------|--------------|
| moisture-sim | high | open | console/resource | Recurring `502` console errors were previously observed on load (2026-07-10 14:26/14:50/18:46), but the failure is not currently reproducible. | RCA/broader intermittent dependency issue: 12 instrumented live reloads produced zero failed responses and zero console errors; every first-party endpoint and all four jsDelivr chart dependencies returned 200. No display change is justified without a captured failing URL. |
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
| moisture-sim | high | open | external CDN dependency failure | An instrumented cold load captured `net::ERR_CONNECTION_RESET` for all four required jsDelivr chart libraries while first-party requests stayed 200. | Self-host pinned chart dependencies and add an explicit dependency-failure state. |
| moisture-sim | med | open | missing dependency error state | Required chart-library failure has no visible error or recovery guidance. | Show a retryable visualization-unavailable state. |
| dashboard / sensor-history / water-usage / costs / camera charts | med | open | shared dependency blast radius | Checked chart pages import Chart.js from jsDelivr, so the captured outage can blank several visualizations. | Self-host pinned audited chart assets. |
| costs | med | open | error state | A simulated water-cost API 500 renders as valid-empty `No data yet`. | Check HTTP status and show a retryable error. |
| costs | med | open | mobile layout | At 390px Bill history makes the document 448px wide. | Contain or reflow the table. |
| costs | med | open | chart accessibility | Three charts lack accessible names and equivalent keyboard-readable values. | Name charts and provide synchronized text alternatives. |
| costs | low | open | mobile navigation accessibility | More lacks state semantics, exposes closed content, and ignores Escape. | Add semantics, inert hiding, and Escape support. |
| costs | low | open | navigation accessibility | Selected Water Cost links lack `aria-current`. | Mark active links programmatically. |
| site-wide | low | open | console/resource | Favicon requests return 404 on multiple pages. | Serve a favicon or correct the reference. |
| flow | med | open | stale current alert | Idle samples followed orphan event 1077, but UI still called its 3.26 gpm alert ongoing. | Suppress or label display alerts stale by sample freshness. |
| flow / water-usage | med | open | connectivity inconsistency | Pages stay at `Connecting...` while APIs/dashboard show online. | Use shared online/offline/stale status. |
| water-usage / flow | med | open | estimate clarity | Usage uses configured rates while Flow shows learned rates; `est` hides the basis. | Label configured-rate estimates and rate used; do not alter control/accounting. |
| flow | med | open | error/stale state | A simulated flow API 500 leaves urgent prior data looking current. | Mark retained data stale and neutralize alerts. |
| forecast | high | open | time to usable / API latency | Under throttling, tiny API responses took about 7.7s; usable at 8.75s. | Profile timing, decouple health, and bound loading. |
| forecast | med | open | intermittent latency | Cold request took 1.594s versus 247-267ms later. | Instrument cold-path queuing/computation. |
| forecast | low | open | responsiveness | Render produced 52ms and 135ms long tasks. | Batch DOM construction. |
| forecast | low | open | cache efficiency | Static CSS retransfers with cache BYPASS. | Add versioned static caching. |
| forecast-vs-actual | high | open | stale/loading state | Refresh leaves old results looking current with no timeout. | Mark updating/stale and bound requests. |
| forecast-vs-actual | med | open | HTTP errors | Non-401 failures become secondary JSON/property errors. | Check response status and show specific recovery. |
| forecast-vs-actual | high | open | malformed response | Partial/null/invalid records can break the whole view. | Validate/normalize and skip invalid rows visibly. |
| forecast-vs-actual | high | open | accuracy truthfulness | Trusted totals and percentages can be impossible or inconsistent. | Recompute/cross-check from validated displayed rows. |
| forecast-vs-actual | med | open | empty semantics | All zero-row states claim no forecast data and offer snapshot creation. | Distinguish no snapshots, no scored rows, and filter no-match. |
| forecast-vs-actual | med | open | retry/recovery | Failures lack Retry and loaded state blocks recovery. | Add accessible retry/reload and reset failure state. |
| forecast-vs-actual | low | open | accessibility | Dynamic states and div tabs lack live/tab semantics. | Add live regions and proper tab behavior. |
| cam/convergence | med | open | DOM injection | API fields are interpolated into `innerHTML`. | Use textContent and validate same-origin image URLs. |
| authenticated site | med | open | security headers | Pages/APIs lack standard defense-in-depth headers. | Add compatible headers; stage CSP around inline content. |
| camera charts / water-usage | low | open | script supply chain | CDN scripts lack SRI and CSP restriction. | Self-host or pin with SRI. |
| cam/archive | low | open | inline active content | Repeated inline onclick handlers expand CSP surface. | Replace with delegated listeners. |
