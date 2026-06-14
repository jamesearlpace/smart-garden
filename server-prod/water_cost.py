"""Real-meter water cost tracker (City of Duvall).

Drives a dollar view of the household's ACTUAL water consumption read off the
physical Sensus meter by the ESP32-CAM OCR pipeline — distinct from billing.py,
which estimates only the irrigation slice from sprinkler run-time.

The meter is the source of truth: it measures whole-house usage, which is
exactly what the City bills. We snapshot the live OCR reading once per day into
``meter_snapshot`` so true billing-cycle history accrues over time, and we anchor
to the real paper bills (verified to the penny) so the page is accurate from day
one — before a full cycle of snapshots exists.

Read-only with respect to all cam code: this module never touches cam_ocr.py,
the cam routes, or the meter lock state. It only reads ``MeterReader.last_good``
(passed in by the caller) and owns its own ``meter_snapshot`` table.

Units
-----
* The Sensus LCD shows 9 digits where the rightmost 3 are DECIMALS, so the
  integer ``last_good`` (e.g. 94008348) means 94,008.348 ft3. cf = last_good/1000.
* The City bills in CCF = hundreds of cubic feet. 1 CCF = 100 ft3 = 748.052 gal.
* Water is billed on an inclining-block tier schedule; the base fee includes the
  first 200 cf. Sewer and storm are flat each month.

Rate source: City of Duvall 2023-2026 Utility Rates History (in-city
residential). See smart-garden-journey.md "Water Rate Structure".
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta

import database as db

log = logging.getLogger("smart-garden.water_cost")

GAL_PER_CF = 7.48052
CF_PER_CCF = 100
GAL_PER_CCF = GAL_PER_CF * CF_PER_CCF  # 748.052

# Source link shown on the page / used to refresh rates for 2027+.
RATE_SOURCE_URL = (
    "https://www.duvallwa.gov/DocumentCenter/View/14564/"
    "2023---2026--Utility-Rates-History"
)
RATE_YEAR = 2026

# Real paper bills, account 001-0006184-004 (Natalie Pace, 27201 NE 144th Pl),
# verified to the penny against the 2026 tier table. Used to (a) anchor the
# current open cycle's starting register and (b) render real history before a
# full cycle of daily snapshots exists. Register reads are CCF; cf = CCF*100.
BILLS = [
    {"due": "2026-04-20", "period": ("2026-02-26", "2026-03-25"),
     "start_ccf": 892, "end_ccf": 896, "used_cf": 400,
     "water": 44.46, "sewer": 91.18, "storm": 32.17, "total": 167.81},
    {"due": "2026-05-20", "period": ("2026-03-25", "2026-04-27"),
     "start_ccf": 896, "end_ccf": 906, "used_cf": 1000,
     "water": 92.60, "sewer": 91.18, "storm": 32.17, "total": 215.95},
    {"due": "2026-06-22", "period": ("2026-04-27", "2026-05-27"),
     "start_ccf": 906, "end_ccf": 931, "used_cf": 2500,
     "water": 257.15, "sewer": 91.18, "storm": 32.17, "total": 380.50},
]

# Typical Duvall read-to-read cycle length (days). Periods above ran 27/33/30d.
DEFAULT_CYCLE_DAYS = 30


# ---------------------------------------------------------------------------
#  Schema (isolated table — created idempotently, never drops anything)
# ---------------------------------------------------------------------------
def ensure_schema() -> None:
    conn = db.get_conn()
    try:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS meter_snapshot ("
            "  date       TEXT PRIMARY KEY,"   # local YYYY-MM-DD, one per day
            "  reading_cf REAL NOT NULL,"      # whole-house register in ft3
            "  source     TEXT NOT NULL,"      # 'auto' | 'bill' | 'manual'
            "  ts         TEXT NOT NULL"        # when captured (ISO local)
            ")"
        )
        conn.commit()
    finally:
        conn.close()


def seed_anchors() -> None:
    """Insert the real bill close-reads as snapshots (once) so usage history is
    correct immediately. Bill rows never overwrite an existing daily snapshot."""
    rows = []
    seen = set()
    for b in BILLS:
        for which in ("period", "end"):
            if which == "period":
                d, ccf = b["period"][0], b["start_ccf"]
            else:
                d, ccf = b["period"][1], b["end_ccf"]
            if d in seen:
                continue
            seen.add(d)
            rows.append((d, ccf * CF_PER_CCF, "bill", d + "T00:00:00"))
    conn = db.get_conn()
    try:
        conn.executemany(
            "INSERT OR IGNORE INTO meter_snapshot (date, reading_cf, source, ts) "
            "VALUES (?, ?, ?, ?)",
            rows,
        )
        conn.commit()
    finally:
        conn.close()


def record_daily_snapshot(reading_cf: float, source: str = "auto") -> bool:
    """Record at most one snapshot per local day. Auto snapshots never clobber a
    'bill' anchor or an earlier same-day auto reading (meter is monotonic; the
    first read of the day is the cycle-aligned one we keep). Returns True if a
    new row was written."""
    if reading_cf is None or reading_cf <= 0:
        return False
    today = date.today().strftime("%Y-%m-%d")
    now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    conn = db.get_conn()
    try:
        existing = conn.execute(
            "SELECT 1 FROM meter_snapshot WHERE date = ?", (today,)
        ).fetchone()
        if existing:
            return False
        conn.execute(
            "INSERT INTO meter_snapshot (date, reading_cf, source, ts) "
            "VALUES (?, ?, ?, ?)",
            (today, round(float(reading_cf), 3), source, now),
        )
        conn.commit()
        return True
    finally:
        conn.close()


def get_snapshots(days: int = 120) -> list[dict]:
    """Daily snapshots (oldest first) with per-day usage = diff of consecutive
    readings. The meter is monotonic so usage is always >= 0."""
    conn = db.get_conn()
    try:
        rows = conn.execute(
            "SELECT date, reading_cf, source FROM meter_snapshot "
            "WHERE date >= date('now','localtime',?) ORDER BY date",
            (f"-{int(days)} days",),
        ).fetchall()
    finally:
        conn.close()
    out = []
    prev = None
    for r in rows:
        cf = float(r["reading_cf"])
        used = max(0.0, cf - prev) if prev is not None else 0.0
        out.append({
            "date": r["date"],
            "reading_cf": round(cf, 1),
            "used_cf": round(used, 1),
            "used_gal": round(used * GAL_PER_CF, 1),
            "source": r["source"],
        })
        prev = cf
    return out


# ---------------------------------------------------------------------------
#  Rate math (inclining block; base fee includes the first tier's 200 cf)
# ---------------------------------------------------------------------------
def _rates(config: dict) -> dict:
    b = config["billing"]
    return {
        "tiers": b["tiers"],          # [{max_cf, rate(per 100cf)} ...]
        "base_fee": b["base_fee"],
        "sewer": b["sewer_flat"],
        "storm": b["storm_flat"],
    }


def water_cost(usage_cf: float, rates: dict) -> float:
    """Water-service charge for a full cycle's usage (includes the base fee),
    matching the City's 'Water Service' bill line."""
    cost = rates["base_fee"]
    remaining = max(0.0, usage_cf)
    prev_max = 0
    for tier in rates["tiers"]:
        if remaining <= 0:
            break
        band = tier["max_cf"] - prev_max
        used = min(remaining, band)
        cost += (used / 100.0) * tier["rate"]
        remaining -= used
        prev_max = tier["max_cf"]
    return cost


