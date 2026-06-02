"""Duvall water billing calculator.

Implements the City of Duvall 2025 tiered water rate structure.
Tracks cumulative monthly usage and calculates actual cost vs
what a dumb timer would have cost.
"""

import logging
from datetime import date

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
