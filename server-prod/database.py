"""SQLite database schema and helpers for Smart Garden Server."""

import logging
import sqlite3
import os
from datetime import datetime, date

log = logging.getLogger("smart-garden")

DB_PATH = os.path.join(os.path.dirname(__file__), "smart-garden.db")

# Collector DB — always has fresh data (polled every 60s by separate service).
# Used as fallback when our own sensor data is stale.
COLLECTOR_DB_PATH = os.path.expanduser(
    "~/smart-garden/server/smart-garden.db"
)


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    """Create all tables if they don't exist."""
    conn = get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS sensor_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            ts          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now','localtime')),
            zone_id     INTEGER NOT NULL,
            soil_pct    REAL,
            soil_raw    INTEGER
        );

        CREATE TABLE IF NOT EXISTS weather_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            ts          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now','localtime')),
            source      TEXT NOT NULL,  -- 'api' or 'dht22'
            temp_f      REAL,
            humidity    REAL,
            wind_mph    REAL,
            rain_mm     REAL,
            et0_mm      REAL,
            solar_rad   REAL
        );

        CREATE TABLE IF NOT EXISTS watering_event (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            zone_id         INTEGER NOT NULL,
            start_ts        TEXT NOT NULL,
            end_ts          TEXT,
            duration_sec    INTEGER,
            soil_before     REAL,
            soil_after      REAL,
            et_demand_mm    REAL,
            est_gallons     REAL,
            est_cf          REAL,
            trigger_reason  TEXT  -- 'soil_dry', 'et_demand', 'manual'
        );

        CREATE TABLE IF NOT EXISTS skip_event (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            ts              TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now','localtime')),
            zone_id         INTEGER NOT NULL,
            reason          TEXT NOT NULL,
            est_gallons_saved REAL,
            est_cf_saved    REAL,
            conditions      TEXT  -- JSON: weather snapshot at decision time
        );

        CREATE TABLE IF NOT EXISTS daily_summary (
            date            TEXT PRIMARY KEY,
            total_gallons   REAL DEFAULT 0,
            total_cf        REAL DEFAULT 0,
            gallons_saved   REAL DEFAULT 0,
            cf_saved        REAL DEFAULT 0,
            cost            REAL DEFAULT 0,
            cost_avoided    REAL DEFAULT 0,
            et0_mm          REAL,
            rain_mm         REAL,
            avg_temp_f      REAL
        );

        CREATE TABLE IF NOT EXISTS billing_cycle (
            month           TEXT PRIMARY KEY,  -- 'YYYY-MM'
            total_cf        REAL DEFAULT 0,
            irrigation_cf   REAL DEFAULT 0,
            tier_reached    INTEGER DEFAULT 1,
            total_cost      REAL DEFAULT 0,
            timer_equiv_cf  REAL DEFAULT 0,
            timer_equiv_cost REAL DEFAULT 0,
            savings         REAL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS system_health (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            ts          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now','localtime')),
            uptime_sec  INTEGER,
            wifi_rssi   INTEGER,
            heap_pct    INTEGER,
            chip_temp_f REAL,
            boot_count  INTEGER,
            battery_v   REAL
        );

        CREATE TABLE IF NOT EXISTS soil_balance (
            zone_id     INTEGER NOT NULL,
            date        TEXT NOT NULL,
            et0_mm      REAL DEFAULT 0,
            kc          REAL DEFAULT 0,
            etc_mm      REAL DEFAULT 0,
            rain_mm     REAL DEFAULT 0,
            irrigation_mm REAL DEFAULT 0,
            balance_mm  REAL DEFAULT 0,
            taw_mm      REAL DEFAULT 0,
            mad_mm      REAL DEFAULT 0,
            PRIMARY KEY (zone_id, date)
        );

        -- Human "looks dry" feedback per zone. A decaying mm offset subtracted
        -- from the zone's effective water balance, so a zone the user reports
        -- as dry waters sooner — and, with repeated reports, the model learns
        -- that zone runs drier than its physics predict. Decays to zero over
        -- DRY_BIAS_DECAY_DAYS so stale one-off observations fade on their own.
        CREATE TABLE IF NOT EXISTS zone_feedback (
            zone_id      INTEGER PRIMARY KEY,
            dry_bias_mm  REAL NOT NULL DEFAULT 0,
            observations INTEGER NOT NULL DEFAULT 0,
            updated_ts   TEXT
        );

        CREATE TABLE IF NOT EXISTS connectivity_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            ts          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now','localtime')),
            success     INTEGER NOT NULL,
            latency_ms  INTEGER,
            error_message TEXT,
            boot_count  INTEGER,
            uptime_sec  INTEGER
        );

        CREATE INDEX IF NOT EXISTS idx_sensor_ts ON sensor_log(ts);
        CREATE INDEX IF NOT EXISTS idx_sensor_zone ON sensor_log(zone_id, ts);
        CREATE INDEX IF NOT EXISTS idx_weather_ts ON weather_log(ts);
        CREATE INDEX IF NOT EXISTS idx_watering_zone ON watering_event(zone_id, start_ts);
        CREATE INDEX IF NOT EXISTS idx_skip_ts ON skip_event(ts);
        CREATE INDEX IF NOT EXISTS idx_health_ts ON system_health(ts);
        CREATE INDEX IF NOT EXISTS idx_balance_zone ON soil_balance(zone_id, date);
        CREATE INDEX IF NOT EXISTS idx_conn_ts ON connectivity_log(ts);

        CREATE TABLE IF NOT EXISTS cycle_summary (
            id                    INTEGER PRIMARY KEY AUTOINCREMENT,
            ts                    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now','localtime')),
            zones_evaluated       INTEGER,
            zones_skipped         INTEGER,
            zones_watered         INTEGER,
            zones_outside_window  INTEGER,
            dominant_reason       TEXT,
            details_json          TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_cycle_ts ON cycle_summary(ts);

        CREATE TABLE IF NOT EXISTS sensor_fault (
            zone_id       INTEGER PRIMARY KEY,
            faulted       INTEGER NOT NULL DEFAULT 0,
            fault_type    TEXT,
            detected_ts   TEXT,
            cleared_ts    TEXT
        );
        CREATE TABLE IF NOT EXISTS server_health_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            ts          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now','localtime')),
            disk_pct    REAL,
            db_size_mb  REAL,
            cpu_temp_c  REAL
        );
        CREATE INDEX IF NOT EXISTS idx_server_health_ts ON server_health_log(ts);

        CREATE TABLE IF NOT EXISTS forecast_snapshot (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            ts              TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now','localtime')),
            forecast_date   TEXT NOT NULL,
            zone_id         INTEGER NOT NULL,
            zone_name       TEXT,
            balance_mm      REAL,
            taw_mm          REAL,
            mad_mm          REAL,
            etc_mm          REAL,
            et0_mm          REAL,
            rain_forecast_mm REAL DEFAULT 0,
            days_until_water REAL,
            predicted_date  TEXT,
            predicted_skip  INTEGER DEFAULT 0,
            skip_reason     TEXT,
            UNIQUE(forecast_date, zone_id)
        );
        CREATE INDEX IF NOT EXISTS idx_forecast_date ON forecast_snapshot(forecast_date);
        CREATE INDEX IF NOT EXISTS idx_forecast_zone ON forecast_snapshot(zone_id, forecast_date);

        -- Soil-moisture "wetting events": when a sensor's reading rises
        -- significantly, we classify the cause (rain / irrigation / unexplained).
        -- Observe-only for now — recorded + shown on the dashboard, NOT yet fed
        -- into watering decisions. See RainDetector in irrigation.py.
        CREATE TABLE IF NOT EXISTS rain_event (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            ts             TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now','localtime')),
            sensor_idx     INTEGER NOT NULL,   -- soil channel 0-3 (GPIO 32-35)
            prev_pct       REAL,
            curr_pct       REAL,
            rise_pct       REAL,
            classification TEXT,               -- 'rain' | 'irrigation' | 'unexplained'
            sky            TEXT,               -- weather snapshot summary
            detail         TEXT                -- human-readable explanation
        );
        CREATE INDEX IF NOT EXISTS idx_rain_event_ts ON rain_event(ts);

        -- Calibration capture log: every time a sensor's dry or wet endpoint is
        -- (re)captured, we record the raw value + timestamp. Drift is measured by
        -- comparing successive captures of the SAME endpoint — the reference
        -- state (dry-in-air / saturated-soil) is constant, so any change in the
        -- captured raw is sensor drift, cleanly separated from seasonal moisture.
        CREATE TABLE IF NOT EXISTS calibration_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            ts          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now','localtime')),
            sensor_idx  INTEGER NOT NULL,   -- soil channel 0-3
            point       TEXT NOT NULL,      -- 'dry' | 'wet'
            raw         INTEGER NOT NULL,   -- captured ADC raw value
            source      TEXT                -- 'capture' (live) | 'manual'
        );
        CREATE INDEX IF NOT EXISTS idx_calib_sensor ON calibration_log(sensor_idx, point, ts);

        -- ESP32-CAM (water-meter cam, .160) device/WiFi telemetry timeline.
        -- Two row sources share one timeline:
        --   source='frame' : recorded on every JPEG upload — transfer_s (upload
        --                    time = a WiFi-quality proxy), size_bytes, gap_s
        --                    (secs since previous frame; ~5 ideal, big = drop),
        --                    and rssi/uptime/reconnects IF the firmware sends the
        --                    optional X-RSSI / X-Uptime / X-Reconnects headers
        --                    (NULL until a reflash adds them).
        --   source='ping'  : a background ICMP pinger — ping_ms (RTT) + reachable.
        CREATE TABLE IF NOT EXISTS cam_telemetry (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            ts          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now','localtime')),
            source      TEXT NOT NULL,      -- 'frame' | 'ping'
            transfer_s  REAL,
            size_bytes  INTEGER,
            gap_s       REAL,
            ping_ms     INTEGER,
            reachable   INTEGER,
            rssi        INTEGER,
            uptime_sec  INTEGER,
            reconnects  INTEGER
        );
        CREATE INDEX IF NOT EXISTS idx_camtel_ts ON cam_telemetry(ts);
        CREATE INDEX IF NOT EXISTS idx_camtel_src ON cam_telemetry(source, ts);
    """)
    # ── Column migrations (ALTER TABLE is no-op if column exists) ──
    for col, coltype in [("wifi_reconnects", "INTEGER"), ("crash_count", "INTEGER"),
                         ("tx_power_raw", "INTEGER")]:
        try:
            conn.execute(f"ALTER TABLE system_health ADD COLUMN {col} {coltype}")
        except sqlite3.OperationalError:
            pass  # column already exists
    conn.commit()
    conn.close()


# ── Rain-event helpers (soil-rise detection) ──

def get_prior_soil_reading(sensor_idx: int, within_hours: int = 6) -> dict | None:
    """Most recent soil reading for a sensor BEFORE the newest one, within a
    lookback window. Used as the baseline to detect a rise. Returns the 2nd-most
    -recent row (the newest is the one we're evaluating)."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT soil_pct, soil_raw, ts FROM sensor_log "
        "WHERE zone_id = ? AND ts >= datetime('now','localtime',?) "
        "ORDER BY ts DESC LIMIT 2",
        (sensor_idx, f"-{within_hours} hours"),
    ).fetchall()
    conn.close()
    # Index 0 = newest (the reading just logged), index 1 = the prior baseline.
    if len(rows) >= 2:
        return dict(rows[1])
    return None


