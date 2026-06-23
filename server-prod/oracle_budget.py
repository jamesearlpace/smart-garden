"""Oracle spend tracking and pacing helpers.

Tracks per-call spend for the meter vision oracle and computes a dynamic daily
call cap that tries to use (but not exceed) a monthly budget.

This is intentionally simple and local:
- stores rows in smart-garden.db,
- estimates per-call USD from token usage (or fallback estimate),
- computes month-to-date spend and suggested daily cap.
"""

from datetime import datetime
import calendar
import logging

import database as db

log = logging.getLogger("smart-garden.oracle_budget")


def ensure_schema():
    conn = db.get_conn()
    try:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS oracle_spend ("
            "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "  ts TEXT NOT NULL,"
            "  provider TEXT,"
            "  model TEXT,"
            "  tokens INTEGER DEFAULT 0,"
            "  usd REAL DEFAULT 0.0"
            ")"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS ix_oracle_spend_ts "
            "ON oracle_spend(ts)"
        )
        conn.commit()
    finally:
        conn.close()


def _cycle_anchor(year, month, day):
    max_day = calendar.monthrange(year, month)[1]
    use_day = min(max(1, int(day)), max_day)
    return datetime(year, month, use_day)


def _add_one_month(dt, cycle_day):
    if dt.month == 12:
        y, m = dt.year + 1, 1
    else:
        y, m = dt.year, dt.month + 1
    return _cycle_anchor(y, m, cycle_day)


def _cycle_bounds(now=None, cycle_start_day=1):
    now = now or datetime.now()
    cycle_day = max(1, int(cycle_start_day or 1))
    this_anchor = _cycle_anchor(now.year, now.month, cycle_day)
    if now >= this_anchor:
        start = this_anchor
    else:
        if now.month == 1:
            py, pm = now.year - 1, 12
        else:
            py, pm = now.year, now.month - 1
        start = _cycle_anchor(py, pm, cycle_day)
    end = _add_one_month(start, cycle_day)
    return start, end


def estimate_usd(tokens, usd_per_1k_tokens=0.0, fallback_call_usd=0.004):
    """Estimate USD cost for one oracle call.

    If token pricing is configured and tokens are known, use token-based cost.
    Otherwise fall back to a flat per-call estimate.
    """
    try:
        tok = int(tokens or 0)
    except Exception:
        tok = 0
    rate = float(usd_per_1k_tokens or 0.0)
    if tok > 0 and rate > 0.0:
        return max(0.0, (tok / 1000.0) * rate)
    return max(0.0, float(fallback_call_usd or 0.0))


def record_call(provider, model, tokens, usd):
    conn = db.get_conn()
    try:
        conn.execute(
            "INSERT INTO oracle_spend (ts, provider, model, tokens, usd) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                datetime.now().isoformat(timespec="seconds"),
                str(provider or ""),
                str(model or ""),
                int(tokens or 0),
                float(usd or 0.0),
            ),
        )
        conn.commit()
    except Exception as e:
        log.debug("record_call failed: %s", e)
    finally:
        conn.close()


def summary(monthly_budget_usd=150.0, fallback_call_usd=0.004,
            now=None, cycle_start_day=1):
    now = now or datetime.now()
    start, nxt = _cycle_bounds(now, cycle_start_day=cycle_start_day)
    start_s = start.isoformat(timespec="seconds")
    next_s = nxt.isoformat(timespec="seconds")
    today = now.strftime("%Y-%m-%d")

    conn = db.get_conn()
    try:
        spent, calls, tokens = conn.execute(
            "SELECT COALESCE(SUM(usd),0), COUNT(*), COALESCE(SUM(tokens),0) "
            "FROM oracle_spend WHERE ts >= ? AND ts < ?",
            (start_s, next_s),
        ).fetchone()
        calls_today = conn.execute(
            "SELECT COUNT(*) FROM oracle_spend WHERE ts >= ? AND ts < ?",
            (f"{today}T00:00:00", f"{today}T23:59:59"),
        ).fetchone()[0]
    finally:
        conn.close()

    spent = float(spent or 0.0)
    calls = int(calls or 0)
    tokens = int(tokens or 0)
    calls_today = int(calls_today or 0)

    budget = max(0.0, float(monthly_budget_usd or 0.0))
    remaining = max(0.0, budget - spent)
    cycle_days_total = max(1, (nxt.date() - start.date()).days)
    cycle_days_elapsed = max(1, (now.date() - start.date()).days + 1)
    days_left = max(1, (nxt.date() - now.date()).days)
    avg_call_usd = (spent / calls) if calls > 0 else float(fallback_call_usd or 0.004)
    avg_call_usd = max(avg_call_usd, 0.0001)

    if cycle_days_elapsed > 0:
        projected_spend = (spent / float(cycle_days_elapsed)) * float(cycle_days_total)
    else:
        projected_spend = spent
    projected_delta = budget - projected_spend
    utilization_pct = (spent / budget * 100.0) if budget > 0 else 0.0

    if budget <= 0.0:
        suggested_daily_cap = 0
    elif remaining <= 0.0:
        suggested_daily_cap = 0
    else:
        daily_budget = remaining / float(days_left)
        suggested_daily_cap = int(daily_budget / avg_call_usd)
        if suggested_daily_cap == 0 and remaining >= (avg_call_usd * 0.5):
            suggested_daily_cap = 1

    return {
        "month_start": start_s,
        "month_end_exclusive": next_s,
        "cycle_start_day": int(max(1, int(cycle_start_day or 1))),
        "cycle_days_total": int(cycle_days_total),
        "cycle_days_elapsed": int(cycle_days_elapsed),
        "monthly_budget_usd": round(budget, 4),
        "spent_month_usd": round(spent, 4),
        "remaining_usd": round(remaining, 4),
        "budget_utilization_pct": round(utilization_pct, 2),
        "projected_cycle_spend_usd": round(projected_spend, 4),
        "projected_delta_vs_budget_usd": round(projected_delta, 4),
        "calls_month": calls,
        "tokens_month": tokens,
        "calls_today": calls_today,
        "days_left": days_left,
        "avg_call_usd": round(avg_call_usd, 6),
        "suggested_daily_cap": int(max(0, suggested_daily_cap)),
    }
