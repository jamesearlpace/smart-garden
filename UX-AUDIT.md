# Smart-Garden UX Audit — Findings Backlog

Maintained by Codex during UX audit runs (see `codex-ux-audit-prompt.md`).
Phase 1 = audit only (fill this table, no code changes). Phase 2 = fix high/med.

**Severity:** high (broken / wrong data shown) · med (usability hurts, still works) · low (polish — NOT fixed this pass)
**Status:** open · fixed · logged-only

## Findings

| Page | Severity | Status | Category | Expected vs Actual | Proposed fix |
|------|----------|--------|----------|--------------------|--------------|
| moisture-sim | high | open | console/resource | Recurring `502` console errors on load (most recent 2026-07-10 18:46, also 14:26/14:50). A fetched resource intermittently 502s. | Identify which fetch 502s (check Network tab / dashboard.py route); handle failure gracefully + fix the failing endpoint. |
| moisture-sim | high | open | data-accuracy | App logs `[chart-engine drift]` warning: 14 days where chart per-event credit disagrees with engine `balance.irrigation_mm` by >5% (deltas up to 142%/122%). Chart and engine tell different stories. | Reconcile chart per-event credit calc with engine balance so the displayed chart matches the source of truth. DISPLAY side only — do not change the engine's watering math. |
| moisture-sim | med | open | correctness | "Next Expected Watering: Fri Jul 10 at 1:20 AM … today" shown at 12:12 PM, but history shows it already watered 1:48 AM today. "Next" watering is in the past / already happened. | Compute "next expected" from now-forward; if today's run already fired, show the next future run, not a past time. |
| moisture-sim | low | open | clarity | Zone dropdown shows "Zone 2 — Front Yard B [selected]" while URL is `#zone=1` (0-indexed URL vs 1-indexed label). Potentially confusing when sharing links. | Confirm intended; consider aligning URL param to the 1-indexed UI number or documenting the offset. |
| dashboard | med | open | dead-link | "Recent Activity → View All →" link points to `href="#"` — clicking does nothing. | Point it at the real activity/history route (or remove if none exists). |
| dashboard | med | open | data-accuracy | Cross-page inconsistency: dashboard "Recent Activity" shows Zone 1 "Watered in progress" at 12:05 PM, but moisture-sim still shows "Next Expected Watering 1:20 AM today". The two pages disagree about current watering state. | Ensure "next watering" and "recent activity" read from the same live source; reconcile so pages agree. |
| dashboard | low | open | clarity | Soil sensors show extreme test values (Sensor 0 = 1% raw 2649, Sensor 2 = 100%) labeled "test sensor". Real-looking % on the main dashboard may mislead. | Visually distinguish test-mode readings (badge/muted styling) so they aren't mistaken for calibrated soil moisture. |
| water-usage | med | open | dead/wrong-link | "← Back to dashboard" link points to `/#cam` (meter-camera anchor), not the dashboard `/`. | Change href to `/`. |
| water-usage | high | open | data-accuracy | Event list shows "0 min" for spans that are clearly longer — e.g. Zone 5 `05:58:08 -> 06:55:49 · 0 min · est 0.0 gal` (57 min elapsed) and `06:56:12 -> 07:02:39 · 0 min`. Duration/volume computed as 0 despite real elapsed time. | Fix duration/gallons computation for these events (likely meter-gap or zero-delta handling) so elapsed time isn't shown as 0 min. |
| water-usage | med | open | loading-state | Main content shows "Loading…" and "Checking for a slow leak…" — verify the chart actually renders and isn't stuck (may be tied to the 502s). | Confirm data loads; add a real error/empty state instead of an indefinite "Loading…". |
| water-usage | low | open | usability | Event picker is a single flat dropdown with 100+ options across many days — hard to scan. | Group by day (optgroup) or add a date filter. |

## Watering-behavior (DO NOT FIX — log for James)

Anything that is actually wrong irrigation/control behavior, not a display bug.

| Page/Area | What's wrong | Why it's control-logic, not display |
|-----------|--------------|-------------------------------------|
| moisture-sim | "Depth Per Cycle 0.06\"" vs target 0.5–0.75" — cycles apply ~10x too little (chronic under-watering). | Irrigation output (runtime × precip rate), not display. Under active tuning — do not change from a UX pass. |
| water-usage / schedule | Many watering events fire 10:15 AM–12:05 PM (Zone 1 running at 12:05 PM) despite the 00:00–10:00 turf window. | Watering-window enforcement / recovery behavior = irrigation engine, not display. Verify with James before touching. |

## Resolved this run

- _(none yet)_
