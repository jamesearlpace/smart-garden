"""Flow monitor — per-zone GPM estimation, leak & anomaly detection.

Correlates the whole-house water-meter reading (from the ESP32-CAM OCR pipeline,
``MeterReader.last_good``) with which sprinkler zone the controller has ON, to:

  1. ESTIMATE each zone's real gallons-per-minute from actual metered flow, and
     keep that estimate fresh over time (recency-weighted, so adding drip
     emitters that raise a zone's GPM is tracked, while stable sprinkler zones
     stay steady).
  2. DETECT problems:
       - unexplained flow  — water moving while NO zone is on (leak, a tap left
         running, a hose left on, or a burst pipe). Severity scales with GPM.
       - zone overrun      — a zone has been ON longer than its allowed runtime.
       - high flow         — sustained big consumption with no zone (urgent).
  3. LOG everything raw (every sample: reading, delta, gpm, active zones, how it
     was classified) so the estimates can be audited and troubleshot later.

Design notes
------------
* ISOLATED like water_cost.py: this module owns its own tables and never writes
  cam_ocr / cam routes / the meter lock. It only READS the values passed in.
* The headline per-zone estimate is an EWMA updated once per single-zone "run
  segment" using that segment's MEDIAN instantaneous GPM (robust to OCR noise),
  so a few jittery frames can't swing the estimate. Raw run records are kept for
  a median cross-check and for troubleshooting.
* "A zone is really running" == the meter shows consumption AND the controller
  says that zone is ON. Consumption with NO zone on is the anomaly signal.

Units: meter register is ft³ (cf). 1 ft³ = 7.48052 US gal. GPM uses gallons.
"""

from __future__ import annotations

import json
import logging
import statistics
import threading
import time
from datetime import datetime

import database as db

log = logging.getLogger("smart-garden.flow_monitor")

GAL_PER_CF = 7.48052

# --- Tunables (all overridable via config["flow_monitor"]) ------------------
DEFAULTS = {
    "sample_interval_s": 15,      # how often the background sampler runs
    "max_gap_s": 90,              # ignore a delta spanning a bigger blind gap
    "max_gpm": 25.0,              # physical ceiling; faster = bad data, drop it
    "idle_gpm": 0.08,             # below this = "no flow" (meter/OCR noise floor)
    "ewma_alpha": 0.30,           # recency weight for the zone GPM estimate
    "run_min_samples": 2,         # samples needed to trust a run-segment median
    # Leak / anomaly thresholds
    "leak_min_gpm": 0.10,         # unexplained flow at/above this is suspicious
    "leak_confirm_s": 120,        # must persist this long before we call it a leak
    "highflow_gpm": 2.0,          # unexplained flow at/above this = urgent
    "overrun_factor": 1.25,       # zone ON longer than max_runtime*this = overrun
    "event_idle_clear_s": 60,     # flow idle this long closes an open flow event
}


def _cfg(config, key):
    fm = (config or {}).get("flow_monitor", {}) if config else {}
    return fm.get(key, DEFAULTS[key])