def any_watering_since(minutes: int = 90) -> bool:
    """True if ANY zone has a watering event that started within the window.
    Conservative irrigation-correlation: if anything watered recently, a soil
    rise is attributed to irrigation, not rain (fail-safe: never over-credit rain)."""
    conn = get_conn()
    row = conn.execute(
        "SELECT 1 FROM watering_event "
        "WHERE start_ts >= datetime('now','localtime',?) LIMIT 1",
        (f"-{minutes} minutes",),
    ).fetchone()
    conn.close()
    return row is not None


def log_rain_event(sensor_idx: int, prev_pct: float, curr_pct: float,
                   rise_pct: float, classification: str, sky: str, detail: str):
    conn = get_conn()
    conn.execute(
        "INSERT INTO rain_event (sensor_idx, prev_pct, curr_pct, rise_pct, "
        "classification, sky, detail) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (sensor_idx, prev_pct, curr_pct, rise_pct, classification, sky, detail),
    )
    conn.commit()
    conn.close()


def get_rain_events(days: int = 7) -> list[dict]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM rain_event WHERE ts >= datetime('now','localtime',?) "
        "ORDER BY ts DESC LIMIT 200",
        (f"-{days} days",),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── Calibration-log helpers (drift tracking) ──

def log_calibration(sensor_idx: int, point: str, raw: int, source: str = "capture"):
    """Record a calibration endpoint capture for drift history."""
    conn = get_conn()
    conn.execute(
        "INSERT INTO calibration_log (sensor_idx, point, raw, source) "
        "VALUES (?, ?, ?, ?)",
        (sensor_idx, point, int(raw), source),
    )
    conn.commit()
    conn.close()


