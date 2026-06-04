"""Irrigation decision engine for Smart Garden Server.

Determines whether to water, skip, or delay each zone based on:
- Soil moisture sensor readings (reality)
- ETΓéÇ ├ù Kc water demand (prediction)
- Soil water balance / checkbook method (Phase 3)
- Weather forecast (rain skip, wind skip, freeze protection)
- Billing tier awareness (budget tightening)
- Cycle-soak scheduling for sprinkler zones on clay soil
"""

import json
import logging
import os
import threading
import time
from datetime import datetime, timedelta, date

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

import database as db
from weather import WeatherClient
from billing import BillingCalculator

log = logging.getLogger("smart-garden.irrigation")

# Valve commands keep a longer timeout because missing an open/close command is
# worse than a slow dashboard update. Status polling is intentionally shorter:
# when the ESP32 is offline, these calls happen from scheduled jobs and should
# fail quickly so the API stays responsive.
ESP32_TIMEOUT = 15
ESP32_MANUAL_TIMEOUT = 4
ESP32_STATUS_TIMEOUT = 5

# After this many consecutive status failures, escalate WARNING ΓåÆ ERROR.
# Single transient failures are noise; sustained failures are alerts.
_FAILURE_ESCALATE_AT = 3

# Cache /api/status responses to reduce TCP connection load on the ESP32.
# Root cause: lwIP TIME_WAIT pool on the chip is only 5 sockets with 60s
# timeout. Sustained polling fills it and the chip starts RST'ing new SYNs
# (smart-garden-server#10, proven via pcap 2026-04-21).
#
# Math: TIME_WAIT holds a PCB for 60s. With 5 PCBs total, the chip can
# safely accept up to 5 connections per 60s window = 1 every 12s.
# A 30s TTL gives us 2 dashboard hits/min + 1 decision-cycle hit/min = 3/min
# peak occupancy, well under the 5-PCB ceiling. Browsers poll the dashboard
# every 30s anyway, so a 30s server cache adds zero perceived latency.
_STATUS_CACHE_TTL_SEC = 30
_STATUS_FAILURE_BACKOFF_SEC = 30

# Badge-state debounce: how many consecutive successes/failures before the
# cached "online" flag flips. Avoids dashboard flapping when a single poll
# happens to land in a TIME_WAIT window OR a WiFi reconnect cycle.
# Asymmetric: instant flip back to ONLINE is fine (good news loud);
# offline requires sustained failure (~5 polls = 2.5 min @ 30s cadence)
# because the chip's RSSI at the wall mount (-80 dBm) produces brief WiFi
# reconnect windows. Sprinklers still work during these windows because
# the decision cycle uses force_fresh=True and the chip recovers within ~1
# WiFi reconnect cycle (15-30s typical).
_DEBOUNCE_OFFLINE_AFTER = 5  # require 5 fails in a row (~2.5 min) before badge goes red
_DEBOUNCE_ONLINE_AFTER = 1   # 1 good poll is enough to flip back green


def _make_esp32_session(retries: int = 3) -> requests.Session:
    """requests.Session with connection pooling + tunable retry.

    Reuses TCP connections (ESP32 WebServer is happier with keep-alive).
    Status-only callers should use retries=0 because each retry burst opens
    additional sockets on the chip, which accelerates lwIP TIME_WAIT pool
    exhaustion (the very thing we're trying to avoid). Valve commands keep
    the default 3-retry policy because they're idempotent-with-state-check
    and we'd rather try harder than miss an open/close.
    """
    s = requests.Session()
    retry = Retry(
        total=retries,
        backoff_factor=0.5,                   # 0.5s, 1s, 2s between retries
        status_forcelist=[502, 503, 504],
        allowed_methods=["GET", "POST"],
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=2, pool_maxsize=4)
    s.mount("http://", adapter)
    s.mount("https://", adapter)
    return s