# ---------------------------------------------------------------------------
#  Schema (own tables — created idempotently, never drops anything)
# ---------------------------------------------------------------------------
def ensure_schema() -> None:
    conn = db.get_conn()
    try:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS flow_sample ("
            "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "  ts TEXT NOT NULL,"            # ISO local
            "  reading_cf REAL,"            # whole-house register, ft3
            "  prev_cf REAL,"
            "  delta_cf REAL,"             # cf since previous sample (>=0)
            "  interval_s REAL,"
            "  gpm REAL,"                  # gallons/min over this interval
            "  active_zones TEXT,"         # csv of zone ids ON, '' if none
            "  state TEXT,"               # 'idle'|'zone'|'multi'|'unexplained'|'gap'
            "  note TEXT"
            ")"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS ix_flow_sample_ts ON flow_sample(ts)")
        conn.execute(
            "CREATE TABLE IF NOT EXISTS zone_flow_est ("
            "  zone_id INTEGER PRIMARY KEY,"
            "  ewma_gpm REAL,"            # headline recency-weighted estimate
            "  median_gpm REAL,"         # median of recent run segments (stable)
            "  last_run_gpm REAL,"
            "  n_runs INTEGER DEFAULT 0,"
            "  n_samples INTEGER DEFAULT 0,"
            "  recent_json TEXT,"         # last N run-median gpm values
            "  last_updated TEXT"
            ")"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS flow_event ("
            "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "  kind TEXT NOT NULL,"       # 'leak'|'highflow'|'overrun'|'unexplained'
            "  zone_id INTEGER,"          # for overrun; NULL for leaks
            "  start_ts TEXT NOT NULL,"
            "  end_ts TEXT,"
            "  gallons REAL DEFAULT 0,"
            "  peak_gpm REAL DEFAULT 0,"
            "  severity TEXT,"            # 'info'|'warning'|'urgent'
            "  resolved INTEGER DEFAULT 0,"
            "  note TEXT"
            ")"
        )
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
#  Runtime state (in-memory; rebuilt cheaply on restart)
# ---------------------------------------------------------------------------
class _State:
    def __init__(self):
        self.prev_cf = None
        self.prev_ts = None
        # current single-zone run segment being measured
        self.run_zone = None
        self.run_gpms = []            # instantaneous gpm samples in this segment
        # zone -> epoch when it was first seen ON (for overrun timing)
        self.zone_on_since = {}
        # open anomaly event id (unexplained/leak/highflow), if any
        self.open_event_id = None
        self.open_event_start = None
        self.open_event_peak = 0.0
        self.open_event_gallons = 0.0
        self.last_unexplained_ts = None
        self.last_idle_ts = None
        # overrun events already notified this run, zone -> True
        self.overrun_notified = set()


_state = _State()
_lock = threading.Lock()


# ---------------------------------------------------------------------------
#  Notifications (ntfy.sh — same topic as the rest of the system)
# ---------------------------------------------------------------------------
def _notify(title, message, priority="high", tags="droplet"):
    try:
        import requests
        safe = title.encode("ascii", "ignore").decode("ascii").strip() or "Flow Alert"
        requests.post("https://ntfy.sh/smart-garden-james",
                      data=message.encode("utf-8"),
                      headers={"Title": safe, "Priority": priority, "Tags": tags},
                      timeout=10)
        log.info("flow alert: %s — %s", safe, message)
    except Exception as e:
        log.warning("notify failed: %s", e)


# ---------------------------------------------------------------------------
#  Zone estimate update (recency-weighted)
# ---------------------------------------------------------------------------
def _commit_run_segment(zone_id, gpms, config):
    """A single-zone run segment ended (or the zone changed). Fold its MEDIAN
    instantaneous GPM into that zone's recency-weighted estimate."""
    gpms = [g for g in gpms if g is not None and g > 0]
    if zone_id is None or len(gpms) < _cfg(config, "run_min_samples"):
        return
    run_gpm = statistics.median(gpms)
    alpha = _cfg(config, "ewma_alpha")
    conn = db.get_conn()
    try:
        row = conn.execute(
            "SELECT ewma_gpm, n_runs, n_samples, recent_json "
            "FROM zone_flow_est WHERE zone_id=?", (zone_id,)).fetchone()
        if row and row["ewma_gpm"] is not None:
            ewma = (1 - alpha) * row["ewma_gpm"] + alpha * run_gpm
            recent = []
            try:
                recent = json.loads(row["recent_json"] or "[]")
            except Exception:
                recent = []
            recent.append(round(run_gpm, 3))
            recent = recent[-40:]            # keep last 40 run medians
            n_runs = (row["n_runs"] or 0) + 1
            n_samples = (row["n_samples"] or 0) + len(gpms)
        else:
            ewma = run_gpm
            recent = [round(run_gpm, 3)]
            n_runs = 1
            n_samples = len(gpms)
        median_gpm = statistics.median(recent) if recent else run_gpm
        conn.execute(
            "INSERT INTO zone_flow_est(zone_id, ewma_gpm, median_gpm, "
            "last_run_gpm, n_runs, n_samples, recent_json, last_updated) "
            "VALUES(?,?,?,?,?,?,?,?) "
            "ON CONFLICT(zone_id) DO UPDATE SET ewma_gpm=excluded.ewma_gpm, "
            "median_gpm=excluded.median_gpm, last_run_gpm=excluded.last_run_gpm, "
            "n_runs=excluded.n_runs, n_samples=excluded.n_samples, "
            "recent_json=excluded.recent_json, last_updated=excluded.last_updated",
            (zone_id, round(ewma, 3), round(median_gpm, 3), round(run_gpm, 3),
             n_runs, n_samples, json.dumps(recent),
             datetime.now().isoformat(timespec="seconds")))
        conn.commit()
        log.info("zone %s GPM est: run=%.2f ewma=%.2f median=%.2f (n_runs=%d)",
                 zone_id, run_gpm, ewma, median_gpm, n_runs)
    finally:
        conn.close()


def _zone_name(config, zone_id):
    for z in (config or {}).get("zones", []):
        if z.get("id") == zone_id:
            return z.get("name", f"Zone {zone_id + 1}")
    return f"Zone {zone_id + 1}"


def _zone_label(config, zone_id):
    return f"Zone {zone_id + 1} - {_zone_name(config, zone_id)}"


def _zone_max_runtime_min(config, zone_id):
    for z in (config or {}).get("zones", []):
        if z.get("id") == zone_id:
            return z.get("max_runtime_min")
    return None


# ---------------------------------------------------------------------------
#  Anomaly events
# ---------------------------------------------------------------------------
def _open_or_extend_event(kind, gpm, gallons, severity, note, config):
    """Open a new anomaly event or extend the currently-open one."""
    now_iso = datetime.now().isoformat(timespec="seconds")
    conn = db.get_conn()
    try:
        if _state.open_event_id is None:
            cur = conn.execute(
                "INSERT INTO flow_event(kind, start_ts, peak_gpm, gallons, "
                "severity, note) VALUES(?,?,?,?,?,?)",
                (kind, now_iso, round(gpm, 3), round(gallons, 4), severity, note))
            conn.commit()
            _state.open_event_id = cur.lastrowid
            _state.open_event_start = time.time()
            _state.open_event_peak = gpm
            _state.open_event_gallons = gallons
        else:
            _state.open_event_peak = max(_state.open_event_peak, gpm)
            _state.open_event_gallons += gallons
            conn.execute(
                "UPDATE flow_event SET peak_gpm=?, gallons=?, severity=?, "
                "kind=?, note=? WHERE id=?",
                (round(_state.open_event_peak, 3),
                 round(_state.open_event_gallons, 4), severity, kind, note,
                 _state.open_event_id))
            conn.commit()
    finally:
        conn.close()


def _close_open_event():
    if _state.open_event_id is None:
        return
    conn = db.get_conn()
    try:
        conn.execute(
            "UPDATE flow_event SET end_ts=?, resolved=1 WHERE id=?",
            (datetime.now().isoformat(timespec="seconds"), _state.open_event_id))
        conn.commit()
    finally:
        conn.close()
    _state.open_event_id = None
    _state.open_event_start = None
    _state.open_event_peak = 0.0
    _state.open_event_gallons = 0.0


# ---------------------------------------------------------------------------
#  Main entry — record one sample
# ---------------------------------------------------------------------------
def record(reading_cf, active_zones, config, ts=None):
    """Process one meter sample with the current active-zone set.

    reading_cf   : whole-house register in ft3 (meter_reader.last_good / 1000)
    active_zones : list[int] of zone ids the controller currently has ON
    config       : the server config dict (zones, flow_monitor tunables)
    """
    if reading_cf is None:
        return
    now = ts or time.time()
    active = sorted(int(z) for z in (active_zones or []))
    with _lock:
        prev_cf, prev_ts = _state.prev_cf, _state.prev_ts
        _state.prev_cf, _state.prev_ts = reading_cf, now

        # Overrun timing: track when each active zone first turned ON.
        for z in active:
            _state.zone_on_since.setdefault(z, now)
        for z in list(_state.zone_on_since):
            if z not in active:
                _state.zone_on_since.pop(z, None)
                _state.overrun_notified.discard(z)

        # First sample after start / restart — nothing to diff yet.
        if prev_cf is None or prev_ts is None:
            return

        interval = now - prev_ts
        if interval <= 0:
            return

        delta_cf = reading_cf - prev_cf
        max_gap = _cfg(config, "max_gap_s")
        state = ""
        note = ""
        gpm = None

        # Reject impossible/garbage deltas and over-long gaps (don't attribute).
        if interval > max_gap:
            state, note = "gap", f"blind gap {interval:.0f}s"
        elif delta_cf < -0.002:
            state, note = "gap", "register went down (bad read)"
        else:
            d = max(0.0, delta_cf)
            gpm = (d * GAL_PER_CF) / (interval / 60.0)
            if gpm > _cfg(config, "max_gpm"):
                state, note = "gap", f"gpm {gpm:.1f} > ceiling"
                gpm = None
            else:
                _classify(active, gpm, d, interval, config)
                state = _last_state
                note = _last_note

        _insert_sample(now, reading_cf, prev_cf, delta_cf, interval, gpm,
                       active, state, note)
        # Overrun is time-based, independent of flow — check every sample.
        _check_overrun(active, now, config)


# module-level scratch for classify -> record handoff
_last_state = ""
_last_note = ""


def _classify(active, gpm, delta_cf, interval, config):
    """Decide what this flow sample means and update estimates / events."""
    global _last_state, _last_note
    idle = _cfg(config, "idle_gpm")
    flowing = gpm is not None and gpm >= idle

    if not flowing:
        # No meaningful flow. Close any single-zone run segment and clear leaks.
        _last_state, _last_note = "idle", ""
        if _state.run_zone is not None:
            _commit_run_segment(_state.run_zone, _state.run_gpms, config)
            _state.run_zone, _state.run_gpms = None, []
        _state.last_idle_ts = time.time()
        # If flow has been idle long enough, close an open anomaly event.
        _close_open_event()
        return

    if len(active) == 1:
        # Single zone running with flow → attribute to that zone.
        z = active[0]
        if _state.run_zone != z:
            # Zone changed — commit the previous segment, start a new one.
            if _state.run_zone is not None:
                _commit_run_segment(_state.run_zone, _state.run_gpms, config)
            _state.run_zone, _state.run_gpms = z, []
        _state.run_gpms.append(gpm)
        _last_state, _last_note = "zone", f"zone {z} @ {gpm:.2f} gpm"
        # A real zone run also means flow IS explained — close leak events.
        _close_open_event()
        return

    if len(active) >= 2:
        # Multiple zones (rare with this controller) — can't attribute cleanly.
        if _state.run_zone is not None:
            _commit_run_segment(_state.run_zone, _state.run_gpms, config)
            _state.run_zone, _state.run_gpms = None, []
        _last_state, _last_note = "multi", f"{len(active)} zones @ {gpm:.2f} gpm"
        _close_open_event()
        return

    # active is empty BUT water is flowing → UNEXPLAINED. Leak / tap / burst.
    if _state.run_zone is not None:
        _commit_run_segment(_state.run_zone, _state.run_gpms, config)
        _state.run_zone, _state.run_gpms = None, []
    gallons = delta_cf * GAL_PER_CF
    _handle_unexplained(gpm, gallons, config)
    _last_state = "unexplained"
    _last_note = f"no zone, {gpm:.2f} gpm"


def _handle_unexplained(gpm, gallons, config):
    """Flow with no zone on — accumulate into a leak/highflow event and alert."""
    now = time.time()
    leak_min = _cfg(config, "leak_min_gpm")
    high = _cfg(config, "highflow_gpm")
    confirm_s = _cfg(config, "leak_confirm_s")
    if gpm < leak_min:
        return  # below suspicion floor

    if _state.last_unexplained_ts is None:
        _state.last_unexplained_ts = now

    # Big unexplained flow → urgent immediately (pipe break / hose / faucet).
    if gpm >= high:
        _open_or_extend_event("highflow", gpm, gallons, "urgent",
                              "High water flow with no sprinkler zone on", config)
        if _state.open_event_start and (now - _state.open_event_start) < 5:
            _notify("Water running — no zone on!",
                    f"{gpm:.1f} gal/min with NO sprinkler zone active. "
                    f"Possible burst pipe, hose, or faucet left on.",
                    priority="urgent", tags="rotating_light")
        return

    # Small sustained flow → confirm over time before calling it a leak.
    _open_or_extend_event("unexplained", gpm, gallons, "warning",
                          "Unexplained low flow (possible leak)", config)
    persisted = now - (_state.open_event_start or now)
    if persisted >= confirm_s and not _state.__dict__.get("_leak_notified"):
        _state.__dict__["_leak_notified"] = True
        _notify("Possible leak",
                f"Water has been flowing ~{gpm:.2f} gal/min for "
                f"{int(persisted/60)} min with no zone on. Check for a leak, "
                f"running toilet, or a tap left on.",
                priority="high", tags="droplet")


def _check_overrun(active, now, config):
    """Alert if a zone has been ON longer than its allowed runtime."""
    factor = _cfg(config, "overrun_factor")
    for z in active:
        started = _state.zone_on_since.get(z)
        if not started:
            continue
        max_min = _zone_max_runtime_min(config, z)
        if not max_min:
            continue
        on_min = (now - started) / 60.0
        if on_min > max_min * factor and z not in _state.overrun_notified:
            _state.overrun_notified.add(z)
            name = _zone_name(config, z)
            conn = db.get_conn()
            try:
                conn.execute(
                    "INSERT INTO flow_event(kind, zone_id, start_ts, peak_gpm, "
                    "severity, note) VALUES('overrun',?,?,0,'warning',?)",
                    (z, datetime.now().isoformat(timespec="seconds"),
                     f"{name} ON {on_min:.0f} min (max {max_min})"))
                conn.commit()
            finally:
                conn.close()
            _notify("Sprinkler running too long",
                    f"{name} has been ON for {on_min:.0f} min "
                    f"(limit {max_min} min). It may be stuck on.",
                    priority="high", tags="warning")
            # Reset leak-notified latch when a real run is happening.
            _state.__dict__["_leak_notified"] = False


def _insert_sample(now, reading_cf, prev_cf, delta_cf, interval, gpm, active,
                   state, note):
    conn = db.get_conn()
    try:
        conn.execute(
            "INSERT INTO flow_sample(ts, reading_cf, prev_cf, delta_cf, "
            "interval_s, gpm, active_zones, state, note) VALUES(?,?,?,?,?,?,?,?,?)",
            (datetime.fromtimestamp(now).isoformat(timespec="seconds"),
             round(reading_cf, 3), round(prev_cf, 3), round(delta_cf, 4),
             round(interval, 1), (round(gpm, 3) if gpm is not None else None),
             ",".join(str(z) for z in active), state, note))
        # Cheap retention: keep ~30 days of samples (every 15s ≈ 173k rows).
        conn.execute(
            "DELETE FROM flow_sample WHERE ts < datetime('now','localtime','-30 days')")
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
#  Reporting (for the UI / API)
# ---------------------------------------------------------------------------
def build_report(config, limit_samples=120):
    ensure_schema()
    conn = db.get_conn()
    try:
        zones = []
        for z in (config or {}).get("zones", []):
            zid = z.get("id")
            row = conn.execute(
                "SELECT ewma_gpm, median_gpm, last_run_gpm, n_runs, n_samples, "
                "recent_json, last_updated FROM zone_flow_est WHERE zone_id=?",
                (zid,)).fetchone()
            est = dict(row) if row else {}
            zones.append({
                "id": zid,
                "zone_number": zid + 1,
                "zone_label": _zone_label(config, zid),
                "name": z.get("name", f"Zone {zid + 1}"),
                "type": z.get("type"),
                "config_gpm": z.get("est_gpm"),
                "measured_gpm": est.get("ewma_gpm"),
                "median_gpm": est.get("median_gpm"),
                "last_run_gpm": est.get("last_run_gpm"),
                "n_runs": est.get("n_runs", 0),
                "n_samples": est.get("n_samples", 0),
                "recent": json.loads(est.get("recent_json") or "[]") if est else [],
                "last_updated": est.get("last_updated"),
            })
        samples = [dict(r) for r in conn.execute(
            "SELECT ts, reading_cf, delta_cf, interval_s, gpm, active_zones, "
            "state, note FROM flow_sample ORDER BY id DESC LIMIT ?",
            (limit_samples,)).fetchall()]
        events = [dict(r) for r in conn.execute(
            "SELECT id, kind, zone_id, start_ts, end_ts, gallons, peak_gpm, "
            "severity, resolved, note FROM flow_event "
            "ORDER BY id DESC LIMIT 50").fetchall()]
        open_events = [e for e in events if not e["resolved"]]
        return {
            "zones": zones,
            "samples": samples,
            "events": events,
            "open_events": open_events,
            "now": datetime.now().isoformat(timespec="seconds"),
        }
    finally:
        conn.close()


# ---------------------------------------------------------------------------
#  Background sampler — call start() once from create_app()
# ---------------------------------------------------------------------------
def start(meter_reader, status_summary_fn, config, reading_cf_fn=None):
    """Spawn the background sampler thread. ``status_summary_fn`` returns the
    dict with 'active_zones'. ``reading_cf_fn`` may supply the canonical
    register; otherwise ``meter_reader.last_good`` is used."""
    ensure_schema()
    interval = _cfg(config, "sample_interval_s")

    def _loop():
        log.info("flow_monitor sampler started (every %ss)", interval)
        while True:
            try:
                reading_cf = None
                if reading_cf_fn:
                    try:
                        reading_cf = reading_cf_fn()
                    except Exception:
                        reading_cf = None
                if reading_cf is None:
                    lg = getattr(meter_reader, "last_good", None)
                    reading_cf = (lg / 1000.0) if lg else None
                try:
                    summ = status_summary_fn() or {}
                    active = summ.get("active_zones", []) or []
                except Exception:
                    active = []
                record(reading_cf, active, config)
            except Exception as e:
                log.debug("flow sample failed: %s", e)
            time.sleep(interval)

    threading.Thread(target=_loop, daemon=True, name="flow-monitor").start()