def get_calibration_history(sensor_idx: int = None, limit: int = 50) -> list[dict]:
    """Calibration captures, newest first. Optionally for one sensor."""
    conn = get_conn()
    if sensor_idx is None:
        rows = conn.execute(
            "SELECT * FROM calibration_log ORDER BY ts DESC LIMIT ?",
            (limit,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM calibration_log WHERE sensor_idx = ? "
            "ORDER BY ts DESC LIMIT ?",
            (sensor_idx, limit),
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── ESP32-CAM telemetry helpers (WiFi/connectivity history) ──

def log_cam_frame(transfer_s: float, size_bytes: int, gap_s: float | None,
                  rssi: int | None = None, uptime_sec: int | None = None,
                  reconnects: int | None = None):
    """Record one frame-upload telemetry sample (called per cam upload)."""
    conn = get_conn()
    conn.execute(
        "INSERT INTO cam_telemetry (source, transfer_s, size_bytes, gap_s, "
        "rssi, uptime_sec, reconnects) VALUES ('frame', ?, ?, ?, ?, ?, ?)",
        (round(float(transfer_s), 3), int(size_bytes),
         (round(float(gap_s), 2) if gap_s is not None else None),
         rssi, uptime_sec, reconnects),
    )
    conn.commit()
    conn.close()


def log_cam_ping(ping_ms: int | None, reachable: bool):
    """Record one background ICMP ping sample. ping_ms NULL when unreachable."""
    conn = get_conn()
    conn.execute(
        "INSERT INTO cam_telemetry (source, ping_ms, reachable) "
        "VALUES ('ping', ?, ?)",
        (ping_ms, 1 if reachable else 0),
    )
    conn.commit()
    conn.close()


def get_cam_telemetry(hours: int = 24, max_points: int = 1500) -> dict:
    """Time-series for the cam-device page: frame rows (transfer/gap/size/rssi)
    and ping rows (rtt/reachable), newest-last for charting. Caps the number of
    returned points by striding so long windows stay light."""
    conn = get_conn()
    frames = conn.execute(
        "SELECT ts, transfer_s, size_bytes, gap_s, rssi, uptime_sec, reconnects "
        "FROM cam_telemetry WHERE source='frame' AND ts >= datetime('now','localtime',?) "
        "ORDER BY ts ASC", (f"-{hours} hours",)).fetchall()
    pings = conn.execute(
        "SELECT ts, ping_ms, reachable FROM cam_telemetry "
        "WHERE source='ping' AND ts >= datetime('now','localtime',?) "
        "ORDER BY ts ASC", (f"-{hours} hours",)).fetchall()
    conn.close()

    def _stride(rows):
        n = len(rows)
        if n <= max_points:
            return [dict(r) for r in rows]
        step = (n // max_points) + 1
        return [dict(rows[i]) for i in range(0, n, step)]

    return {"frames": _stride(frames), "pings": _stride(pings)}


def get_cam_telemetry_summary(hours: int = 24) -> dict:
    """Rolling stats for the cam device: avg/max transfer, frame count, gap-based
    drop rate, ping avg/max + loss %, and the latest RSSI/uptime/reconnects."""
    conn = get_conn()
    win = (f"-{hours} hours",)
    f = conn.execute(
        "SELECT COUNT(*) n, AVG(transfer_s) avg_t, MAX(transfer_s) max_t, "
        "AVG(size_bytes) avg_sz, "
        "SUM(CASE WHEN gap_s > 10 THEN 1 ELSE 0 END) gaps "
        "FROM cam_telemetry WHERE source='frame' AND ts >= datetime('now','localtime',?)",
        win).fetchone()
    p = conn.execute(
        "SELECT COUNT(*) n, AVG(ping_ms) avg_p, MAX(ping_ms) max_p, "
        "SUM(CASE WHEN reachable=0 THEN 1 ELSE 0 END) lost "
        "FROM cam_telemetry WHERE source='ping' AND ts >= datetime('now','localtime',?)",
        win).fetchone()
    latest = conn.execute(
        "SELECT ts, rssi, uptime_sec, reconnects FROM cam_telemetry "
        "WHERE source='frame' AND rssi IS NOT NULL ORDER BY ts DESC LIMIT 1"
    ).fetchone()
    conn.close()
    fn = f["n"] or 0
    pn = p["n"] or 0
    return {
        "hours": hours,
        "frame_count": fn,
        "avg_transfer_s": round(f["avg_t"], 2) if f["avg_t"] is not None else None,
        "max_transfer_s": round(f["max_t"], 2) if f["max_t"] is not None else None,
        "avg_size_kb": round((f["avg_sz"] or 0) / 1024, 1),
        "frame_gaps": f["gaps"] or 0,
        "frame_drop_pct": round(100 * (f["gaps"] or 0) / fn, 1) if fn else None,
        "ping_count": pn,
        "avg_ping_ms": round(p["avg_p"], 1) if p["avg_p"] is not None else None,
        "max_ping_ms": p["max_p"],
        "ping_loss_pct": round(100 * (p["lost"] or 0) / pn, 1) if pn else None,
        "latest_rssi": (latest["rssi"] if latest else None),
        "latest_uptime_sec": (latest["uptime_sec"] if latest else None),
        "latest_reconnects": (latest["reconnects"] if latest else None),
        "rssi_available": latest is not None,
    }


def prune_cam_telemetry(days: int = 14):
    """Delete cam telemetry older than N days to keep the table bounded."""
    conn = get_conn()
    conn.execute(
        "DELETE FROM cam_telemetry WHERE ts < datetime('now','localtime',?)",
        (f"-{days} days",))
    conn.commit()
    conn.close()


def get_calibration_drift() -> list[dict]:
    """Per-sensor/per-endpoint drift: compares the most recent capture of each
    (sensor, point) against the one before it. Returns the raw delta, days
    between, and a per-30-day drift rate. The reference state is controlled
    (dry-in-air / saturated soil), so this delta is pure sensor drift — NOT
    seasonal moisture change (which only affects in-ground readings)."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT sensor_idx, point, raw, ts FROM calibration_log ORDER BY ts DESC"
    ).fetchall()
    conn.close()
    # Group by (sensor_idx, point), preserving newest-first order.
    groups: dict = {}
    for r in rows:
        groups.setdefault((r["sensor_idx"], r["point"]), []).append(r)
    out = []
    from datetime import datetime
    for (idx, point), captures in groups.items():
        latest = captures[0]
        entry = {
            "sensor_idx": idx,
            "point": point,
            "latest_raw": latest["raw"],
            "latest_ts": latest["ts"],
            "captures": len(captures),
            "prev_raw": None,
            "delta": None,
            "days": None,
            "drift_per_30d": None,
        }
        if len(captures) >= 2:
            prev = captures[1]
            entry["prev_raw"] = prev["raw"]
            entry["delta"] = latest["raw"] - prev["raw"]
            try:
                t1 = datetime.strptime(latest["ts"][:19], "%Y-%m-%dT%H:%M:%S")
                t0 = datetime.strptime(prev["ts"][:19], "%Y-%m-%dT%H:%M:%S")
                days = (t1 - t0).total_seconds() / 86400.0
                entry["days"] = round(days, 1)
                if days > 0.5:
                    entry["drift_per_30d"] = round(entry["delta"] / days * 30.0, 0)
            except Exception:
                pass
        out.append(entry)
    return out


# ── Insert helpers ──

def log_sensor(zone_id: int, soil_pct: float, soil_raw: int):
    conn = get_conn()
    conn.execute(
        "INSERT INTO sensor_log (zone_id, soil_pct, soil_raw) VALUES (?, ?, ?)",
        (zone_id, soil_pct, soil_raw),
    )
    conn.commit()
    conn.close()


def log_weather(source: str, temp_f: float = None, humidity: float = None,
                wind_mph: float = None, rain_mm: float = None,
                et0_mm: float = None, solar_rad: float = None):
    conn = get_conn()
    conn.execute(
        "INSERT INTO weather_log (source, temp_f, humidity, wind_mph, rain_mm, et0_mm, solar_rad) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (source, temp_f, humidity, wind_mph, rain_mm, et0_mm, solar_rad),
    )
    conn.commit()
    conn.close()


def start_watering(zone_id: int, soil_before: float, et_demand_mm: float,
                   trigger_reason: str) -> int:
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO watering_event (zone_id, start_ts, soil_before, et_demand_mm, trigger_reason) "
        "VALUES (?, strftime('%Y-%m-%dT%H:%M:%S','now','localtime'), ?, ?, ?)",
        (zone_id, soil_before, et_demand_mm, trigger_reason),
    )
    event_id = cur.lastrowid
    conn.commit()
    conn.close()
    return event_id


def end_watering(event_id: int, soil_after: float, duration_sec: int,
                 est_gallons: float):
    est_cf = est_gallons / 7.48  # 1 cf = 7.48 gallons
    conn = get_conn()
    conn.execute(
        "UPDATE watering_event SET end_ts = strftime('%Y-%m-%dT%H:%M:%S','now','localtime'), "
        "soil_after = ?, duration_sec = ?, est_gallons = ?, est_cf = ? WHERE id = ?",
        (soil_after, duration_sec, est_gallons, est_cf, event_id),
    )
    conn.commit()
    conn.close()


def close_orphaned_watering_events() -> list[dict]:
    """Close any watering_event rows left open by a prior crash/restart.

    Sets end_ts=now, duration_sec=0, est_gallons=0 (we can't trust that the
    valve was actually open for the whole gap) and tags trigger_reason with
    `[orphaned_cleanup]`. Under-credit is safer than over-credit — the
    balance model will just decide to water again next cycle if needed.
    Returns the closed rows so the caller can log them individually.
    """
    conn = get_conn()
    rows = conn.execute(
        "SELECT id, zone_id, start_ts, trigger_reason FROM watering_event "
        "WHERE end_ts IS NULL"
    ).fetchall()
    if not rows:
        conn.close()
        return []
    conn.execute(
        "UPDATE watering_event "
        "SET end_ts = strftime('%Y-%m-%dT%H:%M:%S','now','localtime'), "
        "    duration_sec = COALESCE(duration_sec, 0), "
        "    est_gallons = COALESCE(est_gallons, 0), "
        "    est_cf = COALESCE(est_cf, 0), "
        "    trigger_reason = COALESCE(trigger_reason, '') || ' [orphaned_cleanup]' "
        "WHERE end_ts IS NULL"
    )
    conn.commit()
    conn.close()
    return [dict(r) for r in rows]


def log_skip(zone_id: int, reason: str, est_gallons_saved: float,
             conditions: str = None):
    est_cf = est_gallons_saved / 7.48
    conn = get_conn()
    conn.execute(
        "INSERT INTO skip_event (zone_id, reason, est_gallons_saved, est_cf_saved, conditions) "
        "VALUES (?, ?, ?, ?, ?)",
        (zone_id, reason, est_gallons_saved, est_cf, conditions),
    )
    conn.commit()
    conn.close()


def skip_event_exists_today(zone_id: int) -> bool:
    conn = get_conn()
    row = conn.execute(
        "SELECT 1 FROM skip_event "
        "WHERE zone_id = ? AND DATE(ts) = DATE('now', 'localtime') LIMIT 1",
        (zone_id,),
    ).fetchone()
    conn.close()
    return row is not None


def log_cycle_summary(zones_evaluated: int, zones_skipped: int,
                      zones_watered: int, zones_outside_window: int,
                      dominant_reason: str, details_json: str = None):
    conn = get_conn()
    conn.execute(
        "INSERT INTO cycle_summary (zones_evaluated, zones_skipped, zones_watered, "
        "zones_outside_window, dominant_reason, details_json) VALUES (?, ?, ?, ?, ?, ?)",
        (zones_evaluated, zones_skipped, zones_watered, zones_outside_window,
         dominant_reason, details_json),
    )
    conn.commit()
    conn.close()


def log_connectivity(success: bool, latency_ms: int = None,
                     error_message: str = None, boot_count: int = None,
                     uptime_sec: int = None):
    conn = get_conn()
    conn.execute(
        "INSERT INTO connectivity_log (success, latency_ms, error_message, boot_count, uptime_sec) "
        "VALUES (?, ?, ?, ?, ?)",
        (1 if success else 0, latency_ms, error_message, boot_count, uptime_sec),
    )
    conn.commit()
    conn.close()


def get_connectivity_history(hours: int = 24) -> list[dict]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT ts, success, latency_ms, error_message, boot_count, uptime_sec "
        "FROM connectivity_log WHERE ts >= datetime('now','localtime', ?) ORDER BY ts",
        (f"-{hours} hours",),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_last_connectivity() -> dict | None:
    conn = get_conn()
    row = conn.execute(
        "SELECT ts, success, latency_ms, boot_count, uptime_sec "
        "FROM connectivity_log ORDER BY ts DESC LIMIT 1"
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def log_system_health(uptime_sec: int, wifi_rssi: int, heap_pct: int,
                      chip_temp_f: float, boot_count: int, battery_v: float = None,
                      wifi_reconnects: int = None, crash_count: int = None,
                      tx_power_raw: int = None):
    conn = get_conn()
    conn.execute(
        "INSERT INTO system_health (uptime_sec, wifi_rssi, heap_pct, chip_temp_f, boot_count, battery_v, "
        "wifi_reconnects, crash_count, tx_power_raw) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (uptime_sec, wifi_rssi, heap_pct, chip_temp_f, boot_count, battery_v,
         wifi_reconnects, crash_count, tx_power_raw),
    )
    conn.commit()
    conn.close()


# ── Query helpers ──

def get_latest_soil(zone_id: int) -> dict | None:
    """Get latest soil reading, falling back to collector DB if stale (>10 min)."""
    conn = get_conn()
    row = conn.execute(
        "SELECT soil_pct, soil_raw, ts FROM sensor_log "
        "WHERE zone_id = ? ORDER BY ts DESC LIMIT 1",
        (zone_id,),
    ).fetchone()
    conn.close()

    result = dict(row) if row else None

    # If our data is missing or stale (>10 min), try the collector DB
    if _is_stale(result, minutes=10):
        fallback = _get_collector_soil(zone_id)
        if fallback is not None:
            return fallback

    return result


def _is_stale(reading: dict | None, minutes: int) -> bool:
    """Check if a reading dict with 'ts' key is older than `minutes`."""
    if reading is None:
        return True
    try:
        ts = datetime.fromisoformat(reading["ts"])
        age = (datetime.now() - ts).total_seconds()
        return age > minutes * 60
    except (KeyError, ValueError, TypeError):
        return True


def _get_collector_soil(zone_id: int) -> dict | None:
    """Read latest soil data from the collector's DB (different schema)."""
    if not os.path.exists(COLLECTOR_DB_PATH):
        return None
    try:
        conn = sqlite3.connect(COLLECTOR_DB_PATH, timeout=2)
        conn.row_factory = sqlite3.Row
        # Collector stores soil_N_pct and soil_N_raw as columns (1-indexed naming
        # but 0-indexed in practice: soil_1 = zone 0, soil_2 = zone 1, etc.)
        col_idx = zone_id + 1
        row = conn.execute(
            f"SELECT soil_{col_idx}_pct AS soil_pct, "
            f"soil_{col_idx}_raw AS soil_raw, "
            "timestamp AS ts "
            "FROM sensor_readings ORDER BY id DESC LIMIT 1"
        ).fetchone()
        conn.close()
        if row:
            return {"soil_pct": row["soil_pct"], "soil_raw": row["soil_raw"],
                    "ts": row["ts"]}
    except (sqlite3.Error, Exception):
        pass
    return None


def get_soil_history(zone_id: int, days: int = 7) -> list[dict]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT soil_pct, ts FROM sensor_log WHERE zone_id = ? "
        "AND ts >= datetime('now', 'localtime', ?) ORDER BY ts",
        (zone_id, f"-{days} days"),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_watering_history(days: int = 30) -> list[dict]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM watering_event WHERE start_ts >= datetime('now', 'localtime', ?) "
        "ORDER BY start_ts DESC",
        (f"-{days} days",),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_skip_history(days: int = 30) -> list[dict]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM skip_event WHERE ts >= datetime('now', 'localtime', ?) "
        "ORDER BY ts DESC",
        (f"-{days} days",),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_monthly_usage(month: str = None) -> dict:
    """Get total irrigation cf for a billing month (YYYY-MM)."""
    if month is None:
        month = date.today().strftime("%Y-%m")
    conn = get_conn()
    row = conn.execute(
        "SELECT COALESCE(SUM(est_cf), 0) as total_cf, "
        "COALESCE(SUM(est_gallons), 0) as total_gallons, "
        "COUNT(*) as event_count "
        "FROM watering_event WHERE strftime('%%Y-%%m', start_ts) = ?",
        (month,),
    ).fetchone()
    conn.close()
    return dict(row) if row else {"total_cf": 0, "total_gallons": 0, "event_count": 0}


def get_monthly_savings(month: str = None) -> dict:
    if month is None:
        month = date.today().strftime("%Y-%m")
    conn = get_conn()
    row = conn.execute(
        "SELECT COALESCE(SUM(est_cf_saved), 0) as cf_saved, "
        "COALESCE(SUM(est_gallons_saved), 0) as gallons_saved, "
        "COUNT(*) as skip_count "
        "FROM skip_event WHERE strftime('%%Y-%%m', ts) = ?",
        (month,),
    ).fetchone()
    conn.close()
    return dict(row) if row else {"cf_saved": 0, "gallons_saved": 0, "skip_count": 0}


def get_daily_summaries(days: int = 30) -> list[dict]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM daily_summary WHERE date >= date('now', 'localtime', ?) "
        "ORDER BY date DESC",
        (f"-{days} days",),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_latest_health() -> dict | None:
    """Get latest health, falling back to collector DB if stale (>10 min)."""
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM system_health ORDER BY ts DESC LIMIT 1"
    ).fetchone()
    conn.close()
    result = dict(row) if row else None

    if _is_stale(result, minutes=10):
        fallback = _get_collector_health()
        if fallback is not None:
            return fallback

    return result


def _get_collector_health() -> dict | None:
    """Read latest health data from the collector's DB."""
    if not os.path.exists(COLLECTOR_DB_PATH):
        return None
    try:
        conn = sqlite3.connect(COLLECTOR_DB_PATH, timeout=2)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT uptime_sec, wifi_rssi, heap_pct, chip_temp_f, "
            "boot_count, wifi_reconnects, timestamp AS ts "
            "FROM sensor_readings ORDER BY id DESC LIMIT 1"
        ).fetchone()
        conn.close()
        if row:
            return {
                "ts": row["ts"], "uptime_sec": row["uptime_sec"],
                "wifi_rssi": row["wifi_rssi"], "heap_pct": row["heap_pct"],
                "chip_temp_f": row["chip_temp_f"], "boot_count": row["boot_count"],
                "wifi_reconnects": row["wifi_reconnects"],
                "battery_v": None, "crash_count": None,
            }
    except (sqlite3.Error, Exception):
        pass
    return None


def get_health_history(limit: int = 10) -> list[dict]:
    """Get recent system health entries for telemetry display."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM system_health ORDER BY ts DESC LIMIT ?",
        (limit,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_health_timeseries(hours: int = 24) -> list[dict]:
    """Health metrics time-series for charts. Downsamples to hourly for >72h."""
    conn = get_conn()
    cutoff = f"-{hours} hours"
    if hours > 72:
        rows = conn.execute(
            "SELECT strftime('%Y-%m-%dT%H:00:00',ts) as ts, "
            "ROUND(AVG(wifi_rssi),0) as wifi_rssi, ROUND(AVG(heap_pct),0) as heap_pct, "
            "MAX(uptime_sec) as uptime_sec, MAX(boot_count) as boot_count, "
            "ROUND(AVG(chip_temp_f),1) as chip_temp_f, "
            "MAX(wifi_reconnects) as wifi_reconnects, MAX(crash_count) as crash_count, "
            "ROUND(AVG(battery_v),2) as battery_v "
            "FROM system_health WHERE ts >= datetime('now','localtime', ?) "
            "GROUP BY strftime('%Y-%m-%dT%H',ts) ORDER BY ts",
            (cutoff,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT ts, wifi_rssi, heap_pct, uptime_sec, boot_count, chip_temp_f, "
            "wifi_reconnects, crash_count, battery_v "
            "FROM system_health WHERE ts >= datetime('now','localtime', ?) ORDER BY ts",
            (cutoff,),
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_sensor_flatline(zone_id: int, hours: int = 24) -> dict:
    """Check if a sensor has been reporting the same value for the entire period."""
    conn = get_conn()
    row = conn.execute(
        "SELECT COUNT(*) as cnt, MIN(soil_pct) as min_pct, MAX(soil_pct) as max_pct, "
        "MIN(soil_raw) as min_raw, MAX(soil_raw) as max_raw "
        "FROM sensor_log WHERE zone_id = ? AND ts >= datetime('now','localtime', ?)",
        (zone_id, f"-{hours} hours"),
    ).fetchone()
    conn.close()
    if not row or row["cnt"] == 0:
        return {"flatline": False, "no_data": True, "count": 0}
    return {
        "flatline": row["min_pct"] == row["max_pct"] and row["cnt"] > 5,
        "railed": row["min_pct"] in (0, 100) and row["max_pct"] == row["min_pct"],
        "no_data": False,
        "count": row["cnt"],
        "min_pct": row["min_pct"],
        "max_pct": row["max_pct"],
        "min_raw": row["min_raw"],
        "max_raw": row["max_raw"],
    }


# ── Data retention pruning ──

def prune_old_data(raw_days: int = 30, agg_days: int = 365):
    """Delete raw data older than raw_days. Keep hourly aggregates for agg_days.

    Tables pruned: sensor_log, system_health, connectivity_log, weather_log.
    skip_event and watering_event are kept permanently (low volume).
    """
    conn = get_conn()
    raw_cutoff = f"-{raw_days} days"
    agg_cutoff = f"-{agg_days} days"

    for table, ts_col in [("sensor_log", "ts"), ("system_health", "ts"),
                           ("connectivity_log", "ts"), ("weather_log", "ts"),
                           ("cycle_summary", "ts")]:
        # Delete everything beyond aggregate retention
        deleted = conn.execute(
            f"DELETE FROM {table} WHERE {ts_col} < datetime('now','localtime', ?)",
            (agg_cutoff,),
        ).rowcount

        # For raw retention period → agg retention, keep only hourly samples
        # Delete rows that are NOT the first row of each hour (keep 1 per hour)
        in_between = conn.execute(
            f"DELETE FROM {table} WHERE {ts_col} < datetime('now','localtime', ?) "
            f"AND {ts_col} >= datetime('now','localtime', ?) "
            f"AND id NOT IN ("
            f"  SELECT MIN(id) FROM {table} "
            f"  WHERE {ts_col} < datetime('now','localtime', ?) "
            f"  AND {ts_col} >= datetime('now','localtime', ?) "
            f"  GROUP BY strftime('%Y-%m-%dT%H', {ts_col})"
            f")",
            (raw_cutoff, agg_cutoff, raw_cutoff, agg_cutoff),
        ).rowcount

        if deleted or in_between:
            import logging
            logging.getLogger("smart-garden").info(
                "Pruned %s: %d old + %d downsampled rows removed",
                table, deleted, in_between)

    conn.commit()
    conn.close()


# ── Sensor fault tracking ──

def set_sensor_fault(zone_id: int, fault_type: str):
    conn = get_conn()
    conn.execute(
        "INSERT INTO sensor_fault (zone_id, faulted, fault_type, detected_ts) "
        "VALUES (?, 1, ?, strftime('%Y-%m-%dT%H:%M:%S','now','localtime')) "
        "ON CONFLICT(zone_id) DO UPDATE SET faulted=1, fault_type=excluded.fault_type, "
        "detected_ts=excluded.detected_ts, cleared_ts=NULL",
        (zone_id, fault_type),
    )
    conn.commit()
    conn.close()


def clear_sensor_fault(zone_id: int):
    conn = get_conn()
    conn.execute(
        "UPDATE sensor_fault SET faulted=0, cleared_ts=strftime('%Y-%m-%dT%H:%M:%S','now','localtime') "
        "WHERE zone_id=?",
        (zone_id,),
    )
    conn.commit()
    conn.close()


def get_sensor_faults() -> dict:
    """Returns {zone_id: {faulted, fault_type, detected_ts}} for all faulted sensors."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT zone_id, fault_type, detected_ts FROM sensor_fault WHERE faulted=1"
    ).fetchall()
    conn.close()
    return {r["zone_id"]: {"fault_type": r["fault_type"], "detected_ts": r["detected_ts"]} for r in rows}