def tier_breakdown(usage_cf: float, rates: dict) -> list[dict]:
    """Per-tier fill for the usage, for the stacked tier visualization."""
    out = []
    remaining = max(0.0, usage_cf)
    prev_max = 0
    for i, tier in enumerate(rates["tiers"]):
        band = tier["max_cf"] - prev_max
        used = max(0.0, min(remaining, band))
        label = (f"{prev_max + 1:,}\u2013{tier['max_cf']:,} cf"
                 if tier["max_cf"] < 900000 else f"over {prev_max + 1:,} cf")
        if i == 0:
            label = f"first {tier['max_cf']:,} cf (base)"
        out.append({
            "tier": i + 1,
            "label": label,
            "rate": tier["rate"],
            "band_cf": band if tier["max_cf"] < 900000 else None,
            "used_cf": round(used, 1),
            "cost": round((used / 100.0) * tier["rate"], 2),
        })
        remaining -= used
        prev_max = tier["max_cf"]
    return out


def current_tier(usage_cf: float, rates: dict) -> int:
    for i, tier in enumerate(rates["tiers"]):
        if usage_cf < tier["max_cf"]:
            return i + 1
    return len(rates["tiers"])


def marginal_rate(usage_cf: float, rates: dict) -> float:
    """$ per 100 cf for the NEXT cubic feet at the current usage level."""
    for tier in rates["tiers"]:
        if usage_cf < tier["max_cf"]:
            return tier["rate"]
    return rates["tiers"][-1]["rate"]


