"""Flask dashboard for Smart Garden Server.

Serves a web UI at http://acer:5125 with:
- Live sensor readings and valve status
- Weather conditions and 7-day forecast
- Watering history and skip log
- Billing/savings tracker with Duvall tier visualization
- Manual valve controls
"""

import json
import os
import tempfile
from datetime import datetime

import requests as http_requests
import yaml
from flask import make_response, Response, Flask, render_template, request, jsonify, redirect, url_for

import database as db
from irrigation import ESP32_MANUAL_TIMEOUT
from cam_ocr import MeterReader


def create_app(config, engine, weather, billing):
    import time
    app = Flask(__name__)
    app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0  # no caching during dev
    app.config["TEMPLATES_AUTO_RELOAD"] = True
    app.config["start_time"] = time.time()
    app.config["last_health_check_ts"] = None
    app.config["last_successful_request_ts"] = None

    def coerce_int(raw, default, min_value=None, max_value=None):
        try:
            value = int(str(raw).strip()) if raw not in (None, "") else default
        except (TypeError, ValueError):
            value = default
        if min_value is not None:
            value = max(min_value, value)
        if max_value is not None:
            value = min(max_value, value)
        return value

    def query_int(name, default, min_value=None, max_value=None):
        return coerce_int(request.args.get(name), default, min_value, max_value)

    def optional_query_int(name, min_value=None, max_value=None):
        raw = request.args.get(name)
        if raw in (None, ""):
            return None
        try:
            value = int(str(raw).strip())
        except (TypeError, ValueError):
            return None
        if min_value is not None:
            value = max(min_value, value)
        if max_value is not None:
            value = min(max_value, value)
        return value

    def request_int(name, default, min_value=None, max_value=None):
        raw = request.form.get(name)
        if raw in (None, "") and request.is_json:
            payload = request.get_json(silent=True) or {}
            raw = payload.get(name)
        return coerce_int(raw, default, min_value, max_value)

    def zone_installed(zone_id):
        if zone_id < 0 or zone_id >= len(config["zones"]):
            return False
        return bool(config["zones"][zone_id].get("installed", False))

    def zone_inverted(zone_id):
        if zone_id < 0 or zone_id >= len(config["zones"]):
            return False
        return bool(config["zones"][zone_id].get("inverted", False))

    def apply_inversion(valves):
        """Flip open flag for zones with inverted wiring."""
        import copy
        result = copy.deepcopy(valves)
        for i, v in enumerate(result):
            if zone_inverted(i):
                v["open"] = not v["open"]
        return result



    def _apply_esp32_inversion(status):
        """Return a copy of ESP32 status with valve open flags inverted for inverted zones."""
        import copy
        result = copy.deepcopy(status) if not isinstance(status, dict) else dict(status)
        if "valves" in result:
            result["valves"] = apply_inversion(result["valves"])
        return result

    def cached_valves():
        status = cached_esp32_status()
        return apply_inversion((status or {}).get("valves", []))

    def cached_esp32_status():
        try:
            return getattr(engine, "get_cached_esp32_status", lambda: None)()
        except Exception:
            return None

    def esp32_online_status():
        try:
            return bool(getattr(engine, "is_esp32_online", lambda: False)())
        except Exception:
            return False

    def status_summary():
        fallback = {
            "active_zones": [],
            "weather": None,
            "et0_today": 0,
            "rain_last_24h": 0,
            "rain_forecast": None,
            "season": None,
            "forecast_7day": [],
            "weather_scale": None,
            "budget": None,
            "soil_balances": [],
        }
        try:
            return getattr(
                engine,
                "get_status_summary",
                lambda **kwargs: fallback,
            )(allow_weather_fetch=False) or fallback
        except Exception:
            return fallback

    def fresh_valves():
        """Fetch live valve state from ESP32 after a manual toggle."""
        try:
            status = getattr(engine, "get_esp32_status", lambda **kwargs: None)(
                force_fresh=True
            )
        except Exception:
            status = None
        return apply_inversion((status or {}).get("valves", []))

    def engine_command(name, *args, **kwargs):
        method = getattr(engine, name, None)
        if method is None:
            return False
        try:
            return bool(method(*args, **kwargs))
        except Exception:
            return False

    def write_config_atomic(next_config):
        config_path = os.path.join(os.path.dirname(__file__), "config.yaml")
        config_dir = os.path.dirname(config_path)
        fd, tmp_path = tempfile.mkstemp(
            prefix=".config.",
            suffix=".tmp",
            dir=config_dir,
            text=True,
        )
        try:
            with os.fdopen(fd, "w") as f:
                yaml.dump(
                    next_config,
                    f,
                    default_flow_style=False,
                    sort_keys=False,
                    allow_unicode=True,
                )
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, config_path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except FileNotFoundError:
                pass
            raise

    @app.after_request
    def add_no_cache_headers(response):
        """Prevent browser from caching any response — ensures dashboard updates show immediately."""
        if response.status_code < 500:
            now = time.time()
            app.config["last_successful_request_ts"] = now
            if request.headers.get("X-Smart-Garden-Internal-Health") != "1":
                app.config["last_health_check_ts"] = now
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        return response

    @app.template_filter("currency")
    def currency_filter(value):
        if value is None:
            return "$0.00"
        return f"${value:,.2f}"

    @app.template_filter("number")
    def number_filter(value, decimals=1):
        if value is None:
            return "—"
        return f"{value:,.{decimals}f}"


    # ── Authentication ──────────────────────────────────────────────
    import hashlib, hmac, time, json as auth_json, urllib.request, urllib.parse

    GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
    SESSION_SECRET = os.environ.get("SESSION_SECRET", "smartgarden2026default")
    SESSION_MAX_AGE = 86400 * 30  # 30 days
    ALLOWED_EMAILS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "allowed_emails.json")

    def _load_allowed_emails():
        try:
            with open(ALLOWED_EMAILS_FILE) as f:
                return {e["email"].lower() for e in auth_json.load(f)}
        except Exception:
            return set()

    def _make_session_token(email):
        ts = str(int(time.time()))
        sig = hmac.new(SESSION_SECRET.encode(), f"{email}|{ts}".encode(), hashlib.sha256).hexdigest()
        return f"{email}|{ts}|{sig}"

    def _verify_session_token(token):
        try:
            parts = token.split("|")
            if len(parts) != 3:
                return None
            email, ts, sig = parts
            expected = hmac.new(SESSION_SECRET.encode(), f"{email}|{ts}".encode(), hashlib.sha256).hexdigest()
            if not hmac.compare_digest(sig, expected):
                return None
            if time.time() - int(ts) > SESSION_MAX_AGE:
                return None
            return email
        except Exception:
            return None

    def _verify_google_token(credential):
        url = f"https://oauth2.googleapis.com/tokeninfo?id_token={urllib.parse.quote(credential)}"
        try:
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = auth_json.loads(resp.read().decode())
            if data.get("aud") != GOOGLE_CLIENT_ID:
                return None
            return data.get("email", "").lower()
        except Exception:
            return None

    @app.before_request
    def check_auth():
        # Public routes
        public = ("/login", "/auth/", "/favicon.ico", "/static/", "/api/cam/upload", "/api/cam/status")
        if any(request.path.startswith(p) for p in public) or request.path == "/login":
            return None
        # Check session cookie
        token = request.cookies.get("session")
        if token:
            email = _verify_session_token(token)
            if email and email in _load_allowed_emails():
                return None
        # Not authenticated — redirect to login
        if request.headers.get("X-Requested-With") == "XMLHttpRequest" or request.is_json:
            return jsonify({"error": "Not authenticated"}), 401
        return redirect("/login")

    @app.route("/login")
    def login_page():
        return render_template("login.html")

    @app.route("/auth/config")
    def auth_config():
        return jsonify({"client_id": GOOGLE_CLIENT_ID})

    @app.route("/auth/google", methods=["POST"])
    def auth_google():
        data = request.get_json(silent=True) or {}
        credential = data.get("credential", "")
        email = _verify_google_token(credential)
        if not email:
            return jsonify({"ok": False, "error": "Invalid Google token"}), 401
        if email not in _load_allowed_emails():
            return jsonify({"ok": False, "error": "Not authorized"}), 403
        resp = make_response(jsonify({"ok": True, "email": email}))
        token = _make_session_token(email)
        resp.set_cookie("session", token, max_age=SESSION_MAX_AGE, httponly=True, samesite="Lax", secure=True)
        return resp

    @app.route("/auth/logout")
    def auth_logout():
        resp = make_response(redirect("/login"))
        resp.delete_cookie("session")
        return resp

    @app.route("/auth/check")
    def auth_check():
        token = request.cookies.get("session")
        if token:
            email = _verify_session_token(token)
            if email:
                return jsonify({"authenticated": True, "email": email})
        return jsonify({"authenticated": False}), 401


    @app.route("/forecast")
    def forecast_page():
        return render_template("forecast_merged.html")

    @app.route("/api/forecast")
    def api_forecast():
        """Watering forecast for all installed zones."""
        from datetime import date, timedelta

        summary = status_summary()
        w = summary.get("weather") or {}
        et0 = summary.get("et0_today", 0)
        season_idx = engine.weather.get_season_index() if hasattr(engine, 'weather') else 0

        zones_out = []
        for zone in config["zones"]:
            if not zone.get("installed", False):
                continue
            zid = zone["id"]
            taw_mm = engine.get_zone_taw_mm(zid) if hasattr(engine, 'get_zone_taw_mm') else 10
            mad_mm = engine.get_zone_mad_mm(zid) if hasattr(engine, 'get_zone_mad_mm') else 5
            kc = zone["kc"][season_idx] if season_idx < len(zone.get("kc", [])) else 0.7
            etc_mm = et0 * kc  # daily ET demand for this zone

            # Current balance
            bal = db.get_soil_balance(zid)
            balance_mm = bal["balance_mm"] if bal else taw_mm
            balance_pct = (balance_mm / taw_mm * 100) if taw_mm > 0 else 100

            # Forecast: days until balance drops below MAD threshold
            # threshold = TAW - MAD (the point where watering triggers)
            threshold_mm = taw_mm - mad_mm
            if etc_mm > 0 and balance_mm > threshold_mm:
                days_until = (balance_mm - threshold_mm) / etc_mm
            elif balance_mm <= threshold_mm:
                days_until = 0
            else:
                days_until = None  # no ET demand

            next_date = None
            if days_until is not None:
                next_dt = date.today() + timedelta(days=max(0, int(days_until)))
                next_date = next_dt.strftime("%a %b %d")

            zones_out.append({
                "id": zid,
                "name": zone["name"],
                "type": zone.get("type", "sprinkler"),
                "balance_mm": round(balance_mm, 1),
                "balance_pct": round(balance_pct, 0),
                "taw_mm": round(taw_mm, 1),
                "mad_mm": round(mad_mm, 1),
                "etc_mm": round(etc_mm, 2),
                "days_until_water": round(days_until, 1) if days_until is not None else None,
                "next_water_date": next_date,
            })

        return jsonify({
            "weather": w,
            "et0_today": et0,
            "zones": zones_out,
            "window_start": config.get("watering_window", {}).get("start", "04:00"),
            "window_end": config.get("watering_window", {}).get("end", "07:00"),
        })

    @app.route("/forecast-vs-actual")
    def forecast_vs_actual_page():
        return redirect("/forecast")

    @app.route("/api/forecast-vs-actual")
    def api_forecast_vs_actual():
        """Forecast vs actual comparison data."""
        days = query_int("days", 30, min_value=1, max_value=365)
        return jsonify({
            "comparisons": db.get_forecast_vs_actual(days),
            "accuracy": db.get_forecast_accuracy_summary(days),
            "days": days,
        })

    @app.route("/api/forecast-snapshot", methods=["POST"])
    def api_forecast_snapshot_now():
        """Manually trigger a forecast snapshot (for testing)."""
        try:
            engine.save_daily_forecast_snapshot()
            return jsonify({"ok": True})
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)}), 500

    @app.route("/api/moisture-data")
    def api_moisture_data():
        """Data for the moisture simulation chart.

        Returns soil balance history, watering events, zone config, and
        7-day forecast for the requested zone.
        """
        zone_id = query_int("zone_id", 0, min_value=0, max_value=8)
        days = query_int("days", 90, min_value=7, max_value=365)

        zone_cfg = None
        for z in config["zones"]:
            if z["id"] == zone_id:
                zone_cfg = z
                break
        if not zone_cfg:
            return jsonify({"error": "Zone not found"}), 404

        # Soil balance history (daily checkbook values)
        balances = db.get_soil_balance_history(zone_id, days=days)

        # Watering events (actual sprinkler runs)
        waterings = db.get_watering_history(days=days)
        zone_waterings = [w for w in waterings if w["zone_id"] == zone_id]

        # Skip events
        skips = db.get_skip_history(days=days)
        zone_skips = [s for s in skips if s["zone_id"] == zone_id]

        # 7-day forecast from weather client
        forecast = weather.get_7day_forecast(allow_fetch=False)

        # Current weather
        current_wx = weather.get_current(allow_fetch=False)

        # Today's ET0
        et0_today = weather.get_today_et0(allow_fetch=False)

        return jsonify({
            "zone": {
                "id": zone_cfg["id"],
                "name": zone_cfg["name"],
                "installed": zone_cfg.get("installed", False),
                "precip_rate_iph": zone_cfg.get("precip_rate_iph", 1.0),
                "kc": zone_cfg.get("kc", [0.90, 0.90, 0.90, 0.90]),
                "root_depth_in": zone_cfg.get("root_depth_in", 6),
                "taw_in": zone_cfg.get("taw_in", 1.2),
                "mad_pct": zone_cfg.get("mad_pct", 50),
            },
            "balances": balances,
            "waterings": zone_waterings,
            "skips": zone_skips,
            "forecast_7day": forecast,
            "current_weather": current_wx,
            "et0_today": et0_today,
        })

    @app.route("/moisture-sim")
    def moisture_sim_page():
        """Moisture simulation chart — historical, live 2026, and forecast."""
        zones = [z for z in config["zones"] if z.get("installed", False)]
        return render_template("moisture_sim.html", zones=zones)

    # ── Pages ──

    @app.route("/")
    def index():
        status_data = cached_esp32_status()
        summary = status_summary()
        bill = billing.get_monthly_bill_estimate()
        savings = billing.get_savings_report()
        health = db.get_latest_health()

        return render_template("index.html",
                               esp32=status_data,
                               summary=summary,
                               bill=bill,
                               savings=savings,
                               health=health,
                               zones=config["zones"],
                               now=datetime.now())

    @app.route("/map")
    def zone_map():
        return render_template("map.html")

    @app.route("/history")
    def history():
        days = query_int("days", 30, min_value=1, max_value=3650)
        waterings = db.get_watering_history(days)
        skips = db.get_skip_history(days)
        daily = db.get_daily_summaries(days)
        return render_template("history.html",
                               waterings=waterings,
                               skips=skips,
                               daily=daily,
                               days=days,
                               zones=config["zones"])

    @app.route("/sensors")
    def sensors():
        zone_data = []
        for zone in config["zones"]:
            soil_hist = db.get_soil_history(zone["soil_sensor"], days=7)
            latest = db.get_latest_soil(zone["soil_sensor"])
            zone_data.append({
                "zone": zone,
                "latest": latest,
                "history": soil_hist,
            })
        return render_template("sensors.html",
                               zone_data=zone_data,
                               weather_7day=weather.get_7day_forecast(allow_fetch=False))

    # ── API endpoints ──

    @app.route("/api/valve", methods=["POST"])
    def api_valve():
        zone_id = request_int("id", 0, min_value=0, max_value=len(config["zones"]) - 1)
        payload = request.get_json(silent=True) if request.is_json else {}
        action = request.form.get("action") or (payload or {}).get("action", "")
        if zone_inverted(zone_id):
            action = "close" if action == "open" else "open" if action == "close" else action
        if not zone_installed(zone_id):
            return jsonify({
                "ok": False,
                "zone_id": zone_id,
                "action": action,
                "error": "zone_not_installed",
                "valves": cached_valves(),
            }), 400
        ok = False
        if action == "open":
            ok = engine_command(
                "open_valve",
                zone_id,
                timeout=ESP32_MANUAL_TIMEOUT,
                retry=False,
            )
        elif action == "close":
            # Use stop_zone_watering if the zone is actively tracked,
            # so the watering event gets finalized and _active is cleared.
            # Fall back to raw close_valve if not tracked.
            if hasattr(engine, '_active') and zone_id in engine._active:
                soil = db.get_latest_soil(zone_id)
                soil_pct = soil["soil_pct"] if soil else 0
                engine.stop_zone_watering(zone_id, soil_pct)
                ok = True
            else:
                ok = engine_command(
                    "close_valve",
                    zone_id,
                    timeout=ESP32_MANUAL_TIMEOUT,
                    retry=False,
                )
            # Invalidate the status cache so the next refresh shows updated state
            engine._status_cache_ts = 0
        if request.headers.get("X-Requested-With") == "XMLHttpRequest" or request.is_json:
            return jsonify({
                "ok": ok,
                "zone_id": zone_id,
                "action": action,
                "valves": fresh_valves() if ok else cached_valves(),
            })
        return redirect(url_for("index"))

    @app.route("/api/closeall", methods=["POST"])
    def api_closeall():
        ok = engine_command("close_all", timeout=ESP32_MANUAL_TIMEOUT, retry=False)
        if request.headers.get("X-Requested-With") == "XMLHttpRequest" or request.is_json:
            return jsonify({"ok": ok, "valves": fresh_valves() if ok else cached_valves()})
        return redirect(url_for("index"))

    @app.route("/api/reboot", methods=["POST"])
    def api_reboot():
        """Trigger a remote reboot of the ESP32 via the firmware's
        token-protected /api/reboot endpoint. See issue #12 / firmware
        commit b6e33ae.

        WARNING: On the current Wanderer wall-power setup, ESP.restart()
        draws enough inrush current to brownout the chip and corrupt its
        boot state \u2014 same root cause as the OTA failure (issue #2).
        Verified bricked the chip 2026-04-21 23:55. DO NOT call this
        endpoint until a 1000\u00b5F decoupling cap is added across the 3.3V
        rail. Returns 503 to prevent accidental triggering.

        To re-enable for emergencies (when the chip is on USB power):
        set SMART_GARDEN_REBOOT_ENABLED=1 environment variable.
        """
        if os.environ.get("SMART_GARDEN_REBOOT_ENABLED") != "1":
            return jsonify({
                "ok": False,
                "message": ("Remote reboot disabled \u2014 brownouts the chip on "
                            "wall power. See issue #2. Set "
                            "SMART_GARDEN_REBOOT_ENABLED=1 to override.")
            }), 503
        ok, msg = engine.reboot_esp32()
        return jsonify({"ok": ok, "message": msg}), (200 if ok else 502)

    @app.route("/api/run", methods=["POST"])
    def api_run_zone():
        """Run a zone for X minutes (manual override)."""
        zone_id = request_int("id", 0, min_value=0, max_value=len(config["zones"]) - 1)
        minutes = request_int("minutes", 5, min_value=1, max_value=120)
        if not zone_installed(zone_id):
            return jsonify({
                "ok": False,
                "zone_id": zone_id,
                "minutes": minutes,
                "error": "zone_not_installed",
            }), 400
        soil = db.get_latest_soil(zone_id)
        soil_pct = soil["soil_pct"] if soil else 0
        ok = engine_command(
            "start_zone_watering",
            zone_id, soil_pct, 0, "manual",
            allow_weather_fetch=False,
            command_timeout=ESP32_MANUAL_TIMEOUT,
            retry=False,
        )
        # Note: the safety check + decision engine will auto-close
        # after max_runtime or when soil target is reached
        if request.headers.get("X-Requested-With") == "XMLHttpRequest" or request.is_json:
            return jsonify({"ok": ok, "zone_id": zone_id, "minutes": minutes, "soil_pct": soil_pct})
        return redirect(url_for("index"))

    @app.route("/api/status")
    def api_status():
        return jsonify(status_summary())

    @app.route("/health")
    @app.route("/api/health")
    def api_health():
        """Fast deployment verification endpoint for watchdog checks."""
        import time
        esp32_url = config.get("esp32", {}).get("url", "http://192.168.0.150")
        return jsonify({
            "ok": True,
            "version": "2026-04-11",
            "server_time": datetime.now().isoformat(),
            "uptime_sec": int(time.time() - app.config.get("start_time", time.time())),
            "esp32_reachable": esp32_online_status(),
            "esp32_url": esp32_url,
            "zones": len(config.get("zones", [])),
            "port": config.get("dashboard", {}).get("port", 5125),
        })

    @app.route("/api/billing")
    def api_billing():
        bill = billing.get_monthly_bill_estimate()
        savings = billing.get_savings_report()
        budget = billing.should_tighten_budget()
        return jsonify({"bill": bill, "savings": savings, "budget": budget})

    @app.route("/api/connectivity")
    def api_connectivity():
        hours = query_int("hours", 24, min_value=1, max_value=87600)
        return jsonify(db.get_connectivity_history(hours))

    @app.route("/api/health-history")
    def api_health_history():
        hours = query_int("hours", 24, min_value=1, max_value=87600)
        return jsonify(db.get_health_timeseries(hours))

    @app.route("/api/watering-history")
    def api_watering_history():
        hours = query_int("hours", 24, min_value=1, max_value=87600)
        conn = db.get_conn()
        rows = conn.execute(
            "SELECT zone_id, start_ts, end_ts, duration_sec, trigger_reason, "
            "soil_before, soil_after "
            "FROM watering_event WHERE start_ts >= datetime('now','localtime',?) "
            "ORDER BY start_ts",
            (f"-{hours} hours",),
        ).fetchall()
        conn.close()
        return jsonify([dict(r) for r in rows])

    @app.route("/api/weather-history")
    def api_weather_history():
        hours = query_int("hours", 24, min_value=1, max_value=87600)
        conn = db.get_conn()
        if hours > 72:
            rows = conn.execute(
                "SELECT strftime('%Y-%m-%dT%H:00:00',ts) as ts, "
                "ROUND(AVG(wind_mph),1) as wind_mph, ROUND(SUM(rain_mm),2) as rain_mm, "
                "ROUND(AVG(et0_mm),3) as et0_mm, ROUND(AVG(solar_rad),0) as solar_rad "
                "FROM weather_log WHERE source='api' AND ts >= datetime('now','localtime',?) "
                "GROUP BY strftime('%Y-%m-%dT%H',ts) ORDER BY ts",
                (f"-{hours} hours",),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT ts, wind_mph, rain_mm, et0_mm, solar_rad "
                "FROM weather_log WHERE source='api' AND ts >= datetime('now','localtime',?) "
                "ORDER BY ts",
                (f"-{hours} hours",),
            ).fetchall()
        conn.close()
        return jsonify([dict(r) for r in rows])

    @app.route("/api/cycle-history")
    def api_cycle_history():
        """Cycle summary time-series: skip/water decisions per cycle."""
        hours = query_int("hours", 24, min_value=1, max_value=87600)
        conn = db.get_conn()
        rows = conn.execute(
            "SELECT ts, zones_evaluated, zones_skipped, zones_watered, "
            "zones_outside_window, dominant_reason "
            "FROM cycle_summary WHERE ts >= datetime('now','localtime',?) ORDER BY ts",
            (f"-{hours} hours",),
        ).fetchall()
        conn.close()
        return jsonify([dict(r) for r in rows])

    @app.route("/api/daily-summary-history")
    def api_daily_summary_history():
        """Daily cost & savings time-series."""
        hours = query_int("hours", 24, min_value=1, max_value=87600)
        days = max(1, hours // 24)
        conn = db.get_conn()
        rows = conn.execute(
            "SELECT date, total_gallons, total_cf, gallons_saved, cf_saved, "
            "cost, cost_avoided, et0_mm, rain_mm, avg_temp_f "
            "FROM daily_summary WHERE date >= date('now','localtime',?) ORDER BY date",
            (f"-{days} days",),
        ).fetchall()
        conn.close()
        return jsonify([dict(r) for r in rows])

    @app.route("/api/balance-history")
    def api_balance_history_chart():
        """Soil water balance time-series for zone 0 (primary installed zone)."""
        hours = query_int("hours", 24, min_value=1, max_value=87600)
        zone_id = query_int("zone", 0, min_value=0, max_value=len(config["zones"]) - 1)
        days = max(1, hours // 24)
        conn = db.get_conn()
        rows = conn.execute(
            "SELECT date as ts, balance_mm, taw_mm, mad_mm, et0_mm, "
            "rain_mm, irrigation_mm, etc_mm "
            "FROM soil_balance WHERE zone_id = ? "
            "AND date >= date('now','localtime',?) ORDER BY date",
            (zone_id, f"-{days} days"),
        ).fetchall()
        conn.close()
        return jsonify([dict(r) for r in rows])

    @app.route("/api/sensor-faults")
    def api_sensor_faults():
        """Current sensor fault states."""
        return jsonify(db.get_sensor_faults())

    @app.route("/api/soil-noise")
    def api_soil_noise():
        """Soil noise analysis: rolling stddev and spike detection over 5-reading windows."""
        hours = query_int("hours", 24, min_value=1, max_value=87600)
        zone_id = query_int("index", 0, min_value=0, max_value=len(config["zones"]) - 1)
        conn = db.get_conn()
        rows = conn.execute(
            "SELECT ts, soil_pct, soil_raw FROM sensor_log "
            "WHERE zone_id = ? AND ts >= datetime('now','localtime',?) ORDER BY ts",
            (zone_id, f"-{hours} hours"),
        ).fetchall()
        conn.close()
        if len(rows) < 5:
            return jsonify([])
        # Compute rolling 5-reading stats
        result = []
        window = 5
        for i in range(window, len(rows)):
            chunk = rows[i - window:i]
            vals = [r["soil_pct"] for r in chunk if r["soil_pct"] is not None]
            raws = [r["soil_raw"] for r in chunk if r["soil_raw"] is not None]
            if len(vals) < 3:
                continue
            mean_pct = sum(vals) / len(vals)
            variance = sum((v - mean_pct) ** 2 for v in vals) / len(vals)
            stddev = variance ** 0.5
            cur = rows[i]
            prev = rows[i - 1]
            jump = abs((cur["soil_pct"] or 0) - (prev["soil_pct"] or 0))
            is_spike = 1 if jump > 15 else 0
            is_railed = 1 if (cur["soil_raw"] or 0) >= 4090 else 0
            result.append({
                "ts": cur["ts"],
                "stddev": round(stddev, 1),
                "jump": round(jump, 1),
                "spike": is_spike,
                "railed": is_railed,
                "pct": cur["soil_pct"],
                "raw": cur["soil_raw"],
            })
        return jsonify(result)

    @app.route("/api/logs")
    def api_logs():
        import os
        lines = query_int("lines", 100, min_value=1, max_value=1000)
        level = request.args.get("level", "").upper()
        log_path = os.path.join(os.path.dirname(__file__), "smart-garden.log")
        try:
            with open(log_path, "r") as f:
                all_lines = f.readlines()
            tail = all_lines[-min(lines * 3, len(all_lines)):]  # read extra to filter
            if level:
                tail = [l for l in tail if level in l]
            return jsonify({"lines": [l.rstrip() for l in tail[-lines:]]})
        except FileNotFoundError:
            return jsonify({"lines": ["Log file not found"]})

    @app.route("/api/sensors")
    def api_sensors():
        data = {}
        for zone in config["zones"]:
            latest = db.get_latest_soil(zone["soil_sensor"])
            data[zone["id"]] = latest
        return jsonify(data)

    @app.route("/api/sensor-history")
    def api_sensor_history():
        """Soil or DHT22 history for drill-down charts."""
        sensor_type = request.args.get("type", "soil")
        hours = query_int("hours", 24, min_value=1, max_value=87600)
        if sensor_type == "soil":
            idx = query_int("index", 0, min_value=0, max_value=len(config["zones"]) - 1)
            conn = db.get_conn()
            rows = conn.execute(
                "SELECT soil_pct, soil_raw, ts FROM sensor_log WHERE zone_id = ? "
                "AND ts >= datetime('now','localtime',?) ORDER BY ts",
                (idx, f"-{hours} hours"),
            ).fetchall()
            conn.close()
            return jsonify([{"ts": r["ts"], "pct": r["soil_pct"], "raw": r["soil_raw"]} for r in rows])
        elif sensor_type == "dht22":
            conn = db.get_conn()
            rows = conn.execute(
                "SELECT ts, temp_f, humidity FROM weather_log "
                "WHERE source='dht22' AND ts >= datetime('now','localtime',?) ORDER BY ts",
                (f"-{hours} hours",),
            ).fetchall()
            conn.close()
            return jsonify([{"ts": r["ts"], "temp_f": r["temp_f"], "humidity": r["humidity"]} for r in rows])
        return jsonify([])

    @app.route("/api/dashboard")
    def api_dashboard():
        """Single endpoint returning all data the SPA needs."""
        # Non-blocking cached read — dashboard polls every 30s, multiple tabs are
        # common, and the chip's lwIP TIME_WAIT pool can't keep up if every
        # call opens a new TCP connection. See smart-garden-server#10.
        status_data = cached_esp32_status()
        # Debounced flag for the badge so a single transient failure doesn't
        # flip it red. Real status_data may still be None even when this is
        # True (e.g. fresh restart), so the JS should treat both signals.
        esp32_online = esp32_online_status()
        summary = status_summary()
        bill = billing.get_monthly_bill_estimate()
        savings = billing.get_savings_report()
        health = db.get_latest_health()

        # Zone soil readings
        zone_list = []
        planned_zones = []
        for zone in config["zones"]:
            installed = zone.get("installed", False)
            active = zone["id"] in summary.get("active_zones", [])

            if installed:
                latest = db.get_latest_soil(zone["soil_sensor"])
                soil_hist = db.get_soil_history(zone["soil_sensor"], days=7)
                anomaly = db.get_sensor_flatline(zone["soil_sensor"], hours=24)
            else:
                latest = None
                soil_hist = []
                anomaly = {"no_data": True, "flatline": False, "railed": False, "count": 0}

            entry = {
                "id": zone["id"],
                "name": zone["name"],
                "type": zone["type"],
                "installed": installed,
                "kc": zone["kc"],
                "dry_trigger": zone["dry_trigger"],
                "wet_target": zone["wet_target"],
                "max_runtime_min": zone["max_runtime_min"],
                "cycle_soak": zone.get("cycle_soak", False),
                "est_gpm": zone.get("est_gpm", 0),
                "soil_pct": latest["soil_pct"] if latest else None,
                "soil_raw": latest.get("soil_raw") if latest else None,
                "last_reading": latest["ts"] if latest else None,
                "watering": active,
                "history_7d": [
                    {"ts": p["ts"], "pct": p["soil_pct"]}
                    for p in (soil_hist or [])
                ],
                "anomaly": anomaly,
            }
            if installed:
                zone_list.append(entry)
            else:
                planned_zones.append(entry)

        # Recent events (last 30 of each type)
        waterings = db.get_watering_history(7)
        skips = db.get_skip_history(7)

        # Test sensors — connected but not assigned to any zone
        sensors_cfg = config.get("sensors", {})
        test_sensors = []
        for key, connected in sensors_cfg.items():
            if not connected:
                continue
            if key.startswith("soil_"):
                idx = int(key.split("_")[1])
                latest = db.get_latest_soil(idx)
                anomaly = db.get_sensor_flatline(idx, hours=24)
                hist = db.get_soil_history(idx, days=7)
                test_sensors.append({
                    "type": "soil",
                    "index": idx,
                    "label": f"Soil Sensor {idx}",
                    "soil_pct": latest["soil_pct"] if latest else None,
                    "soil_raw": latest.get("soil_raw") if latest else None,
                    "last_reading": latest["ts"] if latest else None,
                    "anomaly": anomaly,
                    "history_7d": [{"ts": p["ts"], "pct": p["soil_pct"]} for p in (hist or [])],
                })
            elif key == "dht22":
                test_sensors.append({
                    "type": "dht22",
                    "index": None,
                    "label": "DHT22 (Temp/Humidity)",
                })

        recent = []
        for w in (waterings or []):
            recent.append({
                "type": "water", "ts": w["start_ts"],
                "zone_id": w["zone_id"],
                "detail": f"{round(w['duration_sec'] / 60, 1)} min"
                          if w.get("duration_sec") else "in progress",
                "gallons": round(w["est_gallons"], 1) if w.get("est_gallons") else None,
            })
        for s in (skips or []):
            recent.append({
                "type": "skip", "ts": s["ts"],
                "zone_id": s["zone_id"],
                "detail": s["reason"],
                "gallons_saved": round(s["est_gallons_saved"], 1)
                                 if s.get("est_gallons_saved") else None,
            })
        recent.sort(key=lambda x: x["ts"], reverse=True)

        # Billing tiers config for visualization
        tiers = []
        for t in config["billing"]["tiers"]:
            tiers.append({"max_cf": t["max_cf"], "rate": t["rate"]})

        return jsonify({
            "now": datetime.now().isoformat(),
            "esp32": _apply_esp32_inversion(status_data) if status_data else None,
            "esp32_online": esp32_online,
            "connectivity": db.get_last_connectivity(),
            "connectivity_recent": db.get_connectivity_history(hours=1),
            "sensor_faults": db.get_sensor_faults(),
            "weather": summary.get("weather"),
            "et0_today": summary.get("et0_today", 0),
            "rain_last_24h": summary.get("rain_last_24h", 0),
            "rain_forecast": summary.get("rain_forecast"),
            "season": summary.get("season"),
            "forecast_7day": summary.get("forecast_7day"),
            "weather_scale": summary.get("weather_scale"),
            "bill": bill,
            "savings": savings,
            "budget": summary.get("budget"),
            "health": dict(health) if health else None,
            "zones": zone_list,
            "planned_zones": planned_zones,
            "test_sensors": test_sensors,
            "recent": recent[:30],
            "tiers": tiers,
            "soil_balances": summary.get("soil_balances", []),
            "config": {
                "base_fee": config["billing"]["base_fee"],
                "sewer_flat": config["billing"]["sewer_flat"],
                "storm_flat": config["billing"]["storm_flat"],
                "watering_window": config["watering_window"],
                "skip_rules": config["skip_rules"],
                "weather_adjustment": config.get("weather_adjustment", {}),
            },
        })

    # ── Telemetry endpoint ──

    @app.route("/api/telemetry")
    def api_telemetry():
        """All available telemetry: ESP32 events, valve stats, raw ADC, full watering details."""
        esp_events = None
        valve_stats = None
        adc_scan = None

        # Keep this endpoint non-blocking. The telemetry panel can be opened
        # from multiple browser tabs, and live ESP32 calls here previously held
        # Waitress workers while the chip was refusing connections.
        status_data = cached_esp32_status()

        # Recent watering events with ALL columns
        waterings = db.get_watering_history(30)
        watering_detail = []
        for w in (waterings or []):
            watering_detail.append({
                "id": w.get("id"),
                "zone_id": w["zone_id"],
                "zone_name": next((z["name"] for z in config["zones"] if z["id"] == w["zone_id"]), f"Zone {w['zone_id'] + 1}"),
                "start_ts": w["start_ts"],
                "end_ts": w.get("end_ts"),
                "duration_sec": w.get("duration_sec"),
                "soil_before": w.get("soil_before"),
                "soil_after": w.get("soil_after"),
                "et_demand_mm": w.get("et_demand_mm"),
                "est_gallons": w.get("est_gallons"),
                "est_cf": w.get("est_cf"),
                "trigger_reason": w.get("trigger_reason"),
            })

        # Recent skip events with ALL columns including conditions JSON
        skips = db.get_skip_history(30)
        skip_detail = []
        for s in (skips or []):
            skip_detail.append({
                "id": s.get("id"),
                "zone_id": s["zone_id"],
                "zone_name": next((z["name"] for z in config["zones"] if z["id"] == s["zone_id"]), f"Zone {s['zone_id'] + 1}"),
                "ts": s["ts"],
                "reason": s["reason"],
                "est_gallons_saved": s.get("est_gallons_saved"),
                "est_cf_saved": s.get("est_cf_saved"),
                "conditions": s.get("conditions"),
            })

        # System health history (last 10 entries)
        health_history = db.get_health_history(10)

        # Latest weather log entries
        weather_recent = db.get_weather_timeseries(1)

        return jsonify({
            "esp32_status": dict(status_data) if status_data else None,
            "esp32_events": esp_events,
            "valve_stats": valve_stats,
            "adc_scan": adc_scan,
            "watering_events": watering_detail,
            "skip_events": skip_detail,
            "health_history": health_history,
            "weather_recent": weather_recent,
            "weather_scale": status_summary().get("weather_scale"),
        })

    # ── Analytics API endpoints ──

    @app.route("/api/analytics/overview")
    def api_analytics_overview():
        days = query_int("days", 30, min_value=1, max_value=3650)
        return jsonify(db.get_analytics_overview(days))

    @app.route("/api/analytics/decisions")
    def api_analytics_decisions():
        days = query_int("days", 30, min_value=1, max_value=3650)
        zone_id = optional_query_int("zone", min_value=0, max_value=len(config["zones"]) - 1)
        limit = query_int("limit", 500, min_value=1, max_value=2000)
        offset = query_int("offset", 0, min_value=0)
        rows = db.get_decision_log(days, zone_id, limit, offset)
        return jsonify(rows)

    @app.route("/api/analytics/soil")
    def api_analytics_soil():
        days = query_int("days", 7, min_value=1, max_value=3650)
        zone_id = optional_query_int("zone", min_value=0, max_value=len(config["zones"]) - 1)
        if zone_id is not None:
            data = {zone_id: db.get_soil_timeseries(zone_id, days)}
        else:
            data = {}
            seen = set()
            for zone in config["zones"]:
                sid = zone["soil_sensor"]
                if sid not in seen:
                    seen.add(sid)
                    data[zone["id"]] = db.get_soil_timeseries(sid, days)
        return jsonify(data)

    @app.route("/api/analytics/usage")
    def api_analytics_usage():
        days = query_int("days", 30, min_value=1, max_value=3650)
        usage = db.get_daily_water_usage(days)
        savings = db.get_daily_savings(days)
        return jsonify({"usage": usage, "savings": savings})

    @app.route("/api/analytics/skip-reasons")
    def api_analytics_skip_reasons():
        days = query_int("days", 30, min_value=1, max_value=3650)
        return jsonify(db.get_skip_reason_breakdown(days))

    @app.route("/api/analytics/weather")
    def api_analytics_weather():
        days = query_int("days", 7, min_value=1, max_value=3650)
        return jsonify(db.get_weather_timeseries(days))

    # ── Soil Water Balance API ──

    @app.route("/api/balance")
    def api_balance():
        """Get current soil water balance for all zones."""
        return jsonify(db.get_all_balances())

    @app.route("/api/balance/<int:zone_id>")
    def api_balance_history(zone_id):
        """Get soil water balance history for a zone."""
        days = query_int("days", 30, min_value=1, max_value=3650)
        return jsonify(db.get_soil_balance_history(zone_id, days))

    @app.route("/api/balance/update", methods=["POST"])
    def api_balance_update():
        """Manually trigger soil water balance update for all zones."""
        try:
            engine.update_daily_balances()
            return jsonify({"ok": True, "balances": db.get_all_balances()})
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)}), 500

    # ── Configuration API ──

    @app.route("/api/config")
    def api_get_config():
        """Return the full live config."""
        return jsonify(config)

    @app.route("/api/config", methods=["POST"])
    def api_save_config():
        """Update config in memory and persist to config.yaml."""
        patch = request.get_json(force=True)
        if not patch or not isinstance(patch, dict):
            return jsonify({"ok": False, "error": "Invalid JSON"}), 400

        # Whitelist of editable sections
        editable = {
            "zones", "watering_window", "skip_rules",
            "weather_adjustment", "esp32",
        }
        changed = []
        for key in patch:
            if key not in editable:
                continue
            if key == "zones":
                # Merge per-zone fields (don't allow adding/removing zones)
                incoming = patch["zones"]
                if not isinstance(incoming, list):
                    continue
                for zp in incoming:
                    zid = zp.get("id")
                    if zid is None:
                        continue
                    target = next((z for z in config["zones"] if z["id"] == zid), None)
                    if not target:
                        continue
                    for field in ("name", "type", "heads", "description",
                                  "kc", "dry_trigger", "wet_target",
                                  "max_runtime_min", "cycle_soak",
                                  "cycle_run_min", "cycle_soak_min",
                                  "cycle_count", "soil_sensor", "est_gpm",
                                  "precip_rate_iph", "installed"):
                        if field in zp:
                            target[field] = zp[field]
                changed.append("zones")
            else:
                config[key] = patch[key]
                changed.append(key)

        # Persist atomically so watchdog restarts never read a truncated config.
        write_config_atomic(config)

        # Update engine's config reference
        engine.config = config
        engine.zones = {z["id"]: z for z in config["zones"]}

        return jsonify({"ok": True, "changed": changed})

    # ── System Telemetry Endpoints ──

    @app.route("/api/server-health")
    def api_server_health():
        """Server-side health: disk, DB size, CPU temp, row counts."""
        return jsonify(db.get_server_health())

    @app.route("/api/server-health-history")
    def api_server_health_history():
        """Time-series of server disk %, DB size, CPU temp."""
        hours = query_int("hours", 24, min_value=1, max_value=87600)
        return jsonify(db.get_server_health_history(hours))

    @app.route("/api/sensor-gaps")
    def api_sensor_gaps():
        """Find gaps in sensor readings exceeding expected poll interval."""
        zone_id = query_int("zone", 0, min_value=0, max_value=len(config["zones"]) - 1)
        hours = query_int("hours", 24, min_value=1, max_value=87600)
        return jsonify(db.get_sensor_gaps(zone_id, hours))

    @app.route("/api/valve-health")
    def api_valve_health():
        """Get valve open/close counts from cached ESP32 status."""
        data = cached_esp32_status()
        if data is None:
            return jsonify({
                "ok": False,
                "esp32_reachable": False,
                "valves": [],
                "totalOpens": 0,
                "totalCloses": 0,
                "error": "ESP32 unreachable",
            })
        valves = data.get("valves", [])
        health_data = data.get("health", {})
        return jsonify({
            "ok": True,
            "esp32_reachable": True,
            "valves": [{"id": i, "openCount": v.get("openCount", 0),
                        "closeCount": v.get("closeCount", 0)}
                       for i, v in enumerate(valves)],
            "totalOpens": health_data.get("totalValveOpens", 0),
            "totalCloses": health_data.get("totalValveCloses", 0),
        })

    # ═══ Water Meter Cam proxy ═══
    CAM_URL = "http://192.168.0.160"

    # In-memory storage for latest pushed image
    cam_state = {"image": None, "timestamp": None, "flash": False, "ocr_count": 0}
    meter_reader = MeterReader()

    @app.route("/api/cam/upload", methods=["POST"])
    def cam_upload():
        """Receive a JPEG push from the ESP32-CAM."""
        data = request.get_data()
        if not data or len(data) < 100:
            return jsonify({"error": "No image data"}), 400
        cam_state["image"] = data
        cam_state["timestamp"] = datetime.now().isoformat()
        cam_state["ocr_count"] += 1
        # OCR paused — uncomment to re-enable
        # if meter_reader.enabled and cam_state["ocr_count"] % 3 == 0:
        #     from threading import Thread
        #     Thread(target=meter_reader.process, args=(data,), daemon=True).start()
        return "OK", 200

    @app.route("/api/cam/latest")
    def cam_latest():
        """Serve the most recently pushed image."""
        if not cam_state["image"]:
            return jsonify({"error": "No image yet"}), 404
        return Response(cam_state["image"], mimetype="image/jpeg",
                       headers={"Cache-Control": "no-cache"})

    @app.route("/api/cam/status")
    def cam_status():
        """Return cam metadata."""
        return jsonify({
            "has_image": cam_state["image"] is not None,
            "timestamp": cam_state["timestamp"],
            "size": len(cam_state["image"]) if cam_state["image"] else 0,
        })

    @app.route("/api/cam/readings")
    def cam_readings_api():
        """Return OCR meter readings."""
        limit = request.args.get("limit", 100, type=int)
        return jsonify({
            "readings": meter_reader.get_readings(limit),
            "enabled": meter_reader.enabled,
            "orientation": meter_reader.orientation,
            "avg_rate": round(meter_reader.avg_rate, 4),
        })

    @app.route("/api/cam/capture")
    def cam_capture():
        """Proxy a JPEG capture from the ESP32-CAM (fallback)."""
        try:
            r = http_requests.get(f"{CAM_URL}/capture", timeout=5)
            return Response(r.content, mimetype="image/jpeg",
                           headers={"Cache-Control": "no-cache"})
        except Exception as e:
            # Fall back to latest pushed image
            if cam_state["image"]:
                return Response(cam_state["image"], mimetype="image/jpeg",
                               headers={"Cache-Control": "no-cache"})
            return jsonify({"error": str(e)}), 502

    @app.route("/api/cam/flash", methods=["POST"])
    def cam_flash():
        """Toggle the ESP32-CAM flash LED."""
        try:
            r = http_requests.get(f"{CAM_URL}/flash", timeout=3)
            return jsonify({"status": r.text})
        except Exception as e:
            return jsonify({"error": str(e)}), 502

    return app
