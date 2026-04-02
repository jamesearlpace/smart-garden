#!/usr/bin/env python3
"""
Smart Garden Scheduler

Automates watering based on time-of-day schedules and soil moisture
thresholds. Runs on the Acer home server and controls the ESP32 via
its REST API.

Zones 1-4 have soil sensors — these can skip watering when soil is
already wet. Zones 5-7 (lawns) are time-only.

Usage:
    python3 scheduler.py                  # Run forever
    python3 scheduler.py --once           # Single evaluation then exit
    python3 scheduler.py --status         # Show current schedule state
    python3 scheduler.py --run-zone 0 15  # Manually run zone 0 for 15 min
"""

import argparse
import json
import logging
import os
import sqlite3
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.error import URLError

# ============================================================
# Configuration
# ============================================================
ESP32_BASE_URL = os.environ.get("ESP32_URL", "http://192.168.0.150")
CONFIG_PATH = os.environ.get("SCHEDULE_CONFIG",
                             str(Path(__file__).parent / "schedule_config.json"))
DB_PATH = os.environ.get("DB_PATH",
                         str(Path(__file__).parent / "smart-garden.db"))
EVAL_INTERVAL = int(os.environ.get("EVAL_INTERVAL", "30"))  # seconds

LOG_FORMAT = "%(asctime)s [%(levelname)s] %(message)s"
logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
log = logging.getLogger("scheduler")

# Safety: absolute max any valve can stay open (minutes), regardless of config
HARD_MAX_RUNTIME_MIN = 90

# ============================================================
# Database (reuse collector's DB)
# ============================================================

def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    # Scheduler-specific tables
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS scheduler_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            epoch INTEGER NOT NULL,
            zone_id INTEGER NOT NULL,
            zone_name TEXT,
            trigger TEXT NOT NULL,       -- "schedule", "soil", "manual"
            duration_min REAL,           -- Actual minutes valve was open
            soil_before INTEGER,         -- Soil moisture % before watering (null if no sensor)
            soil_after INTEGER,          -- Soil moisture % after watering (null if no sensor)
            result TEXT NOT NULL          -- "completed", "skipped_wet", "skipped_cooldown",
                                         -- "aborted_max_runtime", "aborted_error"
        );
        CREATE INDEX IF NOT EXISTS idx_sched_epoch ON scheduler_runs(epoch);
        CREATE INDEX IF NOT EXISTS idx_sched_zone ON scheduler_runs(zone_id);
    """)
    conn.commit()
    return conn


def log_event(conn: sqlite3.Connection, event_type: str, detail: str):
    now = datetime.now(timezone.utc)
    conn.execute(
        "INSERT INTO system_events (timestamp, epoch, event_type, detail) VALUES (?, ?, ?, ?)",
        (now.isoformat(), int(now.timestamp()), event_type, detail)
    )
    conn.commit()


def log_run(conn: sqlite3.Connection, zone_id: int, zone_name: str,
            trigger: str, duration_min: float, soil_before, soil_after, result: str):
    now = datetime.now(timezone.utc)
    conn.execute("""
        INSERT INTO scheduler_runs
            (timestamp, epoch, zone_id, zone_name, trigger, duration_min,
             soil_before, soil_after, result)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (now.isoformat(), int(now.timestamp()), zone_id, zone_name,
          trigger, round(duration_min, 2), soil_before, soil_after, result))
    conn.commit()


# ============================================================
# ESP32 Communication
# ============================================================

def esp32_request(path: str, method: str = "GET", timeout: int = 10) -> dict | None:
    """Send request to ESP32. Returns parsed JSON or None on failure."""
    url = f"{ESP32_BASE_URL}{path}"
    try:
        req = Request(url, method=method,
                      data=b"" if method == "POST" else None)
        with urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except (URLError, OSError, json.JSONDecodeError) as e:
        log.error(f"ESP32 request failed ({method} {path}): {e}")
        return None


def open_valve(zone_id: int) -> bool:
    result = esp32_request(f"/api/valve?id={zone_id}&action=open", method="POST")
    if result and result.get("ok"):
        log.info(f"Opened valve {zone_id}")
        return True
    log.error(f"Failed to open valve {zone_id}: {result}")
    return False


