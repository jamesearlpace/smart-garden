#!/usr/bin/env python3
"""Observe-only shadow calibration for human zone observations.

This tool diagnoses which physical/model assumptions deserve investigation. It
never writes the database or config and never emits a control command.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

import yaml


# Watering-relevant per-zone settings. The stability clock resets only when one
# of these changes; unrelated config edits (camera, oracle budget, battery
# calibration, etc.) must NOT reset it.
WATERING_ZONE_KEYS = (
    "installed", "type", "auto_mode", "heads", "kc",
    "dry_trigger", "wet_target", "mad_pct",
    "max_runtime_min", "est_gpm", "precip_rate_iph",
    "cycle_soak", "cycle_run_min", "cycle_soak_min", "cycle_count",
)

# The tool's own bookkeeping files (never config / control DB / valves).
POLICY_STATE_FILE = "calibration_state.json"
CALIBRATION_ALERT_LOG = "calibration-alerts.log"


CONDITION_SCORE = {
    "very_dry": -2,
    "somewhat_dry": -1,
    "healthy": 0,
    "somewhat_wet": 1,
    "very_wet": 2,
    "uncertain": None,
}


def parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def rows(conn: sqlite3.Connection, sql: str, args=()) -> list[dict]:
    return [dict(row) for row in conn.execute(sql, args).fetchall()]


def meter_usage(start: str, end: str) -> dict:
    """Use the physical meter ledger when available; degrade explicitly."""
    try:
        import meter_ledger
        result = meter_ledger.usage_for_window(start, end)
        return {
            "gallons": result.get("gallons"),
            "coverage": result.get("coverage"),
            "source": "meter_camera",
        }
    except Exception as exc:
        return {"gallons": None, "coverage": None,
                "source": "unavailable", "error": str(exc)}


def watering_policy_fingerprint(config: dict) -> str:
    """Hash only watering-relevant settings.

    Decouples the stability clock from config.yaml file mtime so that unrelated
    edits do not reset it; only changes that alter how or when water is applied
    should.
    """
    relevant: dict = {"zones": {}}
    for zone in config.get("zones", []):
        relevant["zones"][str(zone.get("id"))] = {
            key: zone.get(key) for key in WATERING_ZONE_KEYS
        }
    for key in ("watering", "weather_adjustment", "schedule"):
        if key in config:
            relevant[key] = config[key]
    blob = json.dumps(relevant, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def policy_stable_since(state_dir: Path, config: dict,
                        now: datetime) -> tuple[datetime, str, bool]:
    """When the current watering policy first appeared.

    Persists a tiny bookkeeping file next to the config. This is the tool's OWN
    state only: it never writes config, the control DB tables, or valves.
    Returns (since_ts, fingerprint, changed_this_run).
    """
    fingerprint = watering_policy_fingerprint(config)
    state_path = state_dir / POLICY_STATE_FILE
    state: dict = {}
    if state_path.exists():
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except Exception:
            state = {}
    if state.get("fingerprint") == fingerprint and state.get("since"):
        return parse_ts(state["since"]) or now, fingerprint, False
    state_path.write_text(json.dumps({
        "fingerprint": fingerprint,
        "since": now.isoformat(timespec="seconds"),
        "previous_fingerprint": state.get("fingerprint"),
        "previous_since": state.get("since"),
    }, indent=2), encoding="utf-8")
    return now, fingerprint, True


def record_review_candidates(state_dir: Path, report: dict,
                             now: datetime) -> None:
    """Back half of the loop: when a zone graduates to review_candidate, append
    an alert line for James to review. This never changes config or control
    state — it only records that a zone is worth a human look.
    """
    candidates = [z for z in report["zones"]
                  if z["shadow_decision"] == "review_candidate"]
    if not candidates:
        return
    log_path = state_dir / CALIBRATION_ALERT_LOG
    with log_path.open("a", encoding="utf-8") as handle:
        for zone in candidates:
            tests = "; ".join(h["parameter_family"] for h in zone["hypotheses"])
            handle.write(f'{now.isoformat(timespec="seconds")}\t'
                         f'zone{zone["zone_id"] + 1}\t{zone["zone_name"]}\t'
                         f'{tests}\n')


def build_report(db_path: Path, config_path: Path) -> dict:
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    zones = {int(zone["id"]): zone for zone in config.get("zones", [])}
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    observations = rows(conn, """
        SELECT * FROM zone_observation ORDER BY observed_ts, id
    """)
    now = datetime.now()
    policy_since, policy_fp, policy_changed = policy_stable_since(
        config_path.parent, config, now)
    zone_reports = []

    for zone_id, zone in zones.items():
        if not zone.get("installed", False):
            continue
        zone_obs = [o for o in observations if o["zone_id"] == zone_id]
        enriched = []
        for obs in zone_obs:
            observed = parse_ts(obs["observed_ts"])
            if observed is None:
                continue
            balance = conn.execute("""
                SELECT * FROM soil_balance WHERE zone_id = ? AND date <= date(?)
                ORDER BY date DESC LIMIT 1
            """, (zone_id, obs["observed_ts"])).fetchone()
            runs = rows(conn, """
                SELECT * FROM watering_event
                WHERE zone_id = ? AND end_ts IS NOT NULL
                  AND end_ts <= ? AND end_ts >= ?
                ORDER BY end_ts
            """, (zone_id, obs["observed_ts"],
                    (observed - timedelta(hours=72)).isoformat(timespec="seconds")))
            meter_gallons = 0.0
            meter_complete = True
            configured_gallons = sum(float(run.get("est_gallons") or 0)
                                     for run in runs)
            for run in runs:
                usage = meter_usage(run["start_ts"], run["end_ts"])
                if usage["gallons"] is None:
                    meter_complete = False
                else:
                    meter_gallons += float(usage["gallons"])
            last_end = parse_ts(runs[-1]["end_ts"]) if runs else None
            hours_since_water = ((observed - last_end).total_seconds() / 3600
                                 if last_end else None)
            balance_pct = None
            if balance and balance["taw_mm"]:
                balance_pct = 100 * balance["balance_mm"] / balance["taw_mm"]
            enriched.append({
                "id": obs["id"],
                "observed_ts": obs["observed_ts"],
                "condition": obs["condition"],
                "water_judgment": obs["water_judgment"],
                "condition_score": CONDITION_SCORE.get(obs["condition"]),
                "modeled_balance_pct": round(balance_pct, 1)
                    if balance_pct is not None else None,
                "water_72h_minutes": round(sum(
                    float(run.get("duration_sec") or 0) for run in runs) / 60, 1),
                "water_72h_meter_gallons": round(meter_gallons, 1)
                    if meter_complete else None,
                "water_72h_configured_gallons": round(configured_gallons, 1),
                "meter_to_configured_ratio": round(
                    meter_gallons / configured_gallons, 2)
                    if meter_complete and configured_gallons >= 10 else None,
                "hours_since_last_water": round(hours_since_water, 1)
                    if hours_since_water is not None else None,
                "response_stage": (
                    "during_or_immediate" if hours_since_water is not None
                    and hours_since_water < 12 else
                    "early_response" if hours_since_water is not None
                    and hours_since_water < 24 else
                    "useful_response_window" if hours_since_water is not None
                    and hours_since_water <= 72 else "unlinked_baseline"
                ),
            })

        distinct_days = len({o["observed_ts"][:10] for o in enriched})
        mature = [o for o in enriched
                  if o["response_stage"] == "useful_response_window"]
        dry_high_model = [o for o in mature
                          if (o["condition_score"] or 0) < 0
                          and (o["modeled_balance_pct"] or 0) >= 60]
        stable_days = max(0.0, (now - policy_since).total_seconds() / 86400)

        blockers = []
        if stable_days < 3:
            blockers.append("control policy changed less than 72 hours ago")
        if distinct_days < 3:
            blockers.append("fewer than 3 observation days")
        if len(mature) < 2:
            blockers.append("fewer than 2 observations in the 24-72h response window")
        if not zone.get("area_sqft"):
            blockers.append("no independently measured zone area")

        hypotheses = []
        delivery_ratios = [o["meter_to_configured_ratio"] for o in mature
                           if o["meter_to_configured_ratio"] is not None]
        if delivery_ratios and (sum(delivery_ratios) / len(delivery_ratios) < 0.75
                                or sum(delivery_ratios) / len(delivery_ratios) > 1.25):
            hypotheses.append({
                "parameter_family": "configured_flow",
                "reason": "meter-camera volume differs materially from configured GPM",
                "next_test": "re-estimate zone GPM from clean single-zone meter windows",
            })
        if dry_high_model:
            hypotheses.append({
                "parameter_family": "application_or_bucket",
                "reason": "dry appearance while modeled balance remained high",
                "next_test": "verify catch-can depth/uniformity before changing MAD",
            })
        if any("uneven_patchiness" in json.loads(o.get("indicators_json") or "[]")
               for o in zone_obs):
            hypotheses.append({
                "parameter_family": "distribution_uniformity",
                "reason": "observer reported uneven/patchy condition",
                "next_test": "catch cans in healthy and stressed portions of this zone",
            })
        if enriched and not hypotheses:
            hypotheses.append({
                "parameter_family": "pending_response",
                "reason": "observations are too early or sparse to identify a bad assumption",
                "next_test": "repeat at similar time tomorrow and again 48-72h after watering",
            })

        zone_reports.append({
            "zone_id": zone_id,
            "zone_name": zone.get("name"),
            "observations": enriched,
            "evidence": {
                "observation_count": len(enriched),
                "distinct_days": distinct_days,
                "mature_response_count": len(mature),
                "days_since_control_change": round(stable_days, 2),
            },
            "shadow_decision": "hold" if blockers else "review_candidate",
            "automation_blockers": blockers,
            "hypotheses": hypotheses,
        })

    conn.close()
    report = {
        "generated_ts": now.isoformat(timespec="seconds"),
        "mode": "shadow_observe_only",
        "writes_config": False,
        "controls_valves": False,
        "watering_policy": {
            "fingerprint": policy_fp,
            "stable_since": policy_since.isoformat(timespec="seconds"),
            "changed_this_run": policy_changed,
        },
        "guardrails": {
            "minimum_stable_policy_days": 3,
            "minimum_observation_days": 3,
            "minimum_mature_observations": 2,
            "response_window_hours": [24, 72],
            "mad_is_not_used_to_correct_delivery_errors": True,
        },
        "global_findings": [
            "A same-time survey across zones is one survey, not repeated evidence.",
            "Visual dryness after a recent policy increase is baseline evidence until response matures.",
            "Meter gallons validate delivered volume; independent area/catch-can depth is required to validate application depth.",
            "MAD should change only after delivery, distribution, ET/Kc, and root-zone bucket assumptions are tested.",
        ],
        "zones": zone_reports,
    }
    record_review_candidates(config_path.parent, report, now)
    return report


def print_text(report: dict) -> None:
    print("SHADOW CALIBRATION — NO CONTROL CHANGES")
    for finding in report["global_findings"]:
        print(f"- {finding}")
    pol = report.get("watering_policy", {})
    print(f"- Watering policy stable since {pol.get('stable_since')} "
          f"(fingerprint {pol.get('fingerprint')}; "
          f"changed_this_run={pol.get('changed_this_run')})")
    for zone in report["zones"]:
        if not zone["observations"]:
            continue
        ev = zone["evidence"]
        print(f"\nZone {zone['zone_id'] + 1} — {zone['zone_name']}: "
              f"{zone['shadow_decision'].upper()}")
        print(f"  evidence: {ev['observation_count']} observation(s), "
              f"{ev['distinct_days']} day(s), {ev['mature_response_count']} mature")
        latest = zone["observations"][-1]
        print(f"  latest: {latest['condition']} / {latest['water_judgment']}; "
              f"model={latest['modeled_balance_pct']}%; "
              f"water72h={latest['water_72h_minutes']} min, "
              f"meter={latest['water_72h_meter_gallons']} gal "
              f"(configured={latest['water_72h_configured_gallons']} gal, "
              f"ratio={latest['meter_to_configured_ratio']}); "
              f"stage={latest['response_stage']}")
        for blocker in zone["automation_blockers"]:
            print(f"  hold: {blocker}")
        for hypothesis in zone["hypotheses"]:
            print(f"  test {hypothesis['parameter_family']}: "
                  f"{hypothesis['next_test']}")


def main() -> int:
    here = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(here))
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=here / "smart-garden.db")
    parser.add_argument("--config", type=Path, default=here / "config.yaml")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    report = build_report(args.db, args.config)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print_text(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
