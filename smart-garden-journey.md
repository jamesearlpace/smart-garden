# Smart Garden — Journey Doc

**Status:** ✅ **System operational + actively self-managing.** Sync-groups live (overlapping turf zones water together, deep+infrequent). ET₀ water-balance brain is the decision-maker. Soil sensors are observe-only supporting "eyes" (not the brain) with full server-side calibration UI. Dashboard de-cluttered.
**Last Updated:** 2026-06-12 (journey doc archive-split — older dated session logs moved to the archive; this doc now keeps active reference + the 3 most-recent entries)

> **2026-06-12 (evening) — Water-meter cam is now a self-correcting, AI-verified reading pipeline + a new Flow/Leak monitor.** See the dated entry "Meter OCR overhaul + vision-LLM oracle + Flow/Leak monitor" below, and repo memory `/memories/repo/water-meter-ocr.md` for full implementation detail. Headline: per-digit 7-segment OCR + physical odometer model + GPT-4o vision oracle (auto-re-anchor, low-conf fallback, gold training labels) + new **/flow** page (per-zone GPM learned from the real meter, leak/overrun/high-flow detection via ntfy). Known limitation: cam WiFi ~30% packet loss → late/stale frames (hardware; relocate/antenna). No trainable model yet — oracle is collecting the gold dataset for a future per-digit CNN.

**Goal:** Solar-powered smart irrigation controlled remotely via Copilot through home server.