def close_valve(zone_id: int) -> bool:
    result = esp32_request(f"/api/valve?id={zone_id}&action=close", method="POST")
    if result and result.get("ok"):
        log.info(f"Closed valve {zone_id}")
        return True
    log.error(f"Failed to close valve {zone_id}: {result}")
    return False


def close_all_valves() -> bool:
    result = esp32_request("/api/closeall", method="POST")
    if result and result.get("ok"):
        log.info("Closed all valves (emergency)")
        return True
    log.error(f"Failed to close all valves: {result}")
    return False


def get_soil_moisture(sensor_idx: int) -> int | None:
    """Get current soil moisture % for a sensor. Returns None on failure."""
    data = esp32_request("/api/status")
    if not data:
        return None
    soil = data.get("soil", [])
    if sensor_idx < len(soil):
        return soil[sensor_idx].get("pct")
    return None


def get_valve_state(zone_id: int) -> bool | None:
    """Check if a valve is currently open. Returns None on failure."""
    data = esp32_request("/api/status")
    if not data:
        return None
    valves = data.get("valves", [])
    if zone_id < len(valves):
        return valves[zone_id].get("open", False)
    return None


# ============================================================
# Config loader
# ============================================================

def load_config() -> dict:
    with open(CONFIG_PATH, "r") as f:
        return json.load(f)


def reload_config_if_changed(last_mtime: float) -> tuple[dict | None, float]:
    """Return (config, mtime) if file changed, else (None, same_mtime)."""
    try:
        mtime = os.path.getmtime(CONFIG_PATH)
        if mtime != last_mtime:
            cfg = load_config()
            log.info("Config reloaded (file changed)")
            return cfg, mtime
    except (OSError, json.JSONDecodeError) as e:
        log.error(f"Config reload failed: {e}")
    return None, last_mtime


# ============================================================
# Schedule evaluation
# ============================================================

# Track per-zone state
_zone_state: dict[int, dict] = {}
# Lock for valve operations (one zone at a time)
_valve_lock = threading.Lock()


def get_zone_state(zone_id: int) -> dict:
    if zone_id not in _zone_state:
        _zone_state[zone_id] = {
            "running": False,
            "last_start": None,
            "last_stop": None,
            "last_trigger": None,
        }
    return _zone_state[zone_id]


def is_in_time_window(schedule: dict, now_local: datetime) -> bool:
    """Check if current time falls within a schedule window."""
    day_name = now_local.strftime("%a").lower()
    if day_name not in schedule.get("days", []):
        return False

    start_parts = schedule["start"].split(":")
    start_h, start_m = int(start_parts[0]), int(start_parts[1])
    duration = schedule.get("duration_min", 15)

    start_time = now_local.replace(hour=start_h, minute=start_m, second=0, microsecond=0)
    end_time = start_time + timedelta(minutes=duration)

    return start_time <= now_local < end_time


def get_matching_schedule(zone_cfg: dict, now_local: datetime) -> dict | None:
    """Return the first matching schedule window, or None."""
    for sched in zone_cfg.get("schedules", []):
        if is_in_time_window(sched, now_local):
            return sched
    return None


