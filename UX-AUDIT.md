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
