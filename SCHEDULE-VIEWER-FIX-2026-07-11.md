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

Deployment completed once at approximately `2026-07-11 08:40 PDT`. Live rollback files:

- `/home/jamesearlpace/smart-garden-server/dashboard.py.bak.schedule-viewer-20260711-084018`
- `/home/jamesearlpace/smart-garden-server/templates/moisture_sim.html.bak.schedule-viewer-20260711-084018`

The service was restarted once and remained active. Pre-restart baseline at `08:40:17 PDT`: maximum watering event ID `778`, open events `0`. Immediate post-restart query at `08:40:37 PDT`: open events `0`, events after ID `778` `0`, new events with `soil_before` from 45–55 `0`; authenticated `/api/status` returned `active_zones=[]`. Delayed recheck at `08:41:03 PDT` returned the same zero counts. The post-restart log showed Garden skipped because manual mode disables auto-watering and contained no error, traceback, or watering-start message.

Live `/login`, authenticated `/moisture-sim`, and authenticated `/api/schedule-7day` returned `200`. The API represented the 24-second South event as `seconds=24`, `minutes=0.4`; manual Garden was absent from schedule columns. Local/live SHA-256 hashes matched: `dashboard.py` `0fe12665e35f24e32fadd73d45730aaff9eee07b96921c33e22373a178e1001c`; `moisture_sim.html` `6bb95530cf1393e3efb54d899a41439d1a53237efda1d34a8e0f1718d915ed1d`.

Implementation commit `644152b` was pushed before deployment. This note's deployment evidence was committed separately after the live checks. No control code/config changed and no database write was performed.