def check_and_update_sensor_faults(zones: list):
    """Auto-detect sensor faults: 48h flatline or railed -> mark faulted. Recovery -> clear."""
    import logging
    _log = logging.getLogger("smart-garden")
    for zone in zones:
        if not zone.get("installed", False):
            continue
        sensor_id = zone["soil_sensor"]
        zone_id = zone["id"]
        # No sensor configured (soil_sensor: null) means there's nothing to
        # fault on. Clear any stale fault row left over from a prior config.
        if sensor_id is None:
            clear_sensor_fault(zone_id)
            continue
        anomaly = get_sensor_flatline(sensor_id, hours=48)
        if anomaly.get("railed"):
            set_sensor_fault(zone_id, "railed")
            _log.warning("Sensor fault (railed): Zone %d (%s) at %s%%",
                         zone_id + 1, zone["name"], anomaly["min_pct"])
        elif anomaly.get("flatline"):
            set_sensor_fault(zone_id, "flatline")
            _log.warning("Sensor fault (flatline): Zone %d (%s) at %s%%",
                         zone_id + 1, zone["name"], anomaly["min_pct"])
        elif not anomaly.get("no_data"):
            clear_sensor_fault(zone_id)


def get_active_watering(zone_id: int) -> dict | None:
    """Check if a zone is currently in an active (unclosed) watering event."""
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM watering_event WHERE zone_id = ? AND end_ts IS NULL "
        "ORDER BY start_ts DESC LIMIT 1",
        (zone_id,),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


