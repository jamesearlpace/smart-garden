# AGENTS.md — Smart Garden (read this first)

You are working on a **LIVE solar-powered irrigation system**. Real valves open and
real water flows based on this code. A bad change can over-water, flood, or starve a
real lawn and garden. Treat every change as production.

Public site: https://sprinklers.savagepace.com · Server: `192.168.0.109` (the "Acer")
· Service: `smart-garden-server` (Flask + waitress, port 5125).

## Golden rules for this repo

1. **Full access — act autonomously.** You may `ssh acer` (Tailscale) / `acer-local` (LAN), `scp`, `sqlite3`, `curl`, restart services, deploy, and `git` freely. `deploy.ps1` is the convenient path but not required. Investigate, edit, deploy, verify end-to-end without stopping for confirmation.
2. **DB safety: back up before writing.** `cp x.db x.db.bak.<ts>` before modifying any `*.db`; stop the service before editing a DB in use. Reads/SELECTs anytime.
3. **`config.yaml`:** `yaml.dump` strips comments — warn if rewriting it programmatically.
4. **Verify before done:** compile/tests where present; smoke-test the live `/login` after deploy.
5. **numpy is NOT in the server venv.** Never `import numpy` in deployed code
   (`irrigation.py`, `dashboard.py`, `database.py`, `server.py`, `billing.py`).
   Pure-Python only (the battery calibration fit is hand-rolled least-squares).

## Where the code lives (3 mirrors; the server is the source of truth)

| Location | Role |
|----------|------|
| `c:\MyCode\smart-garden\server-prod\` | Git-tracked snapshot — **edit here** (this repo) |
| `c:\MyCode\smart-garden-server-live\` | Working mirror (NOT git) — the human syncs it |
| `~/smart-garden-server/` on `192.168.0.109` | The running service |

Deployable files: `irrigation.py`, `dashboard.py`, `database.py`, `server.py`,
`billing.py`, and `templates/*.html`. The real code is in **`server-prod/`** — ignore
the decoy files at the repo root (`irrigation.py.acer`, `irrigation.py.current`).

## Architecture facts (don't break these invariants)

- **The ET water-balance model is the brain.** Soil sensors are observe-only "eyes"
  (`soil_sensor: null` on every zone) — they do NOT drive watering. Do not wire
  sensors into watering decisions.
- **Shared config dict:** `server.py` passes ONE `config` dict to both
  `IrrigationEngine` and the dashboard app, so a route doing `config["x"]=y` is
  instantly visible to the engine (no restart). `write_config_atomic()` only
  persists to disk; it does not replace the in-memory dict.
- **Three predictors must stay in sync:** the engine (`irrigation.py`), the
  client-side JS in `templates/moisture_sim.html`, and the snapshot writer
  (`save_daily_forecast_snapshot`). Change watering logic in one → change all three
  or the schedule/forecast will lie.
- **The schedule has ONE source of truth: `GET /api/schedule-7day`** (dashboard.py).
  The old client-side `predictZoneSchedule` is dead for display — do not revive it.
- **Sync-groups:** `front_yard:[0,1]`, `backyard_grass:[2,3,4,5,6]` water together
  (deep + infrequent). Garden(7)/Grapes(8) are `auto_mode:False` (manual drip).
- **A manual-mode zone must NEVER be shown as if the engine auto-waters it** — this
  is a recurring bug class (banner, status table, forecast tab, snapshot).

## Code footguns

- SQL column is `watering_event.trigger_reason` (not `reason`).
- DB filename uses a HYPHEN: `smart-garden.db`.
- `sensor_log.ts` is `T`-separated; `datetime(?, '+3 hours')` returns space-separated
  → string compares silently fail. Use
  `strftime('%Y-%m-%dT%H:%M:%S', ts, '+N hours')`.
- `sensor_log.zone_id` = sensor index (0–3); `watering_event.zone_id` = irrigation
  zone (0–8). Do not conflate them.
- `/api/moisture-data` `waterings[]` is NOT time-sorted (reduce by `start_ts`);
  `balances[]` IS date-sorted.
- `irrigation.py` has mixed em-dash encoding (`ΓÇö` vs `—`) — match the surrounding
  context when editing strings.

## Water measurement acceptance contract

When James asks whether sprinkler water measurement, OCR, Water Usage, or zone GPM is working, do not validate only the API integrity flag, verified-run record, or median panel. Follow `WATER-USAGE-SUCCESS-CRITERIA.md` against the exact event URL/window.

A pass requires all of these user-visible checks:

1. The first chart has nonzero usage bars during the valve-open interval.
2. The bars total the accepted physical gallons and imply the accepted run GPM.
3. The cumulative usage line rises by the same gallons.
4. The bottom meter-reading line increases during watering by the corresponding register delta; bars with a flat meter line are a failure.
5. Click meter-line points in the middle of the run and compare the displayed value with the attached camera image. The digits must match exactly or be demonstrably very close and explicitly sourced; a stale or unrelated value is a failure.
6. The zone run median/integrity report agrees with those charts.

If any check fails, say measurement is not working end to end and create/update a dated `BUG-*.md` record with the URL, event ID, timestamps, API evidence, and photo comparison. Never call the system healthy from derived/summary data alone.

## Deeper context (read only if you need it)

- `smart-garden-journey.md` — current state + full history.
- `professional-audit-2026-06-07.md` — framework-first review and graded findings.
