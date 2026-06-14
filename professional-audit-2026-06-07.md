# Smart Garden — Professional System Audit

**Audited system:** Solar ESP32 irrigation controller + Flask "brain" server (`smart-garden-server`) on the Acer home server, controlling 7 turf sprinkler zones + 2 drip zones in Duvall, WA.
**Audit date:** 2026-06-07
**Auditor:** Copilot (acting as an independent reviewer)
**Method:** Static read of `weather.py`, `irrigation.py`, `dashboard.py`, `billing.py`, `database.py`, `server.py`, `config.yaml`, and the moisture-sim/index templates, compared against professional irrigation-controller practice (FAO‑56, EPA WaterSense, ANSI/ASABE, OWASP).

> **How to read this:** Part 1 is the **framework** — the questions a professional would ask and the pass criteria, written before looking at results. Part 2 is the **findings** — what the code actually does against each criterion, with a severity. Part 3 is the **scorecard + remediation backlog**.

---

## Part 1 — Audit Framework (written first)

### Severity definitions
| Sev | Meaning | Action expectation |
|-----|---------|--------------------|
| 🔴 **Critical** | Can waste large water, damage turf, flood, or expose control of the system | Fix before next watering season / immediately |
| 🟠 **High** | Wrong decisions likely under common conditions; security weakness on trusted LAN | Fix soon |
| 🟡 **Medium** | Correct most of the time; edge cases or accuracy gaps | Planned improvement |
| 🟢 **Low / Polish** | Cosmetic, maintainability, nice-to-have | Backlog |
| ✅ **Pass** | Meets or exceeds professional practice | None |

### Domains & pass criteria

**A. Agronomic model (does it water the right amount?)**
- A1. ET₀ source is FAO‑56 Penman‑Monteith, not a temperature proxy.
- A2. Crop coefficient (Kc) is per-zone and seasonal, within published turf/drip ranges.
- A3. Soil water capacity (TAW) derived from real root depth × available water content (AWC) for the soil texture.
- A4. Management Allowed Depletion (MAD) is configurable and in the 40–60% range for cool-season turf.
- A5. Runoff control: long runs on clay/slope are split (cycle-soak) to avoid runoff.

**B. Weather data integrity**
- B1. Past rain reflects what *actually fell* (observation-corrected), not a stale forecast.
- B2. Forecast rain used only for *future* skip decisions.
- B3. Caching + retry + fallback so an API outage never opens valves wrongly.
- B4. Coordinates and timezone correct for the site.

**C. Irrigation decision logic**
- C1. Skip on meaningful recent rain and credible forecast rain.
- C2. Freeze and wind guards.
- C3. Water-balance ("checkbook") drives the decision; sensors are advisory.
- C4. Same-day double-water guard.
- C5. Watering window enforced.

**D. Safety & failure modes**
- D1. Only one valve open at a time (or controlled multi), enforced server-side.
- D2. Independent hardware/firmware valve timeout if the server dies mid-run.
- D3. Stuck-valve detection / periodic safety sweep.
- D4. Idempotent start (no double-open from a double-tap).
- D5. Vacation / global stop.

**E. Data & persistence**
- E1. Schema integrity, idempotent upserts, no silent overwrite of good data.
- E2. Balance reconciliation when late data corrects the record.
- E3. Backups of code + data.

**F. Security**
- F1. Dashboard auth on every sensitive route.
- F2. No hardcoded secrets in code/config that grant control.
- F3. Device control endpoints not exposed unauthenticated beyond the trust boundary.
- F4. Session/secret-key management.

**G. Observability**
- G1. Structured logging of every decision with reasons.
- G2. Alerting on faults (low battery, sensor fault, offline).
- G3. Diagnostics retained for post-mortems.

**H. Reliability / ops**
- H1. Single-instance guarantee (no two schedulers fighting).
- H2. Scheduler jobs idempotent and guarded.
- H3. Deploy process safe (no clobbering live data/code drift).

**I. Code quality & correctness**
- I1. No duplicated source-of-truth math between chart and engine.
- I2. Automated tests for the decision engine.
- I3. Encoding/locale safety (no emoji-in-latin1 crashes).

**J. UX / dashboard truthfulness**
- J1. Charts reflect engine truth (no fabricated data).
- J2. Units and alignment correct.
- J3. Manual vs auto state clearly shown.