def is_in_cooldown(zone_id: int, cooldown_hours: float, conn: sqlite3.Connection) -> bool:
    """Check if zone was watered recently (within cooldown period)."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=cooldown_hours)
    row = conn.execute(
        "SELECT COUNT(*) FROM scheduler_runs "
        "WHERE zone_id = ? AND epoch > ? AND result IN ('completed', 'aborted_max_runtime')",
        (zone_id, int(cutoff.timestamp()))
    ).fetchone()
    return row[0] > 0


def run_zone(conn: sqlite3.Connection, zone_id: int, zone_name: str,
             duration_min: float, trigger: str,
             soil_sensor: int | None = None,
             max_moisture_pct: int | None = None) -> str:
    """
    Open a valve, wait for duration or until soil is wet enough, then close.
    Returns result string. Thread-safe via _valve_lock.
    """
    # Clamp duration to hard max
    duration_min = min(duration_min, HARD_MAX_RUNTIME_MIN)

    state = get_zone_state(zone_id)
    if state["running"]:
        log.warning(f"Zone {zone_id} already running, skipping")
        return "skipped_already_running"

    # Get soil moisture before
    soil_before = None
    if soil_sensor is not None:
        soil_before = get_soil_moisture(soil_sensor)

    with _valve_lock:
        state["running"] = True
        state["last_start"] = datetime.now(timezone.utc)
        state["last_trigger"] = trigger

        log.info(f"Starting zone {zone_id} ({zone_name}) for {duration_min} min "
                 f"[trigger={trigger}, soil_before={soil_before}%]")

        if not open_valve(zone_id):
            state["running"] = False
            log_run(conn, zone_id, zone_name, trigger, 0, soil_before, None, "aborted_error")
            return "aborted_error"

        # Wait loop — check soil moisture every 30s if sensor available
        start = time.monotonic()
        deadline = start + (duration_min * 60)
        result = "completed"

        try:
            while time.monotonic() < deadline:
                elapsed_min = (time.monotonic() - start) / 60

                # Check soil moisture for early shutoff
                if soil_sensor is not None and max_moisture_pct is not None:
                    current_soil = get_soil_moisture(soil_sensor)
                    if current_soil is not None and current_soil >= max_moisture_pct:
                        log.info(f"Zone {zone_id} soil at {current_soil}% >= "
                                 f"{max_moisture_pct}%, stopping early at {elapsed_min:.1f} min")
                        result = "completed"
                        break

                # Check hard max
                if elapsed_min >= HARD_MAX_RUNTIME_MIN:
                    log.warning(f"Zone {zone_id} hit hard max runtime ({HARD_MAX_RUNTIME_MIN} min)")
                    result = "aborted_max_runtime"
                    break

                # Verify valve is actually still open (dead-man check)
                if int(time.monotonic() - start) % 120 == 0 and int(time.monotonic() - start) > 0:
                    valve_open = get_valve_state(zone_id)
                    if valve_open is False:
                        log.error(f"Zone {zone_id} valve closed unexpectedly!")
                        result = "aborted_error"
                        break

                time.sleep(30)
        except Exception as e:
            log.error(f"Zone {zone_id} error during run: {e}")
            result = "aborted_error"
        finally:
            close_valve(zone_id)
            state["running"] = False
            state["last_stop"] = datetime.now(timezone.utc)

        actual_min = (time.monotonic() - start) / 60

        # Get soil moisture after
        soil_after = None
        if soil_sensor is not None:
            time.sleep(5)  # Let sensor settle
            soil_after = get_soil_moisture(soil_sensor)

        log.info(f"Zone {zone_id} finished: {result} after {actual_min:.1f} min "
                 f"[soil: {soil_before}% → {soil_after}%]")

        log_run(conn, zone_id, zone_name, trigger, actual_min,
                soil_before, soil_after, result)

        return result


# ============================================================
# Main evaluation loop
# ============================================================

def evaluate_zones(config: dict, conn: sqlite3.Connection):
    """
    One evaluation pass: check each zone's schedule and soil thresholds.
    Only one zone runs at a time (sequential, with pause between).
    """
    import zoneinfo
    tz_name = config.get("global", {}).get("timezone", "America/Los_Angeles")
    try:
        tz = zoneinfo.ZoneInfo(tz_name)
    except Exception:
        log.error(f"Invalid timezone: {tz_name}, using UTC")
        tz = timezone.utc

    now_local = datetime.now(tz)
    global_cfg = config.get("global", {})
    cycle_pause = global_cfg.get("cycle_pause_sec", 30)
    max_runtime = global_cfg.get("max_valve_runtime_min", 60)

    if not global_cfg.get("enabled", True):
        return

    zones_to_run: list[tuple[int, str, float, str, int | None, int | None]] = []

    for zone_cfg in config.get("zones", []):
        zone_id = zone_cfg["id"]
        zone_name = zone_cfg.get("name", f"Zone {zone_id + 1}")
        state = get_zone_state(zone_id)

        if not zone_cfg.get("enabled", True):
            continue
        if state["running"]:
            continue

        soil_sensor = zone_cfg.get("soil_sensor")
        soil_cfg = zone_cfg.get("soil_threshold", {})

        # --- Check schedule-based trigger ---
        matching_sched = get_matching_schedule(zone_cfg, now_local)
        if matching_sched:
            duration = min(matching_sched.get("duration_min", 15), max_runtime)

            # If soil sensor available and wet enough, skip
            if soil_sensor is not None and soil_cfg.get("enabled"):
                current_moisture = get_soil_moisture(soil_sensor)
                if current_moisture is not None and current_moisture >= soil_cfg.get("max_moisture_pct", 80):
                    log.info(f"Zone {zone_id} schedule hit but soil at {current_moisture}% "
                             f"(>= {soil_cfg['max_moisture_pct']}%), skipping")
                    log_run(conn, zone_id, zone_name, "schedule", 0,
                            current_moisture, None, "skipped_wet")
                    continue

            zones_to_run.append((
                zone_id, zone_name, duration, "schedule",
                soil_sensor,
                soil_cfg.get("max_moisture_pct") if soil_cfg.get("enabled") else None
            ))
            continue

        # --- Check soil moisture trigger (outside schedule windows) ---
        if soil_sensor is not None and soil_cfg.get("enabled"):
            min_pct = soil_cfg.get("min_moisture_pct", 30)
            cooldown_h = soil_cfg.get("cooldown_hours", 4)
            auto_dur = min(soil_cfg.get("auto_duration_min", 15), max_runtime)

            current_moisture = get_soil_moisture(soil_sensor)
            if current_moisture is not None and current_moisture < min_pct:
                if is_in_cooldown(zone_id, cooldown_h, conn):
                    log.info(f"Zone {zone_id} soil dry ({current_moisture}% < {min_pct}%) "
                             f"but in cooldown, skipping")
                    log_run(conn, zone_id, zone_name, "soil", 0,
                            current_moisture, None, "skipped_cooldown")
                    continue

                log.info(f"Zone {zone_id} soil dry ({current_moisture}% < {min_pct}%), "
                         f"triggering auto-water for {auto_dur} min")
                zones_to_run.append((
                    zone_id, zone_name, auto_dur, "soil",
                    soil_sensor,
                    soil_cfg.get("max_moisture_pct")
                ))

    # Run zones sequentially with pause between
    for i, (zid, zname, dur, trig, sensor, max_pct) in enumerate(zones_to_run):
        if i > 0:
            log.info(f"Pausing {cycle_pause}s between zones")
            time.sleep(cycle_pause)
        run_zone(conn, zid, zname, dur, trig, sensor, max_pct)


def print_status(config: dict, conn: sqlite3.Connection):
    """Print current schedule status for all zones."""
    import zoneinfo
    tz_name = config.get("global", {}).get("timezone", "America/Los_Angeles")
    try:
        tz = zoneinfo.ZoneInfo(tz_name)
    except Exception:
        tz = timezone.utc

    now_local = datetime.now(tz)
    print(f"\n{'='*60}")
    print(f"Smart Garden Scheduler Status")
    print(f"Time: {now_local.strftime('%Y-%m-%d %H:%M:%S %Z')}")
    print(f"Global enabled: {config.get('global', {}).get('enabled', True)}")
    print(f"{'='*60}\n")

    for zone_cfg in config.get("zones", []):
        zid = zone_cfg["id"]
        name = zone_cfg.get("name", f"Zone {zid}")
        enabled = zone_cfg.get("enabled", True)
        sensor = zone_cfg.get("soil_sensor")

        soil_str = ""
        if sensor is not None:
            moisture = get_soil_moisture(sensor)
            if moisture is not None:
                soil_str = f" | Soil: {moisture}%"

        sched = get_matching_schedule(zone_cfg, now_local)
        sched_str = "IN WINDOW" if sched else "idle"

        # Last run
        row = conn.execute(
            "SELECT timestamp, trigger, duration_min, result FROM scheduler_runs "
            "WHERE zone_id = ? ORDER BY id DESC LIMIT 1",
            (zid,)
        ).fetchone()
        last_run = f"Last: {row[0][:16]} ({row[1]}, {row[2]:.0f}min, {row[3]})" if row else "Last: never"

        status = "DISABLED" if not enabled else sched_str
        print(f"  [{zid}] {name:<30} {status:<12}{soil_str}")
        print(f"       {last_run}")

        # Show next schedule
        for s in zone_cfg.get("schedules", []):
            days = ",".join(s["days"])
            print(f"       Schedule: {days} @ {s['start']} for {s.get('duration_min', 15)} min")
        print()


# ============================================================
# Main
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="Smart Garden Scheduler")
    parser.add_argument("--once", action="store_true",
                        help="Single evaluation then exit")
    parser.add_argument("--status", action="store_true",
                        help="Show current schedule state")
    parser.add_argument("--run-zone", nargs=2, metavar=("ZONE_ID", "MINUTES"),
                        help="Manually run a zone")
    args = parser.parse_args()

    config = load_config()
    conn = get_db()

    log.info(f"Config: {CONFIG_PATH}")
    log.info(f"Database: {DB_PATH}")
    log.info(f"ESP32: {ESP32_BASE_URL}")

    if args.status:
        print_status(config, conn)
        return

    if args.run_zone:
        zone_id = int(args.run_zone[0])
        minutes = float(args.run_zone[1])
        zone_name = f"Zone {zone_id + 1} (manual)"
        for z in config.get("zones", []):
            if z["id"] == zone_id:
                zone_name = z.get("name", zone_name)
                break
        log.info(f"Manual run: zone {zone_id} for {minutes} min")
        log_event(conn, "scheduler", f"Manual run: zone {zone_id} for {minutes} min")
        run_zone(conn, zone_id, zone_name, minutes, "manual",
                 soil_sensor=None, max_moisture_pct=None)
        return

    # Main loop
    log_event(conn, "scheduler", "Scheduler started")
    log.info(f"Scheduler started — evaluating every {EVAL_INTERVAL}s")
    log.info(f"Zones configured: {len(config.get('zones', []))}")

    config_mtime = os.path.getmtime(CONFIG_PATH)
    last_eval_schedules: dict[int, str | None] = {}

    try:
        while True:
            # Hot-reload config
            new_cfg, config_mtime = reload_config_if_changed(config_mtime)
            if new_cfg:
                config = new_cfg

            # Deduplicate: track which schedules already triggered this window
            # so we don't re-trigger every 30s within the same window
            import zoneinfo
            tz_name = config.get("global", {}).get("timezone", "America/Los_Angeles")
            try:
                tz = zoneinfo.ZoneInfo(tz_name)
            except Exception:
                tz = timezone.utc

            now_local = datetime.now(tz)
            current_window_keys: dict[int, str | None] = {}

            for zone_cfg in config.get("zones", []):
                zid = zone_cfg["id"]
                sched = get_matching_schedule(zone_cfg, now_local)
                if sched:
                    key = f"{sched['start']}_{','.join(sched.get('days', []))}"
                    current_window_keys[zid] = key
                else:
                    current_window_keys[zid] = None

            # Only evaluate if at least one zone has a NEW window
            # (or soil check, which always runs)
            has_new_window = False
            for zid, key in current_window_keys.items():
                if key and key != last_eval_schedules.get(zid):
                    has_new_window = True
                    break

            # Also check soil triggers (always evaluate for these)
            has_soil_zones = any(
                z.get("soil_sensor") is not None
                and z.get("soil_threshold", {}).get("enabled")
                and z.get("enabled", True)
                for z in config.get("zones", [])
            )

            if has_new_window or has_soil_zones:
                evaluate_zones(config, conn)
                last_eval_schedules = dict(current_window_keys)

            time.sleep(EVAL_INTERVAL)

    except KeyboardInterrupt:
        log.info("Scheduler stopping (Ctrl+C)")
    finally:
        # Safety: close all valves on shutdown
        log.info("Closing all valves on shutdown")
        close_all_valves()
        log_event(conn, "scheduler", "Scheduler stopped — all valves closed")
        conn.close()


if __name__ == "__main__":
    main()
