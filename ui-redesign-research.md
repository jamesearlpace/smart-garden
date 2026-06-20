# Smart Garden — UI/UX Redesign Research & Feature Backlog

> Captured 2026-06-20 after a competitive teardown of the best smart-irrigation
> dashboards. Purpose: guide a cleanup of the app's sprawling navigation without
> losing any features, and stage a backlog of new features to add on top of the
> cleaner shell. Read this before starting any redesign work.

**Guiding principle from the research:** the clean structure is what *lets* us keep
adding features without the app getting messy again. Every new feature should slot
into one of a small number of tabs — never become another orphan page.

---

## 1. Competitive teardown — the five leaders

| Product | Closest to us? | Standout idea | Lesson |
|---|---|---|---|
| **Hunter Hydrawise** | **Yes** — has flow-meter + leak/electrical monitoring like ours | "**Transparency**" status cards that explain *why* watering did/didn't happen in plain language: *"Watered yesterday," "Aborted due to high daily rainfall," "Next run tomorrow 6 AM."* | Show one human sentence, not raw mm/MAD math. This is our forecast-vs-actual + skip-reason data, presented like a person would say it. |
| **Rachio** | Consumer benchmark | Zones are **named cards with photos**, each with a **Quick Run** button. Schedule adjustments are named cards: *Rain Skip, Seasonal Shift, Heat Wave Boost.* "Track usage in minutes — not complicated metrics." | Identity over numbers; one obvious action per zone; hide engineering. |
| **RainMachine** | Cloud-independent, ET-based | Whole app is a **flat 5–6 item nav**: Dashboard · Zones · Programs · Settings · Weather (+ Devices). Dashboard "monitors everything" (gallons, temp, rain, activity) on one screen. | Nobody serious has more than ~6 destinations. The Home screen answers "is it OK + what's next" at a glance. |
| **Netro** | Consumer | Dead-simple, weather-first framing. | Lead with the answer, bury the engineering. |
| **OpenSprinkler** | **Closest DIY** (open hardware) | Program **preview** + graphical run logs; one schedule, visualized and simulatable. | One schedule view, previewable — not three predictors. |