# ── Analytics queries ──

def get_decision_log(days: int = 30, zone_id: int = None,
                     limit: int = 500, offset: int = 0) -> list[dict]:
    """Merged watering + skip events as a unified decision log."""
    conn = get_conn()
    days_param = f"-{days} days"
    zf = " AND zone_id = ?" if zone_id is not None else ""

    sql = (
        "SELECT 'water' as type, zone_id, start_ts as ts, duration_sec, "
        "soil_before, soil_after, est_gallons as gallons, "
        "trigger_reason as reason, et_demand_mm, NULL as conditions "
        f"FROM watering_event WHERE start_ts >= datetime('now','localtime',?){zf} "
        "UNION ALL "
        "SELECT 'skip' as type, zone_id, ts, NULL, NULL, NULL, "
        "est_gallons_saved, reason, NULL, conditions "
        f"FROM skip_event WHERE ts >= datetime('now','localtime',?){zf} "
        "ORDER BY ts DESC LIMIT ? OFFSET ?"
    )

    params: list = [days_param]
    if zone_id is not None:
        params.append(zone_id)
    params.append(days_param)
    if zone_id is not None:
        params.append(zone_id)
    params.extend([limit, offset])

    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_soil_timeseries(zone_id: int, days: int = 7) -> list[dict]:
    """Soil moisture time-series, downsampled to hourly for ranges > 3 days."""
    conn = get_conn()
    dp = f"-{days} days"
    if days > 3:
        rows = conn.execute(
            "SELECT zone_id, strftime('%Y-%m-%dT%H:00:00',ts) as ts, "
            "ROUND(AVG(soil_pct),1) as soil_pct "
            "FROM sensor_log WHERE zone_id=? AND ts>=datetime('now','localtime',?) "
            "GROUP BY strftime('%Y-%m-%dT%H',ts) ORDER BY ts",
            (zone_id, dp),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT zone_id, ts, soil_pct FROM sensor_log "
            "WHERE zone_id=? AND ts>=datetime('now','localtime',?) ORDER BY ts",
            (zone_id, dp),
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_weather_timeseries(days: int = 7) -> list[dict]:
    """Weather time-series downsampled to hourly."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT strftime('%Y-%m-%dT%H:00:00',ts) as ts, "
        "ROUND(AVG(temp_f),1) as temp_f, ROUND(AVG(humidity),0) as humidity, "
        "ROUND(AVG(wind_mph),1) as wind_mph, ROUND(SUM(rain_mm),2) as rain_mm, "
        "ROUND(AVG(et0_mm),2) as et0_mm "
        "FROM weather_log WHERE ts>=datetime('now','localtime',?) "
        "GROUP BY strftime('%Y-%m-%dT%H',ts) ORDER BY ts",
        (f"-{days} days",),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_daily_water_usage(days: int = 30) -> list[dict]:
    """Daily aggregated water usage from watering events."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT date(start_ts) as day, "
        "COALESCE(SUM(est_gallons),0) as gallons, "
        "COALESCE(SUM(est_cf),0) as cf, "
        "COALESCE(SUM(duration_sec),0) as duration_sec, "
        "COUNT(*) as events "
        "FROM watering_event WHERE start_ts>=datetime('now','localtime',?) AND end_ts IS NOT NULL "
        "GROUP BY date(start_ts) ORDER BY day",
        (f"-{days} days",),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_daily_savings(days: int = 30) -> list[dict]:
    """Daily cycle summary — skips per day from cycle_summary table."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT date(ts) as day, "
        "COALESCE(SUM(zones_skipped),0) as zones_skipped, "
        "COALESCE(SUM(zones_watered),0) as zones_watered, "
        "COUNT(*) as cycles "
        "FROM cycle_summary WHERE ts>=datetime('now','localtime',?) "
        "GROUP BY date(ts) ORDER BY day",
        (f"-{days} days",),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_skip_reason_breakdown(days: int = 30) -> list[dict]:
    """Skip reason breakdown from cycle_summary dominant_reason."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT dominant_reason as reason, COUNT(*) as count, "
        "COALESCE(SUM(zones_skipped),0) as zones_skipped "
        "FROM cycle_summary WHERE ts>=datetime('now','localtime',?) "
        "AND dominant_reason IS NOT NULL "
        "GROUP BY dominant_reason ORDER BY count DESC",
        (f"-{days} days",),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_analytics_overview(days: int = 30) -> dict:
    """High-level analytics summary using cycle_summary instead of per-zone skip_event."""
    conn = get_conn()
    dp = f"-{days} days"

    water = conn.execute(
        "SELECT COUNT(*) as water_events, "
        "COALESCE(SUM(est_gallons),0) as total_gallons, "
        "COALESCE(SUM(est_cf),0) as total_cf, "
        "COALESCE(SUM(duration_sec),0) as total_duration_sec, "
        "COALESCE(AVG(soil_before),0) as avg_soil_before, "
        "COALESCE(AVG(soil_after),0) as avg_soil_after "
        "FROM watering_event WHERE start_ts>=datetime('now','localtime',?) AND end_ts IS NOT NULL",
        (dp,),
    ).fetchone()

    cycles = conn.execute(
        "SELECT COUNT(*) as total_cycles, "
        "COALESCE(SUM(zones_skipped),0) as total_zones_skipped, "
        "COALESCE(SUM(zones_watered),0) as total_zones_watered, "
        "COALESCE(SUM(zones_outside_window),0) as total_outside_window "
        "FROM cycle_summary WHERE ts>=datetime('now','localtime',?)",
        (dp,),
    ).fetchone()

    sensors = conn.execute(
        "SELECT COUNT(*) as readings FROM sensor_log "
        "WHERE ts>=datetime('now','localtime',?)", (dp,),
    ).fetchone()

    conn.close()
    result = {}
    if water:
        result.update(dict(water))
    if cycles:
        result["total_cycles"] = cycles["total_cycles"]
        result["total_zones_skipped"] = cycles["total_zones_skipped"]
        result["total_zones_watered"] = cycles["total_zones_watered"]
        result["total_outside_window"] = cycles["total_outside_window"]
    result["sensor_readings"] = sensors["readings"] if sensors else 0
    return result


# ── Soil Water Balance helpers ──

def upsert_soil_balance(zone_id: int, day: str, et0_mm: float, kc: float,
                        etc_mm: float, rain_mm: float, irrigation_mm: float,
                        balance_mm: float, taw_mm: float, mad_mm: float):
    """Insert or update daily soil water balance for a zone."""
    conn = get_conn()
    conn.execute(
        "INSERT INTO soil_balance (zone_id, date, et0_mm, kc, etc_mm, rain_mm, "
        "irrigation_mm, balance_mm, taw_mm, mad_mm) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(zone_id, date) DO UPDATE SET "
        "et0_mm=excluded.et0_mm, kc=excluded.kc, etc_mm=excluded.etc_mm, "
        "rain_mm=excluded.rain_mm, irrigation_mm=excluded.irrigation_mm, "
        "balance_mm=excluded.balance_mm, taw_mm=excluded.taw_mm, mad_mm=excluded.mad_mm",
        (zone_id, day, et0_mm, kc, etc_mm, rain_mm, irrigation_mm,
         balance_mm, taw_mm, mad_mm),
    )
    conn.commit()
    conn.close()


def get_soil_balance(zone_id: int) -> dict | None:
    """Get the most recent soil water balance for a zone."""
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM soil_balance WHERE zone_id = ? ORDER BY date DESC LIMIT 1",
        (zone_id,),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def get_soil_balance_history(zone_id: int, days: int = 30) -> list[dict]:
    """Get soil water balance history for a zone."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM soil_balance WHERE zone_id = ? "
        "AND date >= date('now', 'localtime', ?) ORDER BY date",
        (zone_id, f"-{days} days"),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── "Looks dry" human feedback ───────────────────────────────────────────────
# A zone the user eyeballs as dry gets a decaying mm offset subtracted from its
# effective water balance, so it waters sooner. Repeated reports stack (capped),
# and the bias fades over DRY_BIAS_DECAY_DAYS so a one-off observation self-heals.
DRY_BIAS_STEP_MM = 4.0       # how much drier one "looks dry" tap makes a zone
DRY_BIAS_MAX_MM = 12.0       # cap so a zone never thinks it's bone-dry from taps
DRY_BIAS_DECAY_DAYS = 14.0   # a single observation fully fades after ~2 weeks


def _decay_bias(bias: float, updated_ts: str | None,
                decay_days: float = DRY_BIAS_DECAY_DAYS,
                now: "datetime | None" = None) -> float:
    """Linearly decay a stored bias to zero over decay_days from updated_ts."""
    if not bias or not updated_ts:
        return 0.0
    from datetime import datetime as _dt
    now = now or _dt.now()
    try:
        t0 = _dt.fromisoformat(updated_ts)
    except Exception:
        return float(bias)
    days = max(0.0, (now - t0).total_seconds() / 86400.0)
    frac = max(0.0, 1.0 - days / decay_days)
    return float(bias) * frac


def get_zone_feedback(zone_id: int) -> dict | None:
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM zone_feedback WHERE zone_id = ?", (zone_id,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def get_all_zone_feedback() -> dict:
    """{zone_id: {dry_bias_mm, observations, updated_ts, effective_mm}}."""
    conn = get_conn()
    rows = conn.execute("SELECT * FROM zone_feedback").fetchall()
    conn.close()
    out = {}
    for r in rows:
        d = dict(r)
        d["effective_mm"] = round(_decay_bias(d["dry_bias_mm"], d["updated_ts"]), 2)
        out[d["zone_id"]] = d
    return out


def effective_zone_dry_bias(zone_id: int,
                            decay_days: float = DRY_BIAS_DECAY_DAYS) -> float:
    """Current (decayed) dry-bias mm to subtract from this zone's balance."""
    row = get_zone_feedback(zone_id)
    if not row:
        return 0.0
    return _decay_bias(row["dry_bias_mm"], row["updated_ts"], decay_days)


def bump_zone_dryness(zone_id: int, step_mm: float = DRY_BIAS_STEP_MM,
                      max_mm: float = DRY_BIAS_MAX_MM,
                      decay_days: float = DRY_BIAS_DECAY_DAYS) -> dict:
    """Record a 'looks dry' observation: decay the existing bias to now, add a
    step (capped), refresh the timestamp. Returns the new feedback row."""
    from datetime import datetime as _dt
    now = _dt.now()
    row = get_zone_feedback(zone_id)
    cur = _decay_bias(row["dry_bias_mm"], row["updated_ts"], decay_days, now) if row else 0.0
    new_bias = round(min(max_mm, cur + step_mm), 3)
    conn = get_conn()
    conn.execute(
        "INSERT INTO zone_feedback (zone_id, dry_bias_mm, observations, updated_ts) "
        "VALUES (?, ?, 1, ?) ON CONFLICT(zone_id) DO UPDATE SET "
        "dry_bias_mm = excluded.dry_bias_mm, "
        "observations = zone_feedback.observations + 1, "
        "updated_ts = excluded.updated_ts",
        (zone_id, new_bias, now.isoformat()),
    )
    conn.commit()
    conn.close()
    return get_zone_feedback(zone_id)


def reset_zone_feedback(zone_id: int):
    conn = get_conn()
    conn.execute("DELETE FROM zone_feedback WHERE zone_id = ?", (zone_id,))
    conn.commit()
    conn.close()



def get_all_balances() -> list[dict]:
    """Get the latest balance for every zone."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT sb.* FROM soil_balance sb "
        "INNER JOIN (SELECT zone_id, MAX(date) as max_date FROM soil_balance GROUP BY zone_id) latest "
        "ON sb.zone_id = latest.zone_id AND sb.date = latest.max_date "
        "ORDER BY sb.zone_id"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_daily_irrigation_mm(zone_id: int, day: str, precip_rate_iph: float) -> float:
    """Calculate total irrigation applied to a zone on a given day, in mm.

    Uses watering event durations × precipitation rate to convert runtime to depth.
    """
    conn = get_conn()
    row = conn.execute(
        "SELECT COALESCE(SUM(duration_sec), 0) as total_sec "
        "FROM watering_event WHERE zone_id = ? AND date(start_ts) = ? AND end_ts IS NOT NULL",
        (zone_id, day),
    ).fetchone()
    conn.close()
    total_sec = row["total_sec"] if row else 0
    # precip_rate is inches per hour → convert to mm: inches × 25.4
    return (precip_rate_iph * (total_sec / 3600.0)) * 25.4


# ── Server / system telemetry helpers ──

def log_server_health():
    """Snapshot disk %, DB size, CPU temp into server_health_log."""
    import shutil
    disk_pct = db_size = cpu_temp = None
    try:
        usage = shutil.disk_usage(os.path.dirname(DB_PATH))
        disk_pct = round(usage.used / usage.total * 100, 2)
    except Exception as e:
        log.warning("log_server_health: disk_usage failed: %s", e)
    try:
        db_size = round(os.path.getsize(DB_PATH) / (1024**2), 3)
    except Exception as e:
        log.warning("log_server_health: db_size read failed: %s", e)
    try:
        with open("/sys/class/thermal/thermal_zone0/temp") as f:
            cpu_temp = round(int(f.read().strip()) / 1000, 1)
    except Exception as e:
        log.debug("log_server_health: cpu_temp unavailable: %s", e)
    conn = get_conn()
    conn.execute(
        "INSERT INTO server_health_log (disk_pct, db_size_mb, cpu_temp_c) VALUES (?,?,?)",
        (disk_pct, db_size, cpu_temp),
    )
    conn.commit()
    conn.close()


def get_server_health_history(hours: int = 24) -> list[dict]:
    """Time-series of server health metrics. Downsamples to hourly for >72h."""
    conn = get_conn()
    cutoff = f"-{hours} hours"
    if hours > 72:
        rows = conn.execute(
            "SELECT strftime('%Y-%m-%dT%H:00:00',ts) as ts, "
            "ROUND(AVG(disk_pct),2) as disk_pct, ROUND(AVG(db_size_mb),3) as db_size_mb, "
            "ROUND(AVG(cpu_temp_c),1) as cpu_temp_c "
            "FROM server_health_log WHERE ts >= datetime('now','localtime', ?) "
            "GROUP BY strftime('%Y-%m-%dT%H',ts) ORDER BY ts",
            (cutoff,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT ts, disk_pct, db_size_mb, cpu_temp_c "
            "FROM server_health_log WHERE ts >= datetime('now','localtime', ?) ORDER BY ts",
            (cutoff,),
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_server_health() -> dict:
    """Server-side health: disk space, DB size, CPU temp, table row counts."""
    import shutil
    result = {}
    # Disk space
    try:
        usage = shutil.disk_usage(os.path.dirname(DB_PATH))
        result["disk_total_gb"] = round(usage.total / (1024**3), 1)
        result["disk_used_gb"] = round(usage.used / (1024**3), 1)
        result["disk_free_gb"] = round(usage.free / (1024**3), 1)
        result["disk_pct"] = round(usage.used / usage.total * 100, 1)
    except Exception as e:
        log.warning("get_server_health: disk_usage failed: %s", e)
    # DB file size
    try:
        result["db_size_mb"] = round(os.path.getsize(DB_PATH) / (1024**2), 2)
        wal = DB_PATH + "-wal"
        if os.path.exists(wal):
            result["db_wal_mb"] = round(os.path.getsize(wal) / (1024**2), 2)
    except Exception as e:
        log.warning("get_server_health: db_size read failed: %s", e)
    # Pi CPU temp (Linux thermal zone)
    try:
        with open("/sys/class/thermal/thermal_zone0/temp") as f:
            result["cpu_temp_c"] = round(int(f.read().strip()) / 1000, 1)
    except Exception as e:
        log.debug("get_server_health: cpu_temp unavailable: %s", e)
    # Table row counts
    conn = get_conn()
    counts = {}
    for tbl in ["sensor_log", "weather_log", "watering_event", "skip_event",
                 "system_health", "connectivity_log", "cycle_summary", "daily_summary"]:
        try:
            row = conn.execute(f"SELECT COUNT(*) as n FROM {tbl}").fetchone()
            counts[tbl] = row["n"]
        except Exception as e:
            log.warning("get_server_health: COUNT(%s) failed: %s", tbl, e)
            counts[tbl] = 0
    result["table_rows"] = counts
    # Rows added today
    today_counts = {}
    for tbl in ["sensor_log", "weather_log", "system_health", "connectivity_log"]:
        try:
            row = conn.execute(
                f"SELECT COUNT(*) as n FROM {tbl} WHERE ts >= date('now','localtime')"
            ).fetchone()
            today_counts[tbl] = row["n"]
        except Exception as e:
            log.warning("get_server_health: today-count(%s) failed: %s", tbl, e)
            today_counts[tbl] = 0
    result["rows_today"] = today_counts
    conn.close()
    return result


def get_sensor_gaps(zone_id: int = 0, hours: int = 24) -> list[dict]:
    """Find gaps in sensor readings where interval exceeds 2x expected poll rate."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT ts FROM sensor_log WHERE zone_id = ? "
        "AND ts >= datetime('now','localtime', ?) ORDER BY ts",
        (zone_id, f"-{hours} hours"),
    ).fetchall()
    conn.close()
    if len(rows) < 2:
        return []
    gaps = []
    for i in range(1, len(rows)):
        t0 = datetime.fromisoformat(rows[i-1]["ts"])
        t1 = datetime.fromisoformat(rows[i]["ts"])
        delta = (t1 - t0).total_seconds()
        if delta > 600:  # >10 minutes = gap (default poll is ~5 min)
            gaps.append({
                "start": rows[i-1]["ts"],
                "end": rows[i]["ts"],
                "gap_sec": int(delta),
                "gap_min": round(delta / 60, 1),
            })
    return gaps


