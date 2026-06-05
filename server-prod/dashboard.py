"""Flask dashboard for Smart Garden Server.

Serves a web UI at http://acer:5125 with:
- Live sensor readings and valve status
- Weather conditions and 7-day forecast
- Watering history and skip log
- Billing/savings tracker with Duvall tier visualization
- Manual valve controls
"""

import json
import logging
import os
import tempfile
from datetime import datetime

import requests as http_requests
import yaml
from flask import make_response, Response, Flask, render_template, request, jsonify, redirect, url_for

import database as db
from irrigation import ESP32_MANUAL_TIMEOUT
from cam_ocr import MeterReader
import seasonal

log = logging.getLogger("smart-garden")


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
        except Exception as e:
            log.warning("cached_esp32_status failed: %s", e)
            return None

    def esp32_online_status():
        try:
            return bool(getattr(engine, "is_esp32_online", lambda: False)())
        except Exception as e:
            log.warning("esp32_online_status failed: %s", e)
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
        except Exception as e:
            log.warning("status_summary failed, using fallback: %s", e)
            return fallback

    def fresh_valves():
        """Fetch live valve state from ESP32 after a manual toggle."""
        try:
            status = getattr(engine, "get_esp32_status", lambda **kwargs: None)(
                force_fresh=True
            )
        except Exception as e:
            log.warning("fresh_valves: ESP32 status fetch failed: %s", e)
            status = None
        return apply_inversion((status or {}).get("valves", []))

    def engine_command(name, *args, **kwargs):
        method = getattr(engine, name, None)
        if method is None:
            return False
        try:
            return bool(method(*args, **kwargs))
        except Exception as e:
            log.warning("engine_command(%s) failed: %s", name, e)
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
    # Shared secret the ESP32-CAM sends as X-Cam-Token. Only enforced for
    # requests that arrive over the cloudflare tunnel (internet); direct LAN
    # posts from the cam don't need it (see cam_upload). Empty = not configured.
    CAM_UPLOAD_SECRET = os.environ.get("CAM_UPLOAD_SECRET", "")
    # Hard cap on a pushed frame (buffered into RAM). Real cam JPEGs are ~20-80KB.
    CAM_MAX_UPLOAD_BYTES = 1_000_000
    SESSION_MAX_AGE = 86400 * 30  # 30 days
    ALLOWED_EMAILS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "allowed_emails.json")
    _allowed_emails_cache = {"mtime": 0.0, "emails": frozenset()}

    def _load_allowed_emails():
        # Called from check_auth() @before_request, so it ran once per HTTP
        # request. Cache by mtime so disk only hits when the file actually changes.
        try:
            mtime = os.path.getmtime(ALLOWED_EMAILS_FILE)
        except OSError:
            return frozenset()
        if mtime != _allowed_emails_cache["mtime"]:
            try:
                with open(ALLOWED_EMAILS_FILE) as f:
                    _allowed_emails_cache["emails"] = frozenset(
                        e["email"].lower() for e in auth_json.load(f)
                    )
                _allowed_emails_cache["mtime"] = mtime
            except Exception as e:
                log.warning("_load_allowed_emails: failed to parse %s: %s", ALLOWED_EMAILS_FILE, e)
                return frozenset()
        return _allowed_emails_cache["emails"]

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
        except Exception as e:
            # Debug because malformed/garbage cookies from scanners hit this regularly.
            log.debug("_verify_session_token rejected: %s", e)
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
        except Exception as e:
            log.warning("_verify_google_token failed: %s", e)
            return None

    @app.before_request
    def check_auth():
        # Public routes
        public = ("/login", "/auth/", "/favicon.ico", "/static/", "/api/cam/upload")
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
        # SameSite=Strict: cookie is never sent on cross-site requests. App is
        # bookmarked / typed directly, so Strict is fine and blocks CSRF.
        resp.set_cookie("session", token, max_age=SESSION_MAX_AGE, httponly=True, samesite="Strict", secure=True)
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

    @app.route("/api/seasonal-outlook")
    def api_seasonal_outlook():
        """6-month SEAS5 forecast vs ERA5 5-yr normal. 24h cache."""
        force = request.args.get("refresh") == "1"
        loc = config.get("location", {})
        lat = loc.get("lat", loc.get("latitude", 47.74))
        lon = loc.get("lon", loc.get("longitude", -121.99))
        tz = loc.get("timezone", "America/Los_Angeles")
        try:
            out = seasonal.get_seasonal_outlook(lat, lon, tz, force_refresh=force)
            return jsonify(out)
        except Exception as e:
            return jsonify({"error": str(e), "months": []}), 500

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
                "auto_mode": zone.get("auto_mode", True),
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
                "auto_mode": zone_cfg.get("auto_mode", True),
                "type": zone_cfg.get("type", "sprinkler"),
                "precip_rate_iph": zone_cfg.get("precip_rate_iph", 1.0),
                "kc": zone_cfg.get("kc", [0.90, 0.90, 0.90, 0.90]),
                "root_depth_in": zone_cfg.get("root_depth_in", 6),
                "taw_in": zone_cfg.get("taw_in", 1.2),
                "mad_pct": zone_cfg.get("mad_pct", 50),
                "heads": zone_cfg.get("heads", 4),
                "est_gpm": zone_cfg.get("est_gpm", 4.0),
                "area_sqft": zone_cfg.get("area_sqft", 0),
                "max_runtime_min": zone_cfg.get("max_runtime_min", 30),
                "wet_target": zone_cfg.get("wet_target", 90),
                "dry_trigger": zone_cfg.get("dry_trigger", 30),
                "soil_sensor": zone_cfg.get("soil_sensor", 0),
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
        # Show installed zones + all drip zones (so Garden/Grapes stay visible for monitoring even when disabled)
        zones = [z for z in config["zones"] if z.get("installed", False) or z.get("type") == "drip"]
        water_groups = config.get("water_groups") or {}
        return render_template("moisture_sim.html", zones=zones,
                               water_groups=water_groups)

    @app.route("/api/zone-config", methods=["POST"])
    def api_zone_config_update():
        """Update tunable zone parameters (precip rate, root depth, etc.)."""
        data = request.get_json(silent=True) or {}
        zone_id = data.get("zone_id")
        if zone_id is None:
            return jsonify({"ok": False, "error": "zone_id required"}), 400

        zone_cfg = None
        zone_idx = None
        for i, z in enumerate(config["zones"]):
            if z["id"] == zone_id:
                # Work on a COPY, not the live dict. config["zones"][i] is the
                # same object the engine reads, so mutating it here would push
                # half-validated values into the running engine even when we
                # later reject the request with 400. Only commit on success.
                zone_cfg = dict(z)
                zone_idx = i
                break
        if zone_cfg is None:
            return jsonify({"ok": False, "error": "Zone not found"}), 404

        # Apply allowed fields
        allowed = {
            "precip_rate_iph": (0.05, 10.0),
            "root_depth_in": (2, 36),
            "heads": (1, 20),
            "est_gpm": (0.1, 40.0),
            "area_sqft": (10, 10000),
            "max_runtime_min": (1, 120),
            "wet_target": (50, 100),
            "dry_trigger": (10, 60),
            "mad_pct": (20, 80),
        }
        changes = {}
        for key, (lo, hi) in allowed.items():
            if key in data and data[key] is not None:
                val = float(data[key])
                val = max(lo, min(hi, val))
                zone_cfg[key] = round(val, 3)
                changes[key] = zone_cfg[key]

        # Integer-only: soil sensor channel (0-7)
        if "soil_sensor" in data and data["soil_sensor"] is not None:
            try:
                sid = int(data["soil_sensor"])
                if 0 <= sid <= 7:
                    zone_cfg["soil_sensor"] = sid
                    changes["soil_sensor"] = sid
            except (TypeError, ValueError):
                pass

        # Boolean: Manual/Automatic mode
        if "auto_mode" in data and data["auto_mode"] is not None:
            zone_cfg["auto_mode"] = bool(data["auto_mode"])
            changes["auto_mode"] = zone_cfg["auto_mode"]

        # Kc array (for garden/grapes)
        if "kc" in data and isinstance(data["kc"], list):
            kc = [max(0.1, min(1.5, float(v))) for v in data["kc"][:4]]
            zone_cfg["kc"] = kc
            changes["kc"] = kc

        if not changes:
            return jsonify({"ok": False, "error": "No valid fields"}), 400

        # Cross-field sanity: the engine waters below dry_trigger and stops
        # at wet_target, so wet_target must sit meaningfully above dry_trigger
        # or the zone either never refills or thrashes. Reject incoherent
        # combinations instead of silently persisting them.
        wt = zone_cfg.get("wet_target")
        dt = zone_cfg.get("dry_trigger")
        if wt is not None and dt is not None and wt <= dt + 5:
            return jsonify({
                "ok": False,
                "error": "Wet Target must be at least 5%% above Dry Trigger "
                         "(got wet=%g, dry=%g)" % (wt, dt),
            }), 400

        # Write updated config
        config["zones"][zone_idx] = zone_cfg
        write_config_atomic(config)

        return jsonify({"ok": True, "changes": changes})

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
            # Route the raw toggle through start_zone_watering so the run
            # is tracked in _active and writes a watering_event row.
            # Without this, get_daily_irrigation_mm() never credits manual
            # toggle runs and the scheduler thinks the zone still needs
            # water. Mirrors what /api/run does. See issue #2.
            soil = db.get_latest_soil(zone_id)
            soil_pct = soil["soil_pct"] if soil else 0
            ok = engine_command(
                "start_zone_watering",
                zone_id, soil_pct, 0, "manual_toggle",
                allow_weather_fetch=False,
                command_timeout=ESP32_MANUAL_TIMEOUT,
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

    @app.route("/api/sensor-test", methods=["POST"])
    def api_sensor_test():
        """Toggle the ESP32's fast-sample test mode so soil sensors update
        quickly while testing, then auto-revert to hourly. Safe — the firmware
        caps the window and reverts on its own (cannot drain the battery)."""
        body = request.get_json(silent=True) or {}
        on = bool(body.get("on", True))
        # Default: 5 min window at 5s interval. 0 seconds = turn off.
        seconds = int(body.get("seconds", 300)) if on else 0
        interval = int(body.get("interval", 5))
        ok, msg = engine.set_fast_sample(seconds, interval)
        return jsonify({"ok": ok, "message": msg}), (200 if ok else 502)

    @app.route("/api/sensor-live")
    def api_sensor_live():
        """Live soil readings straight from the ESP32 (bypasses the DB), plus
        the fast-sample status. Used by the dashboard's Sensor Test panel."""
        status = engine.get_esp32_status(force_fresh=True) or {}
        soil = status.get("soil", []) or []
        sysd = status.get("system", {}) or {}
        pins = [32, 33, 34, 35]
        sensors = []
        for i, s in enumerate(soil):
            sensors.append({
                "index": i,
                "gpio": pins[i] if i < len(pins) else None,
                "name": s.get("name"),
                "raw": s.get("raw"),
                "pct": s.get("pct"),
            })
        return jsonify({
            "ok": bool(status),
            "sensors": sensors,
            "fast_active": sysd.get("fastSampleActive", False),
            "remain_sec": sysd.get("fastSampleRemainSec", 0),
            "interval_sec": sysd.get("sampleIntervalSec"),
        })

    @app.route("/api/rain-events")
    def api_rain_events():
        """Recent soil-rise / wetting events classified as rain / irrigation /
        unexplained. Observe-only — does not affect watering decisions yet."""
        days = query_int("days", 7, min_value=1, max_value=90)
        events = db.get_rain_events(days)
        counts = {"rain": 0, "irrigation": 0, "unexplained": 0}
        for e in events:
            c = e.get("classification")
            if c in counts:
                counts[c] += 1
        return jsonify({"events": events, "counts": counts, "days": days})

    # ── Soil sensor calibration (live, no firmware reflash) ──

    def _calibration_snapshot():
        """Live raw readings + each sensor's stored calibration + computed pct."""
        status = engine.get_esp32_status(force_fresh=True) or {}
        soil = status.get("soil", []) or []
        sysd = status.get("system", {}) or {}
        sensors_cfg = config.get("sensors", {})
        out = []
        # Cover every configured calibration slot plus any soil channel the chip
        # reports, so newly-wired sensors show up even before config is updated.
        n = max(len(soil), 4)
        for idx in range(n):
            cal = engine.get_soil_calibration(idx)
            raw = soil[idx].get("raw") if idx < len(soil) else None
            out.append({
                "index": idx,
                "name": cal["name"],
                "dry": cal["dry"],
                "wet": cal["wet"],
                "raw": raw,
                "pct": engine.soil_raw_to_pct(idx, raw),
                "enabled": bool(sensors_cfg.get(f"soil_{idx}", False)),
            })
        return {
            "sensors": out,
            "fast_active": sysd.get("fastSampleActive", False),
            "remain_sec": sysd.get("fastSampleRemainSec", 0),
            "esp32_ok": bool(status),
        }

    def _save_calibration(idx, *, dry=None, wet=None, name=None):
        """Persist one sensor's calibration into config.yaml (atomic)."""
        cal = config.get("soil_calibration")
        if not isinstance(cal, dict):
            cal = {}
            config["soil_calibration"] = cal
        # YAML may load keys as int; normalize to int and clean any str dupes.
        entry = cal.get(idx) or cal.get(str(idx)) or {}
        cal.pop(str(idx), None)
        if name is not None:
            entry["name"] = name
        if dry is not None:
            entry["dry"] = int(dry)
        if wet is not None:
            entry["wet"] = int(wet)
        entry.setdefault("name", f"Soil {idx}")
        entry.setdefault("dry", engine.SOIL_DEFAULT_DRY)
        entry.setdefault("wet", engine.SOIL_DEFAULT_WET)
        cal[idx] = entry
        write_config_atomic(config)
        return entry

    @app.route("/api/calibration")
    def api_calibration():
        """Current calibration + live raw readings for the calibrate UI."""
        return jsonify(_calibration_snapshot())

    @app.route("/api/calibration/capture", methods=["POST"])
    def api_calibration_capture():
        """Capture the live raw reading as this sensor's dry or wet endpoint.

        Body: {"index": 0, "point": "dry"|"wet"}. Reads a fresh raw value from
        the ESP32 and stores it as the chosen endpoint in config.yaml.
        """
        data = request.get_json(silent=True) or {}
        try:
            idx = int(data.get("index"))
        except (TypeError, ValueError):
            return jsonify({"ok": False, "error": "index required"}), 400
        point = data.get("point")
        if point not in ("dry", "wet"):
            return jsonify({"ok": False, "error": "point must be 'dry' or 'wet'"}), 400
        status = engine.get_esp32_status(force_fresh=True) or {}
        soil = status.get("soil", []) or []
        if idx < 0 or idx >= len(soil):
            return jsonify({"ok": False, "error": "sensor not reported by ESP32"}), 400
        raw = soil[idx].get("raw")
        try:
            raw = int(raw)
        except (TypeError, ValueError):
            return jsonify({"ok": False, "error": "no raw reading"}), 400
        # Guard against capturing a dead/railed reading as an endpoint.
        if raw <= engine.SOIL_RAW_MIN or raw >= engine.SOIL_RAW_MAX:
            return jsonify({"ok": False, "error": f"reading {raw} looks invalid (dead/disconnected) — not captured"}), 400
        entry = _save_calibration(idx, **{point: raw})
        # Record for drift history (reference-state capture over time).
        try:
            db.log_calibration(idx, point, raw, source="capture")
        except Exception as e:
            log.warning("log_calibration failed: %s", e)
        return jsonify({"ok": True, "index": idx, "point": point, "raw": raw, "calibration": entry})

    @app.route("/api/calibration/set", methods=["POST"])
    def api_calibration_set():
        """Manually set a sensor's dry/wet/name. Body: {index, dry?, wet?, name?}."""
        data = request.get_json(silent=True) or {}
        try:
            idx = int(data.get("index"))
        except (TypeError, ValueError):
            return jsonify({"ok": False, "error": "index required"}), 400
        dry = data.get("dry")
        wet = data.get("wet")
        name = data.get("name")
        try:
            dry = int(dry) if dry is not None else None
            wet = int(wet) if wet is not None else None
        except (TypeError, ValueError):
            return jsonify({"ok": False, "error": "dry/wet must be integers"}), 400
        if dry is not None and wet is not None and dry == wet:
            return jsonify({"ok": False, "error": "dry and wet cannot be equal"}), 400
        entry = _save_calibration(idx, dry=dry, wet=wet, name=name)
        # Record manual endpoint edits for drift history too.
        try:
            if dry is not None:
                db.log_calibration(idx, "dry", dry, source="manual")
            if wet is not None:
                db.log_calibration(idx, "wet", wet, source="manual")
        except Exception as e:
            log.warning("log_calibration (manual) failed: %s", e)
        return jsonify({"ok": True, "index": idx, "calibration": entry})

    @app.route("/api/calibration/history")
    def api_calibration_history():
        """Calibration capture history + computed drift per sensor/endpoint."""
        idx = optional_query_int("index", min_value=0, max_value=7)
        return jsonify({
            "drift": db.get_calibration_drift(),
            "history": db.get_calibration_history(idx, limit=60),
        })

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

    @app.route("/api/vacation", methods=["GET", "POST"])
    def api_vacation():
        """Global vacation/pause-all-auto flag.

        GET  -> {enabled: bool}
        POST -> {enabled: bool} sets the flag, persists to config.yaml,
                and is picked up by the engine on the next evaluate_zone()
                call (no restart needed because engine.config is the
                same dict object).
        """
        if request.method == "POST":
            data = request.get_json(silent=True) or {}
            enabled = bool(data.get("enabled"))
            config["vacation_mode"] = enabled
            write_config_atomic(config)
        return jsonify({"enabled": bool(config.get("vacation_mode", False))})

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
                "auto_mode": zone.get("auto_mode", True),
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
            dur_sec = w.get("duration_sec")
            if dur_sec:
                # Sub-minute runs (manual tests, drip pulses) read as "0.0 min" — show seconds.
                detail = f"{dur_sec} sec" if dur_sec < 60 else f"{round(dur_sec / 60, 1)} min"
            else:
                detail = "in progress"
            recent.append({
                "type": "water", "ts": w["start_ts"],
                "zone_id": w["zone_id"],
                "detail": detail,
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
        """Receive a JPEG push from the ESP32-CAM.

        The cam pushes directly over the LAN and can't do OAuth, so this route
        is exempt from the session-cookie check. But it's also reachable from
        the internet via the cloudflare tunnel, so we can't let anyone POST
        images (issue #16: spam / image-poisoning). Rule:
          - Tunnel (internet) requests carry Cf-* headers — they MUST present a
            valid X-Cam-Token shared secret or get 401.
          - Direct LAN posts (no Cf-* headers, can't be forged from the
            internet because port 5125 isn't forwarded) are allowed without a
            token so the cam keeps working without a firmware reflash.
        """
        via_tunnel = bool(request.headers.get("Cf-Connecting-Ip")
                          or request.headers.get("Cf-Ray"))
        if via_tunnel:
            token = request.headers.get("X-Cam-Token", "")
            if not (CAM_UPLOAD_SECRET and token
                    and hmac.compare_digest(token, CAM_UPLOAD_SECRET)):
                log.warning("cam_upload: rejected tunnel request without valid token from %s",
                            request.headers.get("Cf-Connecting-Ip", "?"))
                return jsonify({"error": "unauthorized"}), 401
        data = request.get_data(cache=False)
        if not data or len(data) < 100:
            return jsonify({"error": "No image data"}), 400
        if len(data) > CAM_MAX_UPLOAD_BYTES:
            return jsonify({"error": "image too large"}), 413
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

    # ── DB-table audit (catch silently-empty / silently-stale tables) ──
    # (name, ts_col, ts_is_date, max_age_hours_or_None, label)
    AUDIT_TABLE_SPECS = [
        ("sensor_log",        "ts",          False, None, "DISABLED — all soil_* gates off in config.yaml"),
        ("weather_log",       "ts",          False, 1,    "Weather observations"),
        ("watering_event",    "start_ts",    False, 168,  "Watering events (sparse — days between OK)"),
        ("skip_event",        "ts",          False, 25,   "Per-zone skip decisions (deduped per zone per day)"),
        ("daily_summary",     "date",        True,  48,   "Nightly cost/savings rollup"),
        ("billing_cycle",     "month",       True,  None, "Monthly bill cache (KNOWN UNUSED — dead schema)"),
        ("system_health",     "ts",          False, 1,    "ESP32 health (rssi/heap/temp)"),
        ("soil_balance",      "date",        True,  48,   "Per-zone water balance (nightly)"),
        ("connectivity_log",  "ts",          False, 1,    "ESP32 reachability log"),
        ("cycle_summary",     "ts",          False, 1,    "Per-cycle aggregate decisions"),
        ("sensor_fault",      "detected_ts", False, None, "Active sensor fault flags (rare events)"),
        ("server_health_log", "ts",          False, 1,    "Pi disk/cpu/db-size"),
        ("forecast_snapshot", "ts",          False, 25,   "Daily forecast snapshot"),
    ]

    def _audit_one(conn, name, ts_col, is_date, max_age_h, label):
        try:
            row_count = conn.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
        except Exception as e:
            return {"table": name, "label": label, "status": "ERROR", "error": str(e)}
        last_ts = None
        rows_24h = 0
        if row_count > 0:
            try:
                last_ts = conn.execute(f"SELECT MAX({ts_col}) FROM {name}").fetchone()[0]
                if is_date:
                    rows_24h = conn.execute(
                        f"SELECT COUNT(*) FROM {name} "
                        f"WHERE {ts_col} >= date('now','localtime','-1 day')"
                    ).fetchone()[0]
                else:
                    rows_24h = conn.execute(
                        f"SELECT COUNT(*) FROM {name} "
                        f"WHERE {ts_col} >= datetime('now','localtime','-1 day')"
                    ).fetchone()[0]
            except Exception as e:
                log.warning("audit(%s): MAX/COUNT failed: %s", name, e)
        age_hours = None
        if last_ts:
            try:
                if is_date and len(last_ts) == 7:
                    last_dt = datetime.strptime(last_ts + "-01", "%Y-%m-%d")
                    this_month_first = datetime.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
                    age_hours = max(0.0, (this_month_first - last_dt).total_seconds() / 3600)
                elif is_date:
                    last_dt = datetime.strptime(last_ts, "%Y-%m-%d")
                    today_midnight = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
                    age_hours = max(0.0, (today_midnight - last_dt).total_seconds() / 3600)
                else:
                    age_hours = (datetime.now() - datetime.strptime(last_ts[:19], "%Y-%m-%dT%H:%M:%S")).total_seconds() / 3600
            except Exception as e:
                log.debug("audit(%s): timestamp parse failed for %r: %s", name, last_ts, e)
        if row_count == 0:
            status = "EMPTY"
        elif max_age_h is not None and age_hours is not None and age_hours > max_age_h:
            status = "STALE"
        else:
            status = "OK"
        return {
            "table": name, "label": label, "rows": row_count, "rows_24h": rows_24h,
            "last_write": last_ts,
            "age_hours": round(age_hours, 2) if age_hours is not None else None,
            "max_age_hours": max_age_h, "status": status,
        }

    @app.route("/api/audit")
    def api_audit():
        """Runtime DB-table health audit — row counts, last writes, staleness flags."""
        conn = db.get_conn()
        try:
            tables = [_audit_one(conn, *spec) for spec in AUDIT_TABLE_SPECS]
        finally:
            conn.close()
        summary = {
            "ok":    sum(1 for r in tables if r["status"] == "OK"),
            "stale": sum(1 for r in tables if r["status"] == "STALE"),
            "empty": sum(1 for r in tables if r["status"] == "EMPTY"),
            "error": sum(1 for r in tables if r["status"] == "ERROR"),
        }
        return jsonify({
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "summary": summary,
            "tables": tables,
        })

    @app.route("/audit")
    def audit_page():
        """Self-contained HTML view of /api/audit — no template file needed."""
        html = """<!doctype html>
<html><head><meta charset="utf-8"><title>Smart Garden — System Audit</title>
<style>
body{font-family:-apple-system,BlinkMacSystemFont,sans-serif;margin:24px;background:#0f1419;color:#e6edf3;}
h1{margin:0 0 4px 0;font-size:20px;}
.sub{color:#7d8590;font-size:13px;margin-bottom:16px;}
.summary{display:flex;gap:12px;margin-bottom:18px;}
.pill{padding:8px 14px;border-radius:8px;font-size:13px;font-weight:600;}
.pill.ok{background:#1a3e2a;color:#7ee787;}
.pill.stale{background:#3e2e16;color:#f0b429;}
.pill.empty{background:#3e1a1a;color:#ff7b72;}
.pill.error{background:#3e1a1a;color:#ff7b72;}
table{border-collapse:collapse;width:100%;font-size:13px;background:#161b22;border-radius:8px;overflow:hidden;}
th{background:#21262d;text-align:left;padding:10px 12px;font-weight:600;color:#7d8590;}
td{padding:10px 12px;border-top:1px solid #21262d;vertical-align:top;}
.status{font-weight:600;padding:2px 8px;border-radius:4px;font-size:11px;text-transform:uppercase;}
.status.ok{background:#1a3e2a;color:#7ee787;}
.status.stale{background:#3e2e16;color:#f0b429;}
.status.empty{background:#3e1a1a;color:#ff7b72;}
.status.error{background:#3e1a1a;color:#ff7b72;}
.label{color:#7d8590;font-size:11px;}
.num{text-align:right;font-variant-numeric:tabular-nums;}
button{background:#21262d;border:1px solid #30363d;color:#e6edf3;padding:6px 14px;border-radius:6px;cursor:pointer;font-size:13px;}
button:hover{background:#30363d;}
a{color:#58a6ff;}
</style></head>
<body>
<h1>Smart Garden — DB Audit</h1>
<div class="sub" id="meta">Loading…</div>
<div class="summary" id="summary"></div>
<button onclick="load()">Refresh</button>
<p class="sub" style="margin-top:18px;">Catches silently-empty tables (no writer wired up) and silently-stale tables (writer broken). Bugs #4 (daily_summary) and #5 (skip_event) would have appeared here as EMPTY the day they shipped.</p>
<table id="t"><thead><tr>
<th>Table</th><th>Status</th><th class="num">Rows</th><th class="num">Last 24h</th>
<th>Last write</th><th class="num">Age (h)</th><th class="num">Max age</th>
</tr></thead><tbody></tbody></table>
<script>
async function load(){
  const r = await fetch('/api/audit');
  const d = await r.json();
  document.getElementById('meta').textContent = 'Generated ' + d.generated_at;
  const s = d.summary;
  document.getElementById('summary').innerHTML =
    `<span class="pill ok">${s.ok} OK</span>` +
    `<span class="pill stale">${s.stale} STALE</span>` +
    `<span class="pill empty">${s.empty} EMPTY</span>` +
    (s.error ? `<span class="pill error">${s.error} ERROR</span>` : '');
  const tb = document.querySelector('#t tbody');
  tb.innerHTML = '';
  for (const t of d.tables){
    const tr = document.createElement('tr');
    const fmt = (v) => v === null || v === undefined ? '—' : v;
    tr.innerHTML =
      `<td><strong>${t.table}</strong><div class="label">${t.label || ''}</div></td>` +
      `<td><span class="status ${t.status.toLowerCase()}">${t.status}</span></td>` +
      `<td class="num">${fmt(t.rows)}</td>` +
      `<td class="num">${fmt(t.rows_24h)}</td>` +
      `<td>${fmt(t.last_write)}</td>` +
      `<td class="num">${fmt(t.age_hours)}</td>` +
      `<td class="num">${fmt(t.max_age_hours)}</td>`;
    tb.appendChild(tr);
  }
}
load();
</script>
</body></html>"""
        return Response(html, mimetype="text/html")

    @app.route("/calibrate")
    def calibrate_page():
        """Self-contained soil-sensor calibration UI. Capture each sensor's
        dry (in air) and wet (in water) raw endpoints with a button — stored in
        config.yaml, applied server-side, no firmware reflash."""
        html = """<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Soil Sensor Calibration — Smart Garden</title>
<style>
body{font-family:-apple-system,BlinkMacSystemFont,sans-serif;margin:0;padding:16px;background:#0f1419;color:#e6edf3;}
h1{margin:0 0 2px 0;font-size:19px;}
.sub{color:#7d8590;font-size:13px;margin-bottom:14px;}
.bar{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-bottom:14px;}
button{background:#21262d;border:1px solid #30363d;color:#e6edf3;padding:8px 12px;border-radius:6px;cursor:pointer;font-size:13px;}
button:hover{background:#30363d;}
button:disabled{opacity:.5;cursor:default;}
.btn-dry{background:#3e2e16;border-color:#5c441f;color:#f0b429;}
.btn-wet{background:#16303e;border-color:#1f4a5c;color:#56b6e6;}
.btn-go{background:#1a3e2a;border-color:#1f5c3a;color:#7ee787;}
.card{background:#161b22;border:1px solid #21262d;border-radius:10px;padding:14px;margin-bottom:12px;}
.row{display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap;}
.nm{font-weight:600;font-size:15px;}
.live{font-variant-numeric:tabular-nums;}
.raw{font-size:26px;font-weight:700;}
.pct{font-size:22px;font-weight:700;}
.muted{color:#7d8590;font-size:12px;}
.endpoints{display:flex;gap:18px;margin:8px 0;font-size:13px;}
.endpoints b{color:#e6edf3;}
.drift{font-size:12px;color:#adbac7;margin:2px 0 8px;padding:6px 8px;background:#0d1117;border-radius:6px;}
.badge{padding:2px 8px;border-radius:4px;font-size:11px;font-weight:600;text-transform:uppercase;}
.b-ok{background:#1a3e2a;color:#7ee787;}
.b-bad{background:#3e1a1a;color:#ff7b72;}
.b-off{background:#21262d;color:#7d8590;}
.actions{display:flex;gap:8px;flex-wrap:wrap;margin-top:8px;}
.manual{margin-top:10px;display:flex;gap:6px;flex-wrap:wrap;align-items:center;}
.manual input{width:74px;background:#0d1117;border:1px solid #30363d;color:#e6edf3;border-radius:5px;padding:6px;font-size:13px;}
.manual input.nm{width:120px;}
.toast{position:fixed;bottom:16px;left:50%;transform:translateX(-50%);background:#1a3e2a;color:#7ee787;padding:10px 18px;border-radius:8px;font-size:14px;opacity:0;transition:opacity .2s;pointer-events:none;}
.toast.err{background:#3e1a1a;color:#ff7b72;}
.toast.show{opacity:1;}
a{color:#58a6ff;text-decoration:none;}
.help{background:#161b22;border:1px solid #21262d;border-radius:10px;padding:12px;margin-bottom:14px;font-size:13px;color:#adbac7;line-height:1.5;}
.help b{color:#e6edf3;}
</style></head>
<body>
<h1>🌱 Soil Sensor Calibration</h1>
<div class="sub">Capture each sensor's dry & wet endpoints — saved to the server, no reflash.
<a href="/">🏠 Home</a> · <a href="/moisture-sim">💧 Schedule</a> · <a href="/forecast">🌧️ Forecast</a> · <a href="/map">🗺️ Map</a></div>

<div class="help">
<b>How to calibrate (do it in the ground, the way it really sits):</b><br>
1. Click <b>Start Live Mode</b> so raw readings refresh every few seconds.<br>
2. <b>Saturate the soil</b> around the buried sensor (pour water / soak it), let the live raw <b>stop moving</b>, then tap <b>Set Wet</b>.<br>
3. Pull the sensor out, <b>dry it off</b> (wipe on your shirt, shake, blow on it), let it sit in air until the live raw <b>settles steady</b>, then tap <b>Set Dry</b>.<br>
<b>Wait for the number to stop changing before each capture</b> — there's a few-second lag while surface water clears. You're freezing two steady reference points, not timing the transition.<br>
<span style="color:#7d8590">Tip: saturated soil is a truer "100%" than a cup of water (cup reads wetter than soil ever gets).</span>
</div>

<div class="help" style="border-color:#1f4a5c">
<b>📉 Drift tracking:</b> Each time you recalibrate, we log the raw value of the dry/wet capture. Because those captures are always the <b>same physical reference</b> (air = dry, saturated = wet), any change between them is <b>real sensor drift</b> — not the seasonal moisture change that fools the in-ground reading. The drift number below shows how far each endpoint moved since your last calibration. Big jumps = the sensor is aging; recalibrate (and eventually replace).
</div>

<div class="bar">
  <button class="btn-go" id="liveBtn" onclick="startLive()">▶ Start Live Mode (fast readings)</button>
  <span class="muted" id="liveState">Live mode off — readings update hourly</span>
</div>

<div id="cards"></div>
<div class="toast" id="toast"></div>

<script>
var POLL_MS = 3000;
var pollTimer = null;

function toast(msg, isErr){
  var t = document.getElementById('toast');
  t.textContent = msg;
  t.className = 'toast show' + (isErr ? ' err' : '');
  setTimeout(function(){ t.className = 'toast' + (isErr ? ' err' : ''); }, 2500);
}

function fmt(v){ return (v===null||v===undefined) ? '—' : v; }

var DRIFT = {};  // "idx|point" -> drift entry

async function load(){
  try{
    var r = await fetch('/api/calibration');
    var d = await r.json();
    // Pull drift history in parallel (best-effort).
    try{
      var hr = await fetch('/api/calibration/history');
      var hd = await hr.json();
      DRIFT = {};
      (hd.drift||[]).forEach(function(e){ DRIFT[e.sensor_idx + '|' + e.point] = e; });
    }catch(e){}
    render(d);
  }catch(e){ /* keep last view */ }
}

function driftLine(idx){
  var dry = DRIFT[idx + '|dry'];
  var wet = DRIFT[idx + '|wet'];
  function part(label, e){
    if(!e) return label + ': <span class="muted">no history</span>';
    if(e.delta === null || e.delta === undefined)
      return label + ': <span class="muted">1 capture (' + e.latest_raw + ')</span>';
    var sign = e.delta > 0 ? '+' : '';
    var sev = Math.abs(e.delta) >= 300 ? 'color:#ff7b72' : Math.abs(e.delta) >= 120 ? 'color:#f0b429' : 'color:#7ee787';
    var rate = (e.drift_per_30d !== null && e.drift_per_30d !== undefined) ? ' (' + (e.drift_per_30d>0?'+':'') + e.drift_per_30d + '/mo)' : '';
    return label + ': <span style="' + sev + '">' + sign + e.delta + ' over ' + (e.days||'?') + 'd' + rate + '</span>';
  }
  return '<div class="drift">📉 drift since last cal — ' + part('dry', dry) + ' · ' + part('wet', wet) + '</div>';
}

function render(d){
  var liveState = document.getElementById('liveState');
  if(d.fast_active){
    liveState.textContent = '🟢 Live mode ON — ' + d.remain_sec + 's left (readings every ~5s)';
  } else {
    liveState.textContent = 'Live mode off — readings update hourly';
  }
  var c = document.getElementById('cards');
  var html = '';
  d.sensors.forEach(function(s){
    var valid = s.pct !== null && s.pct !== undefined;
    var railed = s.raw !== null && (s.raw <= 1 || s.raw >= 4094);
    var badge = !s.enabled ? '<span class="badge b-off">disabled</span>'
              : valid ? '<span class="badge b-ok">reading ' + s.pct + '%</span>'
              : '<span class="badge b-bad">' + (railed ? 'invalid (dead/disconnected)' : 'no reading') + '</span>';
    html += '<div class="card">'
      + '<div class="row"><span class="nm">#' + s.index + ' · ' + (s.name||'') + '</span>' + badge + '</div>'
      + '<div class="row" style="margin-top:6px">'
      +   '<div><div class="muted">live raw</div><div class="raw live">' + fmt(s.raw) + '</div></div>'
      +   '<div style="text-align:right"><div class="muted">moisture</div><div class="pct">' + (valid ? s.pct + '%' : '—') + '</div></div>'
      + '</div>'
      + '<div class="endpoints"><span>dry (0%): <b>' + s.dry + '</b></span><span>wet (100%): <b>' + s.wet + '</b></span></div>'
      + driftLine(s.index)
      + '<div class="actions">'
      +   '<button class="btn-dry" onclick="capture(' + s.index + ',\\'dry\\')">☀️ Set Dry (in air)</button>'
      +   '<button class="btn-wet" onclick="capture(' + s.index + ',\\'wet\\')">💧 Set Wet (in water)</button>'
      + '</div>'
      + '<div class="manual">'
      +   '<span class="muted">manual:</span>'
      +   '<input class="nm" id="nm' + s.index + '" placeholder="name" value="' + (s.name||'').replace(/"/g,'&quot;') + '">'
      +   '<input id="dry' + s.index + '" type="number" placeholder="dry" value="' + s.dry + '">'
      +   '<input id="wet' + s.index + '" type="number" placeholder="wet" value="' + s.wet + '">'
      +   '<button onclick="saveManual(' + s.index + ')">Save</button>'
      + '</div>'
      + '</div>';
  });
  c.innerHTML = html;
}

async function startLive(){
  var btn = document.getElementById('liveBtn');
  btn.disabled = true; btn.textContent = 'Starting…';
  try{
    var r = await fetch('/api/sensor-test', {method:'POST', headers:{'Content-Type':'application/json','X-Requested-With':'XMLHttpRequest'}, body: JSON.stringify({on:true, seconds:600, interval:5})});
    var d = await r.json();
    if(d.ok){ toast('Live mode on for 10 min'); POLL_MS = 2500; restartPoll(); }
    else { toast(d.message || 'Failed', true); }
  }catch(e){ toast('Failed to start live mode', true); }
  btn.disabled = false; btn.textContent = '▶ Start Live Mode (fast readings)';
}

async function capture(idx, point){
  try{
    var r = await fetch('/api/calibration/capture', {method:'POST', headers:{'Content-Type':'application/json','X-Requested-With':'XMLHttpRequest'}, body: JSON.stringify({index:idx, point:point})});
    var d = await r.json();
    if(d.ok){ toast('Saved ' + point + ' = ' + d.raw + ' (sensor #' + idx + ')'); load(); }
    else { toast(d.error || 'Capture failed', true); }
  }catch(e){ toast('Capture failed', true); }
}

async function saveManual(idx){
  var name = document.getElementById('nm'+idx).value;
  var dry = document.getElementById('dry'+idx).value;
  var wet = document.getElementById('wet'+idx).value;
  try{
    var r = await fetch('/api/calibration/set', {method:'POST', headers:{'Content-Type':'application/json','X-Requested-With':'XMLHttpRequest'}, body: JSON.stringify({index:idx, name:name, dry:dry, wet:wet})});
    var d = await r.json();
    if(d.ok){ toast('Saved sensor #' + idx); load(); }
    else { toast(d.error || 'Save failed', true); }
  }catch(e){ toast('Save failed', true); }
}

function restartPoll(){ if(pollTimer) clearInterval(pollTimer); pollTimer = setInterval(load, POLL_MS); }
load();
restartPoll();
</script>
</body></html>"""
        return Response(html, mimetype="text/html")

    return app
