#!/usr/bin/env python3
"""
Smart Garden Data Collector

Polls the ESP32 at /api/status every 60 seconds and stores readings
in a local SQLite database for long-term telemetry and analysis.

Run on the Acer home server (192.168.0.109) which has LAN access to
the ESP32 (192.168.0.150).

Usage:
    python3 collector.py                  # Run forever (foreground)
    python3 collector.py --once           # Single poll (for testing)
    python3 collector.py --backfill-events  # Pull /api/events and store
"""

import argparse
import json
import logging
import os
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.error import URLError

# ============================================================
# Configuration
# ============================================================
ESP32_BASE_URL = os.environ.get("ESP32_URL", "http://192.168.0.150")
POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL", "60"))  # seconds
DB_PATH = os.environ.get("DB_PATH", str(Path(__file__).parent / "smart-garden.db"))

LOG_FORMAT = "%(asctime)s [%(levelname)s] %(message)s"
logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
log = logging.getLogger("collector")


# ============================================================
# Database setup
# ============================================================

def init_db(db_path: str) -> sqlite3.Connection:
    """Create tables if they don't exist and return a connection."""
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")  # Better concurrent read performance
    conn.execute("PRAGMA busy_timeout=5000")

    conn.executescript("""
        CREATE TABLE IF NOT EXISTS sensor_readings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,          -- ISO 8601 UTC
            epoch INTEGER NOT NULL,           -- Unix timestamp for fast queries
            temp_f REAL,                      -- DHT22 temperature (°F)
            humidity REAL,                    -- DHT22 humidity (%)
            soil_1_raw INTEGER,               -- Garden raw ADC
            soil_1_pct INTEGER,               -- Garden moisture %
            soil_2_raw INTEGER,               -- Grapes raw ADC
            soil_2_pct INTEGER,               -- Grapes moisture %
            soil_3_raw INTEGER,               -- Fruit Trees raw ADC
            soil_3_pct INTEGER,               -- Fruit Trees moisture %
            soil_4_raw INTEGER,               -- South Lawn raw ADC
            soil_4_pct INTEGER,               -- South Lawn moisture %
            wifi_rssi INTEGER,                -- WiFi signal strength (dBm)
            free_heap INTEGER,                -- Free heap memory (bytes)
            heap_pct INTEGER,                 -- Free heap (%)
            chip_temp_f REAL,                 -- ESP32 die temperature (°F)
            uptime_sec INTEGER,               -- Seconds since last boot
            boot_count INTEGER,               -- Lifetime boot count
            wifi_reconnects INTEGER,          -- WiFi reconnects this session
            event_count INTEGER               -- Events in ring buffer
        );

        CREATE TABLE IF NOT EXISTS valve_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,          -- ISO 8601 UTC (when we polled)
            epoch INTEGER NOT NULL,
            valve_id INTEGER NOT NULL,        -- 0-indexed
            valve_name TEXT,
            is_open INTEGER NOT NULL,         -- 1=open, 0=closed
            open_count INTEGER,               -- Lifetime opens
            close_count INTEGER,              -- Lifetime closes
            open_for_sec INTEGER              -- Seconds valve has been open (if open)
        );

        CREATE TABLE IF NOT EXISTS system_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,          -- ISO 8601 UTC
            epoch INTEGER NOT NULL,
            event_type TEXT NOT NULL,         -- "boot", "valve", "wifi", "error", "collector"
            detail TEXT
        );

        -- Indexes for time-range queries
        CREATE INDEX IF NOT EXISTS idx_sensor_epoch ON sensor_readings(epoch);
        CREATE INDEX IF NOT EXISTS idx_valve_epoch ON valve_events(epoch);
        CREATE INDEX IF NOT EXISTS idx_sysevt_epoch ON system_events(epoch);
        CREATE INDEX IF NOT EXISTS idx_valve_id ON valve_events(valve_id);
    """)

    conn.commit()
    return conn


# ============================================================
# HTTP helpers
# ============================================================

def fetch_json(url: str, timeout: int = 10) -> dict:
    """Fetch JSON from the ESP32. Raises on failure."""
    req = Request(url)
    with urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


# ============================================================
# Data collection
# ============================================================