# ── Forecast snapshot helpers ──

def save_forecast_snapshot(forecast_date: str, zone_id: int, zone_name: str,
                           balance_mm: float, taw_mm: float, mad_mm: float,
                           etc_mm: float, et0_mm: float,
                           rain_forecast_mm: float,
                           days_until_water: float | None,
                           predicted_date: str | None,
                           predicted_skip: bool = False,
                           skip_reason: str | None = None):
    """Record a daily forecast prediction for one zone."""
    conn = get_conn()
    conn.execute(
        "INSERT INTO forecast_snapshot "
        "(forecast_date, zone_id, zone_name, balance_mm, taw_mm, mad_mm, "
        "etc_mm, et0_mm, rain_forecast_mm, days_until_water, predicted_date, "
        "predicted_skip, skip_reason) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(forecast_date, zone_id) DO UPDATE SET "
        "zone_name=excluded.zone_name, balance_mm=excluded.balance_mm, "
        "taw_mm=excluded.taw_mm, mad_mm=excluded.mad_mm, "
        "etc_mm=excluded.etc_mm, et0_mm=excluded.et0_mm, "
        "rain_forecast_mm=excluded.rain_forecast_mm, "
        "days_until_water=excluded.days_until_water, "
        "predicted_date=excluded.predicted_date, "
        "predicted_skip=excluded.predicted_skip, "
        "skip_reason=excluded.skip_reason",
        (forecast_date, zone_id, zone_name, round(balance_mm, 2),
         round(taw_mm, 2), round(mad_mm, 2), round(etc_mm, 3),
         round(et0_mm, 3), round(rain_forecast_mm, 2),
         round(days_until_water, 1) if days_until_water is not None else None,
         predicted_date, 1 if predicted_skip else 0, skip_reason),
    )
    conn.commit()
    conn.close()