> **RESUME HERE — current state as of 2026-06-07 (read the dated entries at the bottom for details):**
> - **Rain source FIXED (2026-06-07)** — past-rain now comes from the Open-Meteo **Archive API** (observation-corrected ERA5), not the forecast endpoint. Root cause: the forecast endpoint keeps its old model guess for past hours, so it reported **0mm for the Jun 6 cats-and-dogs day that actually dropped 9.8mm/0.39"** — the garden never saw the rain, never skipped/credited. `get_rain_last_24h()` now prefers archive (fallback to forecast). Added `get_rain_for_date()` + `get_daily_rain_history()`. Nightly `reconcile_balances(days_back=3)` re-credits recent days so a forecast miss can't carry forward; `update_daily_balances` credits today's archive actual. One-time `backfill_actual_rain.py 7` corrected 31 balance rows (Jun 4–6 rain ≈0.7" that was never credited). Deployed + verified on Acer.
> - **Water Budget chart rebuilt (2026-06-07)** — now **whole-lawn (avg of turf zones 0–6) in INCHES** (`zone=all` on `/api/balance-history`). Blue Rain + green Irrigation both point up (stacked = total water in, directly comparable), red ET points down, orange = soil balance. A heavy-rain day now towers over a sprinkler cycle (Jun 6: 0.39" rain vs 0.01" irrigation) instead of the old stubby-blue/long-green mm view.
> - **Rain shows sooner (2026-06-07)** — archive cache 6h→2h (accurate rain settles within ~2h not 6h); added **mid-day (1 PM) + evening (6 PM) balance reruns** so rain banks into the visible soil-balance/moisture line hours before the 11 PM close. ET is **time-pro-rated** via `IrrigationEngine._et_fraction()` (cosine ramp over 06:00–20:00, mirrors the chart's `getEtFraction`) so mid-day reads aren't pessimistically dry; at/after 20:00 fraction=1.0 so the 11 PM authoritative close is byte-identical to before. Stored `etc_mm` stays the FULL day's demand (chart + reconciliation depend on it); only `balance_mm` reflects partial ET. **Does NOT touch any watering decision** (the 4–8 AM skip logic reads live ET/rain directly).
> - **Test suite (2026-06-07)** — `test_engine.py`, now **21 offline tests** (no network, temp DB): rain-source archive-vs-forecast, reconciliation, weather-scale, TAW/MAD, ET proration. Pre-deploy gate via `run_tests.sh`. Passing locally + on Acer.
> - **Audit (2026-06-07)** — `professional-audit-2026-06-07.md` in the smart-garden repo: framework-first review, graded B+/prosumer. Cycle-soak intentionally NOT implemented (James's call). Remaining: catch-can precip calibration (physical) + firmware valve-timeout/token (USB flash).
> - **Sync-groups SHIPPED + verified** (first live run watered all 7 turf zones together 4–5:45 AM, no errors). front_yard=[0,1], backyard_grass=[2,3,4,5,6]. Window widened 04:00→08:00.
> - **Soil balance credited immediately** after watering (not 11 PM) — predictor/banner/forecast reflect a completed watering in real time.
> - **Forecast-vs-Actual audit cleaned up** — group-aware snapshot, manual runs excluded, water/skip collision fixed (48.9%→99% on live data).
> - **Sensor strategy SETTLED** (evidence-backed): ET model = brain; cheap capacitive sensors = consumable supporting eyes (rain detection, dashboard cross-check, optional skip-gate). NOT a permanent/accurate lawn sensor. Pros use TDR/sealed-potted; passive auto-cal REJECTED as unscientific.
> - **Calibration system BUILT** — `/calibrate` page + nav tab: server-side per-sensor dry/wet (no reflash), invalid-reading guard, drift tracking, recalibration advice. Sensors still `soil_sensor: null` (observe-only).
> - **Battery voltage calibration LIVE (2026-06-05)** — `/calibrate` now has a 🔋 Battery section: read the true voltage off the Wanderer, type it in, tap Add. Server captures the ESP32's raw reading at that instant, least-squares fits a correction (pure-python, no numpy: 1pt=scale, 2–4=linear, 5+=quadratic), applied live via shared config (`battery_calibration`). Replaces the old hardcoded ×1.02884. **numpy is NOT in the server venv — never import it in deployed code.** Includes a scatter chart (X=ESP32 raw, Y=Wanderer actual) with best-fit line + live "right now" ◆ marker, per-point delete, clear-all.
> - **`/calibrate` restyled (2026-06-05)** — converted from standalone dark theme to the light theme + dark-green sidebar + mobile bottom nav matching the dashboard & forecast page. Nav mirrors index.html.
> - **Graceful sensor failure (2026-06-05)** — low-battery ntfy alert (<11.8V, 3-read hysteresis) + battery line in daily digest; sensor-fault check guarded against `soil_sensor: null`. Decisions already immune to dead soil sensors (ET brain; invalid reading → neutral 50).
> - **Dashboard charts cleaned up** — removed duplicate injected Analytics/Usage/Weather sections + dup battery from History, deleted orphaned p-analytics panel, fixed all 6 Chart.js console errors.
> - **Physical TODO (James, at the device):** seal sensor electronics (polyurethane + heat-shrink, blade exposed); reseat/replace Fruit Trees sensor (raw 4095 = open circuit); then use `/calibrate` to capture real dry/wet.
> - **Pending firmware flash (USB only, NEVER OTA):** crashLoop fix + 5-min sampling interval (committed, not flashed). Optional: strip pct math from firmware (server overrides it).
> - **Still open / future:** `precip_rate_iph` uncalibrated (catch-can test, physical); firmware valve-timeout 3600→1800s + reboot-token rotation (USB flash); cycle-soak **intentionally WON'T-DO** (James's call 2026-06-07 — see audit finding A5); journey doc needs archive-split.

**Goal:** Solar-powered smart irrigation controlled remotely via Copilot through home server.

> **Full history → [smart-garden-journey-archive.md](smart-garden-journey-archive.md)** (~234KB, all dated session logs through 2026-06-06, hardware build notes, deployment post-mortems). This doc keeps only active reference + the most-recent work. Newest archived batch is under the divider "Archived 2026-06-12 from main journey".

---

## Plumbing Permit — Irrigation Water Tap

**Status:** Application submitted 2026-05-21 via Duvall permit portal. **Permit #26-175.** Currently in Administrative Review.

### What's being done
Tapping into the potable water supply right after the water meter (NW corner of property) to create a dedicated irrigation supply line. Bypasses house plumbing for better flow (expect ~7.5-8.5 GPM vs. current 6.0 GPM through hose bibb).

### Permit documents (all in `C:\MyCode\smart-garden\`)
| File | Purpose |
|------|---------|
| `permit-plumbing-schematic.svg` | Plumbing connection diagram: meter → tee → ball valve → DCVA → 1" poly → 2 valve boxes (4+5) |
| `permit-site-plan.svg` | Property layout showing meter, tee, DCVA, main line route, valve box locations |
| `permit-acting-as-own-contractor.pdf` | City form — print, sign, scan, upload |

### Backflow preventer decision
- **Proposed:** DCVA (Double Check Valve Assembly) — Watts 007M1-QT, 1" bronze
- **Why DCVA:** Can install underground in valve box (no freeze risk, no ugly riser), handles backpressure, single device for whole system
- **Alternative:** PVB (Pressure Vacuum Breaker) — cheaper (~$150 vs ~$200-500) but must be above ground 12" above highest head
- **Hazard classification:** Low hazard (no chemical injection) per WAC 246-290-490
- **Annual testing required:** By Sept 1 each year, certified BAT tester. City mails reminder in June.
- **Key contact:** Duvall Public Works backflow line: 425-788-3434 / CoDbackflow@duvallwa.gov
- **Permit tech:** 425-788-2779 / permit.technician@duvallwa.gov

### Connection layout
```
Water Meter (¾", NW corner) → existing pipe → NEW TEE
  ├→ Right: existing water to house (no change)
  └→ Down: Ball Valve → DCVA → 1" Poly (100 PSI) → VB1 (4 valves) → VB2 (5 valves)
```

### Next steps after permit approval
1. Call 425-788-3434 to confirm DCVA is accepted (or if they require PVB)
2. Buy the backflow device (Watts 007M1-QT 1" at Lowe's — bookmarked)
3. Do the plumbing work (shut off water, cut in tee, install ball valve + DCVA, run 1" poly)
4. Schedule inspection: permit.technician@duvallwa.gov or 425-788-1160 (24h advance, leave trench open)
5. After approval: hire certified BAT for initial field test (find at https://wcs.greenriver.edu/bat/hire-a-bat/)
6. Annual backflow test due by Sept 1 each year

---

## Water Rate Structure — City of Duvall (in-city residential)

**Source:** [2023–2026 Utility Rates History (PDF)](https://www.duvallwa.gov/DocumentCenter/View/14564/2023---2026--Utility-Rates-History) · [Utility Billing page](https://www.duvallwa.gov/132/Utility-Billing). Use this to convert metered consumption (the OCR ft³ reading) into dollars.

**Unit conversion:** the Sensus meter reads in **cubic feet (ft³)**. `1 cf = 7.48052 gallons`. Tiers below are billed **per 100 cubic feet** (1 "ccf" = 748 gal). Bills go out the last week of each month, due the 20th of the next. Typical residential total ≈ $150–190/mo.

**Water — tiered (inclining block). Base fee includes the first 200 cf:**

| Tier (cubic feet) | Billing | 2023 | 2024 | 2025 | 2026 |
|---|---|---|---|---|---|
| **Base fee** (incl. first 200 cf) | flat/mo | $31.90 | $34.26 | $34.26 | $34.26 |
| 201 – 400 cf | per 100 cf | $4.75 | $5.10 | $5.10 | $5.10 |
| 401 – 600 cf | per 100 cf | $6.11 | $6.56 | $6.56 | $6.56 |
| 601 – 800 cf | per 100 cf | $7.48 | $8.03 | $8.03 | $8.03 |
| 801 – 1,000 cf | per 100 cf | $8.82 | $9.48 | $9.48 | $9.48 |
| Over 1,001 cf | per 100 cf | $10.22 | $10.97 | $10.97 | $10.97 |

**Flat monthly add-ons (residential):**

| Charge | 2023 | 2024 | 2025 | 2026 |
|---|---|---|---|---|
| Sewer | $84.91 | $91.18 | $91.18 | $91.18 |
| Storm drain | $23.88 | $25.64 | $28.72 | $32.17 |

**Marginal water cost per gallon (2026, the rate that matters for "what did this watering cost"):**
- Tier 201–400 cf: $5.10 / 748 gal ≈ **$0.00682/gal**
- Tier 401–600 cf: $6.56 / 748 ≈ **$0.00877/gal**
- Tier 601–800 cf: $8.03 / 748 ≈ **$0.01074/gal**
- Tier 801–1,000 cf: $9.48 / 748 ≈ **$0.01268/gal**
- Over 1,001 cf: $10.97 / 748 ≈ **$0.01467/gal**

Irrigation pushes consumption into the **upper tiers**, so the *marginal* cost of garden watering in summer is realistically **~$0.011–0.015/gal** (≈ **$8–11 per 100 cf / 748 gal**). Sewer and storm are flat, so extra outdoor watering does **not** raise the sewer charge — only the water tiers.

> **Notes:** Sewer/storm rates rise each year; water tier rates were flat 2024→2026. Reduced-rate (10%/40% low-income) and out-of-city/agricultural schedules exist in the PDF if ever needed — the Pace home is **in-city residential** (the table above). A leak-adjustment process exists (Ord. 1130) if a high bill is from a leak.

### Getting 2027+ rates when they're published
The table above is the **2023–2026** schedule. When the city publishes a new cycle, refresh from these durable links (the DocumentCenter PDF URL changes each cycle, so start from the Utility Billing page):
1. **Utility Billing page (start here):** https://www.duvallwa.gov/132/Utility-Billing — always links to the *latest* "utility rate schedule" / "Utility Rates History" PDF under **Utility Billing Forms**.
2. **Current rates PDF (2023–2026, may be superseded):** https://www.duvallwa.gov/DocumentCenter/View/14564/2023---2026--Utility-Rates-History
3. **Duvall Municipal Code (authoritative ordinances):** https://library.municode.com/index.aspx?clientId=16325 — search "utility rates" if the PDF lags behind a rate ordinance.
4. **Billing clerk** (to confirm): utilitybilling@duvallwa.gov · 425-788-1185.

How to extract: download the PDF and run `pdfplumber` (`pdf.extract_text()` per page) — that's how the table above was pulled. Page 1 = residential + commercial; pages 2–3 = reduced-rate / out-of-city / agricultural (ignore for the Pace home).

### Actual bills — account 001-0006184-004 (Natalie Pace, 27201 NE 144th Pl)
Three real water bills (downloaded 2026-06-12, from OpenGov / duvallwa.pay.opengov.com). The meter register on the **bill** reads in **hundreds of cubic feet (CCF)**; the **OCR** reads the same register in **cubic feet (cf)**. These bills **confirm the documented 2026 tiers to the penny** (tier math reproduces each Water Service line exactly), and the meter reads line up with the OCR.

| Bill due | Service period | Meter (CCF) start→end | Used (cf) | Water $ | Sewer $ | Storm $ | **Total** |
|---|---|---|---|---|---|---|---|
| 2026-04-20 | 02/26 – 03/25 | 892 → 896 | 400 | $44.46 | $91.18 | $32.17 | **$167.81** |
| 2026-05-20 | 03/25 – 04/27 | 896 → 906 | 1,000 | $92.60 | $91.18 | $32.17 | **$215.95** |
| 2026-06-22 | 04/27 – 05/27 | 906 → 931 | 2,500 | $257.15 | $91.18 | $32.17 | **$380.50** |

- **Account on auto-pay** (ACH on the due date). Pay/view: https://duvallwa.pay.opengov.com
- **Tier math check (2,500 cf bill):** base $34.26 + (200cf×$5.10) + (200×$6.56) + (200×$8.03) + (200×$9.48) + (1,500cf @ over-1001 ×$10.97 = $164.55) = **$257.15** ✓. The "Water Service" line **includes** the base fee. All three bills reproduce exactly → rate table is validated.
- **Usage is climbing fast into summer:** 400 → 1,000 → 2,500 cf/mo as irrigation ramps. The Jun bill (2,500 cf) is dominated by the over-1,001 tier at **$10.97/100cf ≈ $0.0147/gal** — this is the marginal cost of summer watering.
- **Bill PDFs:** `email_bill_001-0006184-004*.pdf` (3 files) in `~/Downloads` as of 2026-06-12 (not yet filed to a permanent home). Bill fields parsed: account #, due date, total, name/address, service period (start/end), meter type `WT`, register start→end, units used, per-charge breakdown.

### ⭐ Meter ↔ Bill Conversion (READ THIS to turn a meter read into a bill)

**The single most important fact:** the physical Sensus LCD, the OCR, and the bill are all reading **the exact same odometer** — just displayed in different units. Nothing is estimated; it's pure unit conversion.

**1. Reading the 9-digit Sensus LCD.** The display shows **9 digits, and the rightmost 3 are decimals** (fractional cubic feet, like the tenths on a car odometer). The `Ft³` label on the glass confirms the unit.

```
   0 9 4 0 0 8 . 3 4 8   Ft³
   └───────┘   └───┘
   whole ft³   decimal ft³
   = 94,008    = .348
```
So `094008348` = **94,008.348 ft³**. (It is NOT 94 million cf — that would be ~700 million gallons, absurd for a house. The trailing 3 digits are always decimals on this meter.)

**2. The bill register is CCF (hundreds of cubic feet).** The City bills in units of 100 ft³ — `1 bill unit = 1 CCF = 100 ft³ = 748.052 gallons`. The bill register is just the meter's **whole cubic feet with the last two digits dropped**:

```
bill_CCF = floor( whole_ft³ / 100 ) = floor( (meter_9digit / 1000) / 100 )
```

**3. Worked examples (both directions):**

| Direction | Input | Math | Output |
|---|---|---|---|
| Meter → bill | meter `094008348` | 94,008.348 ft³ → floor(94,008 / 100) | bill reads **940 CCF** |
| Meter → bill | meter `093100000` | 93,100 ft³ → 93,100 / 100 | bill reads **931 CCF** |
| Bill → meter | bill `931 CCF` | 931 × 100 = 93,100 ft³ | meter ≈ `093100xxx` |
| Bill → gallons | `2,500 cf` used | 2,500 × 7.48052 | **18,701 gal** that month |

**4. Computing a month's usage (what the bill charges for):** usage = (end register − start register) in CCF, then ×100 for cf, ×7.48052 for gallons.
- Example (Jun bill): `931 − 906 = 25 CCF = 2,500 ft³ = 18,701 gal`.

**5. Live cross-check (verified 2026-06-12):**
- Last bill closing read **05/27 = 931 CCF = 93,100 ft³**.
- Physical meter / OCR on **06/12 = `094008348` = 94,008 ft³ = 940 CCF**.
- Delta = `94,008 − 93,100 = 908 ft³ in 16 days ≈ 57 ft³/day ≈ 425 gal/day` — matches summer irrigation. **The OCR is reading the true physical register.** ✓

**6. Estimating the in-progress bill from a live meter read.** Take the current meter, subtract the last bill's closing register, that's CCF used so far this cycle; project to the next read date at the recent ft³/day, convert CCF→$ through the 2026 tier table (remember the first 200 cf is in the base, and summer usage is mostly in the **over-1,001 tier @ $10.97/100cf**), then add flat **sewer $91.18 + storm $32.17**.
- *Worked (as of 06/12):* 940 − 931 = 9 CCF used so far; at ~0.57 CCF/day to a ~06/27 read → ~`949–950 CCF` close → ~18–19 CCF (1,800–1,900 cf) billed → water ≈ **$200–230** → total ≈ **$330–360**.

**Quick constants for code/dashboards:**
- `CF_PER_CCF = 100`, `GAL_PER_CF = 7.48052`, `GAL_PER_CCF = 748.052`
- `meter_whole_cf = meter_9digit // 1000` (drop 3 decimal digits)
- `bill_CCF = meter_whole_cf // 100`
- 2026 marginal $/gal by tier: 201–400 `$0.00682`, 401–600 `$0.00877`, 601–800 `$0.01074`, 801–1000 `$0.01268`, over-1001 `$0.01467`

---

## 2026-06-13 — Dedicated Sensor History page + unified compact mobile nav + cam-cutoff fix

**Context:** James couldn't see soil-sensor history anywhere (the existing charts are buried in the index History panel's drilldowns), and the mobile bottom nav was broken: 11 items jammed into a `justify-content:space-around` row wrapped onto 2–3 lines on a phone — so the bar was huge, items were cut off, and **the Water Meter Cam panel got hidden behind the over-tall nav** ("camera cut off"). Each page also hardcoded a *different* nav subset (forecast/calibrate showed fewer items than home) because the in-page SPA panels (Zones/History/Cam/Deer) only exist on index.html.

**Live sensor truth at the time (unchanged hardware):** Garden(p32)=754 stuck-low = dead oscillator; **Grapes(p33)=2492 = the one good sensor** (stable, tracks real moisture); Fruit Trees(p34)=0 floating; South Lawn(p35)=0 floating. Config logs only `soil_0`(Garden, 5294 rows) + `soil_1`(Grapes, 2661 rows); `soil_2/3` off (no point logging dead probes).

**What shipped:**
- **New `/sensor-history` page** (`templates/sensor_history.html` + route in `dashboard.py`). One Chart.js line chart with all 4 sensors, **Raw ⇄ Moisture%** toggle and **24h/7d/30d/90d** range. Per-sensor summary cards (live raw, %, status pill — Working/Stuck low/Check wiring/Disabled, window min–max, sample count, dry/wet cal). **Reuses the existing `/api/sensor-history?type=soil&index=N&hours=H` endpoint** (returns `[{ts,pct,raw}]`) + `/api/calibration` for names/cal/live raw — no new API needed. Dead sensors auto-populate once their probes are fixed and `soil_2/3` flipped to true.
- **Shared mobile nav partial `templates/_mobilenav.html`** (self-contained scoped CSS + JS), included via `{% include '_mobilenav.html' %}` in index, forecast_merged, moisture_sim, costs, sensor_history. **Fixes the per-page drift permanently** — one file, identical everywhere. Design = chosen "5 primary tabs + More sheet": Home / Zones / Schedule / Forecast / **More⋯**; the More slide-up sheet holds History, Sensor History, Cam, Deer, Settings, Water Cost, Flow, Calibrate, Zone Map. In-page panel links use `/#panel`; on `/` they're intercepted → `window.showPanel()` (no reload), from other pages they navigate to `/#panel` and index opens it from the hash on load (index already supported hash-deep-link).
- **Cam-cutoff fix:** root cause was the over-tall wrapped nav. New single-row nav is ~62px; also bumped index `.main` mobile bottom padding to `calc(84px + env(safe-area-inset-bottom))` so the cam panel always clears the fixed bar.

**Decisions:** kept dead-sensor logging OFF (no point recording flat zeros); did NOT touch any watering logic or the ESP32 firmware; desktop sidebars left as-is (added Sensor History link to the new page's sidebar + all mobile More sheets).

**Verify:** service `active`, no errors/TemplateNotFound in logs, all routes (`/sensor-history`, `/`, `/forecast`, `/moisture-sim`, `/costs`) return 302→login (render OK, auth-gated). James to confirm on phone. Deployed to Acer `~/smart-garden-server/` + restarted.

---

## 2026-06-12 (night) — Moisture forecast falsely predicted DAILY watering (chart-only bug, model is correct)

**Context:** James looked at the moisture/Schedule page and saw the forecast projecting watering **every single day** in the coming week, which contradicted the design intent (deep + infrequent, ~2–3×/week). He asked whether the model was wrong, whether it was getting extra hot, or whether he really should water daily.

**Diagnosis — pulled REAL data from the live DB (`~/smart-garden-server/smart-garden.db`), not theory:**
- **Actual watering (last 21d) is already 2–3×/week**, exactly as designed: Zone 0 = 9 days/21 (~every 2.3d), Z1=5, Z2=4, Z3=5, Z4=8, Z5=6, Z6=3. The engine is doing the right thing.
- Current soil state: TAW=**22.9mm (0.9")**, MAD=**11.4mm (50%)**, today's ETc≈**4.45mm/day**, ET₀ climbing (2.7mm Jun 6 → ~5.0mm Jun 11–12). Real refill 50%→100% over a ~50-pt band ÷ ~20%/day ET ≈ **water every ~2.6 days** — matches the actual data.

**Root cause = the forecast SIMULATION, not the decision engine.** In `templates/moisture_sim.html`, the projected morning watering refilled the soil only to **`madPct + 20` (≈70% full)** — a shallow top-off — instead of the **deep soak to field capacity (~100%)** the real engine applies (it runs `max_runtime_min` and the balance fills to TAW). With summer ET ≈ 20% of the bucket per day, a shallow 20-pt refill re-crossed MAD the very next morning → forecast falsely showed **daily** watering. The real engine refills the full ~50-pt band → every ~2.6 days.

**Fix (chart-only, ZERO change to any watering decision):** changed the projection's `waterTarget` from `Math.min(100, madPct + 20)` to **`100` (field capacity)**, matching the real engine. The `minutesWateredToday < maxRuntimeMin` cap remains the true limiter on a single morning cycle. `irrigation.py` (the actual decision engine) was **not touched**. Deployed `moisture_sim.html` to the Acer + restarted `smart-garden-server.service` (active, HTTP 200).

**Agronomy note for future-me:** frequency should always be an **output** of ET depletion, never a hardcoded calendar. In cool weather the engine stretches to 4–5d/skips; in a July heat wave it correctly tightens toward ~every 2d. That variability is the system being *right*. If James ever wants genuinely less-frequent summer watering, the correct lever is a **deeper root depth / bigger bucket** (config already ramps root depth to 8" Jul–Aug), NOT a frequency cap. Did not change MAD, root depth, or run times — they're internally consistent and agronomically sound.

---

## 2026-06-13 — Click-to-inspect reading detail (verify each row against its image)

**Context:** James noticed the live image showed ~094098675 while the table's "captured this minute" row read ~094083407 — far behind — and (rightly) didn't trust it. He wanted to click any row and see the exact frame the OCR saw for it, plus all that row's data.

**Problem:** per-reading frames weren't saved at all — only banked high-conf frames (training set) and the single latest `cam_state["image"]`. So a row couldn't be tied to its image.

**What shipped:**
- **`cam_ocr.py`** — every readings-table row now gets a unique `id` (`<epoch_ms>-<seq>`, module counter `_ENTRY_SEQ`, survives restarts, sortable). New `get_reading_by_id(rid)`.
- **`dashboard.py`** — frame ring buffer `FRAME_DIR=/tmp/meter-frames` (env `METER_FRAME_DIR`), keep newest `METER_FRAME_KEEP=720` (~1h, ~30MB); `_save_frame(rid, frame)` writes `<id>.jpg` in the OCR worker right after `process_text` and prunes the evicted oldest via an in-memory `_frame_ids` deque. Routes: `GET /api/cam/frame/<id>` (serves that frame or 404), `GET /api/cam/reading/<id>` (full field dump + `has_frame`), `GET /cam/reading/<id>` (detail page).
- **`templates/cam_reading.html`** (new) — shows the rotated frame + every field (processed/captured/gap/lag/reading/ft³/gal/ocr_guess/Δ/rate/kind/conf/stale/raw_low_match/note/raw OCR/id). Graceful message when the frame was pruned or the row is a derived back-fill (no frame).
- **`index.html`** — table rows are now clickable (`cursor:pointer`, navigate to `/cam/reading/<id>`).

**Verified:** frames saving every ~5s, ids assigned, endpoints registered (auth-gated like the rest of the dashboard). Compile-checked, deployed, service active.

**Oracle low-conf fix (same session, the real root cause):** the detail page immediately proved James right — a row showed `≥94,083.407` **stale 5649s (94 min!)** while the captured image clearly read ~094098.675. Investigation: the vision oracle was **rejecting every read** (173 floor-rejections that day, ~1000+ wasted GPT-4o calls). GPT-4o read the LOW (moving) digits reliably but garbled the leading `09`→`34`/`84` under evening glare, so the raw value fell below the anchor floor and was discarded → meter sat stale for 90+ min.
- **Fix 1 — high-digit garble repair (`_oracle_splice`):** keep the lock's stable high digits, overlay the oracle's trusted low 5–7 digits, accept the first physically-plausible **forward** step. Turns `34038780`→`094038780`.
- **⚠️ Fix 2 — FORWARD-ONLY (critical safety catch):** the first version of the splice allowed a small downward correction, and it *immediately bit* — at 20:38 the oracle pulled the lock **backward** 94083407→94038780 because in deep glare GPT-4o garbles the LOW digits too (`38780` vs true `98675`). A water meter is monotonic, so any oracle value **below the lock is a misread, not a real decrease**. Changed both the splice and the acceptance check to **reject anything below the lock** (`0 ≤ d ≤ ceiling`) and **hold + show stale** instead. Genuine high-drift correction is now only via the **manual "AI Re-anchor" button** (user-triggered override) — never automatic downward.
- **Re-anchored** the corrupted lock to James's eyeball read 94098675 (stop service → write `/tmp/meter_state.json` → start). **Verified live:** oracle misread `34038700` was rejected at the floor and the lock **held at 94098675** (forward-only working).
- **Lesson (again):** corroboration ≠ trust when the error is systematic; and an *independent verifier that can itself be systematically wrong* (GPT-4o in glare) must be constrained by domain physics (monotonicity) — never allowed to move the lock backward automatically.
- **Still open:** the stale anchor floor env is still `94009473` (loose); evening glare is the hardware ceiling (lens focus/exposure). The oracle now ratchets UP correctly but can't fix a static blurry meter — that needs the per-digit CNN or a hardware fix.

**Oracle CONTEXT HINT (same session, James's idea — big win):** James asked "can we send it context — acceptable ranges, starting point — to help it get the right number?" The oracle had been sending GPT-4o ZERO context ("read the 9 digits"), so glare on the high digits left it guessing pixels. Added `vision_oracle._build_hint(hint)`: injects the last value, the monotonic floor + physical ceiling, and the expected high-digit prefix (`0940`) into the prompt — framed so the bounds disambiguate **only** the glare-prone HIGH digits while the LOW digits are still read straight from the image. `read_meter(jpeg, rotate180, hint)` now takes the hint; `_oracle_run` builds it from `last_good` + the physical ceiling; the manual re-anchor passes a soft prefix-only hint (no hard floor, so the override stays free in both directions). **A/B tested on the live glared frame:** no-hint → `794038780` (garbage); with-hint → `094098709` (exact truth). Same image, same model — context alone fixed it. This makes the oracle far more useful on exactly the blurry evening frames that were failing.

---

## 2026-06-12 (night) — Cam readings table: capture-time alignment + display-Δ fallback + gold-set prune

Three small, surgical fixes to the Water Meter Cam page, all verified against the live server (no drift — `dashboard.py` and `index.html` both md5-matched the Acer before editing).

**1. Capture-time alignment (table vs. live image).** The live image's "Captured" (the `X-Capture-Time` header) used the **transfer-corrected** capture moment (`capture_dt = now − transfer_s`), but the frame enqueued for OCR was tagged with **plain arrival time** (`cam_queue.append((time.time(), data))`). So the readings table's "Captured" column ran a couple seconds *later* than the image's for the same frame on the lossy WiFi. Fixed `cam_upload` to enqueue the **same** corrected stamp: `cam_queue.append((capture_dt.timestamp(), data))`. Now both timestamps derive from the identical capture instant. (Residual: the table's top row can still look older than the live image — that's real FIFO *processing* lag, shown in the Lag column, not a timestamp bug.)

**2. Δ (change) columns now track the displayed reading.** Complaint: the reading climbs (e.g. ≥094012120 → 094012171) but **Δ ft³ / Δ gal stay blank**. Root cause: the engine (`cam_ocr._validate`) only emits a Δ on a **confirmed high-confidence advance** — "hold"/"stale"/"pending" rows return `delta=None`, so the Δ cells render `—` even though the shown value went up. Fix is **frontend-only** in `camLoadReadings()` (`index.html`): when the engine left Δ blank, derive a **display-Δ** from the change in the *shown* ft³ vs the previous (older) row (`parseShownFt3` strips the "≥" and commas; threshold 0.0004 ft³; gal = Δft³ × 7.48052; green when positive). Engine-provided Δ and the **rate (gal/min) column are untouched** — rate still needs real timing, so it stays engine-only. **Zero changes** to the OCR lock, validator, banking, or oracle. This is purely how the table presents change. Honest because the meter is monotonic — any rise in the displayed value is real water, including across a stale "≥" catch-up.

**3. Gold-set prune (one-time cleanup).** Training viewer showed 7–8 images of the same number (094010270 ×8, 094008998 ×7, 094010324 ×6) — over the `GOLD_MAX_PER_LABEL=3` cap. The cap was added during the OCR overhaul and only enforces on **new** writes (it can't retroactively prune); those duplicates were banked *before* the cap went live, while the meter sat static and the steady-meter rule saved one frame/~50s. Both banking paths (`_bank_sample`, `_oracle_bank_label`) verified correct (count all `.jpg` for the label, stop at 3). Pruned to the **3 newest per label** (kept lighting variety), removing 12 jpgs + their `.json` sidecars: **60 → 48 samples**, max 3 each. Post-restart banking confirmed capping correctly (new numbers at 1–2). Not a recurring leak.

**Deploy:** `dashboard.py` scp'd + `systemctl restart smart-garden-server` (active); `index.html` scp'd (templates auto-reload, hash-verified). Prune ran via a temp bash script (PS→ssh heredoc quoting forced a file, not inline), then cleaned up.

---

## 2026-06-12 (evening) — Meter OCR overhaul + vision-LLM oracle + Flow/Leak monitor

**Context:** Day-long deep session turning the water-meter cam from "numbers bounce randomly" into a self-correcting, AI-verified reading pipeline, then building per-zone flow estimation + leak detection on top. (Detailed implementation notes live in repo memory `/memories/repo/water-meter-ocr.md` — this is the narrative summary.)

### 1. Reading accuracy — from garbage to reliable
The Sensus iPERL shows **9 digits, decimal 3 from the right** → `094008.348 ft³` (verified against the city bill register + the physical meter). Fixes, in order of impact:
- **Box-ordering (biggest win):** RapidOCR returns the two LCD digit groups out of order (`1593 9400`); the tower now sorts detections by bounding-box X so they read left-to-right.
- **Leading-zero width bug:** `int("094…")` drops the zero → a good 9-digit read looked like 8. `_extract` now returns the true matched digit width.
- **Physical meter model** (`cam_ocr.py`): monotonic odometer + **time-aware flow ceiling** (`max_gpm=20`, even a burst pipe; a 5s frame allows ~290 counts, a 60s gap allows proportionally more). Rejects impossible jumps as `too-fast`.
- **Per-digit 7-segment context scorer:** enumerates every physically-possible reading in a tight window and scores each candidate digit-by-digit by segment similarity (so a blur-induced `7→1` still scores high), gated on the reliable low digits. Beats pass/fail on the whole string.
- **Corroborated advance:** the lock only moves when the same value appears in ≥2 consecutive frames — stops a *systematic* misread from "self-corroborating" into a false-high lock that then rejects every real (lower) read forever. (This false-high drift bit us twice; the heartbeat below is the real safety net.)
- **Known anchor + state persistence:** seeded `METER_ANCHOR_VALUE` (operator-confirmed reading) as a monotonic floor; lock persists to `/tmp/meter_state.json` across restarts so it never re-bootstraps into garbage.
- **CLAHE preprocessing (tower):** by mid-afternoon the glass washes out to near-zero global contrast and RapidOCR found *zero* text; CLAHE local-adaptive equalization recovers the digits where plain autocontrast got nothing.
- **Honesty:** when a frame can't be read it **holds** the last value, and after 20s marks it **stale** (shows `≥ value`) instead of pretending a stale number is current. Dashboard cam table gained columns: Processed | Captured | **Gap** | Lag | Q | Reading | **OCR Guess** | ft³ | Gallons | Δ | gal/min | Kind | Conf | Note | Raw OCR. Plus an image **size slider**, **180° flip**, and gap **back-fill** (derived rows evenly distribute usage across a blind gap).

### 2. Vision-LLM oracle (GPT-4o) — the trusted verifier + closed-loop data engine
- **`vision_oracle.py`** — sends the **original full-color frame** (tower `/raw.jpg`, rotated) to **GPT-4o vision** (key in `/etc/smart-garden/cam-env`, ~$0.002/call). Color frame is essential — the processed CLAHE/gray image gives the LLM garbage.
- **Three jobs, all async (background thread so it never stalls the 5s OCR worker):**
  1. **Auto-re-anchor** — when the lock is stale OR a **verify heartbeat** fires (every 5 min, *even on high-confidence reads* — the only thing that catches self-consistent drift), GPT-4o reads the true value and re-anchors. **Downward correction allowed** (the oracle outranks a drifted lock; only floor is the operator anchor).
  2. **Low-confidence fallback** — any frame the local pipeline can't read cleanly goes to the oracle.
  3. **Trusted training labels** — every trusted oracle read is banked as a **gold** sample for a future custom model.
- **Closed-loop data engine:** high-confidence local reads are free; only hard/changing frames cost an API call, and each becomes labeled training data. Spends ~nothing on a static, cleanly-read meter (skip-unchanged: won't re-send a number it already confirmed).
- **Training-data banking + 🧠 Training Data viewer** on the Cam page: auto-labeled frames (`<reading>_<ms>.jpg` + JSON sidecar with `raw_low_match` independent-agreement flag). **Dedup:** ≤3 images per distinct number (no flooding the set with copies of the same reading). Manual **🤖 AI Re-anchor** button too.
- **Honest status:** there is **no trainable model yet** — the reader is still RapidOCR + physics rules. The oracle is collecting the gold dataset; the per-digit CNN (Tier-3) is the next build, after which the retrain loop closes.

### 3. Timing diagnosis (the "X ago" was lying)
- **Two independent delays.** *Image age* = **network**: the ESP32-CAM WiFi has **~30% packet loss + high jitter**, so uploads crawl (TCP retransmits) and frames arrive late. *Processing lag* was the **synchronous oracle** blocking the worker — fixed by making it async.
- **Timestamp fix:** the capture time was stamped when the upload *finished arriving*, not when the frame was *taken*. The server now measures the body-transfer time and subtracts it (`timestamp = now − transfer_s`) — a no-reflash approximation. Fully accurate timing would need firmware NTP + a capture-epoch header (USB reflash, not done). The real cure for all timing symptoms is the cam's WiFi (relocate / repeater / external antenna).

### 4. Flow & Leak monitor (`flow_monitor.py` — new, isolated like `water_cost.py`)
Correlates the live meter register with which zone the controller has ON to do four things:
- **Per-zone GPM, learned from real flow** — recency-weighted **EWMA (α=0.30)** of each single-zone run-segment's **median** instantaneous GPM. Latest runs count more (tracks a drip line gaining emitters over time); the median is the stable cross-check. Falls back to config `est_gpm` until measured.
- **Leak / anomaly detection** — the core signal is *flow + a zone on = sprinkler (fine); flow + NO zone on = problem.* Small sustained unexplained flow (after 120s) → **"Possible leak"**; big unexplained flow (≥2 gpm) → **urgent "Water running — no zone on!"** (burst/hose/faucet).
- **Zone overrun** — a zone ON longer than `max_runtime_min × 1.25` → **"Sprinkler running too long, may be stuck."**
- **Full raw logging** — every ~15s sample (register, Δ, interval, gpm, active zones, classification) for audit/troubleshooting.
- Alerts push to **ntfy.sh/smart-garden-james**. Tables: `flow_sample` (30d retention), `zone_flow_est`, `flow_event`. API `GET /api/flow`; UI **/flow** page (`templates/flow.html`) + "💧 Flow & Leaks" nav links. Tunables in `config["flow_monitor"]`. Background sampler started in `create_app` after the OCR worker. Verified: idle samples recording cleanly, no false anomalies; per-zone GPM fills in as zones run (nightly).

**Files touched:** `cam_ocr.py`, `dashboard.py`, `vision_oracle.py` (new), `flow_monitor.py` (new), `templates/index.html`, `templates/flow.html` (new) on the Acer (`~/smart-garden-server/`); `meter_ocr_service.py` on the tower (jackmint). **Anchor/state:** `/etc/systemd/system/smart-garden-server.service.d/meter-anchor.conf` (write via base64 to dodge PS→ssh→bash quoting; **always `daemon-reload`** after editing it).

---

## 2026-06-12 — Water Cost page (real-meter billing from the cam)

**Context:** Wanted a dollar view of actual household water cost driven by the real meter the ESP32-CAM reads — separate from the existing `billing.py`, which only estimates the irrigation slice from sprinkler run-time. Built while the cam OCR was being improved in a parallel chat, so the whole feature is deliberately isolated from cam code.

**What shipped (new `/costs` page on sprinklers.savagepace.com):**
- **`water_cost.py`** (new module) — owns its own `meter_snapshot(date PK, reading_cf, source, ts)` table. Reads the live whole-house register from `MeterReader.last_good` (÷1000 → ft³), records one snapshot/day (lazy, on page hit), and seeds the 3 real paper bills as `source='bill'` anchors so history is correct from day one. Tier math reads the 2026 rates from `config["billing"]`.
- **`templates/costs.html`** (new page) — matches the app chrome (light theme, dark-green sidebar, mobile nav). Shows: live meter (ft³/CCF/gal) + projected bill hero, current-cycle detail (usage, gal/day, tier badge, marginal $/gal), projected tier breakdown bar, a stacked bill-history chart (water/sewer/storm) with the 3 real bills + live estimate, and a daily-usage bar chart from snapshots.
- **`dashboard.py`** — added `/costs` + `/api/water-cost` routes in an **isolated block right after `/api/billing`** (far from the cam section at ~1952+). They read `meter_reader` via closure; no cam routes touched.
- **Storm rate fix:** config `storm_flat` was the stale 2025 value `28.72`; bills confirm 2026 = **`32.17`**. Fixed.

**Verified live (server venv, real DB + meter lock):** meter `94011433` → 94,011.433 ft³ = 940 CCF; cycle since 93,100 cf @ 05/27 → 911 ft³ / 6,818 gal used, 426 gal/day, tier 5; cost so far **$207.55**, projected **$293.72** (water $170.37 + sewer $91.18 + storm $32.17). History shows the 3 real bills ($167.81 / $215.95 / $380.50) + the live estimate.

**Deploy gotcha (near-miss clobber):** the server's **`config.yaml` had drifted ahead of local** — it holds **live `battery_calibration` (9 points + fitted coeffs)** and sensor dry/wet cal values written by the app. Pushing local config would have wiped all of it. Fix was applied **in place on the server** with `sed` on just the `storm_flat` line, then local was resynced *from* the server. (Same drift rule as `dashboard.py`; now noted in repo memory.) `dashboard.py` itself was in sync (0 server-only lines), re-checked immediately before push.

**Nav link (follow-up):** the page was reachable at `/costs` but had no link from the main dashboard, so it looked "missing." `index.html` is the cam page being edited in the parallel chat, so instead of overwriting it I added the **💵 Water Cost** sidebar link + **Cost** mobile-nav link with an **idempotent insert script** (`_add_costs_nav.py`, regex-anchored after the Schedule link, makes a `.bak`, no-ops if `/costs` already present). Ran it **both on the server in place AND on local `index.html`** so the link survives a sync in either direction and never collides with cam work. `index.html` templates auto-reload, so no restart was needed for the link.

**Tier insights + "Tier journey" graph (same day, later):**
- **`water_cost.py`** — added `tier_progression(used_cf, daily_cf, cycle_days, start_date, rates)`: computes the day each tier boundary was/will-be crossed assuming cumulative usage climbs linearly at the current daily rate. Tier T (T≥2) is entered when cumulative use crosses the *previous* tier's `max_cf` (e.g. T6 at 1,000 cf). Returns per-tier `{entry_cf, entry_gal, rate, rate_per_gal, crossed, day, date, within_cycle}`. `build_report` now also emits `projected_end_tier`, `num_tiers`, and a plain-language **`insight`** string (e.g. *"You're in Tier 5. At the current pace you'll hit Tier 6 ($10.97/100 ft³) in ~2 days, and the cycle should close in Tier 6."*; turns into a top-tier message when already maxed).
- **`templates/costs.html`** — new **insight banner** (amber→red gradient, red when in the top tier) + a **Tier journey** card: a Chart.js line chart with X = day of billing cycle (0→cycle_days), Y = cumulative ft³ used. Each price tier is a **shaded horizontal band** labeled with its $/100 ft³ rate (custom `tierBands` inline plugin draws the bands + a dashed green "now" vertical marker). **Solid green line** = usage so far (built from real in-cycle snapshots, bracketed by start=0 and now), **dashed orange line** = projection to cycle close. Below it: a tier-color **legend** and a **progression table** (per tier: $/gal, gallons-to-enter, day/date crossed-or-projected, status ✓in-it / projected / not-this-cycle).
- **Verified live (server venv):** Day 16/30, Tier 5, 911 ft³/6,818 gal @ 426 gal/day → **projected to cross into Tier 6 ~day 17.6 (~2 days)**, cycle closes Tier 6, projected bill **$293.72**. Progression table cross-days: T2 day3.5, T3 day7, T4 day10.5, T5 day14, T6 day17.6.
- **Historical drill-in caveat:** last month's bills only give start/end meter reads (no per-day granularity), so the Tier-journey graph can't replay June retroactively. It builds true day-by-day shape **going forward** from the daily snapshots — a full cycle from now, any month can be drilled into with real daily resolution.

**Next ideas:** add a tiny APScheduler job in `server.py` to call `water_cost.record_daily_snapshot()` once/day so history has no gaps even if nobody opens the page (held off — `server.py` overlaps the cam chat's edits); wire `should_tighten_budget`-style conservation off the *real* meter (not just irrigation estimate); push a daily/cycle cost line into the ntfy digest.

---

## 2026-06-11 — Water meter OCR: lag buffer + offload to gaming tower (jackmint)

**Context:** The original water-meter ESP32-CAM (board #1) died (see esp32-cam-journey). Flashed the replacement (board #2, static IP 192.168.0.160), then re-enabled OCR — but running it on the gaming tower (jackmint), 100% on-prem, with a buffer so no frame is lost if OCR lags.
**Architecture:**
- Cam pushes SVGA JPEG every 5s → Acer `/api/cam/upload`.
- Acer `cam_upload` drops the frame into a bounded **in-memory FIFO `deque(maxlen=100)`** — the lag buffer. Non-blocking; a full queue drops the oldest (we only want the latest reading, never a backlog). No disk, no history.
- A background `_ocr_worker` thread drains oldest-first and POSTs each frame to the **tower OCR service** (`http://192.168.0.120:5200/ocr`).
- `MeterReader.process_text(raw_text)` (new, in `cam_ocr.py`) reuses the existing extract/validate/median logic — heavy OCR is off-box, the smarts stay on the Acer.
- `/api/cam/status` now exposes `ocr{queue_depth, processed, errors, dropped, last_ms}`.
**Tower OCR (jackmint, 192.168.0.120):** `meter-ocr` systemd service (enabled), `~/meter-ocr/.venv` + `meter_ocr_service.py` (in `water-meter-cam/tower-ocr/`). Engine = **RapidOCR** (PP-OCRv4 models via ONNXRuntime, CPU). Chose it over PaddlePaddle-GPU because the GTX 970 (Maxwell) + Python 3.12 makes GPU builds painful, and CPU OCR (~600–730ms/frame) is far faster than the 5s cadence anyway. moondream (Ollama VLM) was rejected — unreliable for digit reading.
**Verified end-to-end:** tower log shows frames arriving ~5s apart, each OCR'd in ~700ms (never falls behind). Text currently empty because the cam is on the desk, not mounted over the meter — expected.
**Deploy gotcha:** the Acer's `dashboard.py` was **73 lines ahead** of the local repo — pulled the server copy down and edited against it to avoid clobbering. Service is `smart-garden-server`, dir `~/smart-garden-server/`.
**Next:** mount cam over the meter (upside-down; OCR flips 180°), confirm 9-digit Sensus reads land on the dashboard. To swap OCR engine later, change `OCR_TOWER_URL` env or upgrade the tower service.

---

## Quick Reference

### Control chain
```
Copilot → SSH Acer (192.168.0.109) → curl ESP32 (192.168.0.150) → valve actuates
```
SSH: `jamesearlpace@192.168.0.109` password `KeepingP@ce8!` (key auth configured, no prompt).

### Common commands
```powershell
# Status
ssh jamesearlpace@192.168.0.109 "curl -s http://192.168.0.150/api/status"

# Open / close valve (id=0..9, zero-indexed)
ssh jamesearlpace@192.168.0.109 "curl -s -X POST 'http://192.168.0.150/api/valve?id=0&action=open'"
ssh jamesearlpace@192.168.0.109 "curl -s -X POST 'http://192.168.0.150/api/valve?id=0&action=close'"

# Close all
ssh jamesearlpace@192.168.0.109 "curl -s -X POST 'http://192.168.0.150/api/closeall'"

# Server dashboard
http://192.168.0.109:5125
```

### Deploy server changes
```powershell
cd C:\MyCode\smart-garden\server-prod
scp database.py dashboard.py irrigation.py server.py jamesearlpace@192.168.0.109:~/smart-garden-server/
scp templates/*.html jamesearlpace@192.168.0.109:~/smart-garden-server/templates/
ssh jamesearlpace@192.168.0.109 "sudo systemctl restart smart-garden-server.service"
```
**Local working copies:** `C:\MyCode\smart-garden\server-prod\` (mirrors `~/smart-garden-server/` on Acer).
**NOT a git repo on the server** — deploy by scp, not pull.

### Flash firmware (USB only — OTA disabled)
```powershell
cd C:\MyCode\smart-garden
pio run -e esp32 --target upload --upload-port COM5
pio device monitor --baud 115200 --port COM5
```

---

## Architecture

### Hardware
| Component | Model | Notes |
|-----------|-------|-------|
| MCU | ESP32-WROOM-32U | External antenna, MAC `00:70:07:26:48:DC` (replacement board, old `68:FE:71:0C:BA:98` fried 2026-05-27), static IP 192.168.0.150 |
| I/O Expander | Waveshare MCP23017 | I2C addr 0x27, valves 1-8 on PA0-PB7 |
| Antenna | 2.4 GHz 5dBi external | U.FL/IPEX connector on 32U |
| Solar | ECO-WORTHY 10W 12V | ~1.6 Ah/day in Duvall WA |
| Charge ctrl | Renogy Wanderer Li 10A | Battery + load output. **Brownout source.** |
| Battery | ExpertPower 12V 7Ah SLA | |
| Buck | LM2596 | 12V → 5V to ESP32 VIN. 1000µF cap on output. |
| Power gate | IRF4905 P-FET + 2N3904 NPN | GPIO 2 controls 12V to L298N boards |
| H-bridge | L298N × 5 | 2 valves per board, 10 valves total |
| Valves | Orbit 57861 DC latching | Pulse open, reverse pulse close |
| Caps | 1000µF + 100nF on 3.3V rail | Brownout protection for WiFi TX spikes |
| Server | Acer Aspire A314-23P | Linux Mint 22.1, 192.168.0.109 |

### Network
```
Ziply Fiber → Netgear GS305E → TP-Link ER605 (.1) → Eero 6
  ├─ Acer (.109, wired)
  └─ ESP32 (.150, WiFi static)
```

### Server (Acer)
- Repo deploy path: `~/smart-garden-server/` (NOT git)
- Service: `smart-garden-server.service` (systemd)
- Port: 5125
- Stack: Flask + waitress + apscheduler + SQLite (WAL)
- Logs: `journalctl -u smart-garden-server.service -f`
- Secondary collector service writes to `~/smart-garden/server/smart-garden.db` every 60s — dashboard falls back to this DB if main DB is >10 min stale (see archive: 2026-04-17)

### Alerting
**ntfy.sh/smart-garden-james** (NOT Pushover — ignore any old refs to Pushover). Title header is stripped to ASCII before send (emoji bug fix #11).

**Active monitoring (since 2026-04-22, commit `e53417a`):**
The server's `AlertMonitor` runs every poll cycle (5 min) on the Acer. It fires ntfy alerts on:
- ESP32 unreachable >15 min (`_check_offline`)
- Crash loop: >5 reboots in 1h (`_check_crash_loop`)
- Safe mode active (`_check_safe_mode`)
- Free heap <15% (`_check_memory`)
- Sensor flatline/railed >48h (`_check_sensor_faults`)
- **NVS counter delta** — `bootCount`, `wifiReconnects`, `crashCount` increase between polls (steady state on wall power = 0 delta, any change is news) (`_check_counter_deltas`)
- Chip temp >85°C (`_check_chip_temp`)

**Daily 8 AM digest** — single ntfy with 24h summary: uptime, RSSI, reconnect count, crash count, boot count delta, free heap, dashboard online %.

**Startup ping** — one ntfy 10s after server start = "pipeline alive" confirmation.

Alert cooldown: 30 min per alert key (won't spam the same alert).

---

## Critical reliability rules

### Brownout = root cause of every recent failure
The Wanderer load output sags voltage during high-current bursts. **Affects every high-current op:**
- OTA upload → bricks chip (5–10% into upload)
- `ESP.restart()` via `/api/reboot` → bricks chip
- Suspected: simultaneous valve pulses, WiFi reconnect storms

**Mitigation in firmware** (deployed 2026-05-01):
- Low-boot TX: `WIFI_BOOT_TX_DBM = WIFI_POWER_8_5dBm` during connect, bumps to `WIFI_TX_DBM = WIFI_POWER_19_5dBm` after WiFi established
- ArduinoOTA wrapped in `#ifdef ENABLE_OTA` (default OFF)
- Close-all valves only on clean boot, not crash reboots
- Deep sleep 10 min after 10 consecutive crashes (battery protection)
- Decoupling caps: 1000µF + 100nF on 3.3V rail, 1000µF on buck output

**Real fix (not yet done):** 1000µF + 100nF decoupling cap on 3.3V rail. See GitHub issue #2.
**UPDATE 2026-05-01:** Caps installed ✅. Low-boot TX strategy also deployed — ESP32U boots clean on battery-only power now.

### Verification playbook — confirm "still healthy"

**A. Quick health probe (30s)**
```powershell
ssh jamesearlpace@192.168.0.109 "curl -s --max-time 8 http://192.168.0.150/api/status" | python -c "import sys,json; d=json.load(sys.stdin); s=d['system']; h=d.get('health',{}); print(f'boot={s[\"bootCount\"]} uptime={s[\"uptimeSec\"]}s rssi={s[\"wifiRSSI\"]} reconnects={s[\"wifiReconnects\"]} crashCount={h.get(\"crashCount\")} safeMode={h.get(\"safeMode\")} temp={s.get(\"chipTempC\")}')"
```
Good: rssi -29 to -50, reconnects 0, safeMode False, uptime > 600s, chipTempC < 90.
Red flags: rssi worse than -65, reconnects climbing, safeMode True.

**chipTempC interpretation** — the ESP32 internal temp sensor is famously uncalibrated and noisy. **Real die temp at this deployment is ~77–78°C steady** (verified 2026-04-22 with 10 rapid samples + 30 soak samples: min 77.2, max 86.7, avg 77.8). Single-sample readings of 100°C+ followed seconds later by 78°C are sensor glitches, not thermal events — physics says the die can't cool 30°C in 4 minutes. Trust a *sustained* high reading, not a spike. See open issue for alert hysteresis fix.

**B. Dashboard cadence test (5 min)**
```powershell
ssh jamesearlpace@192.168.0.109 'for i in $(seq 1 10); do printf "%s " "$(date +%H:%M:%S)"; curl -s http://localhost:5125/api/dashboard | python3 -c "import sys,json; d=json.load(sys.stdin); print(\"online_flag=\"+str(d.get(\"esp32_online\")))"; sleep 30; done'
```
Expected: 10/10 `online_flag=True`. Less means TIME_WAIT or signal regression.

**C. Network probe (only if B fails)** — see archive 2026-04-21 for `tcpdump` recipe.

### The "before saying it's fixed" gate
Before any "you can box it up" / "last flash" / "OTA will work" / "ship it" claim:
1. USB physically disconnected
2. Chip on real deployed power source
3. At deployed location
4. Health probe (A) clean
5. Dashboard cadence (B) 10/10 over 5 min
6. **Then** make the claim. Not before.

This rule exists because I broke it 4 times in one session on 2026-04-21. See `/memories/mistake-ledger.md` M2 and [smart-garden#4](https://github.com/jamesearlpace/smart-garden/issues/4).

---

## Open issues

| Repo | # | Sev | Summary |
|------|---|-----|---------|
| smart-garden | [#5](https://github.com/jamesearlpace/smart-garden/issues/5) | **HIGH** | **Web server wedge** — chip RSTs SYNs on port 80 in 3-5 min cycles. ESPAsyncWebServer ruled out 2026-04-27 (5/7 fail at production cadence, identical pcap signature). **Bug is in lwIP / WiFi driver layer, NOT the application web server.** Self-recovers eventually (n=2 confirmed today). Server retry pattern catches most instances. Next candidates: ESP-IDF v5.x upgrade, `WiFi.setCountry()`, sdkconfig `lwip_max_listening` bump, or smart-plug out-of-band recovery. |
| smart-garden | [#6](https://github.com/jamesearlpace/smart-garden/issues/6) | **Med-High** | WiFi TX power varies between boots (7.8 / 14.3 / 14.8 / 14.0 dBm across 4 boots) despite `WIFI_POWER_19_5dBm` config. `setTxPower()` returns true; ESP-IDF runtime regulatory cap silently lowers actual TX. Telemetry pipeline shipped (`tx_power_raw` column + dashboard column). Hypothesis "low-TX boots cause WiFi watchdog cascades" weakened by today's wedges occurring at 14.3 dBm too. Need ~1 week of data. |
| smart-garden | [#2](https://github.com/jamesearlpace/smart-garden/issues/2) | Low | **Decoupling cap on 3.3V rail** — user buying 1000µF + 100nF caps. Fixes brownout class (M3): OTA bricks, ESP.restart() bricks, multi-valve simultaneous brownout. **Does NOT fix wedge** — confirmed today (wedges happen on USB power too, no brownout reset reason). Unlocks re-enabling OTA. |
| smart-garden | — | ~~Med~~ | ~~WiFi watchdog too aggressive~~ ✅ **SHIPPED** commit `53a91d9` (2026-04-27 07:34): threshold 60s→5min, close-all valves before `ESP.restart()`. |
| smart-garden | — | ~~Med~~ | ~~TWDT not subscribed~~ ✅ **STALE** — TWDT IS subscribed (`esp_task_wdt_add(NULL)` at `main.cpp:791`). Confirmed in serial. |
| smart-garden | [#4](https://github.com/jamesearlpace/smart-garden/issues/4) | Meta | Recurrent AI mistake: premature "ship it" claims |
| smart-garden | [#1](https://github.com/jamesearlpace/smart-garden/issues/1) | Meta | (Earlier) contradictory OTA claims |
| smart-garden | — | ~~Low~~ | ~~Wire voltage divider from battery to GPIO 36~~ ✅ **SHIPPED** commit `a01b3f5` (2026-04-27 07:50): 6:1 ratio. Wired — needs multimeter+serial verification before closing. |
| smart-garden-server | (closed) | — | Chip-temp false positives — fixed 2026-04-22. |
| smart-garden-server | (closed) | — | #10 TIME_WAIT, #11 emoji, #12 reboot wiring — closed 2026-04-21. |
| smart-garden-server | ✅ closed | — | dashboard.py bypass routes — FIXED `624b6d9` (2026-04-26). |
| smart-garden-server | ✅ closed | — | #15 banner past-time, #16 mm-as-inches, #17 forecast dark theme, #18 missing templates, #19 orphan routes, #20 dead templates, #21 forecast no sidebar, #22 mobile nav drift, #23 server clutter, #24 redundant breadcrumb, #25 sidebar footer drift — all SHIPPED 2026-06-03. See session log below. |
| smart-garden-server | ✅ closed | — | #3 same-zone double-click leaked orphan `watering_event` rows — FIXED 2026-06-04: idempotent guard in `start_zone_watering()`. Orphan event 164 backfilled. See June 4 session log. |
| smart-garden-server | ✅ closed | — | #4 `daily_summary` table had no populator (empty since inception) — FIXED 2026-06-04: `BillingCalculator.update_daily_summary()` + 23:55 scheduler job + 59-day backfill. See June 4 session log. |
| smart-garden-server | ✅ closed | — | #5 `skip_event` table empty — `log_skip_event()` defined but never called. FIXED 2026-06-04: wired into `run_cycle()`'s skip branch with per-zone per-day de-dupe via `db.skip_event_exists_today()`. First cycle produced 7 rows (648 gal / $0.36 saved). See June 4 session log. |

---

## Key decisions

1. **Latching solenoids** — Orbit 57861, hold position with no power
2. **L298N H-bridge** — Cheap polarity-reversal driver
3. **Acer as bridge** — Copilot can't reach LAN IPs directly

---

## Hardware to-do (when parts arrive)

Per archive 2026-04-14: P-channel MOSFET power gate for L298N rail + ESP32 deep sleep between watering windows. Estimated battery draw 76-148 mA → 11-18 mA (battery life 2-3 days → ~20 days).

Parts ordered: 10kΩ + 1kΩ resistors. **TO ORDER:** ~~IRF4905 P-FET, 2N3904 NPN~~. Full circuit + wiring steps in archive.

**UPDATE 2026-04-26:** MOSFET gate **installed and verified** (see Recently shipped). Battery monitoring also shipped. Deep sleep (Phase 2) deferred — user wants to observe battery behavior with gate alone first.

---

## Physical Installation Plan & Parts Inventory

**Full purchase history, fitting analysis, and shopping list** → [purchase-history.md](purchase-history.md)

**Design:** 2 valve boxes, 9 valves total, 27 Rain Bird 42SA+ rotor heads, 2 drip zones. 1in poly trunk splits to two valve box manifolds. ¾in poly laterals to each zone. ½in swing pipe risers to rotors.

**Water source:** 60 PSI, ~6 GPM at top of hill. No reducers needed for sprinkler zones. Pressure regulators on drip zones only.

**Status (2026-05-01):** ~$106 of fittings/rotors/valves still needed before install. See shopping list at bottom of purchase-history.md.

---

## Pre-flight before auto-watering kicks in

Run this checklist any time you're about to flip the engine on for a new season or after a long pause. The goal is to confirm the engine, the hardware, and the calibration story all agree before grass health depends on it.

### Tier 1 — Must do before tomorrow's first run

1. **Confirm all sprinkler zones are `auto_mode: true` on the server.**
   ```powershell
   ssh jamesearlpace@192.168.0.109 "grep -E '  (auto_mode|name):' ~/smart-garden-server/config.yaml"
   ```
   Expected: zones 0-6 = true, zones 7-9 = false (drip + spare).

2. **Check the watering window in [config.yaml](server-prod/config.yaml).**
   Currently `04:00-07:00`. With 7 zones × 24 min runtime = 168 min = 2:48 → fits in the 3-hour window with no margin. If a zone soaks longer than expected or one starts late, the window can run out and the next zone won't fire. Consider widening to `04:00-08:00` for safety.

3. **Verify the engine actually has a current soil balance for each zone.**
   ```powershell
   ssh jamesearlpace@192.168.0.109 "curl -s http://localhost:5125/api/dashboard | python3 -c 'import sys,json; d=json.load(sys.stdin); [print(z[\"name\"], z.get(\"balance_mm\"), z.get(\"mad_mm\")) for z in d.get(\"zones\",[])]'"
   ```
   If balance is `null` or stale, the engine won't decide correctly on day 1.

4. **Open the dashboard ([http://192.168.0.109:5125](http://192.168.0.109:5125)) and verify each zone's "Next watering" prediction is reasonable.**
   No prediction = engine doesn't know what to do. Wildly soon (today) on a recently-wet zone = stale balance. Far-future = balance might be inflated.

### Tier 2 — Should do within first week

5. **Catch-can calibration test** (15 min, ~$5 worth of tuna cans). This is the highest-leverage thing on the whole list. Steps:
   - Distribute 6-8 empty straight-sided cans randomly across a single zone
   - From dashboard, run that zone for exactly 15 minutes (Manual mode → Run)
   - Measure water depth in each can with a ruler (mm). Average them.
   - Real precip rate (in/hr) = average mm × 4 ÷ 25.4
   - Compare to `precip_rate_iph` in config. If real is much lower (likely 0.5-0.8 vs config's 1.0-1.5), **update config** and redeploy. The audit predicted this; confirm it.
   - Repeat per zone — different head models and pressure give different rates.

6. **Walk the lawn at sunset every 2-3 days for the first 2 weeks.**
   First stress signals: dull blue-green color, yellow tips, footprints staying visible (lack of turgor). If you see any: switch the affected zone to Manual, run a long soak, and lower its `precip_rate_iph` to force more frequent automatic cycles.

7. **Confirm the daily 8 AM ntfy digest is firing** (the same one that reports ESP32 health). It should also show last 24h irrigation events. If watering decisions aren't showing up there, the engine's not actually triggering anything — check `journalctl -u smart-garden-server.service -f`.

### Tier 3 — Optional / nice to have

8. **Set a conservative `precip_rate_iph` floor temporarily.** Until catch-can numbers are in, override config to multiply current rates by ~0.6 (e.g. 1.5 → 0.9, 1.3 → 0.8, 1.0 → 0.6). This makes the engine assume *less* water is being deposited, so it will water *more* often — safer error direction while uncalibrated.

9. **File two GitHub issues from the audit:**
   - "Calibrate `precip_rate_iph` per zone via catch-can test" — captures the calibration TODO and links results back to config.yaml
   - "Engine should size runtime to soil deficit, not run fixed cycle_run_min × cycle_count" — currently the only lever to change watering depth is `cycle_run_min`; engine should compute runtime as `(TAW - balance) / precip_rate_iph` clamped to `max_runtime_min`

10. **Set a manual rollback plan in your head.** If grass starts browning fast: flip all auto-mode zones to Manual on the dashboard, run each one for 30-45 min once, then troubleshoot config rather than letting another auto cycle make it worse.

### Quick rollback if something looks wrong tomorrow morning

```powershell
# Flip ALL zones to manual immediately
ssh jamesearlpace@192.168.0.109 "sed -i 's/auto_mode: true/auto_mode: false/g' ~/smart-garden-server/config.yaml && sudo systemctl restart smart-garden-server.service"
```

This stops the engine from making any further automatic decisions until you've diagnosed. Re-enable per-zone via the dashboard.



---