### Cross-cutting principles (true across all five)
1. **Flat nav, 5–6 destinations max.** Each has exactly one home.
2. **A single "Home/Dashboard"** = now + next + alerts + weather, glanceable.
3. **Plain-language "why" everywhere** (Hydrawise's killer move) — "Skipped: rain coming," not `balance 13.2 > MAD 11.4`.
4. **Zones as cards** with a name (+ photo) and one primary action (Quick Run).
5. **ONE schedule view** — never multiple predictors that can drift.
6. **Reports/Usage is its own simple tab** — gallons + % saved.
7. **Settings holds the nerd knobs** (calibration, tuning, weather config) — out of the main flow.
8. **Notifications/alerts surfaced prominently.**

---

## 2. Honest diagnosis of our current app

We have **~12 destinations** where the leaders have 5:

- **SPA panels at `/`:** Home, Zones, History, Settings, Cam
- **Separate pages:** `/forecast` (Forecast + Forecast-vs-Actual), `/moisture-sim` (scheduling cockpit, ~2640 lines), `/calibrate`, `/costs`, `/sensor-history`, `/water-usage`, `/flow`, `/map`, `/cam/labels`

### Three structural problems the leaders don't have
1. **Three schedule predictors** — the engine (`irrigation.py`), the `moisture-sim` client-side JS, and the daily snapshot writer (`save_daily_forecast_snapshot`). They have repeatedly drifted apart and required manual re-sync. Hydrawise/Rachio have **one**. The authoritative source already exists (`/api/schedule-7day`); the redesign should make it the *only* one.
2. **Overlapping water pages** — `/forecast`, `/moisture-sim`, `/water-usage`, `/flow`, `/costs` are five tabs slicing the same "water + schedule" pie. The leaders use two (Schedule + Reports).
3. **Raw engineering on the front page** — mm, MAD, TAW, balance shown up front. Leaders bury that and say *"South lawn — watered this morning · next Thursday."*

The **meter-OCR + CNN training subsystem** (`/cam`, `/cam/labels`, water-usage frames, flow forensics) is effectively a *separate product* bolted onto an irrigation controller — a major source of the visual mess. It belongs behind a "Meter / Advanced" door, not as a peer of Zones.

---

## 3. Proposed information architecture: collapse 12 → 5

**No feature is removed — every page is re-homed.** Mapping:

| New tab | Absorbs | Job |
|---|---|---|
| **🏠 Home** | Home panel | Now + next + alerts + weather, in plain language (Hydrawise-style "why" cards) |
| **🌿 Zones** | Zones, sensor-history, calibrate (as a per-zone action), map | Named cards w/ status, **Quick Run** + **Looks dry**; tap for detail |
| **📅 Schedule** | `/forecast`, `/moisture-sim`, schedule-7day | **ONE** forecast/schedule — kill the 3-predictor drift |
| **💧 Water** | `/water-usage`, `/costs`, `/flow` | Usage + cost + leaks = the "Reports" tab |
| **⚙️ Settings** | Settings, `/calibrate`, zone config, **Cam + `/cam/labels`** | All nerd knobs + meter-OCR/CNN training under an "Advanced/Meter" section |

Every current route stays alive during migration; pages move one at a time and the old URL keeps working until the new home is verified.

---

## 4. Feature backlog (new — on top of the cleaner shell)

### 🦾 Our superpowers (meter + CNN — competitors can't do these without extra hardware)
| Feature | What it does | Why it's killer | Effort |
|---|---|---|---|
| **"Did this zone actually get water?"** | Compare expected gallons (zone runtime × measured GPM) vs the meter-measured delta during that zone's run. Zone ran but meter saw ~0 flow → *"Zone 3 ran but no water moved — check valve/wire."* | Broken-valve / cut-wire / clog detection that commercial systems need extra hardware for. We already have both signals (per-zone schedule + whole-house meter). **Push this hardest.** | Medium |
| **Per-zone GPM fingerprint drift** | Each zone has a normal flow signature; alert when it drifts (clog = lower, break = higher). | Automatic early failure detection. We already compute per-zone EWMA GPM in `flow_monitor`. | Medium |
| **Camera lawn-health timelapse** | Tie cam frames of each area to its watering history; see green-up vs water over weeks. | Visual proof the schedule works. | Medium |

### 🌟 Borrowed from the best (we don't have these yet)
| Feature | From | Effort |
|---|---|---|
| **Plain-language "why" push alerts** (ntfy: *"Skipped tonight — 8mm rain coming"*) | Hydrawise | Low — we have ntfy + the decision reasons already |
| **Quick Run presets** — one-tap "water Zone X for N min" | Rachio | Low |
| **Zone photos / identity** on cards | Rachio | Low — we have a cam |
| **7-day "what will happen" preview** (simulate upcoming runs) | OpenSprinkler | Medium |
| **Monthly water budget vs goal** | — | Low |
| **Seasonal / heat-wave auto runtime scaling** | Rachio/Hydrawise | Medium — partial `weather_scale` exists |

### Already shipped (keep — these are differentiators)
- Automatic meter reading (OCR + CNN), with human-correction training loop
- Per-frame leak forensics with camera frames
- Water usage graph derived from *validated* flow (not raw lock diffs)
- Water cost / billing-cycle tracking
- **"Looks dry" per-zone learning loop** (irrigation analog of the CNN correction loop) — shipped 2026-06-20, commit fe2735a
- Flow/leak monitor with quiet-hours signature (no steady leak verified 2026-06-20)
- Zone sync-groups (overlapping turf waters together)
- Server-side soil calibration (no reflash)

---

## 5. Safe migration approach (so nothing is lost)
1. Build the new 5-tab shell **alongside** the existing UI (new template / route), don't rip out the old one.
2. Move pages in **one at a time**; keep every old route serving until its new home is verified working (Playwright + live check).
3. Lead with the **lowest-risk, highest-impact** piece: a Hydrawise-style **Home screen** with plain-language status cards. Mock it, react to it, *then* touch structure.
4. Only after the shell is solid, collapse the 3 schedule predictors down to the one authoritative `/api/schedule-7day`.
5. Keep the meter/CNN subsystem fully intact — just relocate it under Settings → Advanced/Meter.

---

## 6. Open decisions (pending James)
- **Start with the shell?** Recommended first step: Home-screen mockup → react → then 5-tab nav.
- **Which new features first?** Top recommendation: the **"Did this zone actually get water?"** valve-check — it turns the meter from a cost tracker into a fault detector no off-the-shelf product can match.
- James's own feature ideas: _(to be added)_

---

*Sources: rachio.com, hunterirrigation.com / hydrawise.com, rainmachine.com, netrohome.com, opensprinkler.com (fetched 2026-06-20).*