def poll_status(conn: sqlite3.Connection) -> bool:
    """Poll /api/status and store readings. Returns True on success."""
    try:
        data = fetch_json(f"{ESP32_BASE_URL}/api/status")
    except (URLError, OSError, json.JSONDecodeError) as e:
        log.warning(f"Failed to reach ESP32: {e}")
        now = datetime.now(timezone.utc)
        conn.execute(
            "INSERT INTO system_events (timestamp, epoch, event_type, detail) VALUES (?, ?, ?, ?)",
            (now.isoformat(), int(now.timestamp()), "collector", f"Poll failed: {e}")
        )
        conn.commit()
        return False

    now = datetime.now(timezone.utc)
    epoch = int(now.timestamp())
    ts = now.isoformat()

    sys_info = data.get("system", {})
    soil = data.get("soil", [])

    # Sensor readings
    conn.execute("""
        INSERT INTO sensor_readings (
            timestamp, epoch, temp_f, humidity,
            soil_1_raw, soil_1_pct, soil_2_raw, soil_2_pct,
            soil_3_raw, soil_3_pct, soil_4_raw, soil_4_pct,
            wifi_rssi, free_heap, heap_pct, chip_temp_f,
            uptime_sec, boot_count, wifi_reconnects, event_count
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        ts, epoch,
        data.get("temp"), data.get("hum"),
        soil[0].get("raw") if len(soil) > 0 else None,
        soil[0].get("pct") if len(soil) > 0 else None,
        soil[1].get("raw") if len(soil) > 1 else None,
        soil[1].get("pct") if len(soil) > 1 else None,
        soil[2].get("raw") if len(soil) > 2 else None,
        soil[2].get("pct") if len(soil) > 2 else None,
        soil[3].get("raw") if len(soil) > 3 else None,
        soil[3].get("pct") if len(soil) > 3 else None,
        sys_info.get("wifiRSSI"),
        sys_info.get("freeHeap"),
        sys_info.get("heapPct"),
        sys_info.get("chipTempF"),
        sys_info.get("uptimeSec"),
        sys_info.get("bootCount"),
        sys_info.get("wifiReconnects"),
        sys_info.get("eventCount"),
    ))

    # Valve snapshots — only store rows when state actually changes
    # (saves ~10K rows/day vs storing all 7 valves every poll)
    for valve_idx, v in enumerate(data.get("valves", [])):
        is_open = 1 if v.get("open") else 0
        open_count = v.get("openCount", 0)
        close_count = v.get("closeCount", 0)

        # Check last known state for this valve
        prev = conn.execute(
            "SELECT is_open, open_count, close_count FROM valve_events "
            "WHERE valve_id = ? ORDER BY id DESC LIMIT 1",
            (valve_idx,)
        ).fetchone()

        if prev is None or prev[0] != is_open or prev[1] != open_count or prev[2] != close_count:
            conn.execute("""
                INSERT INTO valve_events (
                    timestamp, epoch, valve_id, valve_name, is_open,
                    open_count, close_count, open_for_sec
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                ts, epoch, valve_idx, v.get("name"),
                is_open, open_count, close_count,
                v.get("openForSec"),
            ))

    conn.commit()

    log.info(
        f"Stored: temp={data.get('temp')}°F hum={data.get('hum')}% "
        f"rssi={sys_info.get('wifiRSSI')}dBm heap={sys_info.get('heapPct')}% "
        f"uptime={sys_info.get('uptimeSec')}s boots={sys_info.get('bootCount')}"
    )
    return True


def backfill_events(conn: sqlite3.Connection):
    """Pull /api/events from ESP32 and store any we don't already have."""
    try:
        events = fetch_json(f"{ESP32_BASE_URL}/api/events")
    except (URLError, OSError, json.JSONDecodeError) as e:
        log.error(f"Failed to fetch events: {e}")
        return

    now = datetime.now(timezone.utc)
    ts = now.isoformat()
    epoch = int(now.timestamp())

    count = 0
    for evt in events:
        conn.execute(
            "INSERT INTO system_events (timestamp, epoch, event_type, detail) VALUES (?, ?, ?, ?)",
            (ts, epoch, evt.get("type", "unknown"), evt.get("detail", ""))
        )
        count += 1

    conn.commit()
    log.info(f"Backfilled {count} events from ESP32 ring buffer")


# ============================================================
# Main loop
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="Smart Garden data collector")
    parser.add_argument("--once", action="store_true", help="Single poll then exit")
    parser.add_argument("--backfill-events", action="store_true", help="Pull /api/events into DB")
    args = parser.parse_args()

    log.info(f"Database: {DB_PATH}")
    log.info(f"ESP32 URL: {ESP32_BASE_URL}")
    log.info(f"Poll interval: {POLL_INTERVAL}s")

    conn = init_db(DB_PATH)

    # Log collector start
    now = datetime.now(timezone.utc)
    conn.execute(
        "INSERT INTO system_events (timestamp, epoch, event_type, detail) VALUES (?, ?, ?, ?)",
        (now.isoformat(), int(now.timestamp()), "collector", "Collector started")
    )
    conn.commit()

    if args.backfill_events:
        backfill_events(conn)
        return

    if args.once:
        success = poll_status(conn)
        sys.exit(0 if success else 1)

    # Continuous polling loop
    log.info("Starting continuous polling...")
    consecutive_failures = 0
    while True:
        success = poll_status(conn)
        if success:
            consecutive_failures = 0
        else:
            consecutive_failures += 1
            if consecutive_failures >= 10:
                log.error(f"ESP32 unreachable for {consecutive_failures} consecutive polls")

        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