class IrrigationEngine:

    def __init__(self, config: dict, weather: WeatherClient,
                 billing: BillingCalculator):
        self.config = config
        self.zones = {z["id"]: z for z in config["zones"]}
        self.esp32_url = config["esp32"]["url"]
        self.valve_timeout = config["esp32"]["valve_timeout_sec"]
        # Shared secret for /api/reboot ΓÇö must match firmware src/config.h
        # API_REBOOT_TOKEN. Override via SMART_GARDEN_REBOOT_TOKEN env var.
        self.reboot_token = os.environ.get(
            "SMART_GARDEN_REBOOT_TOKEN",
            config["esp32"].get("reboot_token", ""),
        )
        self.skip_rules = config["skip_rules"]
        self.window = config["watering_window"]
        self.weather = weather
        self.billing = billing

        # Active watering state: zone_id → {event_id, start_time}
        self._active = {}

        # Cycle health tracking (for alerting on stuck/crashing cycles)
        self._last_successful_cycle = None

        # Weather adjustment config (Zimmerman method)
        wa = config.get("weather_adjustment", {})
        self._wa_base_temp = wa.get("baseline_temp_f", 60.0)
        self._wa_base_hum = wa.get("baseline_humidity_pct", 50.0)
        self._wa_temp_factor = wa.get("temp_factor", 4.0)
        self._wa_rain_factor = wa.get("rain_factor", -200.0)
        self._wa_min_scale = wa.get("min_scale_pct", 0)
        self._wa_max_scale = wa.get("max_scale_pct", 200)

        # Soil water balance config (checkbook method)
        soil_cfg = config.get("soil", {})
        self._awc = soil_cfg.get("awc_in_per_in", 0.15)
        self._default_root_depth = soil_cfg.get("default_root_depth_in", 6)
        self._default_mad_pct = soil_cfg.get("default_mad_pct", 50)

        # Two HTTP sessions:
        #   _esp32_status: retries=0 ΓÇö fail-fast on /api/status to avoid
        #     bursts that exhaust the chip's lwIP TIME_WAIT pool (#10).
        #     Resilience comes from the cache + debounce, not retry storms.
        #   _esp32_cmd:    retries=3 ΓÇö valve open/close are too important
        #     to drop on a single transient error.
        #   _esp32_manual: retries=0 ΓÇö dashboard button clicks must return
        #     quickly when the controller is down so health checks still get
        #     a free Waitress worker.
        self._esp32_status = _make_esp32_session(retries=0)
        self._esp32 = _make_esp32_session(retries=3)
        self._esp32_manual = _make_esp32_session(retries=0)
        self._consecutive_failures = 0

        # Status cache + badge debounce state (see _STATUS_CACHE_TTL_SEC).
        self._status_cache = None       # last successful response payload
        self._status_cache_ts = 0.0     # epoch when cache was filled
        self._status_failure_ts = 0.0   # epoch of most recent failed status poll
        self._status_lock = threading.Lock()
        self._badge_online = False      # debounced "is the chip reachable"
        self._consecutive_successes = 0

        # Recover from any watering_event rows left open by a prior crash
        # or restart — they'd otherwise sit forever with end_ts=NULL,
        # falsely marking the zone as actively watering and never crediting
        # the soil balance. See issue #2.
        try:
            orphans = db.close_orphaned_watering_events()
            for o in orphans:
                log.warning(
                    "Cleaned orphaned watering event %d (%s, started %s, reason=%s)",
                    o["id"], self._zone_label(o["zone_id"]), o["start_ts"], o.get("trigger_reason"),
                )
        except Exception as e:
            log.error("Failed to clean orphaned watering events: %s", e)

    def _zone_label(self, zone_id):
        # Match dashboard's 1-indexed display so logs and UI agree (issue #6).
        name = self.zones.get(zone_id, {}).get("name", "?")
        return f"Zone {zone_id + 1} ({name})"

    # ΓöÇΓöÇ ESP32 communication ΓöÇΓöÇ

    def get_esp32_status(self, force_fresh: bool = False) -> dict | None:
        """Return latest ESP32 /api/status payload, with short-TTL caching.

        The cache exists to limit how often we open new TCP connections to
        the chip. See _STATUS_CACHE_TTL_SEC for the why. Pass force_fresh=True
        from the irrigation cycle / safety check (which need a true reading)
        to bypass the cache; dashboard polls and other read-only callers
        should leave it False.
        """
        now = time.time()
        if (not force_fresh and self._status_cache is not None
                and (now - self._status_cache_ts) < _STATUS_CACHE_TTL_SEC):
            return self._status_cache
        if (not force_fresh and self._status_failure_ts
                and (now - self._status_failure_ts) < _STATUS_FAILURE_BACKOFF_SEC):
            return self._status_cache
        if not self._status_lock.acquire(blocking=False):
            return self._status_cache

        t0 = now
        try:
            resp = self._esp32_status.get(f"{self.esp32_url}/api/status",
                                          timeout=ESP32_STATUS_TIMEOUT)
            resp.raise_for_status()
            data = resp.json()

            latency = int((time.time() - t0) * 1000)
            system = data.get("system", {})
            db.log_connectivity(
                success=True,
                latency_ms=latency,
                boot_count=system.get("bootCount"),
                uptime_sec=system.get("uptimeSec"),
            )
            if self._consecutive_failures >= _FAILURE_ESCALATE_AT:
                log.info("ESP32 recovered after %d consecutive failures",
                         self._consecutive_failures)
            self._consecutive_failures = 0
            self._consecutive_successes += 1
            self._status_failure_ts = 0.0
            if (not self._badge_online
                    and self._consecutive_successes >= _DEBOUNCE_ONLINE_AFTER):
                self._badge_online = True
            # Refresh cache on success only; we never want to cache a None.
            self._status_cache = data
            self._status_cache_ts = time.time()
            return data
        except requests.RequestException as e:
            latency = int((time.time() - t0) * 1000)
            db.log_connectivity(
                success=False,
                latency_ms=latency,
                error_message=str(e)[:200],
            )
            self._status_failure_ts = time.time()
            self._consecutive_failures += 1
            self._consecutive_successes = 0
            if (self._badge_online
                    and self._consecutive_failures >= _DEBOUNCE_OFFLINE_AFTER):
                self._badge_online = False
            # Single/few failures = transient (WARNING). Sustained = real (ERROR).
            if self._consecutive_failures >= _FAILURE_ESCALATE_AT:
                log.error("ESP32 status failed (%d consecutive): %s",
                          self._consecutive_failures, e)
            else:
                log.warning("ESP32 status failed (attempt %d/%d): %s",
                            self._consecutive_failures, _FAILURE_ESCALATE_AT, e)
            return None
        finally:
            self._status_lock.release()

    def get_cached_esp32_status(self) -> dict | None:
        """Return the last successful ESP32 status without network I/O."""
        return self._status_cache

    def is_esp32_online(self) -> bool:
        """Debounced reachability flag for the dashboard badge.

        True only after a consecutive success; False only after
        _DEBOUNCE_OFFLINE_AFTER consecutive failures. Prevents the badge
        from flickering on single transient failures while still going red
        promptly during a real outage.
        """
        return self._badge_online

    def open_valve(self, zone_id: int, timeout: int | float = ESP32_TIMEOUT,
                   retry: bool = True) -> bool:
        # HARDWARE LOCKOUT: only one valve open at a time. Before opening this
        # zone, preempt any other zone that's currently tracked as running.
        # All open paths go through here (scheduled run_cycle, /api/run manual,
        # /api/valve raw open), so this is the chokepoint that makes parallel
        # operation physically impossible. See
        # https://github.com/jamesearlpace/smart-garden-server/issues/1
        preempted = [z for z in list(self._active.keys()) if z != zone_id]
        if preempted:
            log.warning("Preemption: closing %s before opening %s",
                        ", ".join(self._zone_label(z) for z in preempted),
                        self._zone_label(zone_id))
            for other in preempted:
                try:
                    self.stop_zone_watering(other, 0)
                except Exception as e:
                    log.error("Failed to cleanly stop %s during preemption: %s",
                              self._zone_label(other), e)
                    # Hard fallback: raw close + drop from _active
                    self.close_valve(other, timeout=timeout, retry=retry)
                    self._active.pop(other, None)
            # Belt-and-suspenders: tell the ESP32 to close everything in case
            # an untracked valve is open (manual /api/valve open, drift, etc.).
            try:
                self.close_all(timeout=timeout, retry=retry)
                time.sleep(0.5)  # let latching relays settle
            except Exception as e:
                log.error("close_all during preemption failed: %s", e)

        try:
            session = self._esp32 if retry else self._esp32_manual
            resp = session.post(f"{self.esp32_url}/api/valve",
                                data={"id": zone_id, "action": "open"},
                                timeout=timeout)
            resp.raise_for_status()
            log.info("Opened %s", self._zone_label(zone_id))
            return True
        except Exception as e:
            log.error("Failed to open %s: %s", self._zone_label(zone_id), e)
            return False

    def close_valve(self, zone_id: int, timeout: int | float = ESP32_TIMEOUT,
                    retry: bool = True) -> bool:
        try:
            session = self._esp32 if retry else self._esp32_manual
            resp = session.post(f"{self.esp32_url}/api/valve",
                                data={"id": zone_id, "action": "close"},
                                timeout=timeout)
            resp.raise_for_status()
            log.info("Closed %s", self._zone_label(zone_id))
            return True
        except Exception as e:
            log.error("Failed to close %s: %s", self._zone_label(zone_id), e)
            return False

    def close_all(self, timeout: int | float = ESP32_TIMEOUT,
                  retry: bool = True) -> bool:
        try:
            session = self._esp32 if retry else self._esp32_manual
            resp = session.post(f"{self.esp32_url}/api/closeall",
                                timeout=timeout)
            resp.raise_for_status()
            log.warning("Emergency close all valves")
            return True
        except Exception as e:
            log.error("Failed to close all: %s", e)
            return False

    def reboot_esp32(self) -> tuple[bool, str]:
        """Trigger a token-protected remote reboot of the ESP32.

        Returns (success, message). Useful when the chip is in a sticky bad
        state but still answering HTTP ΓÇö avoids a physical USB trip.
        """
        if not self.reboot_token:
            return False, "reboot_token not configured"
        try:
            resp = self._esp32.post(
                f"{self.esp32_url}/api/reboot",
                params={"token": self.reboot_token},
                timeout=ESP32_TIMEOUT,
            )
            if resp.status_code == 401:
                return False, "401: token rejected by firmware"
            resp.raise_for_status()
            log.warning("Remote reboot triggered (HTTP %d)", resp.status_code)
            return True, "reboot requested"
        except requests.RequestException as e:
            log.error("Remote reboot failed: %s", e)
            return False, str(e)[:200]

    # ΓöÇΓöÇ Decision logic ΓöÇΓöÇ

    def calculate_weather_scale(self, allow_weather_fetch: bool = True) -> dict:
        """Calculate Zimmerman-style weather adjustment factor.

        Returns dict with scale_pct (0-200) and component breakdowns.
        100 = baseline (water for normal duration).
        >100 = hotter/drier than normal, water longer.
        <100 = cooler/wetter, water less. 0 = skip entirely.
        """
        current_wx = self.weather.get_current(allow_fetch=allow_weather_fetch)
        rain_last_24h = self.weather.get_rain_last_24h(allow_fetch=allow_weather_fetch)

        temp_f = current_wx.get("temp_f") or self._wa_base_temp
        humidity = current_wx.get("humidity") or self._wa_base_hum

        # Humidity delta: lower humidity ΓåÆ more evaporation ΓåÆ water more
        humidity_delta = self._wa_base_hum - humidity

        # Temperature delta: higher temp ΓåÆ more evaporation ΓåÆ water more
        temp_delta = (temp_f - self._wa_base_temp) * self._wa_temp_factor

        # Rain delta: recent rain ΓåÆ less watering needed
        rain_delta = rain_last_24h * self._wa_rain_factor

        raw_scale = 100 + humidity_delta + temp_delta + rain_delta
        scale_pct = max(self._wa_min_scale,
                        min(self._wa_max_scale, int(round(raw_scale))))

        return {
            "scale_pct": scale_pct,
            "temp_f": temp_f,
            "humidity": humidity,
            "rain_last_24h_mm": rain_last_24h,
            "humidity_delta": round(humidity_delta, 1),
            "temp_delta": round(temp_delta, 1),
            "rain_delta": round(rain_delta, 1),
            "raw_scale": round(raw_scale, 1),
        }

    def is_in_watering_window(self, zone_id: int) -> bool:
        """Check if current time is within the allowed watering window."""
        now = datetime.now()
        current_time = now.strftime("%H:%M")

        # Morning window ΓÇö all zones
        if self.window["start"] <= current_time <= self.window["end"]:
            return True

        # Evening window ΓÇö drip zones only
        if zone_id in self.window.get("evening_zones", []):
            evening_start = self.window.get("evening_start", "20:00")
            evening_end = self.window.get("evening_end", "22:00")
            if evening_start <= current_time <= evening_end:
                return True

        return False

    def evaluate_zone(self, zone_id: int, soil_pct: float,
                      esp32_status: dict) -> dict:
        """Evaluate whether a zone should water, skip, or wait.

        Uses ET₀-based soil water balance model (not soil sensors).
        Waters when balance drops below MAD (Management Allowable Depletion).

        Returns dict with:
            action: 'water', 'skip', 'wait', 'close'
            reason: human-readable explanation
            details: dict of conditions at decision time
        """
        zone = self.zones[zone_id]
        season_idx = self.weather.get_season_index()

        # Dormant season ΓÇö skip everything
        if season_idx < 0:
            return self._decision("skip", zone_id, "Dormant season ΓÇö no irrigation",
                                  {})

        # Zone-level Manual/Automatic mode (default: automatic for backward compat).
        # Manual mode disables ALL auto-decision watering; only explicit `reason="manual"`
        # calls to start_zone_watering still run.
        if not zone.get("auto_mode", True):
            return self._decision("skip", zone_id,
                                  "Manual mode — auto-watering disabled for this zone",
                                  {"auto_mode": False})

        # Get weather conditions
        current_wx = self.weather.get_current()
        rain_forecast = self.weather.get_rain_forecast_24h()
        rain_last_24h = self.weather.get_rain_last_24h()
        et0 = self.weather.get_today_et0()
        kc = zone["kc"][season_idx]
        et_demand = et0 * kc

        conditions = {
            "soil_pct": soil_pct,
            "dry_trigger": zone["dry_trigger"],
            "wet_target": zone["wet_target"],
            "et0_mm": et0,
            "kc": kc,
            "et_demand_mm": et_demand,
            "temp_f": current_wx.get("temp_f"),
            "wind_mph": current_wx.get("wind_mph"),
            "humidity": current_wx.get("humidity"),
            "rain_forecast_mm": rain_forecast["total_mm"],
            "rain_forecast_prob": rain_forecast["max_probability"],
            "rain_last_24h_mm": rain_last_24h,
        }

        # Check if this zone is already being watered
        if zone_id in self._active:
            return self._evaluate_active_zone(zone_id, soil_pct, conditions)

        # ΓöÇΓöÇ SKIP CONDITIONS (ordered by impact) ΓöÇΓöÇ

        # 1. Water balance check (ET0-based, replaces soil sensor)
        balance = db.get_soil_balance(zone_id)
        balance_mm = balance["balance_mm"] if balance else None
        taw_mm = self.get_zone_taw_mm(zone_id)
        mad_mm = self.get_zone_mad_mm(zone_id)
        conditions["balance_mm"] = balance_mm
        conditions["taw_mm"] = taw_mm
        conditions["mad_mm"] = mad_mm

        if balance_mm is not None and balance_mm > mad_mm:
            return self._decision("skip", zone_id,
                                  f"Water balance {balance_mm:.1f}mm > MAD {mad_mm:.1f}mm — soil has enough water",
                                  conditions)

        # 2. Same-day watering guard — skip only if today's accumulated runtime is
        #    already a substantial fraction of the daily cap. Short manual test runs
        #    (e.g. 5 min spot-check) should NOT block the scheduled nighttime cycle.
        #    Threshold: 50% of max_runtime_min.
        max_runtime_min = zone.get("max_runtime_min", 24)
        skip_threshold_sec = max_runtime_min * 60 * 0.5
        conn = db.get_conn()
        today_total = conn.execute(
            "SELECT COALESCE(SUM(duration_sec), 0) as total_sec FROM watering_event "
            "WHERE zone_id = ? AND duration_sec > 60 "
            "AND date(start_ts) = date('now', 'localtime')",
            (zone_id,),
        ).fetchone()
        conn.close()
        total_sec_today = today_total["total_sec"] if today_total else 0
        if total_sec_today >= skip_threshold_sec:
            mins_today = total_sec_today / 60
            return self._decision("skip", zone_id,
                                  f"Already watered {mins_today:.1f} min today (>={skip_threshold_sec/60:.0f} min threshold) — waiting for 11 PM balance update",
                                  conditions)

        # 3. Significant rain in last 24h
        rules = self.skip_rules
        if rain_last_24h >= rules["recent_rain_mm"]:
            return self._decision("skip", zone_id,
                                  f"Recent rain: {rain_last_24h:.1f}mm in last 24h",
                                  conditions)

        # 4. Rain forecast
        if (rain_forecast["total_mm"] >= rules["rain_forecast_mm"]
                and rain_forecast["max_probability"] >= rules["rain_probability_pct"]):
            return self._decision("skip", zone_id,
                                  f"Rain forecast: {rain_forecast['total_mm']:.1f}mm "
                                  f"({rain_forecast['max_probability']}% prob) in next 24h",
                                  conditions)

        # 5. Freeze protection
        temp_f = current_wx.get("temp_f", 50)
        if temp_f is not None and temp_f < rules["freeze_temp_f"]:
            return self._decision("skip", zone_id,
                                  f"Freeze risk: {temp_f:.0f}┬░F < {rules['freeze_temp_f']}┬░F",
                                  conditions)

        # 6. Wind skip (sprinkler zones only)
        wind_mph = current_wx.get("wind_mph", 0)
        if (zone["type"] == "sprinkler" and wind_mph is not None
                and wind_mph > rules["wind_speed_mph"]):
            return self._decision("skip", zone_id,
                                  f"Wind {wind_mph:.0f} mph > {rules['wind_speed_mph']} mph (sprinkler zone)",
                                  conditions)

        # 7. Budget tightening ΓÇö late in billing cycle and in expensive tier
        budget = self.billing.should_tighten_budget()
        if budget["tighten"]:
            # Still water if soil is critically dry (< 50% of trigger)
            critical = mad_mm * 0.5 if balance_mm is not None else 0
            if balance_mm is not None and balance_mm > critical:
                return self._decision("skip", zone_id,
                                      f"Budget conservation: {budget['reason']}",
                                      conditions)

        # 8. Not in watering window
        if not self.is_in_watering_window(zone_id):
            return self._decision("wait", zone_id,
                                  "Outside watering window ΓÇö will water at next window",
                                  conditions)

        # ΓöÇΓöÇ WATER ΓöÇΓöÇ
        return self._decision("water", zone_id,
                              f"Water balance {balance_mm:.1f}mm <= MAD {mad_mm:.1f}mm ΓÇö watering",
                              conditions)

    def _evaluate_active_zone(self, zone_id: int, soil_pct: float,
                              conditions: dict) -> dict:
        """Check if an actively watering zone should stop."""
        zone = self.zones[zone_id]
        active = self._active[zone_id]
        elapsed = time.time() - active["start_time"]

        # Apply weather-adjusted runtime
        scale = active.get("weather_scale_pct", 100)
        adjusted_runtime_min = zone["max_runtime_min"] * scale / 100.0
        max_sec = adjusted_runtime_min * 60

        # Runtime-based stop (no soil sensor)

        # Stop if adjusted runtime exceeded
        if elapsed >= max_sec:
            return self._decision("close", zone_id,
                                  f"Adjusted runtime {adjusted_runtime_min:.0f}min reached "
                                  f"(base {zone['max_runtime_min']}min ├ù {scale}%)",
                                  conditions)

        # Stop if safety timeout
        if elapsed >= self.valve_timeout:
            return self._decision("close", zone_id,
                                  f"Safety timeout {self.valve_timeout}s reached",
                                  conditions)

        # Continue watering
        return {"action": "continue", "zone_id": zone_id,
                "reason": f"Watering in progress ({elapsed:.0f}s)", "details": conditions}

    def _decision(self, action: str, zone_id: int, reason: str,
                  conditions: dict) -> dict:
        return {"action": action, "zone_id": zone_id, "reason": reason,
                "details": conditions}

    # ΓöÇΓöÇ Execution ΓöÇΓöÇ

    def is_zone_installed(self, zone_id: int) -> bool:
        zone = self.zones.get(zone_id)
        return bool(zone and zone.get("installed", False))

    def start_zone_watering(self, zone_id: int, soil_before: float,
                            et_demand: float, reason: str = "soil_dry",
                            allow_weather_fetch: bool = True,
                            command_timeout: int | float = ESP32_TIMEOUT,
                            retry: bool = True) -> bool:
        """Open valve and track the watering event."""
        if not self.is_zone_installed(zone_id):
            log.warning(
                "Refusing to start watering for disabled or unknown %s (id=%d)",
                self._zone_label(zone_id), zone_id,
            )
            return False

        # Idempotent guard: a duplicate start (e.g. user double-taps the manual
        # button) would otherwise create a second watering_event row and
        # overwrite _active[zone_id], orphaning the original event.
        # See https://github.com/jamesearlpace/smart-garden-server/issues/3
        if zone_id in self._active:
            log.info("%s: already watering (event %d) - ignoring duplicate start",
                     self._zone_label(zone_id), self._active[zone_id]["event_id"])
            return True

        ws = self.calculate_weather_scale(allow_weather_fetch=allow_weather_fetch)
        scale_pct = ws["scale_pct"]

        # If weather scale is 0%, skip instead of opening the valve
        # BUT: manual overrides always run regardless of weather
        is_manual = reason.startswith("manual")
        if scale_pct == 0 and not is_manual:
            log.info("%s: weather scale 0%% - skipping (rain: %.1fmm)",
                     self._zone_label(zone_id), ws["rain_last_24h_mm"])
            return False
        if scale_pct == 0 and is_manual:
            log.info("%s: weather scale 0%% but manual override - running anyway",
                     self._zone_label(zone_id))
            scale_pct = 100  # full runtime for manual

        zone = self.zones[zone_id]
        adjusted_min = zone["max_runtime_min"] * scale_pct / 100.0
        log.info("%s: weather scale %d%% -> runtime %.0fmin (base %dmin) "
                 "[temp_d=%.1f hum_d=%.1f rain_d=%.1f]",
                 self._zone_label(zone_id), scale_pct, adjusted_min, zone["max_runtime_min"],
                 ws["temp_delta"], ws["humidity_delta"], ws["rain_delta"])

        if self.open_valve(zone_id, timeout=command_timeout, retry=retry):
            event_id = db.start_watering(zone_id, soil_before, et_demand, reason)
            self._active[zone_id] = {
                "event_id": event_id,
                "start_time": time.time(),
                "soil_before": soil_before,
                "weather_scale_pct": scale_pct,
            }
            log.info("%s watering started (event %d)", self._zone_label(zone_id), event_id)
            return True
        return False

    def stop_zone_watering(self, zone_id: int, soil_after: float):
        """Close valve and finalize the watering event."""
        if zone_id not in self._active:
            self.close_valve(zone_id)
            return

        active = self._active.pop(zone_id)
        duration_sec = int(time.time() - active["start_time"])
        zone = self.zones[zone_id]
        est_gallons = (duration_sec / 60.0) * zone["est_gpm"]

        self.close_valve(zone_id)
        db.end_watering(active["event_id"], soil_after, duration_sec, est_gallons)
        log.info("%s watering stopped: %ds, ~%.1f gal",
                 self._zone_label(zone_id), duration_sec, est_gallons)

    def log_skip_event(self, zone_id: int, reason: str, conditions: dict):
        """Log that we skipped watering ΓÇö estimates what WOULD have been used."""
        zone = self.zones[zone_id]
        # Estimate: a timer would run for the full max_runtime
        timer_minutes = zone["max_runtime_min"]
        if zone.get("cycle_soak"):
            timer_minutes = zone.get("cycle_run_min", 8) * zone.get("cycle_count", 3)
        est_gallons_saved = timer_minutes * zone["est_gpm"]

        db.log_skip(zone_id, reason, est_gallons_saved,
                    json.dumps(conditions, default=str))

    def _coerce_soil_sensor_index(self, zone: dict, soil_count: int) -> int | None:
        sensor_idx = zone.get("soil_sensor")
        if sensor_idx in (None, ""):
            return None
        try:
            sensor_idx = int(sensor_idx)
        except (TypeError, ValueError):
            return None
        if sensor_idx < 0 or sensor_idx >= soil_count:
            return None
        return sensor_idx

    # ΓöÇΓöÇ Main loop (called by scheduler) ΓöÇΓöÇ

    def run_cycle(self):
        """Main decision cycle ΓÇö evaluate all zones and act."""
        log.info("=== Starting irrigation decision cycle ===")

        installed_zones = [
            zone for zone in self.config["zones"]
            if zone.get("installed", False)
        ]
        if not installed_zones:
            log.info("No installed zones configured ΓÇö skipping irrigation decisions")
            return []

        status = self.get_esp32_status(force_fresh=True)
        if status:
            system = status.get("system", {})
            health = status.get("health", {})
            if system:
                db.log_system_health(
                    uptime_sec=system.get("uptimeSec", 0),
                    wifi_rssi=system.get("wifiRSSI", 0),
                    heap_pct=system.get("heapPct", 0),
                    chip_temp_f=system.get("chipTempF", 0),
                    boot_count=system.get("bootCount", 0),
                    battery_v=round(system.get("batteryV",0)*1.02884,2) if system.get("batteryV") else None,
                    wifi_reconnects=system.get("wifiReconnects"),
                    crash_count=health.get("crashCount"),
                    tx_power_raw=system.get("txPowerRaw"),
                )

        # Log sensor + weather data (runs even with no installed zones)
        if status:
            soil_list = status.get("soil", [])
            sensors_cfg = self.config.get("sensors", {})
            for idx, sensor in enumerate(soil_list):
                if sensors_cfg.get(f"soil_{idx}", False):
                    db.log_sensor(idx, sensor["pct"], sensor["raw"])

            temp = status.get("temp", 0)
            hum = status.get("hum", 0)
            if temp or hum:
                db.log_weather("dht22", temp_f=temp if temp else None,
                               humidity=hum)

        current_wx = self.weather.get_current()
        if current_wx:
            et0 = self.weather.get_today_et0()
            db.log_weather("api",
                           temp_f=current_wx.get("temp_f"),
                           humidity=current_wx.get("humidity"),
                           wind_mph=current_wx.get("wind_mph"),
                           rain_mm=current_wx.get("precip_mm"),
                           et0_mm=et0,
                           solar_rad=current_wx.get("solar_rad"))

        if not status:
            log.error("Cannot reach ESP32 ΓÇö skipping cycle")
            return

        # Build soil reading map: zone_id → pct (installed zones only)
        soil_readings = {}
        invalid_sensor_zones = set()
        for zone in installed_zones:
            sensor_idx = self._coerce_soil_sensor_index(zone, len(soil_list))
            if sensor_idx is None:
                # No soil sensor — that's fine, we use water balance model
                continue
            soil_readings[zone["id"]] = soil_list[sensor_idx]["pct"]

        # Evaluate each zone (installed only)
        actions = []
        skip_reasons = {}
        n_watered = 0
        n_skipped = 0
        n_outside = 0
        for zone in installed_zones:
            zid = zone["id"]
            # Water balance model — no soil sensor needed
            soil = soil_readings.get(zid, 50)
            decision = self.evaluate_zone(zid, soil, status)
            actions.append(decision)

            action = decision["action"]
            log.info("%s: %s - %s",
                     self._zone_label(zid), action, decision["reason"])

            if action == "water":
                # INVARIANT: only one valve open at a time. Power budget (solar +
                # SLA + H-bridge) and water-pressure plan both depend on it.
                # If another zone is already running, defer to the next cycle
                # rather than open a second valve in parallel. Worst-case wait
                # for the second zone = poll_interval_sec (5 min) after the
                # first one closes. Manual /api/run and /api/valve paths
                # PREEMPT instead (see open_valve lockout). See
                # https://github.com/jamesearlpace/smart-garden-server/issues/1
                if self._active:
                    busy = ", ".join(self._zone_label(z) for z in self._active.keys())
                    log.info("%s: deferring - %s already running",
                             self._zone_label(zid), busy)
                    defer_reason = "deferred ΓÇö another zone running"
                    skip_reasons[defer_reason] = skip_reasons.get(defer_reason, 0) + 1
                    n_skipped += 1
                    continue
                et_demand = decision["details"].get("et_demand_mm", 0)
                self.start_zone_watering(zid, soil, et_demand)
                n_watered += 1
            elif action == "skip":
                reason = decision["reason"]
                skip_reasons[reason] = skip_reasons.get(reason, 0) + 1
                n_skipped += 1
                if "window" in reason.lower():
                    n_outside += 1
                # Persist at most one skip_event per zone per day so the
                # daily savings rollup doesn't multi-count the same skip
                # across 5-minute cycles. Manual-mode disables aren't
                # weather-driven savings, so don't credit them.
                if ("manual mode" not in reason.lower()
                        and not db.skip_event_exists_today(zid)):
                    self.log_skip_event(zid, reason, decision["details"])
            elif action == "close":
                self.stop_zone_watering(zid, soil)

        # Safety net: this loop should never leave more than one valve active.
        # If it does, something opened a second valve between the guard and now
        # (race, manual override, or future bug). Log loudly so it shows up.
        if len(self._active) > 1:
            log.error("INVARIANT VIOLATED: %d zones active after run_cycle: %s",
                      len(self._active), list(self._active.keys()))

        # Log one summary row per cycle instead of per-zone skip events
        if n_skipped > 0 or n_watered > 0:
            dominant = max(skip_reasons, key=skip_reasons.get) if skip_reasons else "n/a"
            db.log_cycle_summary(
                zones_evaluated=len(actions),
                zones_skipped=n_skipped,
                zones_watered=n_watered,
                zones_outside_window=n_outside,
                dominant_reason=dominant,
                details_json=json.dumps(skip_reasons) if skip_reasons else None,
            )

        log.info("=== Decision cycle complete ===")
        self._last_successful_cycle = datetime.now()
        return actions

    def safety_check(self):
        """Safety: close any valve that's been open too long."""
        now = time.time()
        for zone_id, active in list(self._active.items()):
            elapsed = now - active["start_time"]
            if elapsed > self.valve_timeout:
                log.warning("Safety timeout: %s open for %ds - forcing close",
                            self._zone_label(zone_id), int(elapsed))
                self.stop_zone_watering(zone_id, soil_after=0)

    def get_zone_taw_mm(self, zone_id: int) -> float:
        """Total Available Water in mm for a zone."""
        zone = self.zones[zone_id]
        root_depth = zone.get("root_depth_in", self._default_root_depth)
        taw_in = root_depth * self._awc  # inches
        return taw_in * 25.4  # convert to mm

    def get_zone_mad_mm(self, zone_id: int) -> float:
        """Management Allowed Depletion threshold in mm."""
        zone = self.zones[zone_id]
        mad_pct = zone.get("mad_pct", self._default_mad_pct) / 100.0
        return self.get_zone_taw_mm(zone_id) * mad_pct

    def update_daily_balances(self):
        """Update soil water balance for all zones (called daily by scheduler).

        Checkbook method: balance starts at TAW (field capacity).
        Each day: balance -= ETΓéÇ ├ù Kc  (demand)
                  balance += rain_mm    (credit)
                  balance += irrigation_mm (credit, from watering events ├ù precip rate)
        Balance is clamped to [0, TAW_mm].
        """
        today = date.today().isoformat()
        et0 = self.weather.get_today_et0()
        rain_last_24h = self.weather.get_rain_last_24h()
        season_idx = self.weather.get_season_index()

        log.info("Updating soil water balances for %s (ETΓéÇ=%.2fmm, rain=%.1fmm)",
                 today, et0, rain_last_24h)

        for zone in self.config["zones"]:
            zid = zone["id"]
            taw_mm = self.get_zone_taw_mm(zid)
            mad_mm = self.get_zone_mad_mm(zid)

            # Get yesterday's closing balance (or start at field capacity)
            prev = db.get_soil_balance(zid)
            if prev and prev["date"] != today:
                balance = prev["balance_mm"]
            elif prev and prev["date"] == today:
                # Already updated today — use yesterday's balance to recompute
                yesterday = (date.today() - timedelta(days=1)).isoformat()
                yprev = None
                hist = db.get_soil_balance_history(zid, days=2)
                for h in hist:
                    if h["date"] == yesterday:
                        yprev = h
                        break
                if yprev:
                    balance = yprev["balance_mm"]
                else:
                    # Can't find yesterday — carry forward today's existing
                    # balance rather than resetting to TAW (bug #7 fix)
                    balance = prev["balance_mm"]
                    log.warning("%s: no yesterday record, carrying forward "
                                "today's balance %.1fmm (not resetting to TAW)",
                                self._zone_label(zid), balance)
            else:
                # True first entry ever — only time we assume field capacity
                balance = taw_mm
                log.info("%s: first balance entry, starting at field "
                         "capacity %.1fmm", self._zone_label(zid), taw_mm)

            # Crop coefficient for current season
            kc = zone["kc"][season_idx] if season_idx >= 0 else 0
            etc_mm = et0 * kc

            # Irrigation applied today (from watering events ├ù precip rate)
            precip_rate = zone.get("precip_rate_iph", 1.0)
            irrig_mm = db.get_daily_irrigation_mm(zid, today, precip_rate)

            # Update balance
            balance = balance - etc_mm + rain_last_24h + irrig_mm
            balance = max(0, min(balance, taw_mm))  # clamp to [0, TAW]

            db.upsert_soil_balance(
                zone_id=zid, day=today, et0_mm=et0, kc=kc,
                etc_mm=etc_mm, rain_mm=rain_last_24h,
                irrigation_mm=irrig_mm, balance_mm=balance,
                taw_mm=taw_mm, mad_mm=mad_mm,
            )

            deficit_pct = (1 - balance / taw_mm) * 100 if taw_mm > 0 else 0
            log.info("%s balance: %.1fmm / %.1fmm TAW (%.0f%% depleted, MAD=%.1fmm)",
                     self._zone_label(zid), balance, taw_mm, deficit_pct, mad_mm)

    def save_daily_forecast_snapshot(self):
        """Capture today's watering forecast for every installed zone.

        Called daily before the morning watering window (3:55 AM by scheduler).
        Records what the system predicts will happen so we can compare to
        actual events later.
        """
        from datetime import date, timedelta

        today = date.today().isoformat()
        et0 = self.weather.get_today_et0()
        rain_forecast_data = self.weather.get_rain_forecast_24h()
        rain_forecast_mm = rain_forecast_data.get("total_mm", 0) if rain_forecast_data else 0
        rain_prob = rain_forecast_data.get("max_probability", 0) if rain_forecast_data else 0
        rain_last_24h = self.weather.get_rain_last_24h()
        season_idx = self.weather.get_season_index()
        rules = self.skip_rules

        log.info("Saving forecast snapshot for %s (ETΓéÇ=%.2fmm, rain_fcst=%.1fmm)",
                 today, et0, rain_forecast_mm)

        for zone in self.config["zones"]:
            if not zone.get("installed", False):
                continue
            zid = zone["id"]
            taw_mm = self.get_zone_taw_mm(zid)
            mad_mm = self.get_zone_mad_mm(zid)
            kc = zone["kc"][season_idx] if season_idx >= 0 and season_idx < len(zone.get("kc", [])) else 0
            etc_mm = et0 * kc

            # Current balance
            bal = db.get_soil_balance(zid)
            balance_mm = bal["balance_mm"] if bal else taw_mm

            # Forecast: days until balance drops below MAD threshold
            threshold_mm = taw_mm - mad_mm
            if etc_mm > 0 and balance_mm > threshold_mm:
                days_until = (balance_mm - threshold_mm) / etc_mm
            elif balance_mm <= threshold_mm:
                days_until = 0
            else:
                days_until = None

            predicted_date = None
            if days_until is not None:
                next_dt = date.today() + timedelta(days=max(0, int(days_until)))
                predicted_date = next_dt.isoformat()

            # Check if a skip would fire today
            predicted_skip = False
            skip_reason = None

            if season_idx < 0:
                predicted_skip = True
                skip_reason = "dormant_season"
            elif rain_last_24h >= rules.get("recent_rain_mm", 999):
                predicted_skip = True
                skip_reason = f"recent_rain_{rain_last_24h:.1f}mm"
            elif (rain_forecast_mm >= rules.get("rain_forecast_mm", 999)
                  and rain_prob >= rules.get("rain_probability_pct", 999)):
                predicted_skip = True
                skip_reason = f"rain_forecast_{rain_forecast_mm:.1f}mm_{rain_prob}%"

            db.save_forecast_snapshot(
                forecast_date=today,
                zone_id=zid,
                zone_name=zone["name"],
                balance_mm=balance_mm,
                taw_mm=taw_mm,
                mad_mm=mad_mm,
                etc_mm=etc_mm,
                et0_mm=et0,
                rain_forecast_mm=rain_forecast_mm,
                days_until_water=days_until,
                predicted_date=predicted_date,
                predicted_skip=predicted_skip,
                skip_reason=skip_reason,
            )

        log.info("Forecast snapshot saved for %s", today)

    def get_status_summary(self, allow_weather_fetch: bool = True) -> dict:
        """Get a summary of current system state for the dashboard."""
        budget = self.billing.should_tighten_budget()
        season = self.weather.get_season()
        current_wx = self.weather.get_current(allow_fetch=allow_weather_fetch)

        return {
            "season": season,
            "weather": current_wx,
            "et0_today": self.weather.get_today_et0(allow_fetch=allow_weather_fetch),
            "rain_forecast": self.weather.get_rain_forecast_24h(allow_fetch=allow_weather_fetch),
            "rain_last_24h": self.weather.get_rain_last_24h(allow_fetch=allow_weather_fetch),
            "budget": budget,
            "active_zones": list(self._active.keys()),
            "forecast_7day": self.weather.get_7day_forecast(allow_fetch=allow_weather_fetch),
            "weather_scale": self.calculate_weather_scale(allow_weather_fetch=allow_weather_fetch),
            "soil_balances": db.get_all_balances(),
            "last_successful_cycle": self._last_successful_cycle.isoformat() if self._last_successful_cycle else None,
        }
