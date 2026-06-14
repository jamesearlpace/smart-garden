# Smart Garden — Session Changelog, 2026-06-07

Complete record of everything done in this session, with verification status for each item. Companion to the [professional audit](professional-audit-2026-06-07.md) and the [journey doc](smart-garden-journey.md).

**System:** Solar ESP32 irrigation controller + Flask "brain" (`smart-garden-server`) on the Acer (192.168.0.109), 7 turf + 2 drip zones, Duvall WA.
**Deployed dir:** `~/smart-garden-server/` · **Local source:** `C:\MyCode\smart-garden-server-live\` · **Service:** `smart-garden-server.service`

---

## 1. Rain-source fix — the root cause (🔴 → ✅)

**Problem:** Saturday Jun 6 it rained ~0.39″ in Duvall but the system recorded **0 mm** and never skipped/credited. Root cause: the garden read past rain from Open-Meteo's **forecast** endpoint, which keeps its stale model guess for elapsed hours instead of what actually fell.

**Fix (`weather.py`):**
- Past-rain methods now read the **Open-Meteo Archive API** (ERA5, observation-corrected). `get_rain_last_24h()` prefers archive, falls back to forecast on outage.
- Added `_fetch_archive()`, `_sum_hourly_precip()`, `get_rain_for_date()`, `get_daily_rain_history()`.
- Forecast endpoint still used for **future** rain (`get_rain_forecast_24h`) — correct separation.

**Evidence (verified against Jun 6):**
| Source | Jun 6 reported | Truth |
|--------|---------------|-------|
| Forecast (old source) | 0 mm | ❌ |
| Archive (new source) | 9.8 mm / 0.386″ | ✅ |
| `get_rain_last_24h()` after fix | 12.1 mm (was 0) | ✅ |

**Reconciliation + backfill (`irrigation.py`, `backfill_actual_rain.py`):**
- New `reconcile_balances(days_back=N)` re-credits recent days from archive actuals each night, so a forecast miss can't carry a stale rain=0 forward.
- One-time `backfill_actual_rain.py 7` ran on the server → **31 balance rows corrected** (the ~0.7″ of Jun 4–6 rain that was never credited).

**Status:** ✅ Deployed + verified earlier today.

---

## 2. Charts — truthful, aligned, inches

**Water Budget chart (History page, `index.html` + `/api/balance-history`):**
- Now **whole-lawn** (avg of turf zones 0–6) via `zone=all`, in **inches** (was zone-0-only, mm).
- Blue Rain + green Irrigation both point up (stacked = total water in, directly comparable); red ET down; orange = soil balance.

**Moisture-sim chart (`moisture_sim.html`):**
- Rain bars were `hourlyPrecip/4` slivers (invisible). Now **aggregated to one bar per day** = the day's total rainfall, matching the sprinkler bars' daily grain.
- **Alignment fixed permanently:** merged the rain/sprinkler bars INTO the moisture chart (single shared x-axis on a dedicated reversed `yPrecip` axis) instead of two stacked charts that drifted. Bars are now mathematically guaranteed to sit over their dates.
- **NOW marker** made prominent: bold red dashed line + filled red "NOW" pill (was faint thin gray).

**Status:** ✅ Deployed + visually confirmed by James (Jun 6 rain bar now shows, aligned).

---

## 3. "Show rain sooner" — caches + mid-day balance (this turn)

Goal: make the *accurate* rain number reach the dashboard hours sooner (without pretending a weather model can detect rain in real-time — that needs a physical gauge).

**Audited my own plan first and rejected part of it:** tested `current`/`minutely_15` Open-Meteo endpoints against Jun 6 — they reported **0.024″ vs the real 0.386″** (16× low). They're the same blind model, so I did NOT make them authoritative. Honest call documented.

**What shipped:**
- **Archive cache 6h → 2h** (`weather.py`): accurate rain settles within ~2h instead of up to 6h.
- **Mid-day (1 PM) + evening (6 PM) balance reruns** (`server.py`): rain banks into the visible soil-balance/moisture line hours before the 11 PM close.
- **Time-pro-rated ET** (`irrigation.py` `_et_fraction()`): cosine ramp over 06:00–20:00 (mirrors the chart's `getEtFraction`). Mid-day refresh subtracts only ET consumed so far → not pessimistically dry. At/after 20:00 fraction = 1.0, so the **11 PM authoritative close is byte-identical to before.**
- Stored `etc_mm` stays the FULL day's demand (chart + reconciliation depend on it); only `balance_mm` reflects partial ET.
- **Touches NO watering decision** — the 4–8 AM skip logic reads live ET/rain directly, not the balance row.

**Status:** ✅ Deployed; compile OK; 21/21 tests pass on server; service active; 3 balance jobs registered (1 PM/6 PM/11 PM). First live mid-day demonstration: tonight's 6 PM run. ⚠️ Final re-verification this turn blocked by an Acer network blip (intermittent all day) — not a system fault.

---

## 4. Test suite (🟠 → ✅)

**`test_engine.py`** — offline unit suite (no network, temp DB, no ESP32). Grew from 0 → **21 tests** this session:
- Rain-source: archive-vs-forecast preference, fallback, `_sum_hourly_precip` None-vs-0, `get_rain_for_date`, history.
- Weather scale: baseline=100, rain lowers, heat raises, clamp 0–200.
- Soil math: TAW = root×AWC×25.4, MAD = 50% TAW.
- Reconciliation: corrects stale rain=0, no-ops when correct, safe on empty history.
- ET proration (6 tests): zero before dawn, 1.0 after 20:00, monotonic, ~half at 13:00, midnight resets, close == full ET.

**`run_tests.sh`** — pre-deploy gate; exits non-zero on any failure so a bad change can't reach the controller.

**Safety:** swaps `db.DB_PATH` to a temp file — never touches the live `smart-garden.db` (verified on the Acer).

**Status:** ✅ Passing locally + on Acer.

---

## 5. Professional audit (deliverable)

**`professional-audit-2026-06-07.md`** — framework-first review (criteria written before findings), 12 domains (A–L), severity-graded.

**Overall grade: B+ / "prosumer-grade."** Beats consumer timers (Rachio/Orbit) on decisions: real FAO-56 ET₀, water-balance checkbook, reconciliation, structured decision logs, single-instance hardening.

**Findings corrected by live verification (assumptions that were wrong):**
- Backup: ✅ already exists (`~/server-backup/` + `backup.sh`/`restore.sh`/`DISASTER-RECOVERY.md`); deployed dir is a git work tree.
- Session secret: ✅ `SESSION_SECRET` is a strong 96-hex random value in the systemd unit (not the hardcoded fallback).
- `reboot_token`: 🟡 hardcoded + in use, but dashboard is authed; full fix coupled to a firmware flash.

**Owner decisions:**
- **Cycle-soak: WON'T-DO** (James, 2026-06-07). Documented as accepted limitation, removed from backlog. Modeled meter savings were only $0–80/yr and uncertain; value is lawn health, not dollars.

**Remaining backlog (all need physical access or a USB flash):**
1. 🟠 Catch-can measure `precip_rate_iph` per zone (physical) — makes every depth/gallon/cost number accurate.
2. 🟠 Lower firmware valve auto-close 3600 s → 1800 s **+** rotate reboot token (one USB flash).
3. 🟡 Shared-secret header on ESP32 `/api/valve` (also a flash).
4. 🟢 Document the AWC 0.15 assumption; unify server/browser coordinates; `deploy.sh` wrapping `run_tests.sh`.

---

## Files changed this session
| File | Change |
|------|--------|
| `weather.py` | Archive API client + actual-rain methods; cache 6h→2h |
| `irrigation.py` | `reconcile_balances()`; `_et_fraction()`; pro-rated balance; `import math` |
| `server.py` | Mid-day (1 PM) + evening (6 PM) balance cron jobs |
| `dashboard.py` | `/api/balance-history` `zone=all` aggregation |
| `templates/index.html` | Water Budget chart → whole-lawn inches |
| `templates/moisture_sim.html` | Daily rain bars; merged single-axis chart; bold NOW marker |
| `backfill_actual_rain.py` | NEW — one-time rain backfill (reuses `reconcile_balances`) |
| `test_engine.py` | NEW — 21-test offline suite |
| `run_tests.sh` | NEW — pre-deploy test gate |

## Docs produced
- `professional-audit-2026-06-07.md` (this folder)
- `session-changelog-2026-06-07.md` (this file)
- Journey doc resume section updated (`smart-garden-journey.md`)

## Open verification item
Re-run on the Acer once the network blip clears (it's been intermittent all day):
```
ssh jamesearlpace@192.168.0.109 "systemctl is-active smart-garden-server; cd ~/smart-garden-server && .venv/bin/python -m unittest test_engine 2>&1 | tail -2"
```
Expected: `active` + `Ran 21 tests … OK`. Then watch tonight's 6 PM balance run land rain into the visible moisture line before 11 PM.
