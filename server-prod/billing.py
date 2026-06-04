"""Duvall water billing calculator.

Implements the City of Duvall 2025 tiered water rate structure.
Tracks cumulative monthly usage and calculates actual cost vs
what a dumb timer would have cost.
"""

import logging
from datetime import date, datetime

import database as db

log = logging.getLogger("smart-garden.billing")

CF_PER_GALLON = 1 / 7.48  # 1 cubic foot = 7.48 gallons


class BillingCalculator:

    def __init__(self, config: dict):
        billing = config["billing"]
        self.cycle_start_day = billing["cycle_start_day"]
        self.tiers = billing["tiers"]     # list of {max_cf, rate}
        self.base_fee = billing["base_fee"]
        self.sewer_flat = billing["sewer_flat"]
        self.storm_flat = billing["storm_flat"]

    def cost_for_cf(self, total_cf: float) -> float:
        """Calculate the water cost for a given total cubic feet usage.
        Applies Duvall's progressive tiered rates."""
        cost = self.base_fee
        remaining = total_cf
        prev_max = 0

        for tier in self.tiers:
            tier_max = tier["max_cf"]
            rate = tier["rate"]
            tier_size = tier_max - prev_max  # cf in this tier band

            if remaining <= 0:
                break

            used_in_tier = min(remaining, tier_size)
            # Rate is per 100 cf
            cost += (used_in_tier / 100.0) * rate
            remaining -= used_in_tier
            prev_max = tier_max

        return cost

    def marginal_rate(self, current_cf: float) -> float:
        """What does the NEXT 100 cf cost at the current usage level?
        This is what the smart system saves."""
        for tier in self.tiers:
            if current_cf < tier["max_cf"]:
                return tier["rate"]
        return self.tiers[-1]["rate"]

    def current_tier_index(self, current_cf: float) -> int:
        """Which tier is the customer currently in? (1-indexed)"""
        for i, tier in enumerate(self.tiers):
            if current_cf < tier["max_cf"]:
                return i + 1
        return len(self.tiers)

    def get_monthly_bill_estimate(self, month: str = None) -> dict:
        """Calculate current month's estimated bill from actual irrigation data."""
        if month is None:
            month = date.today().strftime("%Y-%m")

        usage = db.get_monthly_usage(month)
        irrigation_cf = usage["total_cf"]

        # Estimate indoor usage at ~150 cf/month (typical household)
        indoor_cf = 150.0
        total_cf = indoor_cf + irrigation_cf

        water_cost = self.cost_for_cf(total_cf)
        total_bill = water_cost + self.sewer_flat + self.storm_flat

        return {
            "month": month,
            "indoor_cf": indoor_cf,
            "irrigation_cf": irrigation_cf,
            "total_cf": total_cf,
            "water_cost": round(water_cost, 2),
            "sewer": self.sewer_flat,
            "storm": self.storm_flat,
            "total_bill": round(total_bill, 2),
            "current_tier": self.current_tier_index(total_cf),
            "marginal_rate": self.marginal_rate(total_cf),
        }

    def get_savings_report(self, month: str = None) -> dict:
        """Compare actual usage vs what a timer-based system would use."""
        if month is None:
            month = date.today().strftime("%Y-%m")

        usage = db.get_monthly_usage(month)
        savings = db.get_monthly_savings(month)

        actual_irrigation_cf = usage["total_cf"]
        cf_saved = savings["cf_saved"]
        timer_irrigation_cf = actual_irrigation_cf + cf_saved

        indoor_cf = 150.0

        actual_total = indoor_cf + actual_irrigation_cf
        timer_total = indoor_cf + timer_irrigation_cf

        actual_cost = self.cost_for_cf(actual_total)
        timer_cost = self.cost_for_cf(timer_total)
        money_saved = timer_cost - actual_cost

        return {
            "month": month,
            "smart_irrigation_cf": round(actual_irrigation_cf, 1),
            "timer_irrigation_cf": round(timer_irrigation_cf, 1),
            "cf_saved": round(cf_saved, 1),
            "gallons_saved": round(cf_saved * 7.48, 0),
            "skip_count": savings["skip_count"],
            "smart_cost": round(actual_cost, 2),
            "timer_cost": round(timer_cost, 2),
            "money_saved": round(money_saved, 2),
            "savings_pct": round((cf_saved / timer_irrigation_cf * 100), 1)
            if timer_irrigation_cf > 0 else 0,
            "smart_tier": self.current_tier_index(actual_total),
            "timer_tier": self.current_tier_index(timer_total),
        }

    def should_tighten_budget(self, month: str = None) -> dict:
        """Check if we're trending toward an expensive tier and should conserve.
        Returns advice for the decision engine."""
        if month is None:
            month = date.today().strftime("%Y-%m")

        today = date.today()
        day_of_month = today.day
        days_in_month = 30  # approximate

        usage = db.get_monthly_usage(month)
        current_cf = 150.0 + usage["total_cf"]  # indoor + irrigation
        daily_rate = usage["total_cf"] / max(day_of_month, 1)
        projected_cf = current_cf + daily_rate * (days_in_month - day_of_month)

        tier = self.current_tier_index(current_cf)
        projected_tier = self.current_tier_index(projected_cf)

        tighten = False
        reason = None

        if projected_tier >= 5 and day_of_month > 15:
            tighten = True
            reason = f"Projected {projected_cf:.0f} cf (tier {projected_tier}) — conserving to avoid tier {projected_tier} rates"
        elif tier >= 5:
            tighten = True
            reason = f"Already in tier {tier} at {current_cf:.0f} cf — marginal water costs ${self.marginal_rate(current_cf):.2f}/100cf"

        return {
            "tighten": tighten,
            "reason": reason,
            "current_cf": round(current_cf, 1),
            "projected_cf": round(projected_cf, 1),
            "current_tier": tier,
            "projected_tier": projected_tier,
            "marginal_rate": self.marginal_rate(current_cf),
            "day_of_month": day_of_month,
        }

    # Indoor baseline assumed when computing tier-aware daily costs.
    # Matches the 150 cf/month estimate used by get_monthly_bill_estimate().
    INDOOR_CF_PER_MONTH = 150.0
    DAYS_IN_MONTH = 30  # approximation matching should_tighten_budget()

    def update_daily_summary(self, date_str: str | None = None) -> dict:
        """Aggregate per-day water + skip + weather + cost into daily_summary.

        Cost uses the difference-of-cumulative-cost approach so that tier
        transitions mid-day are charged correctly and the base fee cancels.
        Safe to re-run for any date — upserts on (date) primary key.
        """
        if date_str is None:
            date_str = date.today().strftime("%Y-%m-%d")

        month = date_str[:7]
        try:
            day_of_month = datetime.strptime(date_str, "%Y-%m-%d").day
        except ValueError:
            log.error("update_daily_summary: invalid date_str %r", date_str)
            return {}

        indoor_today = self.INDOOR_CF_PER_MONTH * (day_of_month / self.DAYS_IN_MONTH)
        indoor_yday = (
            self.INDOOR_CF_PER_MONTH * ((day_of_month - 1) / self.DAYS_IN_MONTH)
            if day_of_month > 1 else 0.0
        )

        conn = db.get_conn()
        try:
            row = conn.execute(
                "SELECT COALESCE(SUM(est_gallons), 0) AS gal, "
                "       COALESCE(SUM(est_cf), 0) AS cf "
                "FROM watering_event "
                "WHERE DATE(start_ts) = ? AND end_ts IS NOT NULL",
                (date_str,),
            ).fetchone()
            total_gallons = float(row["gal"])
            total_cf = float(row["cf"])

            row = conn.execute(
                "SELECT COALESCE(SUM(est_gallons_saved), 0) AS gal, "
                "       COALESCE(SUM(est_cf_saved), 0) AS cf "
                "FROM skip_event WHERE DATE(ts) = ?",
                (date_str,),
            ).fetchone()
            gallons_saved = float(row["gal"])
            cf_saved = float(row["cf"])

            row = conn.execute(
                "SELECT COALESCE(SUM(est_cf), 0) AS cf "
                "FROM watering_event "
                "WHERE strftime('%Y-%m', start_ts) = ? "
                "  AND DATE(start_ts) <= ? AND end_ts IS NOT NULL",
                (month, date_str),
            ).fetchone()
            cum_cf_today = float(row["cf"])
            cum_cf_yday = cum_cf_today - total_cf

            row = conn.execute(
                "SELECT COALESCE(SUM(est_cf_saved), 0) AS cf "
                "FROM skip_event "
                "WHERE strftime('%Y-%m', ts) = ? AND DATE(ts) <= ?",
                (month, date_str),
            ).fetchone()
            cum_saved_today = float(row["cf"])
            cum_saved_yday = cum_saved_today - cf_saved

            cost_after = self.cost_for_cf(indoor_today + cum_cf_today)
            cost_before = self.cost_for_cf(indoor_yday + cum_cf_yday)
            cost = max(0.0, cost_after - cost_before)

            timer_after = self.cost_for_cf(
                indoor_today + cum_cf_today + cum_saved_today)
            timer_before = self.cost_for_cf(
                indoor_yday + cum_cf_yday + cum_saved_yday)
            cost_avoided = max(0.0, (timer_after - timer_before) - cost)

            row = conn.execute(
                "SELECT et0_mm, rain_mm FROM soil_balance "
                "WHERE zone_id = 0 AND date = ?",
                (date_str,),
            ).fetchone()
            et0_mm = row["et0_mm"] if row else None
            rain_mm = row["rain_mm"] if row else None

            row = conn.execute(
                "SELECT AVG(temp_f) AS avg_f FROM weather_log "
                "WHERE source = 'api' AND DATE(ts) = ?",
                (date_str,),
            ).fetchone()
            avg_temp_f = row["avg_f"] if row else None

            conn.execute(
                "INSERT INTO daily_summary "
                "(date, total_gallons, total_cf, gallons_saved, cf_saved, "
                " cost, cost_avoided, et0_mm, rain_mm, avg_temp_f) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(date) DO UPDATE SET "
                "  total_gallons = excluded.total_gallons, "
                "  total_cf      = excluded.total_cf, "
                "  gallons_saved = excluded.gallons_saved, "
                "  cf_saved      = excluded.cf_saved, "
                "  cost          = excluded.cost, "
                "  cost_avoided  = excluded.cost_avoided, "
                "  et0_mm        = excluded.et0_mm, "
                "  rain_mm       = excluded.rain_mm, "
                "  avg_temp_f    = excluded.avg_temp_f",
                (date_str, total_gallons, total_cf, gallons_saved, cf_saved,
                 cost, cost_avoided, et0_mm, rain_mm, avg_temp_f),
            )
            conn.commit()
        finally:
            conn.close()

        log.info(
            "daily_summary[%s]: %.1f gal / $%.2f (saved %.1f gal / $%.2f)",
            date_str, total_gallons, cost, gallons_saved, cost_avoided,
        )
        return {
            "date": date_str,
            "total_gallons": round(total_gallons, 1),
            "total_cf": round(total_cf, 2),
            "gallons_saved": round(gallons_saved, 1),
            "cf_saved": round(cf_saved, 2),
            "cost": round(cost, 2),
            "cost_avoided": round(cost_avoided, 2),
            "et0_mm": et0_mm,
            "rain_mm": rain_mm,
            "avg_temp_f": avg_temp_f,
        }