# ---------------------------------------------------------------------------
#  Report builder (everything the /api/water-cost route returns)
# ---------------------------------------------------------------------------
def _latest_bill_anchor() -> dict:
    """The most recent real bill close-read = start of the current open cycle."""
    b = BILLS[-1]
    return {"date": b["period"][1], "reading_cf": b["end_ccf"] * CF_PER_CCF}


def tier_progression(used_cf: float, daily_cf: float, cycle_days: int,
                     start_date: datetime, rates: dict) -> list[dict]:
    """When did / will the cycle cross into each tier, assuming the cumulative
    usage climbs linearly from the cycle start at ``daily_cf`` per day.

    Tier T (T>=2) is entered when cumulative usage crosses the PREVIOUS tier's
    ``max_cf`` boundary (e.g. tier 2 at 200 cf, tier 6 at 1000 cf). The first
    tier (the base allotment) has no crossing — you start in it.
    """
    tiers = rates["tiers"]
    rate_day = daily_cf if daily_cf > 0 else 0.0
    out = []
    for t in range(2, len(tiers) + 1):
        entry_cf = tiers[t - 2]["max_cf"]           # boundary you cross to enter T
        rate = tiers[t - 1]["rate"]                  # $/100cf charged inside T
        crossed = used_cf >= entry_cf
        day = (entry_cf / rate_day) if rate_day else None
        within = day is not None and day <= cycle_days
        date_str = None
        if day is not None:
            date_str = (start_date + timedelta(days=day)).strftime("%Y-%m-%d")
        out.append({
            "tier": t,
            "entry_cf": entry_cf,
            "entry_gal": round(entry_cf * GAL_PER_CF, 0),
            "rate": rate,
            "rate_per_gal": round(rate / GAL_PER_CCF, 5),
            "crossed": bool(crossed),
            "day": round(day, 1) if day is not None else None,
            "date": date_str,
            "within_cycle": bool(within),
        })
    return out