def get_forecast_vs_actual(days: int = 30) -> list[dict]:
    """Join forecast snapshots with actual watering/skip events.

    For each forecast day + zone, returns:
    - The prediction (days_until_water, predicted_date, predicted_skip)
    - What actually happened (did it water? when? was it skipped? why?)
    - Accuracy metrics (prediction error in days, false skip, missed skip)
    """
    conn = get_conn()
    rows = conn.execute("""
        SELECT
            f.forecast_date,
            f.zone_id,
            f.zone_name,
            f.balance_mm,
            f.taw_mm,
            f.mad_mm,
            f.etc_mm,
            f.et0_mm,
            f.rain_forecast_mm,
            f.days_until_water AS predicted_days,
            f.predicted_date,
            f.predicted_skip,
            f.skip_reason AS predicted_skip_reason,
            -- Actual watering on this forecast date
            w.start_ts AS actual_water_ts,
            w.duration_sec AS actual_duration_sec,
            w.soil_before AS actual_soil_before,
            w.soil_after AS actual_soil_after,
            w.trigger_reason AS actual_trigger,
            w.est_gallons AS actual_gallons,
            -- Actual skip on this forecast date
            s.ts AS actual_skip_ts,
            s.reason AS actual_skip_reason,
            s.est_gallons_saved AS actual_gallons_saved
        FROM forecast_snapshot f
        LEFT JOIN (
            SELECT zone_id, date(start_ts) AS water_date,
                   MIN(start_ts) AS start_ts, SUM(duration_sec) AS duration_sec,
                   MIN(soil_before) AS soil_before, MAX(soil_after) AS soil_after,
                   GROUP_CONCAT(DISTINCT trigger_reason) AS trigger_reason,
                   SUM(est_gallons) AS est_gallons
            FROM watering_event
            WHERE start_ts >= date('now', 'localtime', ?)
              -- Forecast accuracy measures the ENGINE's auto-watering brain only.
              -- Exclude manual "Run Now" / hand-test runs (trigger_reason 'manual'
              -- or 'manual [orphaned_cleanup]') so they don't count as the engine
              -- watering when the forecast correctly predicted it wouldn't.
              AND trigger_reason NOT LIKE 'manual%'
            GROUP BY zone_id, date(start_ts)
        ) w ON f.zone_id = w.zone_id AND f.forecast_date = w.water_date
        LEFT JOIN (
            SELECT zone_id, date(ts) AS skip_date,
                   MIN(ts) AS ts,
                   GROUP_CONCAT(DISTINCT reason) AS reason,
                   SUM(est_gallons_saved) AS est_gallons_saved
            FROM skip_event
            WHERE ts >= date('now', 'localtime', ?)
            GROUP BY zone_id, date(skip_date)
        ) s ON f.zone_id = s.zone_id AND f.forecast_date = s.skip_date
        WHERE f.forecast_date >= date('now', 'localtime', ?)
        ORDER BY f.forecast_date DESC, f.zone_id
    """, (f"-{days} days", f"-{days} days", f"-{days} days")).fetchall()
    conn.close()

    result = []
    for r in rows:
        d = dict(r)
        # Compute accuracy metrics
        actually_watered = d["actual_water_ts"] is not None
        actually_skipped = d["actual_skip_ts"] is not None
        predicted_skip = bool(d["predicted_skip"])

        d["actually_watered"] = actually_watered
        d["actually_skipped"] = actually_skipped

        # Prediction accuracy
        if d["predicted_days"] is not None and d["predicted_days"] <= 0:
            d["predicted_would_water"] = True
        else:
            d["predicted_would_water"] = False

        # False skip: predicted skip but engine actually watered
        d["false_skip"] = predicted_skip and actually_watered
        # Missed skip: predicted watering but engine actually skipped (and didn't water)
        d["missed_skip"] = d["predicted_would_water"] and actually_skipped and not actually_watered

        # Outcome label. A zone can log BOTH a water and a skip on the same day
        # (different cycles); watering is the zone's real disposition, so it takes
        # precedence — this avoids the meaningless "other" bucket the old logic
        # produced whenever both events were present.
        if actually_watered:
            if predicted_skip:
                d["outcome"] = "false_skip"      # predicted skip, but it watered
            elif d["predicted_would_water"]:
                d["outcome"] = "correct_water"    # predicted to water today, did
            else:
                d["outcome"] = "early_water"      # watered sooner than predicted (model ran wet)
        elif actually_skipped:
            if predicted_skip or not d["predicted_would_water"]:
                d["outcome"] = "correct_skip"     # predicted skip OR not-today, and it didn't water
            else:
                d["outcome"] = "missed_skip"      # predicted water today, engine skipped
        else:
            d["outcome"] = "no_event"             # predicted future water, nothing today — fine

        # Only completed auto-engine decisions are comparable. Manual-mode
        # snapshots and days with no decision remain available as history, but
        # must not inflate the accuracy denominator.
        d["scored"] = (
            d["predicted_skip_reason"] != "manual_mode"
            and d["outcome"] != "no_event"
        )

        result.append(d)

    return result


