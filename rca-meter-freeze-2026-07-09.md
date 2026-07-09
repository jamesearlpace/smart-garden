# RCA: Water-usage meter froze for a full day — oracle silently disabled by budget-cycle mismatch + $10 throttle

**Severity:** High (core feature dead — no water consumption measured for ~15h)
**Reported:** 2026-07-09
**Component:** meter reader / oracle budget pacer (`dashboard.py`, `oracle_budget.py`, systemd drop-ins)
**Status:** Diagnosed, fix pending

## Summary

The water-usage meter (sprinklers.savagepace.com) silently stopped measuring consumption. The committed meter value was **frozen at `95,376.901 cf` for all of 2026-07-09** — 6,241 consecutive `held` frames since overnight. The true value at time of diagnosis was **`95,483.460 cf`** (confirmed by a live gpt-4o oracle read), meaning **~106.6 cf ≈ 797 gallons of real usage went unmeasured** and the site displayed a wrong-low number.

This is a "we thought it would work but it didn't" failure: the 2026-07-08 *local-first* experiment intentionally throttled the paid oracle on the assumption the local CNN reader could carry steady-state reading. It cannot at the leading edge, and a second latent bug (budget-cycle mismatch) made the throttle far more severe than intended, killing the only working reader entirely.

## Impact

- No water consumption recorded 2026-07-08 ~overnight → 2026-07-09 13:40 (~15h).
- ~797 gal of real usage (overnight sprinkler runs + household) lost / not attributable.
- Displayed meter value wrong-low by ~106 cf the entire time.
- Silent failure — no alert fired; discovered only because the user noticed the number wasn't moving.

## Root Cause (chain)

Three independent factors combined; all three had to be true:

1. **Local reader can't read the current leading edge.** CNN `loc2-v9` read `95283411` on *every* frame — ~93 cf low (the documented high-digit collapse: the `4` in `95_4_83` reads as `2`). Because that's below the monotonic lock, every frame was rejected → `held`. Expected behavior for the CNN at a new digit range; it is not a safe single-frame authority.

2. **The oracle — the only reader that actually works — was throttled to $10/mo.** The 2026-07-08 drop-in `zzz-openai-local-first.conf` set `METER_ORACLE_MONTHLY_BUDGET_USD=10`, `DAILY_CAP=40`. Because systemd applies drop-ins in **lexical order**, the `zzz-` file overrode the good `oracle-accuracy.conf` (`$150` / cap `1200` / min `800`). Intent was "use the oracle sparingly and let the local reader lead" — but the local reader was blind (factor 1), so this removed the only functioning reader.

3. **Budget pacer measured spend against the WRONG cycle window (the actual bug).** The pacer uses `METER_ORACLE_BUDGET_CYCLE_START_DAY=1` (calendar month). Natalie's real Azure billing/credit cycle runs **the 10th → the 9th** (confirmed via `az billing period list`: current period `202608-1` = 2026-06-10 → 2026-07-09). The pacer therefore computed "July (calendar) spent $163.91 vs $10 budget → 1639% utilization → `remaining_usd=0` → `daily_cap_effective=0`." Result: **zero oracle calls allowed.** Even restoring the $150 config would NOT have unblocked it, because the calendar-month window still showed over-budget.

**Net:** blind local reader + oracle starved to $0 by a cycle-window bug = no reader at all = permanent freeze at the last committed value.

## Evidence

- `meter_reading` ledger: 6,241 rows on 2026-07-09, all `committed=95376901 method=held reader=cnn raw_reading=95283411`.
- Last real forward move: `2026-07-08T22:27:35 → 95432.15` (visual), then re-anchored down to `95376.901` overnight; frozen since.
- Live status: `oracle{ daily_cap_effective:0, day_calls:0, monthly_budget_usd:10.0 }`, `budget{ cycle_start_day:1, month_start:2026-07-01, spent_month_usd:163.91, utilization:1639%, remaining:0 }`.
- Fresh direct `vision_oracle.read_meter()` on newest frame `20260709-134318.jpg` → `095483460` **high** confidence, `ok=True` → the oracle works; only the pacer blocked it.
- `az billing period list` → current period `2026-06-10 → 2026-07-09`; next cycle starts **2026-07-10**.
- Two conflicting drop-ins present: `oracle-accuracy.conf` ($150/1200/800, Jun 23) vs `zzz-openai-local-first.conf` ($10/40, Jul 8) — the latter wins by lex order.

## Contributing / Secondary Findings

- **Credit amount is ambiguous.** Subscription profile doc says VS benefit "expected $50/month"; smart-garden notes assumed $150. The sub is a **"Web Direct Offer"** (spending limit off → overage bills to card). App-estimated spend for the real current cycle (06-10→07-09) is **~$350** (late-June storm ~$173 + July ~$164) — over either credit figure, two cycles running. Exact $/overage not retrievable via CLI (`consumption` returns `pretaxCost=None`, credit-covered); portal Cost Management is authoritative.
- **No freeze alarm.** A meter that stops advancing while household/sprinkler activity continues should alert. The engine-vs-meter reconciler exists but did not surface this as a user-visible alert.
- **Silent, order-dependent config.** Layering many `*.conf` drop-ins where a later filename silently reverses an earlier one is fragile and hard to audit.

## The "thought it would work" gap

The local-first change assumed: *(a)* the local CNN could read steady-state, and *(b)* throttling the oracle to a small budget was a safe fallback. Both assumptions were wrong in combination: the CNN is structurally blind at every new leading edge (documented recurring loop), and the throttle — amplified by the cycle-window bug — didn't degrade gracefully to "read less often," it degraded to "don't read at all." No canary/alert caught the resulting total loss of reading.

## Fix Plan

**Immediate (reversible):**
1. Re-anchor lock to confirmed true `095483460` → display correct now.
2. Set `METER_ORACLE_BUDGET_CYCLE_START_DAY=10` to match the real Azure cycle. (Fresh cycle starts 2026-07-10 → pacer sees $0 spent → oracle auto-unblocks tomorrow with no mid-cycle overspend.)
3. Remove / neutralize `zzz-openai-local-first.conf` so the intended budget config applies; consolidate conflicting oracle drop-ins into one file.
4. `daemon-reload` + restart `smart-garden-server`.

**Follow-ups (separate issues):**
- Confirm actual monthly credit ($50 vs $150) and set `METER_ORACLE_MONTHLY_BUDGET_USD` to reality; add a hard overage guard.
- **Freeze/stale-reading alarm:** ntfy alert when committed value doesn't advance for N minutes while frames are arriving (would have caught this in minutes, not a day).
- **Graceful degradation:** when the budget cap is hit, the reader should still fire a minimal sparse cadence (e.g. 1 read / 10 min) rather than 0, so the meter never fully freezes.
- **Config hygiene:** collapse the drop-in stack; assert at startup that effective oracle budget/cap are non-zero and log a warning if the pacer computes cap 0.
- Durable exit from the recurring loop: local reader / phase tracker so reading no longer depends on the metered oracle.

## Prevention

- Startup assertion + daily scorecard check: `daily_cap_effective > 0` (or explicitly intended 0).
- Budget-cycle start day must be sourced from the real billing period, not assumed calendar month.
- Any change that reduces the oracle budget must ship with a freeze alarm active.