def build_report(config: dict, current_reading_cf: float | None,
                 stale: bool = False) -> dict:
    rates = _rates(config)
    now = datetime.now()

    meter = None
    if current_reading_cf and current_reading_cf > 0:
        ccf = int(current_reading_cf // CF_PER_CCF)
        meter = {
            "reading_cf": round(current_reading_cf, 3),
            "reading_gal": round(current_reading_cf * GAL_PER_CF, 0),
            "ccf": ccf,
            "stale": bool(stale),
        }

    anchor = _latest_bill_anchor()
    start_cf = anchor["reading_cf"]
    start_date = datetime.strptime(anchor["date"], "%Y-%m-%d")

    cycle = None
    if meter:
        used_cf = max(0.0, current_reading_cf - start_cf)
        days_elapsed = max(1, (now - start_date).days)
        daily_cf = used_cf / days_elapsed
        cycle_days = DEFAULT_CYCLE_DAYS
        days_remaining = max(0, cycle_days - days_elapsed)
        close_date = start_date + timedelta(days=cycle_days)
        projected_used = used_cf + daily_cf * days_remaining

        so_far_water = water_cost(used_cf, rates)
        proj_water = water_cost(projected_used, rates)
        tier_now = current_tier(used_cf, rates)
        tier_end = current_tier(projected_used, rates)
        marg = marginal_rate(used_cf, rates)
        progression = tier_progression(
            used_cf, daily_cf, cycle_days, start_date, rates)
        n_tiers = len(rates["tiers"])

        # Plain-language headline insight.
        next_cross = next((p for p in progression
                           if not p["crossed"] and p["within_cycle"]), None)
        if tier_now >= n_tiers:
            insight = (f"You're in the top tier (Tier {tier_now}) — every gallon "
                       f"now costs the max {marg:.2f}/100 ft\u00b3.")
        elif next_cross:
            days_to = max(0, round(next_cross["day"] - days_elapsed))
            when = "today" if days_to == 0 else (
                "tomorrow" if days_to == 1 else f"in ~{days_to} days")
            insight = (f"You're in Tier {tier_now}. At the current pace you'll "
                       f"hit Tier {next_cross['tier']} "
                       f"(${next_cross['rate']:.2f}/100 ft\u00b3) {when}, and the "
                       f"cycle should close in Tier {tier_end}.")
        else:
            insight = (f"You're in Tier {tier_now} and projected to stay there "
                       f"through the cycle close.")

        cycle = {
            "start_date": anchor["date"],
            "start_cf": start_cf,
            "close_date": close_date.strftime("%Y-%m-%d"),
            "cycle_days": cycle_days,
            "days_elapsed": days_elapsed,
            "days_remaining": days_remaining,
            "used_cf": round(used_cf, 1),
            "used_gal": round(used_cf * GAL_PER_CF, 0),
            "used_ccf": round(used_cf / CF_PER_CCF, 1),
            "daily_cf": round(daily_cf, 1),
            "daily_gal": round(daily_cf * GAL_PER_CF, 0),
            "projected_used_cf": round(projected_used, 0),
            "projected_used_gal": round(projected_used * GAL_PER_CF, 0),
            "so_far_water": round(so_far_water, 2),
            "so_far_total": round(so_far_water + rates["sewer"] + rates["storm"], 2),
            "projected_water": round(proj_water, 2),
            "sewer": rates["sewer"],
            "storm": rates["storm"],
            "projected_total": round(proj_water + rates["sewer"] + rates["storm"], 2),
            "current_tier": tier_now,
            "projected_end_tier": tier_end,
            "num_tiers": n_tiers,
            "marginal_rate": marg,
            "marginal_per_gal": round(marg / GAL_PER_CCF, 5),
            "insight": insight,
            "tier_progression": progression,
            "breakdown": tier_breakdown(projected_used, rates),
        }

    # History: real bills + the in-progress estimate.
    history = []
    for b in BILLS:
        history.append({
            "label": _month_label(b["period"][1]),
            "due": b["due"],
            "period": list(b["period"]),
            "used_cf": b["used_cf"],
            "used_gal": round(b["used_cf"] * GAL_PER_CF, 0),
            "water": b["water"], "sewer": b["sewer"], "storm": b["storm"],
            "total": b["total"], "actual": True,
        })
    if cycle:
        history.append({
            "label": _month_label(cycle["close_date"]) + " (est)",
            "due": None,
            "period": [cycle["start_date"], cycle["close_date"]],
            "used_cf": cycle["projected_used_cf"],
            "used_gal": cycle["projected_used_gal"],
            "water": cycle["projected_water"], "sewer": cycle["sewer"],
            "storm": cycle["storm"], "total": cycle["projected_total"],
            "actual": False,
        })

    return {
        "as_of": now.strftime("%Y-%m-%dT%H:%M:%S"),
        "meter": meter,
        "cycle": cycle,
        "history": history,
        "snapshots": get_snapshots(120),
        "rates": {
            "year": RATE_YEAR,
            "base_fee": rates["base_fee"],
            "sewer": rates["sewer"],
            "storm": rates["storm"],
            "tiers": rates["tiers"],
            "source_url": RATE_SOURCE_URL,
            "gal_per_ccf": round(GAL_PER_CCF, 3),
        },
    }


def _month_label(date_str: str) -> str:
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").strftime("%b %Y")
    except ValueError:
        return date_str