def get_forecast_accuracy_summary(days: int = 30,
                                  excluded_zone_ids: set[int] | None = None) -> dict:
    """Aggregate accuracy stats over the last N days."""
    rows = get_forecast_vs_actual(days)
    if excluded_zone_ids:
        rows = [r for r in rows if r["zone_id"] not in excluded_zone_ids]
    rows = [r for r in rows if r.get("scored")]
    total = len(rows)
    if total == 0:
        return {"total": 0, "accuracy_pct": None, "message": "No forecast data yet"}

    correct = sum(1 for r in rows if r["outcome"] in ("correct_water", "correct_skip"))
    false_skips = sum(1 for r in rows if r["outcome"] == "false_skip")
    missed_skips = sum(1 for r in rows if r["outcome"] == "missed_skip")
    early_waters = sum(1 for r in rows if r["outcome"] == "early_water")
    waters = sum(1 for r in rows if r["actually_watered"])
    skips = sum(1 for r in rows if r["actually_skipped"])

    return {
        "total": total,
        "correct": correct,
        "accuracy_pct": round(correct / total * 100, 1) if total > 0 else None,
        "false_skips": false_skips,
        "missed_skips": missed_skips,
        "early_waters": early_waters,
        "total_waterings": waters,
        "total_skips": skips,
        "days": days,
    }
