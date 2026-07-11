# Schedule Viewer display fix — 2026-07-11

## Root cause and display semantics

- The page started two competing initial data loads. A slower response wave could overwrite the first schedule/chart generation. Initial loading now has one owner and starts after vacation state is known.
- `Gallons / 7d` ignored each event's API `est_gallons` and recomputed every event from configured GPM and runtime. It now totals event gallons, falling back to GPM only when an event has no estimate. Read-only live reconciliation found material differences, including Southwest `392.6` vs `416.3` gallons and Grapes `116.8` vs `78.7` gallons.
- Completed sub-minute runs were forced to `1 min`. The schedule API now carries exact display seconds and the grid shows seconds below one minute. The filtered runtime used for same-day projection remains separate and unchanged.
- Chart tooltip moisture impact divided applied inches by physical root depth. It now divides by the zone's plant-available-water bucket (`taw_in`), matching the chart's percentage axis. This changes labels only.
- When the display projection moved a zone to the evening eligibility window, it advanced the chart/schedule cursor from the old daytime timestamp. The display cursor now advances from the rendered start time.

## Boundary finding

Live data reports Garden (DB zone 7 / display Zone 8) as manual and excludes it from `/api/schedule-7day`, as required. Live config reports Grapes (DB zone 8 / display Zone 9) as automatic, so the endpoint includes it. Restoring Grapes to manual is a control/configuration change and was intentionally not made under this display-only authority.

## Verification and deployment

Pre-deploy: `dashboard.py` compiled; extracted inline JavaScript passed `node --check`; zone-label guard and `git diff --check` passed. The allowed files were clean at baseline, so no pre-existing edits overlap this patch. No control code, config, or database data was changed.

Deployment, live safety query timestamps/results, hashes, rollback files, and commit/push status are recorded below after deployment.