**K. Water efficiency & cost**
- K1. Deep-infrequent scheduling (not daily shallow).
- K2. Cost model matches the local tariff.

**L. Calibration**
- L1. Precipitation rate per zone is measured (catch-can), not guessed.
- L2. Sensor calibration path exists.

---

## Part 2 — Findings

### A. Agronomic model
- ✅ **A1** — ET₀ is `et0_fao_evapotranspiration` straight from Open‑Meteo (FAO‑56 Penman‑Monteith). This is the professional standard; most consumer timers use a crude temperature proxy. **Exceeds typical practice.**
- ✅ **A2** — Kc is a per-zone 4-element seasonal array (e.g. turf `0.85/0.90/0.95/0.85`, drip lower). Within published cool-season turf ranges. Good.
- 🟡 **A3** — TAW = `root_depth_in × awc_in_per_in` with a single global `awc_in_per_in: 0.15`. 0.15 in/in is reasonable for loam, but Duvall soils vary (glacial till / silty). One global AWC across all zones is an approximation. *Recommend per-zone soil texture, or at least document the assumption.*
- ✅ **A4** — MAD default 50%, per-zone overridable. Correct band for turf.
- � **A5 — Cycle-soak configured but not implemented (ACCEPTED / WON'T-DO, James 2026‑06‑07).** Every zone has `cycle_soak: true` + `cycle_run_min/soak_min/count` in config, but the engine runs a single straight `max_runtime_min` (~24 min) block — there is no soak loop. On sloped or tighter-soil zones this risks runoff. **James has decided not to implement cycle-soak.** Documented here as an accepted limitation, not an open action. If runoff is ever observed (water reaching the street/beds during a run), revisit. The unused config keys can stay as-is or be removed for tidiness.

### B. Weather data integrity
- ✅ **B1** — *(Fixed 2026‑06‑07 during this engagement.)* Past rain now comes from the Open‑Meteo Archive (ERA5, observation-corrected); the forecast endpoint's stale-0mm past hours are no longer trusted. Nightly reconciliation re-credits recent days.
- ✅ **B2** — `get_rain_forecast_24h()` stays on the forecast endpoint for *future* skip decisions. Correct separation.
- ✅ **B3** — 30‑min forecast cache + 6‑h archive cache, non-blocking locks, failure TTL, and fallback to cached/forecast data. Solid.
- ✅ **B4** — 47.74/−121.98, America/Los_Angeles. Correct for Duvall. (Note: browser moisture-sim uses 47.7382/−121.9856 — a ~1 km difference; harmless but worth unifying.)

### C. Decision logic
- ✅ **C1** — Skips on `recent_rain_mm ≥ 8mm` and forecast `≥ 5mm at ≥ 60%`. Sensible thresholds.
- ✅ **C2** — Freeze guard `< 35°F`, wind guard `> 15 mph` (sprinkler zones only). Good.
- ✅ **C3** — Water-balance checkbook is the decision-maker; soil sensors are `null`/advisory. This is the right architecture and matches your stated design.
- ✅ **C4** — Same-day guard skips if today's runtime ≥ 50% of cap, so a manual spot-check doesn't block the nightly cycle. Thoughtful.
- ✅ **C5** — Watering window 04:00–08:00 enforced via `is_in_watering_window`.

### D. Safety & failure modes
- ✅ **D1** — Hardware lockout: server preempts any open valve before opening another (one-valve-at-a-time), with an explicit audited multi-valve override for manual use.
- 🟠 **D2** — Firmware valve timeout is `valve_timeout_sec: 3600` (1 hour). It exists (good — if the server dies, the valve eventually closes), but **1 hour at 1.5 in/hr ≈ 1.5" of water in one spot** — enough to flood a bed or run a meaningful water bill before the safety net trips. *Recommend lowering the firmware auto-close to ~30 min, matching the longest legitimate single run.*
- ✅ **D3** — `safety_check` sweep runs every 120 s to close untracked/stuck valves.
- ✅ **D4** — Start is idempotent under `_start_lock` with a sentinel reservation; documented races (#3/#8/#15/#17) are handled. Unusually robust for a hobby system.
- ✅ **D5** — Vacation mode + Stop All global kill exist.

### E. Data & persistence
- ✅ **E1** — `upsert_soil_balance` uses explicit `ON CONFLICT … DO UPDATE`; the COALESCE-overwrite class of bug (seen in the family-history project) is not present here.
- ✅ **E2** — Reconciliation added 2026‑06‑07; late-confirmed rain now lands in the checkbook.
- ✅ **E3** — *(Verified 2026‑06‑07.)* A full `~/server-backup/` system already exists (`backup.sh`, `restore.sh`, `DISASTER-RECOVERY.md`) and captures `smart-garden-server__smart-garden.db` in staging nightly. The deployed `~/smart-garden-server` dir is also a git work tree. My initial concern was wrong — backup + version control are in place. *(Only the local `smart-garden-server-live` mirror is not a git repo, which is cosmetic.)*

### F. Security
- ✅ **F1** — Google OAuth + allowed-emails allowlist; sensitive routes redirect to `/login` (verified: `/moisture-sim` → 302).
- 🟠 **F2** — *(Re-assessed 2026‑06‑07.)* `reboot_token: garden-reboot-9847` is hardcoded in `config.yaml` and **is** in effect (no `SMART_GARDEN_REBOOT_TOKEN` env override on the live unit). Severity is **Low–Medium**: the dashboard `/api/reboot` is already behind auth, so the exposure is a LAN actor POSTing the known token straight to the ESP32. Fully fixing it requires rotating the token in *both* the env and the firmware (USB flash) — so it's coupled to the firmware-flash task.
- 🟠 **F3** — The **ESP32 `/api/valve` endpoint is unauthenticated on the LAN.** Any device on the home WiFi can open/close valves directly, bypassing the server's lockout and logging. Acceptable risk on a trusted home LAN, but it *is* below commercial practice. *Recommend a shared-secret header on the firmware valve API (the reboot endpoint already uses a token — extend the same pattern).*
- ✅ **F4** — *(Verified 2026‑06‑07.)* Auth is a custom HMAC-signed cookie (`email|ts|HMAC-SHA256(SESSION_SECRET, …)`). `SESSION_SECRET` **is** set to a strong 96-hex-char random value in the systemd unit and is live in the process env — the hardcoded `"smartgarden2026default"` fallback is NOT in effect. Session security is sound. *(If that env var were ever dropped, the public default would allow cookie forgery — so keep it in the unit file.)*

### G. Observability
- ✅ **G1** — Every decision logs a structured reason; skip/water events persisted with conditions JSON. Excellent — better than most commercial controllers expose.
- ✅ **G2** — Low-battery ntfy alert (<11.8 V, 3-read hysteresis), sensor-fault detection, daily digest. Good.
- ✅ **G3** — Diagnostics retained (health-history, sensor-log, audit log). Good.

### H. Reliability / ops
- ✅ **H1** — Elaborate single-instance enforcement (scheduler-lock + port-bind recovery of stale PIDs). This is the hardest hobby-system failure mode and it's handled seriously.
- ✅ **H2** — Jobs wrapped in `api_guarded(...)`; APScheduler with explicit cron/interval. Good.
- 🟡 **H3** — Deploy is manual scp + restart. It works and you diff against the server first (per your memory rules), but there's no one-command deploy script or post-deploy smoke test in the repo. *Recommend a `deploy.sh` that scp's, compiles, runs a health curl, and rolls back on failure.*

### I. Code quality
- ✅ **I1** — The moisture chart has an explicit chart-vs-engine **invariant assertion** (#17) that warns if chart credits drift >5% from `balance.irrigation_mm`. That's a senior-level guardrail.
- ✅ **I2** — *(Resolved 2026‑06‑07.)* Added `test_engine.py` — a 15-test offline unit suite (no network, temp DB, no ESP32) covering the rain-source archive-vs-forecast fix, the checkbook reconciliation, the weather-adjustment scale, and TAW/MAD math. Runnable via `run_tests.sh` as a pre-deploy gate. Verified passing locally and on the Acer.
- 🟡 **I3** — Journey doc records a past latin‑1/emoji alert crash. Confirm all alert payloads are UTF‑8 encoded end-to-end (the templates are emoji-heavy).

### J. UX / dashboard truthfulness
- ✅ **J1** — Live mode is explicitly "pure DB data — no fabricated decisions," with the drift assertion above. Trustworthy.
- ✅ **J2** — *(Fixed 2026‑06‑07.)* Water Budget chart now in inches/whole-lawn; moisture-sim rain+sprinkler bars aggregated to daily grain and merged onto one shared x-axis (alignment now mathematically guaranteed); NOW marker made prominent.
- ✅ **J3** — Manual/auto and not-installed states surfaced in the banner.

### K. Water efficiency & cost
- ✅ **K1** — Sync-groups water overlapping turf together, deep+infrequent — the correct strategy.
- 🟡 **K2** — Billing model has Duvall tiers + sewer/storm flats, but cost accuracy is bounded by L1 below (runtime→gallons depends on the uncalibrated precip rate and `est_gpm`).

### L. Calibration
- 🟠 **L1** — `precip_rate_iph` (1.0–1.5) and `est_gpm` are **estimates, not measured.** Every depth-based number downstream — soil credit, the green sprinkler bars, gallons, cost — inherits that error. A 30-minute catch-can test per zone would convert the whole system from "calibrated-ish" to "calibrated." **Highest-value physical task.**
- ✅ **L2** — Full server-side sensor calibration UI (`/calibrate`) with dry/wet capture, drift tracking, battery least-squares fit. Strong.

---

## Part 3 — Scorecard & Remediation Backlog

### Domain scorecard
| Domain | Grade | One-line |
|--------|-------|----------|
| A. Agronomic model | B | FAO‑56 done right; cycle-soak intentionally skipped (accepted risk) |
| B. Weather integrity | A | Archive + reconciliation now correct |
| C. Decision logic | A | Thresholds and checkbook are sound |
| D. Safety | B+ | Strong, but 1‑hr firmware timeout too long |
| E. Data | A− | Good upserts; add DB backup + git |
| F. Security | B | Fine for a home LAN; session secret verified strong; reboot token hardcoded (low risk, coupled to flash) |
| G. Observability | A | Better than commercial |
| H. Reliability | A− | Serious single-instance handling |
| I. Code quality | B+ | Great guardrails; offline unit suite now in place |
| J. UX truthfulness | A | Honest charts, now aligned |
| K. Efficiency/cost | B+ | Right strategy, cost bounded by calibration |
| L. Calibration | B | Sensor cal excellent; precip rate still guessed |

**Overall: B+ / "prosumer-grade."** This is meaningfully better than any consumer timer (Rachio/Orbit) on the *decision* side — real ET₀, water balance, reconciliation, structured decision logs, single-instance hardening. The gaps that separate it from commercial-grade are now **precip-rate calibration**, **a test suite**, and **device-API/token hardening** (cycle-soak intentionally out of scope per owner decision).

### Prioritized remediation backlog
| # | Sev | Item | Effort | Domain |
|---|-----|------|--------|--------|
| 1 | � | Catch-can measure `precip_rate_iph` per zone (physical) | S (at device) | L1 |
| 2 | 🟠 | Lower firmware valve auto-close 3600 s → ~1800 s **+** rotate reboot token in firmware+env (one flash) | S | D2/F2 |
| 3 | 🟡 | Add shared-secret header to ESP32 `/api/valve` (also a flash) | M | F3 |
| 4 | ✅ | ~~Unit-test suite~~ — DONE 2026‑06‑07 (`test_engine.py`, 15 tests) | — | I2 |
| 5 | ✅ | ~~Nightly DB backup + version control~~ — already in place (`~/server-backup/`, git work tree) | — | E3 |
| 6 | ✅ | ~~Confirm Flask session secret~~ — verified strong random in systemd unit | — | F4 |
| 7 | 🟡 | Per-zone AWC / document the 0.15 assumption | S | A3 |
| 8 | 🟢 | Unify coordinates (server vs browser) | XS | B4 |
| 9 | 🟢 | One-command `deploy.sh` that runs `run_tests.sh` + post-deploy smoke test | S | H3 |

*Cycle-soak (former #1) removed 2026‑06‑07 — James elected not to implement it; see finding A5.*

---

*This audit is a point-in-time static review. It does not replace a live season of observed watering + a physical catch-can calibration, which together would validate the agronomic model end-to-end.*
