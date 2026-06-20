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
import sys
from datetime import datetime, timedelta

import requests as http_requests
import yaml
from flask import make_response, Response, Flask, render_template, request, jsonify, redirect, url_for

import database as db
from irrigation import ESP32_MANUAL_TIMEOUT
from cam_ocr import MeterReader
import cam_ocr
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

    @app.route("/sensor-history")
    def sensor_history_page():
        """Dedicated soil-sensor history page (raw + calibrated %, per sensor)."""
        return render_template("sensor_history.html")

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

    @app.route("/api/schedule-7day")
    def api_schedule_7day():
        """AUTHORITATIVE 7-day watering schedule — the single source of truth
        for the schedule page grid, the all-zones "Next" column, AND each
        single-zone "Next Expected Watering" banner. Mirrors the engine:
          - per-zone ET water-balance depletion from the live forecast
          - sync-group coordination (whole group waters when its driest auto
            member hits MAD); independent auto zones water on their own MAD
          - site-wide rain skip (>= engine rain_forecast_mm threshold)
          - serial scheduling inside the watering window, ordered by zone id
          - weather-scaled runtime (max_runtime_min * scale_pct/100)
        Returns day-rows x zone-cols so every consumer reads ONE computation
        and they can never drift apart again.
        """
        from datetime import date, datetime, timedelta

        # ── Inputs: source from status_summary() — the SAME warm-cached path
        #    /api/status and /api/forecast use (the non-blocking weather.* calls
        #    return empty in this request context). ──
        summary = status_summary()
        et0_today = summary.get("et0_today", 0) or 0.0
        forecast = summary.get("forecast_7day") or []
        # Cold cache (e.g. seconds after a restart) → the non-blocking summary
        # comes back empty. Warm it once with a blocking fetch so the schedule
        # isn't computed against zero ET (which would fire everything day 1 then
        # nothing). Normal operation hits the warm path and skips this.
        if not forecast:
            try:
                summary = engine.get_status_summary(allow_weather_fetch=True) or summary
                et0_today = summary.get("et0_today", 0) or et0_today
                forecast = summary.get("forecast_7day") or []
            except Exception:
                pass
        fc_by_date = {f.get("date"): f for f in forecast}
        season_idx = engine.weather.get_season_index()
        ws = summary.get("weather_scale") or {}
        scale_pct = ws.get("scale_pct", 100) if isinstance(ws, dict) else 100
        groups = config.get("water_groups") or {}
        member_of = {}
        for gname, ids in groups.items():
            for zid in ids:
                member_of[zid] = gname
        win = config.get("watering_window", {}) or {}
        win_start = str(win.get("start", "04:00"))
        try:
            wh, wm = int(win_start.split(":")[0]), int(win_start.split(":")[1])
        except Exception:
            wh, wm = 4, 0

        rain_skip_mm = 5.0  # engine skip_rules.rain_forecast_mm

        # ── Per-zone sim state: installed AUTO zones only (manual/drip-manual
        #    never auto-water, so they get no schedule column). ──
        zstate = {}
        cols = []
        for z in config["zones"]:
            if not z.get("installed", False):
                continue
            if not z.get("auto_mode", True):
                continue
            zid = z["id"]
            taw = engine.get_zone_taw_mm(zid)
            mad = engine.get_zone_mad_mm(zid)
            bal = db.get_soil_balance(zid)
            balance_mm = (bal["balance_mm"] if bal
                          and bal.get("balance_mm") is not None else taw)
            zstate[zid] = {
                "taw": taw, "mad": mad, "bal": float(balance_mm),
                "kc": z.get("kc", [0.9, 0.9, 0.9, 0.9]),
                "run": z.get("max_runtime_min", 24),
            }
            cols.append({"id": zid, "name": z["name"],
                         "type": z.get("type", "sprinkler")})

        # ── Day boundary: window is e.g. 04:00-08:00. If it has already passed
        #    today, the first simulated morning is tomorrow. ──
        now = datetime.now()
        win_end = str(win.get("end", "08:00"))
        try:
            end_h = int(win_end.split(":")[0])
        except Exception:
            end_h = 8
        first_offset = 0 if now.hour < end_h else 1

        def kc_for(zid):
            arr = zstate[zid]["kc"]
            if 0 <= season_idx < len(arr):
                return arr[season_idx]
            return 0.0  # dormant -> no ET demand (engine skips irrigation)

        days = []
        next_water = {}  # zid -> {date_label, start, minutes, days_away}
        for n in range(7):
            d = date.today() + timedelta(days=first_offset + n)
            fc = fc_by_date.get(d.isoformat())
            et0 = (fc["et0"] if fc and fc.get("et0") is not None else et0_today)
            rain = (fc["rain"] if fc and fc.get("rain") is not None else 0.0)

            # Deplete every zone by its ET demand; credit rain.
            for zid, s in zstate.items():
                etc = et0 * kc_for(zid)
                s["bal"] = max(0.0, s["bal"] - etc + rain)

            rain_skips = rain >= rain_skip_mm

            # Firing set: group triggers + independent auto zones.
            firing = set()
            for gname, ids in groups.items():
                members = [zid for zid in ids if zid in zstate]
                if members and any(zstate[m]["bal"] <= zstate[m]["mad"]
                                   for m in members):
                    firing.update(members)
            for zid, s in zstate.items():
                if zid not in member_of and s["bal"] <= s["mad"]:
                    firing.add(zid)
            if rain_skips:
                firing = set()

            # Serial schedule inside the window, ordered by zone id.
            t = datetime(d.year, d.month, d.day, wh, wm)
            day_sched = {}
            for zid in sorted(firing):
                run = int(round(zstate[zid]["run"] * scale_pct / 100.0))
                day_sched[str(zid)] = {
                    "start": t.strftime("%H:%M"), "minutes": run,
                }
                t = t + timedelta(minutes=run)
                zstate[zid]["bal"] = zstate[zid]["taw"]  # refill to field cap
                if zid not in next_water:
                    next_water[zid] = {
                        "date_label": d.strftime("%a %b %d"),
                        "iso": d.isoformat(),
                        "start": day_sched[str(zid)]["start"],
                        "minutes": run,
                        "days_away": first_offset + n,
                    }

            days.append({
                "date_label": d.strftime("%a %b %d"),
                "iso": d.isoformat(),
                "rain_skip": rain_skips,
                "zones": day_sched,
            })

        return jsonify({
            "columns": cols,
            "days": days,
            "next_water": {str(k): v for k, v in next_water.items()},
            "scale_pct": scale_pct,
            "window_start": win_start,
            "generated": now.isoformat(timespec="seconds"),
        })

    @app.route("/api/zone-history")
    def api_zone_history():
        """Per-zone run history + sensor response. For each zone, returns its
        watering runs classified as auto / manual / test, with gallons, and (for
        zones a soil sensor sits in) the mapped sensor's reading just before the
        run vs its peak in the hours after — so you can see if the sensor
        actually responds to that zone's water (sensor-calibration validation).

        Query: days (default 14), include_other (0/1, default 0).
        Default view = AUTO runs only (the engine's real decisions). Manual runs
        and short tests are both "James poking at it" noise → hidden unless
        include_other=1. Counts are always returned so the header chips show
        what's hidden.
        """
        from datetime import datetime, timedelta

        days = query_int("days", 14, min_value=1, max_value=120)
        # include_other reveals BOTH manual and test runs (the user treats manual
        # as testing too). Back-compat: include_tests=1 still works.
        include_other = (request.args.get("include_other", "0") == "1"
                         or request.args.get("include_tests", "0") == "1")
        after_window_h = 3  # hours after a run to look for the sensor's peak

        # sensor index -> [zone ids]; default mirrors the physical layout but is
        # config-overridable (sensors move over time).
        szmap_raw = config.get("sensor_zone_map") or {0: [], 1: [8], 2: [3], 3: [3]}
        szmap = {int(k): list(v or []) for k, v in szmap_raw.items()}
        # reverse: zone id -> [sensor indices that should respond to it]
        zone_sensors = {}
        for sidx, zids in szmap.items():
            for z in zids:
                zone_sensors.setdefault(int(z), []).append(sidx)
        # sensor display names from calibration block
        cal = config.get("soil_calibration") or {}
        sensor_names = {}
        for sidx in range(4):
            entry = cal.get(sidx) or cal.get(str(sidx)) or {}
            sensor_names[sidx] = entry.get("name", f"Sensor {sidx}")

        est_gpm = {z["id"]: z.get("est_gpm", 4.0) for z in config["zones"]}

        def classify(reason, dur):
            r = reason or ""
            if "orphaned_cleanup" in r:
                return "test"
            if r.startswith("soil_dry"):
                return "auto"
            if r == "manual_toggle":
                return "test"
            if r == "manual":
                return "test" if (dur or 0) < 60 else "manual"
            return "test" if (dur or 0) < 60 else "manual"

        conn = db.get_conn()
        rows = conn.execute(
            "SELECT id, zone_id, start_ts, end_ts, duration_sec, est_gallons, "
            "trigger_reason, soil_before, soil_after FROM watering_event "
            "WHERE start_ts >= datetime('now','localtime',?) ORDER BY start_ts DESC",
            (f"-{days} days",),
        ).fetchall()

        def sensor_before(sidx, start_ts):
            r = conn.execute(
                "SELECT soil_pct FROM sensor_log WHERE zone_id=? AND ts<=? "
                "AND ts>=strftime('%Y-%m-%dT%H:%M:%S', ?, '-2 hours') "
                "ORDER BY ts DESC LIMIT 1",
                (sidx, start_ts, start_ts),
            ).fetchone()
            return r["soil_pct"] if r and r["soil_pct"] is not None else None

        def sensor_peak_after(sidx, end_ts):
            if not end_ts:
                return None
            # NOTE: sensor_log.ts is stored T-separated (2026-06-16T07:53), but
            # SQLite datetime() returns space-separated — string-comparing the two
            # silently fails. Use strftime to keep the bound T-separated.
            r = conn.execute(
                "SELECT MAX(soil_pct) AS pk FROM sensor_log WHERE zone_id=? "
                "AND ts>? AND ts<=strftime('%Y-%m-%dT%H:%M:%S', ?, ?)",
                (sidx, end_ts, end_ts, f"+{after_window_h} hours"),
            ).fetchone()
            return r["pk"] if r and r["pk"] is not None else None

        zones_out = []
        for z in config["zones"]:
            if not (z.get("installed", False) or z.get("type") == "drip"):
                continue
            zid = z["id"]
            mapped = zone_sensors.get(zid, [])
            runs = []
            counts = {"auto": 0, "manual": 0, "test": 0}
            for row in rows:
                if row["zone_id"] != zid:
                    continue
                dur = row["duration_sec"] or 0
                kind = classify(row["trigger_reason"], dur)
                counts[kind] += 1
                # Default view = AUTO only. Manual + test are both "poking at it".
                if kind != "auto" and not include_other:
                    continue
                gallons = row["est_gallons"]
                if gallons is None or gallons == 0:
                    gallons = est_gpm.get(zid, 4.0) * (dur / 60.0)
                sensors = []
                # Only do the (heavier) sensor lookup for non-test runs.
                if kind != "test":
                    for sidx in mapped:
                        b = sensor_before(sidx, row["start_ts"])
                        a = sensor_peak_after(sidx, row["end_ts"])
                        delta = (round(a - b, 1) if (a is not None and b is not None)
                                 else None)
                        sensors.append({
                            "idx": sidx, "name": sensor_names.get(sidx, f"S{sidx}"),
                            "before": round(b, 1) if b is not None else None,
                            "after": round(a, 1) if a is not None else None,
                            "delta": delta,
                        })
                runs.append({
                    "id": row["id"],
                    "start": row["start_ts"],
                    "end": row["end_ts"],
                    "dur_min": round(dur / 60.0, 1),
                    "dur_sec": dur,
                    "kind": kind,
                    "gallons": round(gallons, 1) if gallons is not None else None,
                    "reason": row["trigger_reason"],
                    "sensors": sensors,
                })
            zones_out.append({
                "id": zid,
                "name": z["name"],
                "type": z.get("type", "sprinkler"),
                "auto_mode": z.get("auto_mode", True),
                "installed": z.get("installed", False),
                "mapped_sensors": [
                    {"idx": s, "name": sensor_names.get(s, f"S{s}")} for s in mapped
                ],
                "counts": counts,
                "runs": runs,
            })
        conn.close()

        return jsonify({
            "days": days,
            "include_other": include_other,
            "sensor_zone_map": {str(k): v for k, v in szmap.items()},
            "sensor_names": {str(k): v for k, v in sensor_names.items()},
            "after_window_h": after_window_h,
            "zones": zones_out,
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
            #
            # multi=True is the manual multi-valve override: open this zone
            # ALONGSIDE any already-running zones instead of preempting them.
            multi = bool((payload or {}).get("multi") or request.form.get("multi"))
            soil = db.get_latest_soil(zone_id)
            soil_pct = soil["soil_pct"] if soil else 0
            ok = engine_command(
                "start_zone_watering",
                zone_id, soil_pct, 0, "manual_toggle",
                allow_weather_fetch=False,
                command_timeout=ESP32_MANUAL_TIMEOUT,
                retry=False,
                allow_multi=multi,
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

    @app.route("/api/deer-repellent/sound", methods=["POST"])
    def api_deer_sound():
        """Play a scare sound (e.g. dog barking) on the yard Amazon Echo.

        Shells out to alexa_remote_control.sh (path via ALEXA_RC env), which plays
        an Amazon soundbank clip on the configured Echo (ALEXA_DEVICE). The sound key
        must be in the allowlist below so nothing user-supplied reaches the shell.
        Until the one-time Alexa login is done on the server, returns a clear 503.
        """
        import subprocess

        SOUNDS = {
            "dog_bark": "amzn_sfx_dog_med_bark_1x_02",
            "dog_bark_2x": "amzn_sfx_dog_med_bark_2x_02",
            "wolf_howl": "amzn_sfx_wolf_howl_1x_01",
        }
        data = request.get_json(silent=True) or {}
        key = str(data.get("sound", "dog_bark"))
        sound_id = SOUNDS.get(key)
        if not sound_id:
            return jsonify({"ok": False, "message": f"Unknown sound '{key}'"}), 400

        rc = os.environ.get(
            "ALEXA_RC", "/home/jamesearlpace/alexa-sounds/alexa_remote_control.sh")
        device = os.environ.get("ALEXA_DEVICE", "").strip()
        if not os.path.exists(rc):
            return jsonify({
                "ok": False,
                "message": "Echo not linked yet — run the one-time Alexa login on the server.",
            }), 503

        cmd = ["bash", rc]
        if device:
            cmd += ["-d", device]
        cmd += ["-e", "sound:" + sound_id]
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=25)
            if res.returncode == 0:
                return jsonify({"ok": True,
                                "message": f"Played {key.replace('_', ' ')} on Echo"})
            msg = (res.stderr or res.stdout or "alexa_remote_control failed").strip()
            return jsonify({"ok": False, "message": msg[:200]}), 502
        except subprocess.TimeoutExpired:
            return jsonify({"ok": False, "message": "Echo command timed out"}), 504
        except Exception as e:  # noqa: BLE001
            return jsonify({"ok": False, "message": str(e)[:200]}), 502

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
        """Live raw readings + each sensor's stored calibration + computed pct +
        a per-sensor recalibration recommendation."""
        status = engine.get_esp32_status(force_fresh=True) or {}
        soil = status.get("soil", []) or []
        sysd = status.get("system", {}) or {}
        sensors_cfg = config.get("sensors", {})
        # Drift + last-calibration timestamps (keyed by sensor_idx).
        try:
            drift = db.get_calibration_drift()
        except Exception:
            drift = []
        last_cal = {}      # idx -> most recent calibration ts (any point)
        drift_by_idx = {}  # idx -> max |delta| across its points
        for e in drift:
            i = e["sensor_idx"]
            ts = e.get("latest_ts")
            if ts and (i not in last_cal or ts > last_cal[i]):
                last_cal[i] = ts
            if e.get("delta") is not None:
                drift_by_idx[i] = max(drift_by_idx.get(i, 0), abs(e["delta"]))
        out = []
        # Cover every configured calibration slot plus any soil channel the chip
        # reports, so newly-wired sensors show up even before config is updated.
        n = max(len(soil), 4)
        for idx in range(n):
            cal = engine.get_soil_calibration(idx)
            raw = soil[idx].get("raw") if idx < len(soil) else None
            pct = engine.soil_raw_to_pct(idx, raw)
            advice = _calibration_advice(
                idx, raw, pct, cal,
                last_cal.get(idx), drift_by_idx.get(idx),
                bool(sensors_cfg.get(f"soil_{idx}", False)),
            )
            out.append({
                "index": idx,
                "name": cal["name"],
                "dry": cal["dry"],
                "wet": cal["wet"],
                "raw": raw,
                "pct": pct,
                "enabled": bool(sensors_cfg.get(f"soil_{idx}", False)),
                "last_cal": last_cal.get(idx),
                "advice": advice,
            })
        return {
            "sensors": out,
            "fast_active": sysd.get("fastSampleActive", False),
            "remain_sec": sysd.get("fastSampleRemainSec", 0),
            "esp32_ok": bool(status),
        }

    # How often to recommend recalibration (days).
    CAL_DUE_SOON_DAYS = 45
    CAL_OVERDUE_DAYS = 75

    def _calibration_advice(idx, raw, pct, cal, last_cal_ts, max_drift, enabled):
        """Decide whether a sensor should be recalibrated and WHY. Returns
        {status, reason} where status ∈ ok|info|due|overdue|bad. The reasons
        are concrete so the user knows what to do, not just 'recalibrate'."""
        from datetime import datetime
        # 1. Dead / disconnected — calibration can't help, it's hardware.
        if raw is None:
            return {"status": "bad", "reason": "No reading — sensor disabled or not reporting."}
        try:
            rawi = int(raw)
        except (TypeError, ValueError):
            rawi = None
        if rawi is not None and (rawi <= engine.SOIL_RAW_MIN or rawi >= engine.SOIL_RAW_MAX):
            return {"status": "bad",
                    "reason": "Reading is railed (%s) — sensor looks dead or disconnected. Check wiring/reseat; calibration won't fix this." % rawi}
        # 2. Never calibrated — still on factory defaults.
        if last_cal_ts is None:
            return {"status": "due",
                    "reason": "Never calibrated — using factory defaults (3500/1500). Calibrate once for accurate readings."}
        # 3. Live raw outside the calibrated window → endpoints are wrong.
        dry, wet = cal["dry"], cal["wet"]
        if rawi is not None and dry != wet:
            if rawi < wet:
                return {"status": "due",
                        "reason": "Reading is wetter than your calibrated wet point (raw %s < wet %s) — it's pinned at 100%%. Recapture Wet." % (rawi, wet)}
            if rawi > dry:
                return {"status": "due",
                        "reason": "Reading is drier than your calibrated dry point (raw %s > dry %s) — it's pinned at 0%%. Recapture Dry." % (rawi, dry)}
        # 4. Age-based: recommend periodic recalibration.
        days = None
        try:
            days = (datetime.now() - datetime.strptime(last_cal_ts[:19], "%Y-%m-%dT%H:%M:%S")).total_seconds() / 86400.0
        except Exception:
            pass
        drift_note = ""
        if max_drift is not None and max_drift >= 120:
            drift_note = " Last recalibration moved by %d counts, so it's drifting." % max_drift
        if days is not None:
            if days >= CAL_OVERDUE_DAYS:
                return {"status": "overdue",
                        "reason": "%d days since last calibration (overdue — recalibrate every ~%d days).%s" % (int(days), CAL_DUE_SOON_DAYS, drift_note)}
            if days >= CAL_DUE_SOON_DAYS:
                return {"status": "due",
                        "reason": "%d days since last calibration — due for a refresh soon.%s" % (int(days), drift_note)}
        # 5. Healthy.
        if max_drift is not None and max_drift >= 120:
            return {"status": "info",
                    "reason": "Calibrated %d days ago, but drifting (%d counts last time). Watch it." % (int(days) if days else 0, max_drift)}
        if days is not None:
            return {"status": "ok", "reason": "Calibrated %d days ago — looks good." % int(days)}
        return {"status": "ok", "reason": "Calibrated — looks good."}

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

    # ── Battery voltage calibration ──────────────────────────────────────
    # James reads the true battery voltage off the Wanderer charge controller
    # at the junction box and enters it here. We pair it with what the ESP32
    # reported at that instant (raw, uncorrected), then least-squares fit a
    # correction so the dashboard voltage matches reality. Stored in
    # config['battery_calibration']; applied live by engine.battery_raw_to_v().
    BATTERY_LEGACY_SCALE = 1.0   # uncalibrated = show the raw ESP32 reading 1:1

    def _solve_linear_system(matrix, vector):
        """Gaussian elimination with partial pivoting. Solves A·x = b for a
        small dense system. Returns the solution list, or None if singular."""
        n = len(vector)
        # Work on an augmented copy.
        aug = [list(matrix[i]) + [vector[i]] for i in range(n)]
        for col in range(n):
            piv = max(range(col, n), key=lambda r: abs(aug[r][col]))
            if abs(aug[piv][col]) < 1e-12:
                return None
            aug[col], aug[piv] = aug[piv], aug[col]
            pivot = aug[col][col]
            for r in range(n):
                if r == col:
                    continue
                factor = aug[r][col] / pivot
                for c in range(col, n + 1):
                    aug[r][c] -= factor * aug[col][c]
        return [aug[i][n] / aug[i][i] for i in range(n)]

    def _polyfit_increasing(xs, ys, degree):
        """Pure-Python least-squares polynomial fit (no numpy). Returns
        coefficients in increasing power order: [c0, c1, ... c_degree]."""
        m = degree + 1
        # Normal equations: (XᵀX) c = Xᵀy, where X columns are x^0..x^degree.
        # XᵀX[i][j] = Σ x^(i+j) ; Xᵀy[i] = Σ y·x^i.
        powers = [sum(x ** p for x in xs) for p in range(2 * degree + 1)]
        a = [[powers[i + j] for j in range(m)] for i in range(m)]
        b = [sum(y * (x ** i) for x, y in zip(xs, ys)) for i in range(m)]
        sol = _solve_linear_system(a, b)
        return sol

    def _fit_battery_model(points):
        """Least-squares fit actual_v = f(raw_v). Returns coeffs (increasing
        power order), degree, rmse, n, and a human description. Picks the
        simplest model the data supports to avoid overfitting:
          0 pts → raw passthrough (×1.0)   1 pt → scale-through-origin
          2-4 pts → linear          5+ pts → quadratic
        (A resistor divider is physically linear; quadratic only kicks in with
        enough points to justify capturing ESP32 ADC curvature.)"""
        pts = []
        for p in points:
            try:
                rv = float(p["raw_v"]); av = float(p["actual_v"])
            except (TypeError, ValueError, KeyError):
                continue
            if rv > 0 and av > 0:
                pts.append((rv, av))
        n = len(pts)
        if n == 0:
            return {"coeffs": [0.0, BATTERY_LEGACY_SCALE], "degree": 1,
                    "rmse": None, "n": 0,
                    "model": "uncalibrated (raw passthrough)"}
        if n == 1:
            rv, av = pts[0]
            a = av / rv if rv else 1.0
            return {"coeffs": [0.0, round(a, 6)], "degree": 1, "rmse": 0.0,
                    "n": 1, "model": "1-point scale (×%.5f)" % a}
        deg = 2 if n >= 5 else 1
        xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
        coeffs = _polyfit_increasing(xs, ys, deg)
        if coeffs is None:
            # Degenerate (e.g. all identical raw values) → fall back to linear,
            # then to a simple average scale if even that is singular.
            coeffs = _polyfit_increasing(xs, ys, 1)
            deg = 1
        if coeffs is None:
            a = sum(ys) / sum(xs)
            coeffs = [0.0, a]
            deg = 1

        def predict(x):
            return sum(c * (x ** i) for i, c in enumerate(coeffs))

        rmse = (sum((predict(x) - y) ** 2 for x, y in pts) / n) ** 0.5
        return {"coeffs": [round(c, 8) for c in coeffs], "degree": deg,
                "rmse": round(rmse, 4), "n": n,
                "model": ("quadratic" if deg == 2 else "linear") + " fit (n=%d)" % n}

    def _save_battery_calibration(points):
        fit = _fit_battery_model(points)
        config["battery_calibration"] = {
            "points": points,
            "coeffs": fit["coeffs"],
            "degree": fit["degree"],
            "rmse": fit["rmse"],
            "model": fit["model"],
            "updated": datetime.now().isoformat(timespec="seconds"),
        }
        write_config_atomic(config)
        return config["battery_calibration"], fit

    def _battery_live_reading():
        """Fresh (raw_v, corrected_v) from the ESP32, or (None, None)."""
        status = engine.get_esp32_status(force_fresh=True) or {}
        raw_v = (status.get("system") or {}).get("batteryV")
        try:
            raw_v = float(raw_v)
        except (TypeError, ValueError):
            return None, None
        if raw_v <= 0:
            return None, None
        return round(raw_v, 4), engine.battery_raw_to_v(raw_v)

    def _battery_fresh_reading(timeout_sec=12):
        """Force the ESP32 to take a NEW battery sample, then return it.

        The firmware only re-reads the battery ADC on its sensor interval
        (hourly on the currently-flashed build), so a plain force_fresh fetch
        just returns the same stale cached value. We kick fast-sample mode and
        poll until the reported batteryV actually changes (a real ADC read
        always jitters a few mV) or we time out. Returns (raw_v, corrected_v,
        was_fresh)."""
        baseline, _ = _battery_live_reading()
        # Kick a short fast-sample window so the firmware re-reads every ~3s.
        try:
            engine.set_fast_sample(60, 3)
        except Exception as e:
            log.warning("battery fresh-read: fast-sample kick failed: %s", e)
        deadline = time.time() + timeout_sec
        last = baseline
        while time.time() < deadline:
            time.sleep(3.2)
            raw_v, corrected_v = _battery_live_reading()
            if raw_v is None:
                continue
            last = raw_v
            # A genuinely new ADC sample differs from the stale cached value.
            if baseline is None or abs(raw_v - baseline) > 1e-4:
                return raw_v, corrected_v, True
        # Timed out without a change — return whatever we last saw (may be stale).
        if last is None:
            return None, None, False
        return last, engine.battery_raw_to_v(last), False

    def _battery_cal_snapshot():
        cal = config.get("battery_calibration") or {}
        points = cal.get("points") or []
        coeffs = cal.get("coeffs") or [0.0, BATTERY_LEGACY_SCALE]

        def predict(x):
            return round(sum(c * (x ** i) for i, c in enumerate(coeffs)), 3)

        enriched = []
        for p in points:
            try:
                rv = float(p["raw_v"]); av = float(p["actual_v"])
            except (TypeError, ValueError, KeyError):
                continue
            pred = predict(rv)
            enriched.append({"ts": p.get("ts"), "raw_v": rv, "actual_v": av,
                             "predicted_v": pred, "error_v": round(pred - av, 3)})
        raw_v, corrected_v = _battery_live_reading()
        legacy_v = round(raw_v * BATTERY_LEGACY_SCALE, 2) if raw_v else None
        return {
            "points": enriched,
            "coeffs": coeffs,
            "degree": cal.get("degree", 1),
            "rmse": cal.get("rmse"),
            "model": cal.get("model", "uncalibrated (raw passthrough)"),
            "updated": cal.get("updated"),
            "live": {"raw_v": raw_v, "corrected_v": corrected_v, "legacy_v": legacy_v},
        }

    @app.route("/api/battery-calibration")
    def api_battery_calibration():
        return jsonify(_battery_cal_snapshot())

    @app.route("/api/battery-calibration/add", methods=["POST"])
    def api_battery_calibration_add():
        """Add a reference point. Body: {actual_v}. Forces the ESP32 to take a
        FRESH battery sample (it otherwise only re-reads hourly) and pairs that
        with the real Wanderer voltage the user just read."""
        data = request.get_json(silent=True) or {}
        try:
            actual_v = float(data.get("actual_v"))
        except (TypeError, ValueError):
            return jsonify({"ok": False, "error": "actual_v (a number) required"}), 400
        if not (5.0 <= actual_v <= 18.0):
            return jsonify({"ok": False, "error": "actual_v %.2f is out of range for a 12V SLA (5–18V)" % actual_v}), 400
        raw_v, _, was_fresh = _battery_fresh_reading()
        if raw_v is None:
            return jsonify({"ok": False, "error": "ESP32 isn't reporting a battery reading right now — try again in a moment"}), 400
        cal = config.get("battery_calibration") or {}
        points = list(cal.get("points") or [])
        points.append({
            "ts": datetime.now().isoformat(timespec="seconds"),
            "raw_v": round(raw_v, 4),
            "actual_v": round(actual_v, 3),
        })
        saved, fit = _save_battery_calibration(points)
        return jsonify({"ok": True, "captured": {"raw_v": round(raw_v, 4), "actual_v": actual_v, "fresh": was_fresh},
                        "fit": fit, "snapshot": _battery_cal_snapshot()})

    @app.route("/api/battery-calibration/live-refresh", methods=["POST"])
    def api_battery_calibration_live_refresh():
        """Force a fresh ESP32 battery sample and return the current live values
        (without saving a point) — lets the user see the true current voltage
        before entering the Wanderer reading."""
        raw_v, corrected_v, was_fresh = _battery_fresh_reading()
        if raw_v is None:
            return jsonify({"ok": False, "error": "no battery reading"}), 400
        legacy_v = round(raw_v * BATTERY_LEGACY_SCALE, 2)
        return jsonify({"ok": True, "fresh": was_fresh,
                        "live": {"raw_v": raw_v, "corrected_v": corrected_v, "legacy_v": legacy_v}})

    @app.route("/api/battery-calibration/delete", methods=["POST"])
    def api_battery_calibration_delete():
        """Remove one reference point by its ts. Body: {ts}."""
        data = request.get_json(silent=True) or {}
        ts = data.get("ts")
        cal = config.get("battery_calibration") or {}
        points = [p for p in (cal.get("points") or []) if p.get("ts") != ts]
        _save_battery_calibration(points)
        return jsonify({"ok": True, "snapshot": _battery_cal_snapshot()})

    @app.route("/api/battery-calibration/reset", methods=["POST"])
    def api_battery_calibration_reset():
        """Clear all reference points → revert to raw passthrough (×1.0)."""
        _save_battery_calibration([])
        return jsonify({"ok": True, "snapshot": _battery_cal_snapshot()})

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

    # ── Water Cost page (real meter usage from the cam) ───────────────────
    # Isolated from the cam pipeline: reads `meter_reader.last_good` only and
    # owns its own meter_snapshot table via the water_cost module. Safe to edit
    # alongside cam work — touches no cam routes or OCR state.
    import water_cost
    _water_cost_ready = {"done": False}

    def _ensure_water_cost():
        if not _water_cost_ready["done"]:
            try:
                water_cost.ensure_schema()
                water_cost.seed_anchors()
                _water_cost_ready["done"] = True
            except Exception as e:
                log.warning("water_cost init failed: %s", e)

    def _live_meter_cf():
        """Current whole-house register in ft³ from the OCR lock, plus a stale
        flag. last_good is a 9-digit int where the last 3 digits are decimals."""
        lg = getattr(meter_reader, "last_good", None)
        if not lg:
            return None, False
        reading_cf = lg / 1000.0
        stale = False
        try:
            lock_ts = getattr(meter_reader, "_lock_ts", None) or 0
            stale_secs = getattr(meter_reader, "stale_secs", 20) or 20
            if lock_ts:
                stale = (time.time() - lock_ts) > max(120, stale_secs * 6)
        except Exception:
            pass
        return reading_cf, stale

    @app.route("/costs")
    def costs_page():
        return render_template("costs.html")

    @app.route("/flow")
    def flow_page():
        return render_template("flow.html")

    @app.route("/water-usage")
    def water_usage_page():
        return render_template("water_usage.html")

    @app.route("/api/water-usage")
    def api_water_usage():
        """Water usage over time for leak-spotting, at any zoom. Buckets the
        meter reading (flow_sample.reading_cf, cumulative ft³) into deltas →
        gallons used per bucket. Bucket size auto-scales to the window
        (?minutes=N) so 1 min shows 15s buckets and 12 h shows ~20 min buckets.
        Flat = no water moving; a steady small step every bucket = a slow leak."""
        from datetime import datetime as _dt
        GAL = 7.48052
        minutes = query_int("minutes", 60, min_value=1, max_value=129600)
        win_s = minutes * 60
        # aim for ~40 buckets, snapped to the 15s sample cadence
        bucket_s = max(15, int(round(win_s / 40 / 15)) * 15)
        conn = db.get_conn()
        try:
            rows = conn.execute(
                "SELECT ts, delta_cf, gpm FROM flow_sample "
                # flow_sample.ts is T-separated; datetime() returns SPACE-
                # separated, so a plain >= datetime(...) compares wrong and never
                # bounds the window. Use strftime to build a T-separated bound.
                "WHERE ts >= strftime('%Y-%m-%dT%H:%M:%S','now','localtime',?) "
                "ORDER BY ts",
                (f"-{minutes} minutes",)).fetchall()
        finally:
            conn.close()
        # METHODOLOGY: usage = the flow monitor's VALIDATED per-sample flow, NOT a
        # re-diff of the raw lock value. flow_monitor.record() already nulls gpm
        # for rejected samples — register went DOWN (a re-anchor/operator
        # correction), an impossible over-ceiling jump, or a blind gap — so
        # summing only accepted positive deltas counts real water. Re-anchors and
        # bad reads can never become "usage", and this stays consistent with the
        # leak monitor (one source of truth) instead of clamping the display.
        buckets, order, line = {}, [], []
        step = max(1, len(rows) // 400)
        cum = 0.0
        for i, r in enumerate(rows):
            accepted = r["gpm"] is not None
            dgal = (max(0.0, r["delta_cf"] or 0.0) * GAL) if accepted else 0.0
            cum += dgal
            try:
                ep = _dt.fromisoformat(r["ts"]).timestamp()
            except Exception:
                continue
            key = int(ep // bucket_s)
            b = buckets.get(key)
            if b is None:
                b = {"ts": r["ts"], "gal": 0.0, "gpm_sum": 0.0, "gpm_n": 0}
                buckets[key] = b
                order.append(key)
            b["ts"] = r["ts"]
            b["gal"] += dgal
            if accepted:
                b["gpm_sum"] += r["gpm"]
                b["gpm_n"] += 1
            if i % step == 0:
                line.append({"t": r["ts"], "gal": round(cum, 2)})
        usage = []
        for k in order:
            b = buckets[k]
            gpm = b["gpm_sum"] / b["gpm_n"] if b["gpm_n"] else 0.0
            usage.append({"t": b["ts"], "gallons": round(b["gal"], 2),
                          "gpm": round(gpm, 2),
                          "start_ms": int(k * bucket_s * 1000),
                          "end_ms": int((k + 1) * bucket_s * 1000)})
        if bucket_s < 60:
            blabel = f"{bucket_s}s"
        elif bucket_s < 3600:
            blabel = f"{bucket_s // 60} min"
        else:
            blabel = f"{bucket_s // 3600} hr"
        # flat if every bucket used ~nothing
        steps = [u["gallons"] for u in usage]
        total = round(cum, 2)
        flat = bool(steps) and max(steps) < 0.3
        leak_hint = bool(steps) and len(steps) >= 5 and min(steps) > 0.3
        return jsonify({"minutes": minutes, "bucket_s": bucket_s,
                        "bucket_label": blabel, "usage": usage, "line": line,
                        "total_gal": total, "flat": flat, "leak_hint": leak_hint})

    @app.route("/api/water-usage/frames")
    def api_water_usage_frames():
        """Captured meter frames that JUSTIFY a usage bar: the reading just
        BEFORE the bucket plus the frames within it, so the climb (before →
        after) can be seen. Each frame carries an id/file so a misread can be
        corrected into training. Pulls from the per-reading frame ring (recent
        ~1h) and the banked gold frames (sparse but longer history)."""
        start_ms = query_int("start_ms", 0, min_value=0, max_value=4102444800000)
        end_ms = query_int("end_ms", 0, min_value=0, max_value=4102444800000)
        if end_ms <= start_ms:
            return jsonify({"frames": [], "before": None})
        from datetime import datetime as _dt

        def _hhmmss(ms):
            return _dt.fromtimestamp(ms / 1000.0).strftime("%H:%M:%S")

        in_win = {}          # ms -> frame dict (in [start,end))
        before = {}          # ms -> frame dict (up to 1h before start)

        def _add(ms, rec):
            if start_ms <= ms < end_ms:
                in_win[ms] = rec
            elif start_ms - 3600000 <= ms < start_ms:
                before[ms] = rec

        # banked gold frames: <reading>_<epoch_ms>[_oracle].jpg
        try:
            for name in os.listdir(BANK_DIR):
                if not name.endswith(".jpg"):
                    continue
                parts = name[:-4].split("_")
                if len(parts) < 2:
                    continue
                try:
                    ms = int(parts[1])
                except ValueError:
                    continue
                _add(ms, {"ts": _hhmmss(ms), "ms": ms, "reading": parts[0],
                          "img": "/api/cam/training/img/" + name,
                          "file": name, "source": "banked"})
        except FileNotFoundError:
            pass
        # per-reading frame ring: <epoch_ms>-<seq>.jpg
        try:
            for name in os.listdir(FRAME_DIR):
                if not name.endswith(".jpg"):
                    continue
                rid = name[:-4]
                try:
                    ms = int(rid.split("-")[0])
                except (ValueError, IndexError):
                    continue
                if ms in in_win or ms in before:
                    continue
                entry = meter_reader.get_reading_by_id(rid) or {}
                rd = entry.get("reading") or ""
                guess = entry.get("ocr_guess") or ""
                _add(ms, {"ts": _hhmmss(ms), "ms": ms, "reading": rd,
                          "guess": guess, "note": entry.get("note") or "",
                          "img": "/api/cam/frame/" + rid,
                          "id": rid, "source": "live"})
        except FileNotFoundError:
            pass

        # Human truth + Anchor&Propagate overlay: a frame the user has corrected
        # (or that Propagate resolved from the user's anchors) must show THAT
        # value here too — not the filename's stale read or a fresh CNN guess.
        # Keyed by capture-ms so it lands on the live ring frame, the banked
        # oracle frame, and the corrected copy that all share one timestamp.
        import re as _re_ms
        _ms_re = _re_ms.compile(r"_(\d{10,})")

        def _ms_of(fname):
            m = _ms_re.search(fname or "")
            return int(m.group(1)) if m else None

        manual_by_file, manual_by_ms = {}, {}
        for fname, mv in _load_manual().items():
            lbl = mv.get("label")
            if not lbl or mv.get("action") == "reject":
                continue
            manual_by_file[fname] = lbl
            ms = _ms_of(fname)
            if ms is not None:
                manual_by_ms[ms] = lbl
        prop_by_ms = {}
        for fname, pr in _load_propagated().items():
            if pr.get("status") not in ("anchor", "confirmed", "repaired"):
                continue
            lbl, ms = pr.get("label"), _ms_of(fname)
            if lbl and ms is not None:
                prop_by_ms.setdefault(ms, lbl)

        def _truth(fr):
            lbl = manual_by_file.get(fr.get("file")) or manual_by_ms.get(fr.get("ms"))
            if lbl:
                fr["reading"], fr["guess"], fr["corrected"] = lbl, "", True
                return
            lbl = prop_by_ms.get(fr.get("ms"))
            if lbl:
                fr["reading"], fr["guess"], fr["propagated"] = lbl, "", True

        for _bucket in (in_win, before):
            for _fr in _bucket.values():
                _truth(_fr)

        frames = [in_win[k] for k in sorted(in_win)]
        if len(frames) > 60:
            step = len(frames) / 60.0
            frames = [frames[int(i * step)] for i in range(60)]
        before_frame = before[max(before)] if before else None

        # On-demand: for frames with no stored read (metadata lost on restart, or
        # the live reader couldn't commit under glare), ask the CNN what it reads
        # NOW so the user always sees the model's best guess to judge/correct.
        # Bounded so a click doesn't fire hundreds of CNN calls.
        def _fill_guess(fr, budget):
            # Compute the CNN's read of THIS specific frame so the user sees what
            # the model thinks per image (varies frame to frame), not just the
            # repeated held lock value. Banked frames already carry their label.
            # Skip frames the user already corrected / Propagate resolved — we
            # know the truth, so don't ask the CNN (and don't overwrite it).
            if (budget[0] <= 0 or fr.get("guess")
                    or fr.get("corrected") or fr.get("propagated")):
                return
            if fr.get("source") != "live" or not fr.get("id"):
                return
            path = os.path.join(FRAME_DIR, f"{fr['id']}.jpg")
            try:
                data = open(path, "rb").read()
            except Exception:
                return
            budget[0] -= 1
            res = _read_via_cnn(data)
            if not res:
                return
            g = res.get("digits")
            if isinstance(g, list):
                g = "".join(str(x) for x in g)
            g = "".join(c for c in str(g or "") if c.isdigit())
            if len(g) != 9 and res.get("value") is not None:
                g = f"{int(res['value']):09d}"
            if len(g) == 9:
                fr["guess"] = g
                fr["guess_conf"] = res.get("confidence")

        budget = [24]
        if before_frame:
            _fill_guess(before_frame, budget)
        for fr in frames:
            _fill_guess(fr, budget)
        return jsonify({"frames": frames, "count": len(in_win),
                        "before": before_frame})

    @app.route("/api/cam/usage-correct", methods=["POST"])
    def api_usage_correct():
        """Human correction of a captured frame's reading, from the usage view.
        Works for BOTH banked frames (have a training file) and live ring frames
        (materialized into the training set on correction). Body: {label, file?,
        id?, ms?}. Writes manual_labels.jsonl so it trains like a gallery fix."""
        import json as _json
        import shutil as _shutil
        data = request.get_json(silent=True) or {}
        lbl = "".join(c for c in str(data.get("label", "")) if c.isdigit())
        if len(lbl) != 9:
            return jsonify({"ok": False, "error": "label must be 9 digits"}), 400
        fname = os.path.basename(str(data.get("file", "")))
        if not (fname and fname.endswith(".jpg")):
            # live ring frame → copy it into the training set under a gold name
            rid = os.path.basename(str(data.get("id", "")))
            try:
                ms = int(data.get("ms") or rid.split("-")[0])
            except Exception:
                ms = 0
            src = os.path.join(FRAME_DIR, f"{rid}.jpg")
            if not rid or not os.path.exists(src):
                return jsonify({"ok": False, "error": "frame not found"}), 404
            fname = f"{lbl}_{ms}_manual.jpg"
            try:
                os.makedirs(BANK_DIR, exist_ok=True)
                _shutil.copy2(src, os.path.join(BANK_DIR, fname))
            except Exception as e:
                return jsonify({"ok": False, "error": f"bank: {e}"}), 500
        rec = {"file": fname, "action": "correct", "label": lbl,
               "ts": datetime.now().isoformat()}
        try:
            os.makedirs(LABELS_DIR, exist_ok=True)
            with open(MANUAL_PATH, "a") as f:
                f.write(_json.dumps(rec) + "\n")
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)}), 500
        # Smart-update the surrounding frames: re-run Anchor & Propagate so every
        # banked frame between the user's anchors snaps to the corrected
        # monotonic value. No AI, ~0.05s, so it's safe inline on each save — the
        # correction is already persisted regardless of whether this succeeds.
        prop = {}
        try:
            import subprocess as _sp
            script = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                  "propagate.py")
            _sp.run([sys.executable, script], capture_output=True,
                    text=True, timeout=60)
            prop = _json.load(open(PROPAGATE_STATUS)).get("counts", {})
        except Exception as e:
            log.debug("auto-propagate after correction skipped: %s", e)
        return jsonify({"ok": True, "saved": rec, "propagated": prop})

    @app.route("/api/water-cost")
    def api_water_cost():
        _ensure_water_cost()
        reading_cf, stale = _live_meter_cf()
        # Lazily record one snapshot per day from the live reading so true
        # billing-cycle history accrues without a separate scheduler job.
        if reading_cf:
            try:
                water_cost.record_daily_snapshot(reading_cf, source="auto")
            except Exception as e:
                log.debug("snapshot skipped: %s", e)
        return jsonify(water_cost.build_report(config, reading_cf, stale))

    @app.route("/api/flow")
    def api_flow():
        """Per-zone GPM estimates + raw flow samples + leak/anomaly events."""
        try:
            import flow_monitor
            limit = query_int("samples", 120, min_value=10, max_value=2000)
            return jsonify(flow_monitor.build_report(config, limit))
        except Exception as e:
            log.warning("api_flow failed: %s", e)
            return jsonify({"error": str(e), "zones": [], "samples": [],
                            "events": [], "open_events": []})

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
        """Soil water balance time-series. `zone` may be a zone id, or "all"
        to aggregate across installed turf zones (whole-lawn view): rain is
        common across zones, while balance/ET/irrigation are averaged so every
        series stays a comparable water DEPTH."""
        hours = query_int("hours", 24, min_value=1, max_value=87600)
        days = max(1, hours // 24)
        zone_arg = (request.args.get("zone") or "0").strip().lower()
        conn = db.get_conn()
        if zone_arg == "all":
            turf_ids = [z["id"] for z in config["zones"]
                        if z.get("installed", False) and z.get("type") == "sprinkler"]
            if not turf_ids:
                conn.close()
                return jsonify([])
            placeholders = ",".join("?" for _ in turf_ids)
            # rain is identical across zones on a given day -> AVG == that value.
            # balance/ET/irrigation averaged = typical depth the lawn experienced.
            rows = conn.execute(
                "SELECT date as ts, AVG(balance_mm) as balance_mm, "
                "AVG(taw_mm) as taw_mm, AVG(mad_mm) as mad_mm, AVG(et0_mm) as et0_mm, "
                "AVG(rain_mm) as rain_mm, AVG(irrigation_mm) as irrigation_mm, "
                "AVG(etc_mm) as etc_mm FROM soil_balance "
                f"WHERE zone_id IN ({placeholders}) "
                "AND date >= date('now','localtime',?) GROUP BY date ORDER BY date",
                (*turf_ids, f"-{days} days"),
            ).fetchall()
        else:
            try:
                zone_id = max(0, min(int(zone_arg), len(config["zones"]) - 1))
            except ValueError:
                zone_id = 0
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
    cam_state = {"image": None, "timestamp": None, "flash": False, "ocr_count": 0,
                 "transfer_s": None, "last_frame_ts": None, "gap_s": None,
                 "rssi": None, "uptime_sec": None, "reconnects": None}
    meter_reader = MeterReader()

    # ── OCR lag buffer + tower worker ──────────────────────────────────
    # The cam pushes a frame every 5s. OCR runs off-box on the gaming tower
    # (jackmint). To survive OCR being slower than capture, frames land in a
    # bounded in-memory FIFO; a worker drains it oldest-first. If OCR ever
    # falls behind by >100 frames (~8 min), the oldest are dropped (we only
    # care about the latest meter reading, never a backlog). No disk, no DB.
    from collections import deque as _deque
    import threading as _threading
    OCR_TOWER_URL = os.environ.get("OCR_TOWER_URL", "http://192.168.0.120:5200/ocr")
    OCR_ENABLED = os.environ.get("OCR_ENABLED", "1") == "1"
    # Custom CNN reader (tower :5201) — the FAST FREE path. The OCR worker calls
    # the CNN first; if it reads all 9 digits with high confidence we use that
    # (free, ~100ms). Only when the CNN is unsure do we fall back to RapidOCR +
    # the paid GPT-4o oracle. The CNN's digits are still fed through the physics
    # validator (meter_reader), so the monotonic / forward-only guard stays on
    # top of whatever reads the digits (guardrail #3).
    CNN_URL = os.environ.get("METER_CNN_URL", "http://192.168.0.120:5201/cnn")
    CNN_ENABLED = os.environ.get("METER_CNN_ENABLED", "1") == "1"
    # Training-data banking: when the validator produces a HIGH-confidence read,
    # save (raw frame JPEG, validated 9-digit label) so a custom per-digit model
    # can be trained later on THIS meter under THIS camera's real conditions.
    # Banking continuously over days captures glare in every position and any
    # camera drift, which is exactly the variation a robust model must learn.
    # Auto-labeled = free: the label is the validator's own high-confidence read.
    BANK_ENABLED = os.environ.get("METER_BANK_ENABLED", "1") == "1"
    # Local-OCR banking is SEPARATE and OFF by default now that the CNN is the
    # primary reader: banking a CNN read keyed by its own digits is CIRCULAR
    # (the model would label itself), and RapidOCR is too noisy to be a trusted
    # verifier. So the ONLY banking path is the oracle (an independent verifier).
    # _bank_sample stays gated behind this extra flag (default off).
    LOCAL_BANK_ENABLED = os.environ.get("METER_LOCAL_BANK_ENABLED", "0") == "1"
    BANK_DIR = os.environ.get("METER_BANK_DIR", "/home/jamesearlpace/meter-training")
    BANK_MAX = int(os.environ.get("METER_BANK_MAX", "20000"))
    BANK_MIN_INTERVAL = float(os.environ.get("METER_BANK_MIN_INTERVAL", "5"))
    # Per-reading frame ring: stash EVERY processed frame keyed by its row id so
    # the UI can show "this is the exact image the OCR saw for this row." Bounded
    # ring (newest N) so disk stays small — this is for live inspection/trust,
    # not training (that's BANK_DIR). Default ~720 ≈ 1h of 5s frames (~30MB).
    FRAME_DIR = os.environ.get("METER_FRAME_DIR", "/tmp/meter-frames")
    FRAME_KEEP = int(os.environ.get("METER_FRAME_KEEP", "720"))
    _frame_ids = _deque(maxlen=FRAME_KEEP)   # ids with a saved frame, oldest-left
    cam_queue = _deque(maxlen=720)            # the lag buffer (~1h at 5s/frame)
    cam_queue_lock = _threading.Lock()
    cam_ocr_stats = {"processed": 0, "errors": 0, "last_ms": None, "dropped": 0,
                     "banked": 0, "cnn_used": 0, "cnn_fellback": 0,
                     "reader": "?"}
    _bank_state = {"last_ts": 0.0, "last_label": None}

    def _save_frame(rid, frame):
        """Persist a frame under its reading id, pruning the oldest beyond the
        ring cap. Best-effort: never let a disk hiccup break OCR."""
        if not rid or not frame:
            return
        try:
            os.makedirs(FRAME_DIR, exist_ok=True)
            with open(os.path.join(FRAME_DIR, f"{rid}.jpg"), "wb") as f:
                f.write(frame)
            if len(_frame_ids) == _frame_ids.maxlen:
                old = _frame_ids[0]              # about to be evicted by append
                try:
                    os.remove(os.path.join(FRAME_DIR, f"{old}.jpg"))
                except OSError:
                    pass
            _frame_ids.append(rid)
        except Exception as e:
            log.debug("save_frame failed: %s", e)


    def _bank_sample(frame, entry, captured_ts):
        """Save a high-confidence (frame, label) pair for future model training.

        Only banks genuine high-confidence reads (not holds/stale/derived), at
        most one per BANK_MIN_INTERVAL seconds, and skips consecutive duplicates
        of the same label so a steady meter doesn't flood the disk with identical
        frames. Filename embeds the label + timestamp so it's self-describing:
        ``<9-digit-reading>_<epoch_ms>.jpg``.
        """
        if not (BANK_ENABLED and LOCAL_BANK_ENABLED):
            return            # local/circular banking off — oracle is the only banker
        try:
            if entry.get("confidence") != "high" or entry.get("kind") != "raw":
                return
            # Only bank when the OCR INDEPENDENTLY corroborates the reading: its
            # raw low-5 digits must match the validated reading's low-5. This is
            # the non-circular trust signal — it stops a drifted/garbage label
            # from poisoning the training set (the bug that mislabeled frames
            # showing 094008797 as 094012008).
            if entry.get("raw_low_match") is not True:
                return
            label = str(entry.get("reading", "")).replace("\u2014", "").strip()
            if not label.isdigit() or len(label) != 9:
                return
            now = captured_ts or time.time()
            if now - _bank_state["last_ts"] < BANK_MIN_INTERVAL:
                return
            if label == _bank_state["last_label"]:
                # Steady meter: keep occasional samples (every ~10x interval)
                # so we still capture lighting drift, but don't spam identical
                # frames every cycle.
                if now - _bank_state["last_ts"] < BANK_MIN_INTERVAL * 10:
                    return
            os.makedirs(BANK_DIR, exist_ok=True)
            # Per-distinct-number cap: don't flood the dataset with many images
            # of the SAME reading (a model learns nothing from duplicates). Keep
            # a few per number for lighting variety, skip the rest.
            try:
                same = sum(1 for f in os.listdir(BANK_DIR)
                           if f.startswith(label + "_") and f.endswith(".jpg"))
                if same >= GOLD_MAX_PER_LABEL:
                    return
            except OSError:
                pass
            # Cheap size cap: prune oldest if over BANK_MAX (count .jpg only).
            try:
                jpgs = sorted(f for f in os.listdir(BANK_DIR)
                              if f.endswith(".jpg"))
                if len(jpgs) >= BANK_MAX:
                    for old in jpgs[:max(1, len(jpgs) - BANK_MAX + 1)]:
                        for ext in (".jpg", ".json"):
                            try:
                                os.remove(os.path.join(
                                    BANK_DIR, old[:-4] + ext))
                            except OSError:
                                pass
            except OSError:
                pass
            stem = f"{label}_{int(now * 1000)}"
            with open(os.path.join(BANK_DIR, stem + ".jpg"), "wb") as f:
                f.write(frame)
            # Sidecar metadata so label-filtering later can be rigorous: keep
            # the OCR's own raw guess + fit score + what the validator did, so a
            # training sample is only trusted when guess==label AND fit is high
            # AND it's consistent with neighbours / audited against your manual
            # anchor readings. This is what keeps the model from learning the
            # current pipeline's mistakes.
            try:
                guess = str(entry.get("ocr_guess", "")).split()[0] \
                    if entry.get("ocr_guess") else ""
                meta = {
                    "label": label,
                    "ocr_guess": guess,
                    "fit": entry.get("note", ""),
                    "confidence": entry.get("confidence"),
                    "captured_ts": now,
                    "raw_ocr": entry.get("raw_n", ""),
                    # Independent corroboration: raw OCR low-5 matched the label.
                    "agree": entry.get("raw_low_match") is True,
                }
                import json as _json
                with open(os.path.join(BANK_DIR, stem + ".json"), "w") as f:
                    _json.dump(meta, f)
            except Exception:
                pass
            _bank_state["last_ts"] = now
            _bank_state["last_label"] = label
            cam_ocr_stats["banked"] += 1
        except Exception as e:
            log.debug("bank_sample failed: %s", e)

    # --- Vision-LLM oracle: the high-quality fallback + drift fix -----------
    # The fast pipeline can't read through bad glare and can't recover from a
    # false-high lock. So we call GPT-4o vision in two cases:
    #   (a) STALE — the lock hasn't moved on a trusted read for a while, or
    #   (b) LOW-CONFIDENCE — this very frame couldn't be read cleanly.
    # Each trusted oracle read both RE-ANCHORS the lock (so the dashboard shows
    # the truth) AND is banked as a GOLD training label (independent ground
    # truth from a different model — exactly the data a future custom model
    # needs). Rate-limited so cost stays at a few tenths of a cent per call.
    ORACLE_ENABLED = os.environ.get("METER_ORACLE_ENABLED", "1") == "1"
    ORACLE_STALE_SECS = float(os.environ.get("METER_ORACLE_STALE_SECS", "180"))
    ORACLE_MIN_INTERVAL = float(os.environ.get("METER_ORACLE_MIN_INTERVAL", "45"))
    ORACLE_LOWCONF_INTERVAL = float(
        os.environ.get("METER_ORACLE_LOWCONF_INTERVAL", "60"))
    # Trust-but-verify heartbeat: re-check even HIGH-confidence reads this often,
    # to catch a systematic-misread drift the local pipeline is falsely sure of.
    ORACLE_VERIFY_SECS = float(os.environ.get("METER_ORACLE_VERIFY_SECS", "300"))
    ORACLE_DAILY_CAP = int(os.environ.get("METER_ORACLE_DAILY_CAP", "800"))
    # Counts of read-jitter to allow when the meter is IDLE (no zone on): the
    # register shouldn't move, so any advance beyond this when idle is suspect
    # and must be corroborated before it moves the lock. 200 counts = 0.2 ft³.
    ORACLE_IDLE_JITTER = float(os.environ.get("METER_ORACLE_IDLE_JITTER", "200"))
    # Two oracle reads within this many counts of each other are reading the
    # same physical state — used to corroborate a meaningful move (real
    # household use, a downward correction, or stale catch-up) before committing
    # it. Kept TIGHT: under glare the oracle scatters wildly (e.g. 634 then 911
    # for a 620 meter), and a loose tol would let two unrelated garbles "agree".
    # A readable meter (real use or static) reads consistently within a few
    # counts, so a tight tol commits only genuinely readable states.
    ORACLE_CORROB_TOL = float(os.environ.get("METER_ORACLE_CORROB_TOL", "40"))
    # A forward step this small (counts) with no sprinkler running is in the
    # last-digit GLARE-NOISE range — real household water use (shower/toilet/tap)
    # moves the register far more. Tiny steps need an exact-repeat to commit, so
    # noise can't ratchet the lock upward. 20 counts ≈ 0.02 ft³ ≈ 0.15 gal.
    ORACLE_NOISE_BAND = int(os.environ.get("METER_ORACLE_NOISE_BAND", "20"))
    # Max gold-dataset images to keep PER DISTINCT reading. One clean image per
    # number is enough to train a per-digit model (a model learns nothing extra
    # from 3 copies of the same digits), and it keeps the set lean. Raise via env
    # if lighting variety per number turns out to matter for the CNN.
    GOLD_MAX_PER_LABEL = int(os.environ.get("METER_GOLD_MAX_PER_LABEL", "1"))
    # CONFIDENT-WRONG GUARD: a high-confidence CNN read is normally trusted
    # directly (free path, no oracle). But a CNN can be CONFIDENTLY WRONG — on
    # 2026-06-15 a 0.95-conf misread ratcheted the lock ~2000 counts too high,
    # and because high-conf reads skip the oracle nothing caught it until the
    # meter sat ~2000 high for a while. So: if a high-conf CNN read would
    # ADVANCE the lock by more than this many counts (more than one frame of
    # plausible flow), do NOT trust it directly — force the independent oracle
    # to corroborate before the lock moves. Real fast usage / stale-recovery
    # still works (the oracle confirms it); only confident-wrong jumps are
    # stopped. A normal 5s frame at max flow advances ~290 counts.
    CNN_MAX_TRUST_ADVANCE = float(
        os.environ.get("METER_CNN_MAX_TRUST_ADVANCE", "500"))
    _oracle_state = {"last_call": 0.0, "last_verify": 0.0, "calls": 0,
                     "reanchors": 0, "labels": 0, "dupes": 0, "day": "",
                     "day_calls": 0, "busy": False, "confirmed_val": None,
                     "last_result": None, "last_value": None,
                     "pending_val": None, "pending_ts": 0.0}

    def _active_gpm():
        """Sum of est_gpm for zones the controller currently has ON (0 if idle).

        Lets the oracle judge how far the register could PHYSICALLY have moved:
        when no zone is running the meter shouldn't climb at all, so a big jump
        is almost certainly a misread — not real water.
        """
        try:
            active = status_summary().get("active_zones", []) or []
        except Exception:
            active = []
        if not active:
            return 0.0
        gpm = 0.0
        for z in config.get("zones", []):
            if z.get("id") in active:
                gpm += float(z.get("est_gpm", 4.0) or 0.0)
        return max(gpm, 1.0)

    def _oracle_ceiling(elapsed_s):
        """Max plausible forward advance (counts) over elapsed_s, given which
        zones are running. Idle → just read jitter; a zone on → its est_gpm ×
        time × a safety margin. Far tighter than the old max_gpm-always bound,
        which let a static meter 'advance' thousands of counts."""
        gpm = _active_gpm()
        margin = 1.5 if gpm > 0 else 1.0
        counts = (gpm / 60.0) * max(elapsed_s, 0) * cam_ocr.COUNTS_PER_GAL * margin
        return counts + ORACLE_IDLE_JITTER

    def _oracle_bank_label(frame, value, captured_ts, conf, local_low=None,
                           cnn_digits=None):
        """Bank a frame with an oracle-provided GOLD label.

        DEDUP: only keep a small number of images PER DISTINCT reading. A static
        meter would otherwise flood the gold set with hundreds of identical
        numbers, which adds no training value (a model learns nothing from 200
        copies of the same digits) and wastes disk. We keep up to
        GOLD_MAX_PER_LABEL per value (a few, to capture lighting/glare variety)
        and skip the rest.

        TRUST HONESTY: the oracle is a SINGLE reader, so we must NOT claim the
        label was independently corroborated. ``agree`` is true only if the
        local RapidOCR's low-5 digits (``local_low``, a genuinely independent
        reader) match the oracle's value. Otherwise agree=false — the label is
        oracle-only and must be cross-verified before it trains a CNN (see
        ocr-harness/build_cnn_dataset.py). Never hardcode agree=true here;
        that's the circular bug that let bad labels pose as ground truth.
        """
        if not BANK_ENABLED:
            return            # collection turned off — keep reading, stop banking
        try:
            label = f"{int(value):09d}"
            os.makedirs(BANK_DIR, exist_ok=True)
            existing = 0
            try:
                existing = sum(1 for f in os.listdir(BANK_DIR)
                               if f.startswith(label + "_") and f.endswith(".jpg"))
            except OSError:
                pass
            if existing >= GOLD_MAX_PER_LABEL:
                _oracle_state["dupes"] = _oracle_state.get("dupes", 0) + 1
                return  # already have enough of this exact number
            stem = f"{label}_{int((captured_ts or time.time()) * 1000)}_oracle"
            with open(os.path.join(BANK_DIR, stem + ".jpg"), "wb") as f:
                f.write(frame)
            # Honest agreement: only true if an INDEPENDENT reader (local
            # RapidOCR low-5) matched the oracle's value. Oracle-alone = false.
            agree = bool(local_low) and (local_low == label[-5:])
            # CORRECTION TAGGING: record what the CNN said for this frame and
            # whether it matched the oracle. cnn_correct=False = this is a
            # genuine CNN failure the oracle caught = the highest-value training
            # example for the next retrain. The LABEL is always the oracle's
            # value (the trusted reader); cnn_* is just metadata.
            cnn_correct = None
            if cnn_digits and len(str(cnn_digits)) == 9:
                cnn_correct = (str(cnn_digits) == label)
            import json as _json
            with open(os.path.join(BANK_DIR, stem + ".json"), "w") as f:
                _json.dump({"label": label, "ocr_guess": label,
                            "confidence": conf, "captured_ts": captured_ts,
                            "source": "oracle", "agree": agree,
                            "local_low": local_low or "",
                            "cnn_said": cnn_digits or "",
                            "cnn_correct": cnn_correct}, f)
            if cnn_correct is False:
                _oracle_state["corrections"] = _oracle_state.get("corrections", 0) + 1
                cam_ocr_stats["cnn_corrections"] = _oracle_state["corrections"]
                log.info("CNN correction banked: cnn said %s, oracle %s",
                         cnn_digits, label)
            _oracle_state["labels"] += 1
            cam_ocr_stats["oracle_labels"] = _oracle_state["labels"]
            # Persist the oracle-vs-CNN comparison for improvement reporting
            # (every oracle read is a free CNN-accuracy sample).
            try:
                import cnn_metrics
                cnn_metrics.log_eval(
                    cnn_digits, _oracle_state.get("last_cnn_conf"),
                    label, _oracle_state.get("cnn_version", "v1"),
                    cam_ocr_stats.get("reader"))
            except Exception:
                pass
        except Exception as e:
            log.debug("oracle bank failed: %s", e)

    def _maybe_oracle(frame, entry, captured_ts, cnn_digits=None, force=False):
        """Fast, NON-BLOCKING decision: should the oracle run? If so, spawn a
        background thread for the slow GPT-4o call so the OCR worker keeps
        processing frames every 5s. The worker must never block on the network.

        force=True bypasses the rate-limit / change gates (still respects the
        in-flight lock and the daily cap) — used for high-risk events like a
        suspicious big CNN jump that must be corroborated immediately.
        """
        if not ORACLE_ENABLED:
            return
        try:
            import vision_oracle
        except Exception:
            return
        if not vision_oracle.available():
            return
        # Only one oracle call in flight at a time.
        if _oracle_state.get("busy"):
            return
        now = time.time()
        today = time.strftime("%Y-%m-%d")
        if _oracle_state["day"] != today:
            _oracle_state["day"] = today
            _oracle_state["day_calls"] = 0
        if _oracle_state["day_calls"] >= ORACLE_DAILY_CAP:
            return

        conf = (entry or {}).get("confidence")
        lock_ts = getattr(meter_reader, "_lock_ts", None) or 0
        stale_for = now - lock_ts
        since_call = now - _oracle_state["last_call"]
        since_verify = now - _oracle_state.get("last_verify", 0)

        # When to call the oracle:
        #  - LOW-CONF: this frame couldn't be read cleanly.
        #  - STALE: the lock hasn't moved on a trusted read for a while.
        #  - VERIFY HEARTBEAT: periodically check EVEN high-confidence reads, to
        #    catch a systematic-misread drift the pipeline is falsely sure of.
        is_stale = stale_for >= ORACLE_STALE_SECS
        is_lowconf = conf in ("low", "medium", "stale", "none", None)
        is_verify = since_verify >= ORACLE_VERIFY_SECS
        # Don't re-send the SAME number to the AI. If this frame's reading is
        # high-confidence and equals the value the oracle already confirmed,
        # there's nothing new to verify or learn — skip the call. The oracle
        # only needs to weigh in when the number is CHANGING (water moving) or
        # when the local read is uncertain. This stops a static meter from
        # racking up identical verification calls.
        cur_val = None
        try:
            rd = str((entry or {}).get("reading", "")).strip()
            if rd.isdigit():
                cur_val = int(rd)
        except Exception:
            pass
        unchanged = (cur_val is not None
                     and cur_val == _oracle_state.get("confirmed_val"))
        # A forced call (e.g. a suspicious big CNN jump) skips the normal gates
        # below — it's a high-risk event we always want verified right away.
        if not force:
            if conf == "high" and unchanged:
                return
            if is_stale and since_call < ORACLE_MIN_INTERVAL:
                return
            if is_lowconf and (not is_stale) \
                    and since_call < ORACLE_LOWCONF_INTERVAL:
                return
            if not (is_stale or is_lowconf or is_verify):
                return

        # Reserve the slot NOW (so the next frames don't also fire), then hand
        # the slow work to a background thread and return immediately.
        _oracle_state["busy"] = True
        _oracle_state["last_call"] = now
        if is_verify:
            _oracle_state["last_verify"] = now
        _oracle_state["day_calls"] += 1
        # Capture the LOCAL reader's independent low-5 digits for this frame so
        # the oracle bank can honestly record whether a second reader agreed.
        local_low = None
        try:
            rl = (entry or {}).get("raw_n") or ""
            digs = "".join(ch for ch in str(rl) if ch.isdigit())
            if len(digs) >= 5:
                local_low = digs[-5:]
        except Exception:
            local_low = None
        _threading.Thread(
            target=_oracle_run,
            args=(bytes(frame), captured_ts, stale_for, now, local_low, cnn_digits),
            daemon=True, name="oracle").start()

    def _oracle_splice(oracle_digits, lock, ceiling):
        """Repair an oracle read whose HIGH digits are garbled.

        Under glare GPT-4o reads the LOW (moving) digits of the LCD reliably but
        sometimes mangles the leading 1-2 digits (09 -> 34/84), so the raw value
        lands far below the anchor floor and gets discarded — the meter then
        sits stale for hours even though AI read the changing digits correctly.
        The meter's high digits barely ever move (094 won't roll for thousands
        of cubic feet), so keep the lock's high digits and overlay the oracle's
        trusted low digits. Try the longest overlay first; accept the first that
        is a physically-plausible forward step from the lock. Returns int|None.
        """
        if lock is None or not oracle_digits:
            return None
        lock_s = f"{int(lock):09d}"
        for k in range(7, 4, -1):                 # overlay low 7..5 digits
            if len(oracle_digits) < k:
                continue
            low = oracle_digits[-k:]
            try:
                cand = int(lock_s[:9 - k] + low)
            except ValueError:
                continue
            d = cand - lock
            # FORWARD-ONLY: a water meter is monotonic. Only accept a spliced
            # value at or ahead of the lock (within the physical ceiling). A
            # candidate below the lock means the oracle's low digits were ALSO
            # misread (systematic evening blur) — never let that pull the lock
            # backward; hold instead.
            if 0 <= d <= ceiling:
                return cand
        return None

    def _oracle_run(frame, captured_ts, stale_for, now, local_low=None,
                    cnn_digits=None):
        """Background: the slow GPT-4o call + re-anchor. Never runs in the OCR
        worker thread, so frame processing keeps its 5s cadence."""
        try:
            import vision_oracle
            # Give the model physics context so it can reason through glare on
            # the HIGH digits: the leading digits barely change, so tell it the
            # expected prefix. We DELIBERATELY do NOT send a hard "you're at
            # least X" floor: the lock itself can be wrong (a local over-read can
            # ratchet it too high), and a floor would then bias the oracle to
            # confirm the bad value instead of correcting it. Prefix alone fixes
            # the glare-on-high-digits problem; the low digits come from pixels.
            lg0 = getattr(meter_reader, "last_good", None)
            hint = None
            if lg0 is not None:
                hint = {
                    "last_value": int(lg0),
                    "high_prefix": f"{int(lg0):09d}"[:4],
                }
            res = vision_oracle.read_meter(frame, rotate180=True, hint=hint)
            _oracle_state["calls"] += 1
            _oracle_state["last_result"] = res
            _oracle_state["last_value"] = res.get("value")
            cam_ocr_stats["oracle_calls"] = _oracle_state["calls"]
            if not res.get("ok") or res.get("confidence") == "low" \
                    or not res.get("readable"):
                log.info("oracle read not trusted: %s", res)
                return
            val = res["value"]
            digits = res.get("digits", "") or ""
            lg = getattr(meter_reader, "last_good", None)
            anchor = getattr(meter_reader, "anchor_value", 0)
            # Idle-aware physical ceiling since the lock last moved (counts).
            elapsed = max(stale_for, 5)
            ceiling = _oracle_ceiling(elapsed)
            # HIGH-DIGIT GARBLE REPAIR: if the raw oracle value is implausible
            # (its high digits were mangled by glare while the low digits are
            # good), splice the trusted low digits onto the lock's stable high
            # digits so a glared frame still produces a usable reading.
            raw_ok = (val is not None and val >= anchor - 5
                      and lg is not None and 0 <= val - lg <= ceiling)
            if not raw_ok and lg is not None:
                spliced = _oracle_splice(digits, lg, ceiling)
                if spliced is not None:
                    log.info("oracle high-digit garble repaired: raw %s -> "
                             "%09d (low digits trusted, lock %s)",
                             val, spliced, lg)
                    val = spliced
            if val is None or val < anchor - 5:
                log.warning("oracle value %s below anchor floor %s — ignored",
                            val, anchor)
                _oracle_state["pending_val"] = None
                return
            # ── Accept / corroborate ────────────────────────────────────────
            # A water meter is monotonic, but the LOCK is only an estimate and
            # can be wrong in EITHER direction (a local over-read ratchets it too
            # high; a glare misread could read low). So:
            #   • A small FORWARD step within the idle-aware physical ceiling is
            #     normal real flow → accept immediately.
            #   • ANY larger move — a big jump up OR a downward correction —
            #     requires a SECOND oracle read to agree within ORACLE_CORROB_TOL
            #     before it moves the lock. One-off garbage (high or low) never
            #     repeats, so it's held as "pending"; two independent reads that
            #     agree are trusted (this is what lets the lock self-heal back
            #     DOWN after a local over-read, instead of being stuck high).
            # A water meter moves with ALL household use (showers, toilets,
            # taps) — not just sprinklers — so "no zone running" does NOT mean
            # the meter is static. But under glare the oracle's last-digit
            # guesses jitter by a few counts, and a forward-only lock would
            # ratchet on that noise. Discriminate by MAGNITUDE instead: real
            # water use moves the register far more than the last-digit noise.
            commit = False
            zone_on = _active_gpm() > 0
            if lg is None:
                commit = True
            else:
                d = val - lg
                prev = _oracle_state.get("pending_val")
                if d == 0:
                    commit = True                      # confirms the held value
                elif zone_on and 0 < d <= ceiling:
                    commit = True                      # sprinklers on — real flow
                elif 0 < d <= ORACLE_NOISE_BAND:
                    # tiny forward step, no sprinkler running: almost certainly
                    # last-digit GLARE NOISE (a shower/toilet/tap moves the meter
                    # far more). Commit only if a 2nd read EXACTLY repeats it —
                    # random noise never does, so the lock holds (no ratchet).
                    if prev is not None and val == prev:
                        commit = True
                    else:
                        _oracle_state["pending_val"] = val
                        _oracle_state["pending_ts"] = now
                        log.info("oracle %09d vs lock %s held — last-digit noise "
                                 "guard (no sprinkler flow)", val, lg)
                        return
                elif prev is not None and abs(val - prev) <= ORACLE_CORROB_TOL:
                    # A MEANINGFUL move — real household use (shower/toilet/tap),
                    # or stale catch-up — confirmed by a 2nd agreeing read. This
                    # is what lets non-sprinkler usage register while one-off
                    # garbage (which never repeats) is rejected.
                    commit = True
                    log.info("oracle move corroborated: %09d (lock %s, prev %s)",
                             val, lg, prev)
                else:
                    _oracle_state["pending_val"] = val
                    _oracle_state["pending_ts"] = now
                    log.info("oracle %09d vs lock %s held for a confirming read",
                             val, lg)
                    return
            if not commit:
                return
            _oracle_state["pending_val"] = None
            if meter_reader.reanchor(val, ts=now, source="oracle"):
                _oracle_state["reanchors"] += 1
                cam_ocr_stats["oracle_reanchors"] = _oracle_state["reanchors"]
                log.info("oracle read %09d (conf=%s, was lock %s) — reanchored + banked",
                         val, res.get("confidence"), lg)
                # Surface this as a real readings-table row: the AI genuinely
                # read THIS frame, so it shows its number (fresh_read) instead of
                # the local OCR's "reading pending" for the same glared frame.
                try:
                    oentry = meter_reader.record_oracle_reading(
                        val, captured_ts=captured_ts)
                    # Save the frame the oracle actually read under the new row's
                    # id so the reading-detail page can show its image (the local
                    # OCR worker only saves frames for ITS own rows, so oracle
                    # rows had no inspectable frame).
                    if oentry and oentry.get("id"):
                        _save_frame(oentry["id"], frame)
                except Exception as e:
                    log.debug("record_oracle_reading failed: %s", e)
            # Remember the confirmed value so we don't re-send the SAME number.
            _oracle_state["confirmed_val"] = val
            _oracle_bank_label(frame, val, captured_ts, res.get("confidence"),
                               local_low=local_low, cnn_digits=cnn_digits)
        except Exception as e:
            log.debug("oracle thread failed: %s", e)
        finally:
            _oracle_state["busy"] = False

    def _read_via_cnn(frame):
        """Ask the tower CNN to read the frame. Returns its JSON dict
        ({digits, min_conf, confidence, value, ms}) or None if unavailable.
        The CNN is the fast free path; only its HIGH-confidence reads are used
        directly (the caller decides), but its digits still pass through the
        physics validator."""
        if not CNN_ENABLED:
            return None
        try:
            r = http_requests.post(
                CNN_URL, data=frame,
                headers={"Content-Type": "image/jpeg"}, timeout=8)
            if r.status_code == 200:
                return r.json()
        except Exception as e:
            log.debug("cnn call failed: %s", e)
        return None

    def _ocr_worker():
        """OCR every frame in order, oldest-first (FIFO).

        Data quality over latency: we want EVERY 5s frame processed and shown,
        preserving the 5-second spacing, even if that means falling behind for
        a while and catching up later. OCR on the tower (~1s/frame) is normally
        faster than the 5s capture cadence, so the queue stays near empty; if
        the tower hiccups and a backlog builds, the worker simply works through
        it in order. The deque is still bounded (maxlen=720 ≈ 1h) so a long
        outage can't grow memory without limit — only then are the very oldest
        frames dropped.
        """
        while True:
            item = None
            depth = 0
            with cam_queue_lock:
                if cam_queue:
                    item = cam_queue.popleft()      # oldest frame first
                depth = len(cam_queue)              # frames still waiting
            if item is None:
                time.sleep(0.25)
                continue
            captured_ts, frame = item
            try:
                # 1) FAST FREE PATH: ask the custom CNN first. If it reads all 9
                #    digits with high confidence, use that — no RapidOCR, no
                #    paid oracle. Its digits still go through the physics
                #    validator below, so the monotonic guard stays on top.
                cnn = _read_via_cnn(frame)
                text = None
                used_cnn = False
                cnn_big_jump = False    # high-conf CNN read, but a suspicious
                                        # big advance -> force oracle to confirm
                trust_cnn = False
                if cnn and cnn.get("confidence") == "high" and cnn.get("digits"):
                    # CONFIDENT-WRONG GUARD: don't trust a high-conf CNN read
                    # blindly if it would jump the lock a long way forward — a
                    # systematic misread can be confidently wrong. Let the
                    # oracle (independent reader) corroborate big jumps first.
                    lg = getattr(meter_reader, "last_good", None)
                    cnn_val = None
                    try:
                        cnn_val = int(cnn["digits"])
                    except (ValueError, TypeError):
                        cnn_val = None
                    if (lg is not None and cnn_val is not None
                            and (cnn_val - int(lg)) > CNN_MAX_TRUST_ADVANCE):
                        cnn_big_jump = True
                        cam_ocr_stats["cnn_bigjump"] = (
                            cam_ocr_stats.get("cnn_bigjump", 0) + 1)
                        log.warning(
                            "CNN high-conf BIG JUMP held for oracle: "
                            "cnn=%s lock=%s (+%s) min_conf=%s",
                            cnn.get("digits"), lg, cnn_val - int(lg),
                            cnn.get("min_conf"))
                    else:
                        trust_cnn = True
                if trust_cnn:
                    text = cnn["digits"]
                    cam_ocr_stats["last_ms"] = cnn.get("ms")
                    cam_ocr_stats["cnn_used"] += 1
                    cam_ocr_stats["reader"] = "cnn"
                    used_cnn = True
                else:
                    # 2) FALLBACK: RapidOCR on the tower (the CNN was unsure,
                    #    unavailable, or made a suspicious big jump). The paid
                    #    oracle kicks in below for low-conf/stale/big-jump.
                    if cnn is not None:
                        cam_ocr_stats["cnn_fellback"] += 1
                    r = http_requests.post(
                        OCR_TOWER_URL, data=frame,
                        headers={"Content-Type": "image/jpeg"}, timeout=20,
                    )
                    if r.status_code == 200:
                        text = r.json().get("text", "")
                        cam_ocr_stats["last_ms"] = r.json().get("ms")
                        cam_ocr_stats["reader"] = "rapidocr"
                    else:
                        cam_ocr_stats["errors"] += 1
                        log.warning("tower OCR %s: %s", r.status_code, r.text[:120])
                        continue
                if text is not None:
                    entry = meter_reader.process_text(
                        text, captured_ts=captured_ts, queue_depth=depth)
                    cam_ocr_stats["processed"] += 1
                    # Stash THIS frame under the row's id so the reading-detail
                    # page can show the exact image the OCR saw for this row.
                    _save_frame(entry.get("id"), frame)
                    # Bank the raw frame + label when the read is high-confidence
                    # (builds an auto-labeled dataset for a future custom model).
                    _bank_sample(frame, entry, captured_ts)
                    # Low-confidence or stale? Ask the vision LLM to read it,
                    # re-anchor, and bank a gold label (rate-limited internally).
                    # Also fires the periodic spot-check heartbeat even when the
                    # CNN was confident — catches confident-but-wrong drift.
                    # Pass the CNN's reading so the oracle bank can tag whether
                    # the CNN was right (confirmation) or wrong (CORRECTION) —
                    # corrections are the highest-value training data.
                    cnn_digits = (cnn or {}).get("digits") if cnn else None
                    # Stash CNN conf + version so the oracle eval log can record
                    # a full accuracy sample.
                    if cnn:
                        _oracle_state["last_cnn_conf"] = cnn.get("min_conf")
                        _oracle_state["cnn_version"] = cnn.get("version", "v1")
                    # force=True on a suspicious big CNN jump so the oracle
                    # corroborates it NOW (bypassing the rate limit) before the
                    # lock is allowed to move that far.
                    _maybe_oracle(frame, entry, captured_ts, cnn_digits,
                                  force=cnn_big_jump)
                    # Daily reader-split counters for cost-ramp reporting.
                    try:
                        import cnn_metrics
                        cnn_metrics.bump_daily(
                            cam_ocr_stats.get("reader"), used_cnn,
                            (cnn is not None and not used_cnn))
                    except Exception:
                        pass
            except Exception as e:
                cam_ocr_stats["errors"] += 1
                log.debug("reader call failed: %s", e)
                time.sleep(1.0)  # back off when the tower is unreachable

    if OCR_ENABLED:
        _threading.Thread(target=_ocr_worker, daemon=True, name="ocr-worker").start()
        log.info("OCR worker started -> %s", OCR_TOWER_URL)

    # Flow monitor: correlate the live meter register with which zone is ON to
    # estimate per-zone GPM (recency-weighted) and detect leaks / overruns /
    # high-flow anomalies. Isolated module, owns its own tables, read-only on
    # the meter lock. Background sampler runs independently of the OCR worker.
    try:
        import flow_monitor
        flow_monitor.start(meter_reader, status_summary, config)
    except Exception as e:
        log.warning("flow_monitor start failed: %s", e)

    # CNN metrics: persistent improvement reporting (live CNN accuracy over time
    # from oracle verifications + daily reader split). Isolated, own tables.
    try:
        import cnn_metrics
        cnn_metrics.ensure_schema()
    except Exception as e:
        log.warning("cnn_metrics init failed: %s", e)

    # ── ESP32-CAM background pinger ────────────────────────────────────
    # Frame telemetry covers the cam while it's uploading, but if it drops off
    # WiFi entirely the frames just stop — a ping gives an independent reachable/
    # RTT signal even during an outage. Lightweight: one ICMP ping/60s. Also
    # prunes the telemetry table daily so it stays bounded.
    import subprocess as _subprocess, re as _re
    CAM_PING_HOST = CAM_URL.replace("http://", "").replace("https://", "").split("/")[0]

    def _cam_pinger():
        _prune_at = 0.0
        while True:
            try:
                r = _subprocess.run(["ping", "-c", "1", "-W", "2", CAM_PING_HOST],
                                    capture_output=True, text=True, timeout=6)
                ok = (r.returncode == 0)
                ms = None
                if ok:
                    m = _re.search(r"time=([\d.]+)\s*ms", r.stdout)
                    if m:
                        ms = int(round(float(m.group(1))))
                db.log_cam_ping(ms, ok)
            except Exception as e:
                try:
                    db.log_cam_ping(None, False)
                except Exception:
                    pass
                log.debug("cam pinger: %s", e)
            # Daily prune (keep 14 days).
            if time.time() - _prune_at > 86400:
                try:
                    db.prune_cam_telemetry(days=14)
                    _prune_at = time.time()
                except Exception as e:
                    log.debug("cam telemetry prune failed: %s", e)
            time.sleep(60)

    _threading.Thread(target=_cam_pinger, daemon=True, name="cam-pinger").start()
    log.info("cam pinger started -> %s", CAM_PING_HOST)

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
        # Time the body read — on this lossy WiFi a 50KB JPEG can take many
        # seconds to actually transfer (TCP retransmits). That transfer time is
        # the gap between when the camera CAPTURED the frame and when it lands
        # here. Subtract it so the "capture time" reflects the pixels, not the
        # arrival. (Fully accurate timing needs a firmware capture-timestamp;
        # this is a good no-reflash approximation.)
        _t_recv0 = time.time()
        data = request.get_data(cache=False)
        transfer_s = time.time() - _t_recv0
        if not data or len(data) < 100:
            return jsonify({"error": "No image data"}), 400
        if len(data) > CAM_MAX_UPLOAD_BYTES:
            return jsonify({"error": "image too large"}), 413
        cam_state["image"] = data
        # Capture time ≈ now − transfer time (the body was being sent during
        # the transfer; the frame was grabbed at the START of that send).
        capture_dt = datetime.now() - timedelta(seconds=transfer_s)
        cam_state["timestamp"] = capture_dt.isoformat()
        cam_state["transfer_s"] = round(transfer_s, 2)
        cam_state["ocr_count"] += 1
        # ── Device/WiFi telemetry ──────────────────────────────────────
        # gap = secs since the previous frame landed (~5s ideal; a big gap means
        # the cam dropped off the WiFi). Optional X-RSSI/X-Uptime/X-Reconnects
        # headers are sent only if the firmware was flashed with them (NULL
        # otherwise — graceful). transfer_s itself is a no-reflash WiFi-quality
        # proxy (a slow upload = weak signal / retransmits).
        _now_ts = time.time()
        _gap = (_now_ts - cam_state["last_frame_ts"]) if cam_state["last_frame_ts"] else None
        cam_state["last_frame_ts"] = _now_ts
        cam_state["gap_s"] = round(_gap, 2) if _gap is not None else None

        def _hdr_int(name):
            try:
                v = request.headers.get(name)
                return int(v) if v not in (None, "") else None
            except (TypeError, ValueError):
                return None
        _rssi = _hdr_int("X-RSSI")
        _uptime = _hdr_int("X-Uptime")
        _recon = _hdr_int("X-Reconnects")
        if _rssi is not None:
            cam_state["rssi"] = _rssi
        if _uptime is not None:
            cam_state["uptime_sec"] = _uptime
        if _recon is not None:
            cam_state["reconnects"] = _recon
        try:
            db.log_cam_frame(transfer_s, len(data), _gap, _rssi, _uptime, _recon)
        except Exception as _e:
            log.debug("cam telemetry log failed: %s", _e)
        if transfer_s >= 2:
            log.info("cam upload slow: %.1fs transfer (%d bytes) — frame is that old",
                     transfer_s, len(data))
        # Enqueue for off-box OCR (lag buffer). Non-blocking: the deque is
        # bounded (maxlen=720 ≈ 1h) so only a very long outage drops the oldest
        # frame. We tag each frame with its capture time so the readings table
        # can show capture-vs-processed lag and preserve true 5s spacing.
        if OCR_ENABLED:
            with cam_queue_lock:
                if len(cam_queue) == cam_queue.maxlen:
                    cam_ocr_stats["dropped"] += 1
                # Tag with the SAME transfer-corrected capture time the live
                # image exposes (X-Capture-Time), not plain arrival time, so the
                # readings table's "Captured" column and the live image agree on
                # exactly when the cam grabbed the frame.
                cam_queue.append((capture_dt.timestamp(), data))
        return "OK", 200

    @app.route("/api/cam/latest")
    def cam_latest():
        """Serve the most recently pushed image."""
        if not cam_state["image"]:
            return jsonify({"error": "No image yet"}), 404
        # Expose the REAL capture time (when the cam uploaded this frame) so the
        # UI can show that instead of the browser's clock-at-load. The image can
        # be many seconds/minutes old if OCR is backed up — the browser must not
        # claim it's current.
        return Response(cam_state["image"], mimetype="image/jpeg",
                       headers={"Cache-Control": "no-cache",
                                "X-Capture-Time": cam_state["timestamp"] or ""})

    @app.route("/api/cam/status")
    def cam_status():
        """Return cam metadata."""
        return jsonify({
            "has_image": cam_state["image"] is not None,
            "timestamp": cam_state["timestamp"],
            "size": len(cam_state["image"]) if cam_state["image"] else 0,
            "wifi": {
                "rssi": cam_state.get("rssi"),
                "transfer_s": cam_state.get("transfer_s"),
                "gap_s": cam_state.get("gap_s"),
                "uptime_sec": cam_state.get("uptime_sec"),
                "reconnects": cam_state.get("reconnects"),
                "rssi_available": cam_state.get("rssi") is not None,
            },
            "ocr": {
                "enabled": OCR_ENABLED,
                "tower": OCR_TOWER_URL,
                "queue_depth": len(cam_queue),
                "queue_max": cam_queue.maxlen,
                "processed": cam_ocr_stats["processed"],
                "errors": cam_ocr_stats["errors"],
                "dropped": cam_ocr_stats["dropped"],
                "banked": cam_ocr_stats.get("banked", 0),
                "last_ms": cam_ocr_stats["last_ms"],
            },
        })

    @app.route("/api/cam-telemetry")
    def cam_telemetry_api():
        """WiFi/connectivity time-series + rolling stats for the cam-device page."""
        hours = request.args.get("hours", 24, type=int)
        hours = max(1, min(hours, 24 * 30))
        return jsonify({
            "series": db.get_cam_telemetry(hours=hours),
            "summary": db.get_cam_telemetry_summary(hours=hours),
            "live": {
                "rssi": cam_state.get("rssi"),
                "transfer_s": cam_state.get("transfer_s"),
                "gap_s": cam_state.get("gap_s"),
                "uptime_sec": cam_state.get("uptime_sec"),
                "reconnects": cam_state.get("reconnects"),
                "timestamp": cam_state.get("timestamp"),
            },
        })

    @app.route("/cam-device")
    def cam_device_page():
        """Device-detail page for the ESP32-CAM: WiFi strength + history + stats."""
        return render_template("cam_device.html")

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

    @app.route("/api/cam/training")
    def cam_training_list():
        """List banked training samples (newest first) with their metadata, so
        the Training tab can show the auto-labeled dataset for review."""
        import json as _json
        limit = request.args.get("limit", 60, type=int)
        out = []
        total = 0
        try:
            jpgs = sorted((f for f in os.listdir(BANK_DIR)
                           if f.endswith(".jpg")), reverse=True)
            total = len(jpgs)
            for name in jpgs[:limit]:
                stem = name[:-4]
                meta = {}
                try:
                    with open(os.path.join(BANK_DIR, stem + ".json")) as mf:
                        meta = _json.load(mf)
                except Exception:
                    pass
                label = meta.get("label") or stem.split("_")[0]
                out.append({
                    "file": name,
                    "label": label,
                    "ocr_guess": meta.get("ocr_guess", ""),
                    "agree": meta.get("agree"),
                    "confidence": meta.get("confidence", ""),
                    "fit": meta.get("fit", ""),
                })
        except FileNotFoundError:
            pass
        return jsonify({"samples": out, "total": total,
                        "dir": BANK_DIR, "max": BANK_MAX})

    @app.route("/api/cam/training/img/<path:fname>")
    def cam_training_img(fname):
        """Serve one banked training JPEG (filename only, no path traversal)."""
        safe = os.path.basename(fname)
        if not safe.endswith(".jpg"):
            return jsonify({"error": "bad name"}), 400
        path = os.path.join(BANK_DIR, safe)
        if not os.path.exists(path):
            return jsonify({"error": "not found"}), 404
        return Response(open(path, "rb").read(), mimetype="image/jpeg",
                        headers={"Cache-Control": "max-age=3600"})

    @app.route("/api/cam/frame/<rid>")
    def cam_frame(rid):
        """Serve the exact frame the OCR saw for a given reading id (or 404)."""
        safe = os.path.basename(str(rid))
        path = os.path.join(FRAME_DIR, f"{safe}.jpg")
        if not os.path.exists(path):
            return jsonify({"error": "frame not found"}), 404
        return Response(open(path, "rb").read(), mimetype="image/jpeg",
                        headers={"Cache-Control": "max-age=3600"})

    @app.route("/api/cam/reading/<rid>")
    def cam_reading_one(rid):
        """Return one reading row's full field dump + whether its frame exists."""
        entry = meter_reader.get_reading_by_id(rid)
        if entry is None:
            return jsonify({"found": False}), 404
        has_frame = os.path.exists(os.path.join(FRAME_DIR, f"{os.path.basename(rid)}.jpg"))
        return jsonify({"found": True, "entry": entry, "has_frame": has_frame})

    @app.route("/cam/reading/<rid>")
    def cam_reading_page(rid):
        """Per-reading detail page: the captured image + every table field."""
        return render_template("cam_reading.html", rid=rid)

    # Dir holding the verified-dataset manifests (cnn-dataset builder output).
    LABELS_DIR = os.environ.get("METER_LABELS_DIR",
                                "/home/jamesearlpace/cnn-dataset-oracle")
    MANUAL_PATH = os.path.join(LABELS_DIR, "manual_labels.jsonl")
    PROPOSED_PATH = os.path.join(LABELS_DIR, "proposed_labels.jsonl")
    REPROCESS_STATUS = os.path.join(LABELS_DIR, "reprocess_status.json")
    PROPAGATED_PATH = os.path.join(LABELS_DIR, "propagated_labels.jsonl")
    PROPAGATE_STATUS = os.path.join(LABELS_DIR, "propagate_status.json")

    def _load_manual():
        """Manual corrections are the HIGHEST trust tier — a human looked at the
        image and fixed/confirmed/rejected the label. Last action per file wins,
        but the last EXPLICIT label is carried forward so a label-less 'ok'
        after a 'Fix' still confirms the fixed value (not the old auto read).
        Returns {file: {label, action, ts}}; action ∈ correct|reject|ok."""
        import json as _json
        out = {}
        if os.path.exists(MANUAL_PATH):
            for line in open(MANUAL_PATH):
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = _json.loads(line)
                except Exception:
                    continue
                f = rec.get("file")
                if not f:
                    continue
                rec["label"] = rec.get("label") or out.get(f, {}).get("label")
                out[f] = rec
        return out

    def _load_proposed():
        """AI-proposed corrections from the batch reprocess (oracle 3× majority).
        These are SUGGESTIONS awaiting human confirm — they do NOT change the
        training label until accepted. Last write per file wins; a 'dismiss'
        record clears a proposal. Returns {file: {proposed, votes, agree, ...}}
        of ACTIVE (non-dismissed) proposals."""
        import json as _json
        out = {}
        if os.path.exists(PROPOSED_PATH):
            for line in open(PROPOSED_PATH):
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = _json.loads(line)
                except Exception:
                    continue
                f = rec.get("file")
                if not f:
                    continue
                if rec.get("dismissed"):
                    out.pop(f, None)
                else:
                    out[f] = rec
        return out

    def _load_propagated():
        """Anchor & Propagate results — monotonic cleanup derived from human
        anchors. {file: {label, status, was}}; status ∈ anchor|confirmed|
        repaired|flagged|outside. Trusted = anchor+confirmed+repaired."""
        import json as _json
        out = {}
        if os.path.exists(PROPAGATED_PATH):
            for line in open(PROPAGATED_PATH):
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = _json.loads(line)
                    out[rec["file"]] = rec
                except Exception:
                    pass
        return out

    @app.route("/api/cam/labels")
    def cam_labels_api():
        """Merge the verified manifest + needs-review into one status list so the
        whole training/ground-truth set can be eyeballed in a gallery. Each item:
        {file, label, status, detail}. status ∈ manual|verified|promoted|corrected|
        review|rejected. Manual corrections override everything (highest trust).
        Frames are served by /api/cam/training/img/<file>."""
        import json as _json
        items = []

        def load(name):
            p = os.path.join(LABELS_DIR, name)
            out = []
            if os.path.exists(p):
                for line in open(p):
                    line = line.strip()
                    if line:
                        try:
                            out.append(_json.loads(line))
                        except Exception:
                            pass
            return out

        for m in load("manifest.jsonl"):
            corrected = m.get("corrected_from")
            if m.get("verifier") == "oracle-consensus":
                status = "corrected" if corrected else "promoted"
            else:
                status = "verified"
            detail = ""
            if corrected:
                detail = f"was {corrected} · {m.get('votes','?')}/{m.get('reps','?')} votes"
            elif status == "promoted":
                detail = f"{m.get('votes','?')}/{m.get('reps','?')} votes"
            items.append({"file": m["file"], "label": m["label"],
                          "status": status, "detail": detail})
        for r in load("needs_review.jsonl"):
            cw = r.get("consensus_winner")
            detail = ""
            if cw:
                detail = f"2nd reader said {cw} ({r.get('consensus_count','?')} agree)"
            elif r.get("second_read"):
                detail = f"2nd reader said {r['second_read']}"
            items.append({"file": r["file"], "label": r["label"],
                          "status": "review", "detail": detail})

        # Optional: fold in BANKED capture frames (live oracle/CNN reads in
        # BANK_DIR) so the newest captures — not yet in the curated manifest —
        # can be reviewed and corrected. ?captures=<N> includes the newest N
        # banked frames (status "banked" if not already in the manifest). This
        # is the "review what's been captured / check it's reading right" view.
        # Filename convention: <label>_<epoch_ms>[_oracle].jpg
        cap_n = request.args.get("captures", type=int)
        if cap_n and cap_n > 0:
            have = {it["file"]: it for it in items}
            cand = []
            try:
                for name in os.listdir(BANK_DIR):
                    if not name.endswith(".jpg"):
                        continue
                    parts = name[:-4].split("_")
                    if len(parts) < 2:
                        continue
                    try:
                        ts_ms = int(parts[1])
                    except ValueError:
                        continue
                    cand.append((ts_ms, name, parts[0]))
            except FileNotFoundError:
                cand = []
            cand.sort(reverse=True)            # newest first
            for ts_ms, name, fallback_lbl in cand[:cap_n]:
                if name in have:
                    have[name]["recent"] = True
                    have[name]["captured_ms"] = ts_ms
                    continue
                meta = {}
                try:
                    with open(os.path.join(BANK_DIR,
                                           name[:-4] + ".json")) as mf:
                        meta = _json.load(mf)
                except Exception:
                    pass
                label = meta.get("label") or fallback_lbl
                src = meta.get("source", "")
                if src == "oracle":
                    detail = "AI-read (oracle) — confirm or fix"
                elif src:
                    detail = f"banked {src} — confirm or fix"
                else:
                    detail = "captured — confirm or fix"
                items.append({"file": name, "label": label,
                              "status": "banked", "detail": detail,
                              "recent": True, "captured_ms": ts_ms})

        # Apply manual overrides — a human's edit beats every automated verdict.
        manual = _load_manual()
        for it in items:
            mv = manual.get(it["file"])
            if not mv:
                continue
            act = mv.get("action")
            if act == "reject":
                it["status"] = "rejected"
                it["detail"] = "manually excluded from training"
            elif act == "ok":
                if mv.get("label"):
                    it["label"] = mv["label"]   # confirm the value shown, not the old one
                it["status"] = "manual"
                it["detail"] = "manually confirmed"
            elif act == "correct":
                prev = it["label"]
                it["label"] = mv["label"]
                it["status"] = "manual"
                it["detail"] = (f"manually corrected (was {prev})"
                                if mv["label"] != prev else "manually confirmed")

        # Overlay AI proposals (from batch reprocess) — a suggestion the human
        # can Accept/Dismiss. Manual decisions win, so skip files already
        # decided by a human.
        proposed = _load_proposed()
        for it in items:
            pv = proposed.get(it["file"])
            if not pv or manual.get(it["file"]):
                continue
            it["proposed"] = pv.get("proposed")
            it["proposed_votes"] = pv.get("votes")
            it["proposed_reps"] = pv.get("reps")
            it["proposed_agree"] = bool(pv.get("agree"))

        # Anchor & Propagate overlay (?propagated=1): show the monotonic-cleanup
        # status + corrected label for every banked frame. Manual (your anchors)
        # always wins. confirmed/repaired/flagged/outside become the tile status.
        if request.args.get("propagated"):
            prop = _load_propagated()
            have = {it["file"]: it for it in items}
            _pdetail = {
                "confirmed": "confirmed by your anchors",
                "repaired": "auto-fixed from your anchors",
                "flagged": "couldn't auto-resolve — please check",
                "outside": "outside your anchor range",
            }
            for f, pr in prop.items():
                st = pr.get("status")
                if st == "anchor":
                    continue  # that's a manual frame; leave its manual status
                disp_status = {"confirmed": "confirmed", "repaired": "repaired",
                               "flagged": "flagged", "outside": "banked"
                               }.get(st, "banked")
                detail = _pdetail.get(st, "")
                if st == "repaired" and pr.get("was") != pr.get("label"):
                    detail = f"auto-fixed (was {pr['was']})"
                it = have.get(f)
                if it is not None:
                    if manual.get(f):
                        continue  # human decision wins
                    it["label"] = pr.get("label", it["label"])
                    it["status"] = disp_status
                    it["detail"] = detail
                    it["prop_status"] = st
                else:
                    items.append({"file": f, "label": pr.get("label"),
                                  "status": disp_status, "detail": detail,
                                  "prop_status": st})

        # Sort by reading value so it reads like the meter climbing.
        def keyfn(it):
            d = "".join(c for c in it["label"] if c.isdigit())
            return int(d) if d else 0
        items.sort(key=keyfn)
        # Every banked frame's filename embeds its capture time
        # (<label>_<epoch_ms>[_oracle].jpg) — surface it so the reviewer can see
        # how recent each tile is.
        import re as _re
        _ts_re = _re.compile(r"_(\d{10,})")
        for it in items:
            if "captured_ms" not in it:
                m = _ts_re.search(it["file"])
                if m:
                    it["captured_ms"] = int(m.group(1))

        counts = {}
        for it in items:
            counts[it["status"]] = counts.get(it["status"], 0) + 1
        n_proposed = sum(1 for it in items if it.get("proposed"))
        n_recent = sum(1 for it in items if it.get("recent"))
        return jsonify({"items": items, "counts": counts,
                        "proposed": n_proposed, "recent": n_recent,
                        "total": len(items)})

    @app.route("/api/cam/labels/update", methods=["POST"])
    def cam_labels_update():
        """Save a HUMAN correction for a frame (highest trust). Body JSON:
        {file, action, label?}. action ∈ correct|reject|ok. Appended to
        manual_labels.jsonl (last write per file wins on read)."""
        import json as _json
        data = request.get_json(silent=True) or {}
        fname = os.path.basename(str(data.get("file", "")))
        action = data.get("action")
        if not fname.endswith(".jpg") or action not in ("correct", "reject", "ok"):
            return jsonify({"ok": False, "error": "bad file or action"}), 400
        rec = {"file": fname, "action": action,
               "ts": datetime.now().isoformat()}
        if action == "correct":
            lbl = "".join(c for c in str(data.get("label", "")) if c.isdigit())
            if len(lbl) != 9:
                return jsonify({"ok": False, "error": "label must be 9 digits"}), 400
            rec["label"] = lbl
        elif action == "ok":
            # 'OK' confirms the CURRENTLY-shown label. Store it so a prior Fix
            # isn't lost — last-write-wins would otherwise drop the corrected
            # value (the label-less 'ok' record would override the 'correct').
            lbl = "".join(c for c in str(data.get("label", "")) if c.isdigit())
            if len(lbl) == 9:
                rec["label"] = lbl
        try:
            os.makedirs(LABELS_DIR, exist_ok=True)
            with open(MANUAL_PATH, "a") as f:
                f.write(_json.dumps(rec) + "\n")
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)}), 500
        return jsonify({"ok": True, "saved": rec})

    @app.route("/api/cam/reprocess", methods=["POST"])
    def cam_reprocess():
        """Launch a batch oracle re-read over a set of frames (detached). Each
        frame is read 3× by GPT-4o; a majority value lands as a PROPOSED
        correction in the gallery for human confirm. Body: {files:[basename...]}."""
        import json as _json
        import subprocess as _sp
        data = request.get_json(silent=True) or {}
        files = [os.path.basename(str(f)) for f in (data.get("files") or [])
                 if str(f).endswith(".jpg")]
        if not files:
            return jsonify({"ok": False, "error": "no files"}), 400
        if len(files) > 500:
            return jsonify({"ok": False, "error": "max 500 frames per batch"}), 400
        # Already running? Don't stack jobs.
        try:
            st = _json.load(open(REPROCESS_STATUS))
            if st.get("running"):
                return jsonify({"ok": False, "error": "reprocess already running",
                                "status": st}), 409
        except Exception:
            pass
        list_path = "/tmp/reprocess_list.json"
        try:
            _json.dump(files, open(list_path, "w"))
        except Exception as e:
            return jsonify({"ok": False, "error": f"write list: {e}"}), 500
        script = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              "reprocess.py")
        py = sys.executable
        try:
            _sp.Popen([py, script, "--list", list_path],
                      stdout=open("/tmp/reprocess.log", "a"),
                      stderr=_sp.STDOUT, start_new_session=True)
        except Exception as e:
            return jsonify({"ok": False, "error": f"launch: {e}"}), 500
        return jsonify({"ok": True, "launched": True, "count": len(files)})

    @app.route("/api/cam/reprocess/status")
    def cam_reprocess_status():
        """Progress of the running/last batch reprocess job."""
        import json as _json
        try:
            return jsonify(_json.load(open(REPROCESS_STATUS)))
        except Exception:
            return jsonify({"running": False, "total": 0, "done": 0})

    @app.route("/api/cam/proposed/dismiss", methods=["POST"])
    def cam_proposed_dismiss():
        """Dismiss an AI proposal without applying it. Body: {file}."""
        import json as _json
        data = request.get_json(silent=True) or {}
        fname = os.path.basename(str(data.get("file", "")))
        if not fname.endswith(".jpg"):
            return jsonify({"ok": False, "error": "bad file"}), 400
        try:
            os.makedirs(LABELS_DIR, exist_ok=True)
            with open(PROPOSED_PATH, "a") as f:
                f.write(_json.dumps({"file": fname, "dismissed": True,
                                     "ts": datetime.now().isoformat()}) + "\n")
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)}), 500
        return jsonify({"ok": True})

    @app.route("/api/cam/retrain", methods=["POST"])
    def cam_retrain():
        """Force a gated retrain on the tower right now (champion/challenger —
        a worse model can never ship). Launches detached over SSH."""
        import subprocess as _sp
        cmd = ("cd ~/meter-cnn && nohup ~/meter-ocr/.venv/bin/python retrain.py "
               "--force > /tmp/retrain_run.log 2>&1 &")
        try:
            r = _sp.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8",
                         "jack@192.168.0.120", cmd],
                        capture_output=True, text=True, timeout=20)
        except Exception as e:
            return jsonify({"ok": False, "error": f"ssh: {e}"}), 502
        if r.returncode != 0:
            return jsonify({"ok": False, "error": r.stderr.strip() or "ssh failed"}), 502
        return jsonify({"ok": True, "launched": True})

    @app.route("/api/cam/retrain/status")
    def cam_retrain_status():
        """Read the tower's last retrain_status.json (gated retrain outcome)."""
        import subprocess as _sp
        import json as _json
        try:
            r = _sp.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8",
                         "jack@192.168.0.120", "cat ~/meter-cnn/retrain_status.json"],
                        capture_output=True, text=True, timeout=15)
            if r.returncode == 0 and r.stdout.strip():
                return jsonify(_json.loads(r.stdout))
        except Exception as e:
            return jsonify({"error": str(e)}), 502
        return jsonify({"error": "no status"}), 404

    @app.route("/api/cam/propagate", methods=["POST"])
    def cam_propagate():
        """Anchor & Propagate: turn your confirmed labels into clean labels for
        the whole banked set via the meter's monotonic physics. Fast (no AI).
        Confirms banked labels your anchors vouch for, repairs the violators,
        flags the few it can't resolve. Returns the summary."""
        import subprocess as _sp
        import json as _json
        script = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              "propagate.py")
        try:
            r = _sp.run([sys.executable, script],
                        capture_output=True, text=True, timeout=120)
        except Exception as e:
            return jsonify({"ok": False, "error": f"run: {e}"}), 500
        if r.returncode != 0:
            return jsonify({"ok": False,
                            "error": (r.stderr or "propagate failed")[:400]}), 500
        try:
            summary = _json.load(open(PROPAGATE_STATUS))
        except Exception:
            summary = {}
        return jsonify({"ok": True, "summary": summary})

    @app.route("/api/cam/propagate/status")
    def cam_propagate_status():
        """Last Anchor & Propagate summary (counts + conflicts)."""
        import json as _json
        try:
            return jsonify(_json.load(open(PROPAGATE_STATUS)))
        except Exception:
            return jsonify({"counts": {}, "conflicts": []})

    @app.route("/cam/labels")
    def cam_labels_page():
        """Gallery to review every banked frame + its label + verification status."""
        return render_template("cam_labels.html")

    @app.route("/api/cam/cnn-report")
    def cam_cnn_report():
        """CNN improvement report: live accuracy over time (from oracle
        verifications), per-version accuracy, and the daily reader split."""
        try:
            import cnn_metrics
            rep = cnn_metrics.report(days=60)
        except Exception as e:
            return jsonify({"error": str(e)}), 500
        rep["stats"] = {k: cam_ocr_stats.get(k) for k in
                        ("cnn_used", "cnn_fellback", "cnn_corrections",
                         "oracle_labels", "reader", "processed")}
        return jsonify(rep)

    @app.route("/cam/cnn-report")
    def cam_cnn_report_page():
        return render_template("cnn_report.html")

    @app.route("/api/cam/reanchor", methods=["POST"])
    def cam_reanchor():
        """Manually trigger a vision-LLM read + re-anchor right now."""
        try:
            import vision_oracle
        except Exception as e:
            return jsonify({"ok": False, "error": f"oracle import: {e}"}), 500
        if not vision_oracle.available():
            return jsonify({"ok": False, "error": "no OPENAI_API_KEY"}), 400
        try:
            raw = http_requests.get(
                OCR_TOWER_URL.replace("/ocr", "/raw.jpg"), timeout=8).content
        except Exception as e:
            return jsonify({"ok": False, "error": f"no frame: {e}"}), 502
        # Soft hint: give the model the expected high-digit prefix to fight
        # glare, but NO hard floor — this is the manual override, so it must be
        # free to correct the lock in either direction.
        lg0 = getattr(meter_reader, "last_good", None)
        hint = ({"last_value": int(lg0), "high_prefix": f"{int(lg0):09d}"[:4]}
                if lg0 is not None else None)
        res = vision_oracle.read_meter(raw, rotate180=True, hint=hint)
        applied = False
        if res.get("ok") and res.get("readable") and res.get("confidence") != "low":
            applied = meter_reader.reanchor(res["value"], source="manual-oracle")
        return jsonify({"ok": res.get("ok"), "value": res.get("value"),
                        "confidence": res.get("confidence"),
                        "readable": res.get("readable"),
                        "reanchored": applied,
                        "cost_tokens": res.get("cost_tokens"),
                        "error": res.get("error")})

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
<script src="https://cdn.jsdelivr.net/npm/chart.js@4/dist/chart.umd.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4/dist/chart.umd.min.js"></script>
<style>
:root{
  --bg:#f5f7f9;--card:#ffffff;--bg-card:#ffffff;
  --border:#e8ecf0;--border-light:#f0f2f5;
  --text:#1a2b3c;--text2:#5f7082;--text3:#9ba8b5;
  --green:#22c55e;--green-dark:#16a34a;--green-light:#dcfce7;
  --blue:#3b82f6;--amber:#f59e0b;--red:#ef4444;
  --bg-sidebar:#1b2e1f;--bg-sidebar-hover:rgba(255,255,255,.08);
  --shadow:0 1px 3px rgba(0,0,0,.06),0 1px 2px rgba(0,0,0,.04);
  --sidebar-w:220px;
}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Inter',-apple-system,BlinkMacSystemFont,'Segoe UI',system-ui,sans-serif;
  background:var(--bg);color:var(--text);line-height:1.55;min-height:100vh;}

/* ── Sidebar (cloned from dashboard) ── */
.sidebar{position:fixed;top:0;left:0;width:var(--sidebar-w);height:100vh;background:var(--bg-sidebar);
  color:#fff;display:flex;flex-direction:column;z-index:100;}
.sidebar-brand{padding:24px 20px 20px;display:flex;align-items:center;gap:10px;border-bottom:1px solid rgba(255,255,255,.08)}
.sidebar-brand .logo{font-size:1.8rem}
.sidebar-brand .name{font-size:1.05rem;font-weight:700;letter-spacing:-.01em}
.sidebar-brand .loc{font-size:.7rem;color:rgba(255,255,255,.5);margin-top:1px}
.sidebar-nav{flex:1;padding:12px 10px;overflow-y:auto}
.sidebar .nav-item{display:flex;align-items:center;gap:12px;padding:10px 14px;border-radius:8px;
  cursor:pointer;transition:all .2s;color:rgba(255,255,255,.6);font-size:.88rem;font-weight:500;margin-bottom:2px;text-decoration:none}
.sidebar .nav-item:hover{background:var(--bg-sidebar-hover);color:rgba(255,255,255,.85)}
.sidebar .nav-item.active{background:rgba(34,197,94,.18);color:#4ade80;font-weight:600}
.sidebar .nav-item .icon{font-size:1.15rem;width:24px;text-align:center}
.sidebar-footer{padding:16px 20px;border-top:1px solid rgba(255,255,255,.08);font-size:.72rem;color:rgba(255,255,255,.35)}
.sidebar-footer .status-dot{width:7px;height:7px;border-radius:50%;display:inline-block;margin-right:5px}
.sidebar-footer .status-dot.online{background:#4ade80;box-shadow:0 0 6px rgba(74,222,128,.5)}
.sidebar-footer .status-dot.offline{background:#f87171;box-shadow:0 0 6px rgba(248,113,113,.5)}

.main{margin-left:var(--sidebar-w);min-height:100vh;padding:24px 32px 80px;max-width:1000px;}
h1{margin:0 0 2px 0;font-size:1.4rem;font-weight:700;letter-spacing:-.02em;}
.sub{color:var(--text2);font-size:.85rem;margin-bottom:16px;}
.bar{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-bottom:14px;}
button{background:var(--card);border:1px solid var(--border);color:var(--text);padding:8px 12px;border-radius:6px;cursor:pointer;font-size:13px;font-weight:500;}
button:hover{background:var(--border-light);}
button:disabled{opacity:.5;cursor:default;}
.btn-dry{background:#fef3c7;border-color:#f59e0b;color:#92400e;}
.btn-wet{background:#dbeafe;border-color:#3b82f6;color:#1e40af;}
.btn-go{background:#dcfce7;border-color:#16a34a;color:#166534;}
.card{background:var(--card);border:1px solid var(--border);border-radius:12px;padding:14px;margin-bottom:12px;box-shadow:var(--shadow);}
.row{display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap;}
.nm{font-weight:600;font-size:15px;}
.live{font-variant-numeric:tabular-nums;}
.raw{font-size:26px;font-weight:700;color:var(--text);}
.pct{font-size:22px;font-weight:700;color:var(--text);}
.muted{color:var(--text2);font-size:12px;}
.endpoints{display:flex;gap:18px;margin:8px 0;font-size:13px;color:var(--text2);}
.endpoints b{color:var(--text);}
.drift{font-size:12px;color:var(--text2);margin:2px 0 8px;padding:6px 8px;background:var(--border-light);border-radius:6px;}
.advice{font-size:13px;margin:8px 0 4px;padding:8px 10px;border-radius:6px;line-height:1.45;border-left:3px solid;}
.advice b{font-weight:700;}
.adv-ok{background:rgba(34,197,94,.10);border-color:#16a34a;color:#166534;}
.adv-info{background:rgba(59,130,246,.10);border-color:#3b82f6;color:#1e40af;}
.adv-due{background:rgba(245,158,11,.12);border-color:#f59e0b;color:#92400e;}
.adv-overdue{background:rgba(239,68,68,.10);border-color:#ef4444;color:#991b1b;}
.adv-bad{background:rgba(239,68,68,.14);border-color:#ef4444;color:#991b1b;}
.badge{padding:2px 8px;border-radius:4px;font-size:11px;font-weight:600;text-transform:uppercase;}
.b-ok{background:#dcfce7;color:#166534;}
.b-bad{background:#fee2e2;color:#991b1b;}
.b-off{background:var(--border-light);color:var(--text2);}
.actions{display:flex;gap:8px;flex-wrap:wrap;margin-top:8px;}
.manual{margin-top:10px;display:flex;gap:6px;flex-wrap:wrap;align-items:center;}
.manual input{width:74px;background:var(--card);border:1px solid var(--border);color:var(--text);border-radius:5px;padding:6px;font-size:13px;}
.manual input.nm{width:120px;}
.toast{position:fixed;bottom:16px;left:50%;transform:translateX(-50%);background:#dcfce7;color:#166534;padding:10px 18px;border-radius:8px;font-size:14px;opacity:0;transition:opacity .2s;pointer-events:none;border:1px solid #16a34a;z-index:300;}
.toast.err{background:#fee2e2;color:#991b1b;border-color:#ef4444;}
.toast.show{opacity:1;}
a{color:var(--blue);text-decoration:none;}
.help{background:var(--card);border:1px solid var(--border);border-radius:12px;padding:12px;margin-bottom:14px;font-size:13px;color:var(--text2);line-height:1.5;box-shadow:var(--shadow);}
.help b{color:var(--text);}

/* ── Mobile bottom nav ── */
.mobile-nav{display:none;position:fixed;bottom:0;left:0;right:0;background:#fff;
  border-top:1px solid var(--border);box-shadow:0 -2px 8px rgba(0,0,0,.05);z-index:200;padding:4px 0;}
.mobile-nav-inner{display:flex;justify-content:space-around;}
.mob-nav-item{display:flex;flex-direction:column;align-items:center;gap:2px;padding:6px 8px;
  font-size:.62rem;color:var(--text2);text-decoration:none;cursor:pointer;font-weight:600;}
.mob-nav-item.active{color:var(--green-dark);}
.mob-nav-item .mob-icon{font-size:1.2rem;}
@media(max-width:768px){
  .sidebar{display:none;}
  .main{margin-left:0;padding:16px 16px 80px;}
  .mobile-nav{display:block;}
}
</style></head>
<body>

<!-- ═══ Sidebar ═══ -->
<nav class="sidebar">
  <div class="sidebar-brand">
    <span class="logo">🌱</span>
    <div>
      <div class="name">Smart Garden</div>
      <div class="loc">Duvall, WA</div>
    </div>
  </div>
  <div class="sidebar-nav">
    <a href="/" class="nav-item"><span class="icon">🏠</span> Home</a>
    <a href="/#zones" class="nav-item"><span class="icon">🌿</span> Zones</a>
    <a href="/#history" class="nav-item"><span class="icon">📊</span> History</a>
    <a href="/sensor-history" class="nav-item"><span class="icon">🌡️</span> Sensor History</a>
    <a href="/#settings" class="nav-item"><span class="icon">⚙️</span> Settings</a>
    <a href="/forecast" class="nav-item"><span class="icon">🌧️</span> Forecast</a>
    <a href="/moisture-sim" class="nav-item"><span class="icon">💧</span> Schedule</a>
    <a href="/calibrate" class="nav-item active"><span class="icon">🎛️</span> Calibrate</a>
    <a href="/#cam" class="nav-item"><span class="icon">📷</span> Cam</a>
  </div>
  <div class="sidebar-footer">
    <span class="status-dot" id="sb-dot"></span>
    <span id="sb-status">Connecting…</span>
    <div style="margin-top:6px">Auto-refresh</div>
  </div>
</nav>

<div class="main">
<h1>🎛️ Sensor Calibration</h1>
<div class="sub">Tune the server-side calibration for the battery and soil sensors — saved to the server, no reflash.</div>

<h2 style="font-size:16px;margin:18px 0 6px">🔋 Battery Voltage</h2>
<div class="help">
<b>Make the dashboard voltage match the real battery.</b> Open the junction box, read the true voltage off the <b>Wanderer charge controller</b>, type it in below, and tap <b>Add reading</b>. We force a fresh sample from the ESP32 at that instant (it normally only re-reads the battery on a long interval) and fit a correction so the dashboard matches reality.<br>
<span style="color:#7d8590">The divider you built (5 resistors instead of 4) reads slightly off and not perfectly linear. One reading already helps; add a few at different charge levels (morning low, midday charging) and the fit gets sharper. 2+ points → linear fit, 5+ → quadratic. Capturing takes a few seconds while the ESP32 re-samples.</span>
</div>
<div id="battery-cal" class="card">Loading…</div>
<div class="card" id="battery-chart-card" style="display:none">
  <div class="muted" style="margin-bottom:8px">Calibration curve — <b style="color:#3b82f6">your readings</b> (dots), <b style="color:#16a34a">best-fit</b> (line), <b style="color:#d97706">right now</b> (◆). X = ESP32 raw, Y = Wanderer actual.</div>
  <div style="height:230px"><canvas id="bat-chart"></canvas></div>
</div>

<h2 style="font-size:16px;margin:22px 0 6px">🌱 Soil Sensors</h2>
<div class="help">
<b>How to calibrate (do it in the ground, the way it really sits):</b><br>
1. Click <b>Start Live Mode</b> so raw readings refresh every few seconds.<br>
2. <b>Saturate the soil</b> around the buried sensor (pour water / soak it), let the live raw <b>stop moving</b>, then tap <b>Set Wet</b>.<br>
3. Pull the sensor out, <b>dry it off</b> (wipe on your shirt, shake, blow on it), let it sit in air until the live raw <b>settles steady</b>, then tap <b>Set Dry</b>.<br>
<b>Wait for the number to stop changing before each capture</b> — there's a few-second lag while surface water clears. You're freezing two steady reference points, not timing the transition.<br>
<span style="color:#7d8590">Tip: saturated soil is a truer "100%" than a cup of water (cup reads wetter than soil ever gets).</span>
</div>

<div class="help" style="border-color:#3b82f6">
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
    var sev = Math.abs(e.delta) >= 300 ? 'color:#ef4444' : Math.abs(e.delta) >= 120 ? 'color:#b45309' : 'color:#16a34a';
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
    // Recalibration recommendation banner.
    var adv = s.advice || {status:'ok', reason:''};
    var advCls = {ok:'adv-ok', info:'adv-info', due:'adv-due', overdue:'adv-overdue', bad:'adv-bad'}[adv.status] || 'adv-ok';
    var advIcon = {ok:'✅', info:'👀', due:'🔧', overdue:'⏰', bad:'❌'}[adv.status] || '✅';
    var advLabel = {ok:'Good', info:'Watch', due:'Recalibrate soon', overdue:'Recalibrate now', bad:'Hardware issue'}[adv.status] || 'Good';
    var advHtml = '<div class="advice ' + advCls + '"><b>' + advIcon + ' ' + advLabel + '</b> — ' + (adv.reason||'') + '</div>';
    html += '<div class="card">'
      + '<div class="row"><span class="nm">#' + s.index + ' · ' + (s.name||'') + '</span>' + badge + '</div>'
      + advHtml
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

/* ── Battery voltage calibration ── */
function vfmt(v){ return (v===null||v===undefined) ? '—' : (Number(v).toFixed(2) + 'V'); }

var batEditMode = false;     // delete controls hidden until the user taps Edit
var _lastBatSnapshot = null; // remembered so the Edit toggle can re-render

function toggleBatEdit(){
  batEditMode = !batEditMode;
  if(_lastBatSnapshot) renderBattery(_lastBatSnapshot);
}

async function loadBattery(){
  try{
    var r = await fetch('/api/battery-calibration');
    var d = await r.json();
    renderBattery(d);
  }catch(e){ /* keep last view */ }
}

function renderBattery(d){
  _lastBatSnapshot = d;
  var el = document.getElementById('battery-cal');
  if(!el) return;
  var live = d.live || {};
  var hasLive = live.raw_v !== null && live.raw_v !== undefined;
  var off = Math.abs((live.corrected_v||0) - 0);
  // Current reading row
  var liveHtml;
  if(hasLive){
    liveHtml = '<div class="row" style="align-items:flex-end">'
      + '<div><div class="muted">ESP32 raw reading</div><div class="raw live" id="bat-live-raw">' + vfmt(live.raw_v) + '</div></div>'
      + '<div style="text-align:center;color:#9ba8b5;font-size:20px">→</div>'
      + '<div style="text-align:right"><div class="muted">dashboard shows</div><div class="raw" style="color:#16a34a" id="bat-live-corr">' + vfmt(live.corrected_v) + '</div></div>'
      + '</div>'
      + '<div style="margin-top:6px"><button onclick="refreshBatteryLive()" id="bat-refresh-btn" style="font-size:12px;padding:5px 10px">🔄 Refresh reading now</button>'
      + ' <span class="muted" id="bat-refresh-note">ESP32 samples the battery on its own interval — tap to force a fresh read.</span></div>';
  } else {
    liveHtml = '<div class="advice adv-overdue"><b>🔌 No battery reading</b> — the ESP32 isn\\'t reporting a voltage right now. Add a point once it\\'s back online.</div>';
  }
  // Model summary
  var rmse = (d.rmse===null||d.rmse===undefined) ? '' : ' · ±' + Number(d.rmse).toFixed(3) + 'V fit error';
  var modelHtml = '<div class="drift">📐 model: <b>' + (d.model||'uncalibrated') + '</b>' + rmse
      + (d.updated ? ' · updated ' + d.updated.replace('T',' ') : '') + '</div>';
  // Add-reading input
  var inputHtml = '<div class="manual" style="margin-top:10px">'
    + '<span class="muted">Actual voltage from the Wanderer:</span>'
    + '<input id="bat-actual" type="number" step="0.01" placeholder="e.g. 13.40" style="width:100px">'
    + '<button class="btn-go" onclick="addBatteryPoint()">➕ Add reading</button>'
    + '</div>';
  // Points table
  var rows = (d.points||[]).map(function(p){
    var errCls = Math.abs(p.error_v) >= 0.3 ? 'color:#ef4444' : Math.abs(p.error_v) >= 0.12 ? 'color:#b45309' : 'color:#16a34a';
    var sign = p.error_v > 0 ? '+' : '';
    return '<tr>'
      + '<td style="color:#9ba8b5;font-size:11px">' + (p.ts||'').replace('T',' ') + '</td>'
      + '<td><b>' + vfmt(p.actual_v) + '</b></td>'
      + '<td>' + vfmt(p.raw_v) + '</td>'
      + '<td>' + vfmt(p.predicted_v) + '</td>'
      + '<td style="' + errCls + '">' + sign + Number(p.error_v).toFixed(2) + '</td>'
      + (batEditMode
          ? '<td><button onclick="deleteBatteryPoint(\\'' + (p.ts||'') + '\\')" title="Delete this reading" style="padding:3px 9px;font-size:12px;background:#fee2e2;border-color:#ef4444;color:#991b1b">✕</button></td>'
          : '')
      + '</tr>';
  }).join('');
  var nPts = (d.points || []).length;
  var tableHtml;
  if (nPts) {
    var editBtn = '<button onclick="toggleBatEdit()" style="padding:5px 12px;font-size:12px;'
        + (batEditMode ? 'background:#dcfce7;border-color:#16a34a;color:#166534' : '')
        + '">' + (batEditMode ? '✓ Done' : '✏️ Edit readings') + '</button>';
    if (batEditMode) {
      // Expanded: full table with per-row delete + clear-all.
      var clearBtn = ' <button onclick="resetBattery()" style="padding:5px 12px;font-size:12px;background:#fee2e2;border-color:#ef4444;color:#991b1b">🗑 Clear all points</button>';
      tableHtml = '<table style="width:100%;border-collapse:collapse;margin-top:12px;font-size:13px">'
        + '<thead><tr style="color:#9ba8b5;text-align:left;font-size:11px;text-transform:uppercase">'
        + '<th>when</th><th>actual</th><th>esp32 raw</th><th>predicted</th><th>err</th><th></th></tr></thead>'
        + '<tbody>' + rows + '</tbody></table>'
        + '<div class="actions" style="margin-top:10px">' + editBtn + clearBtn + '</div>';
    } else {
      // Collapsed: just a summary + Edit button. The table (and its delete
      // controls) stay hidden so precious readings aren't a stray tap away.
      tableHtml = '<div class="row" style="margin-top:12px;padding:10px 12px;background:var(--border-light);border-radius:8px">'
        + '<span class="muted">' + nPts + ' calibration reading' + (nPts===1?'':'s') + ' saved · the curve above uses them</span>'
        + editBtn + '</div>';
    }
  } else {
    tableHtml = '<div class="muted" style="margin-top:10px">No reference points yet — add your first reading above.</div>';
    batEditMode = false;  // nothing to edit
  }

  el.innerHTML = liveHtml + modelHtml + inputHtml + tableHtml;
  renderBatteryChart(d);
}

var _batChart = null;
function batPredict(coeffs, x){ var y=0; for(var i=0;i<coeffs.length;i++){ y += coeffs[i]*Math.pow(x,i); } return y; }

function renderBatteryChart(d){
  var card = document.getElementById('battery-chart-card');
  var canvas = document.getElementById('bat-chart');
  if(!card || !canvas || typeof Chart === 'undefined') return;
  var pts = (d.points||[]).map(function(p){ return {x:p.raw_v, y:p.actual_v}; });
  var live = d.live || {};
  var hasLive = live.raw_v !== null && live.raw_v !== undefined;
  if(!pts.length && !hasLive){ card.style.display='none'; return; }
  // X-range from the readings + the live point, padded a touch.
  var xs = pts.map(function(p){ return p.x; });
  if(hasLive) xs.push(live.raw_v);
  var lo = Math.min.apply(null, xs), hi = Math.max.apply(null, xs);
  if(hi - lo < 0.5){ var mid=(lo+hi)/2; lo=mid-0.75; hi=mid+0.75; }
  var pad = Math.max(0.25, (hi-lo)*0.15); lo-=pad; hi+=pad;
  // Sample the fit polynomial across the range.
  var coeffs = d.coeffs || [0, 1.0];
  var curve=[], N=40;
  for(var i=0;i<=N;i++){ var x=lo+(hi-lo)*i/N; curve.push({x:x, y:batPredict(coeffs,x)}); }
  var nowPt = hasLive ? [{x:live.raw_v, y:(live.corrected_v!=null ? live.corrected_v : batPredict(coeffs,live.raw_v))}] : [];
  card.style.display='';
  if(_batChart) _batChart.destroy();
  _batChart = new Chart(canvas.getContext('2d'), {
    data: { datasets: [
      { type:'line', label:'Best-fit', data:curve, borderColor:'#16a34a', borderWidth:2, pointRadius:0, tension:0, fill:false, order:3 },
      { type:'scatter', label:'Your readings', data:pts, backgroundColor:'#3b82f6', borderColor:'#3b82f6', pointRadius:5, pointHoverRadius:7, order:2 },
      { type:'scatter', label:'Right now', data:nowPt, backgroundColor:'#f59e0b', borderColor:'#1a2b3c', borderWidth:2, pointRadius:8, pointHoverRadius:10, pointStyle:'rectRot', order:1 }
    ]},
    options: {
      responsive:true, maintainAspectRatio:false,
      plugins: {
        legend: { labels:{ color:'#5f7082', boxWidth:10, font:{size:11} } },
        tooltip: { callbacks: { label: function(ctx){ return ctx.dataset.label+': raw '+ctx.parsed.x.toFixed(2)+'V → '+ctx.parsed.y.toFixed(2)+'V'; } } }
      },
      scales: {
        x: { type:'linear', title:{display:true,text:'ESP32 raw (V)',color:'#5f7082',font:{size:11}}, ticks:{color:'#5f7082',font:{size:10}}, grid:{color:'#e8ecf0'} },
        y: { type:'linear', title:{display:true,text:'Wanderer actual (V)',color:'#5f7082',font:{size:11}}, ticks:{color:'#5f7082',font:{size:10}}, grid:{color:'#e8ecf0'} }
      }
    }
  });
}

async function refreshBatteryLive(){
  var btn = document.getElementById('bat-refresh-btn');
  var note = document.getElementById('bat-refresh-note');
  if(btn){ btn.disabled = true; btn.textContent = '⏳ Reading…'; }
  if(note){ note.textContent = 'Forcing a fresh ESP32 sample (a few seconds)…'; }
  try{
    var r = await fetch('/api/battery-calibration/live-refresh', {method:'POST', headers:{'Content-Type':'application/json','X-Requested-With':'XMLHttpRequest'}, body:'{}'});
    var d = await r.json();
    if(d.ok){
      var rawEl = document.getElementById('bat-live-raw');
      var corrEl = document.getElementById('bat-live-corr');
      if(rawEl) rawEl.textContent = vfmt(d.live.raw_v);
      if(corrEl) corrEl.textContent = vfmt(d.live.corrected_v);
      toast(d.fresh ? ('Fresh reading: ' + Number(d.live.raw_v).toFixed(2) + 'V') : 'Reading unchanged (may still be settling)');
      if(note) note.textContent = d.fresh ? 'Fresh — captured a new ADC sample.' : 'No change detected; try once more.';
    } else { toast(d.error || 'Refresh failed', true); }
  }catch(e){ toast('Refresh failed', true); }
  if(btn){ btn.disabled = false; btn.textContent = '🔄 Refresh reading now'; }
}

async function addBatteryPoint(){
  var inp = document.getElementById('bat-actual');
  var v = parseFloat(inp.value);
  if(isNaN(v)){ toast('Enter the voltage you read', true); return; }
  var btn = document.querySelector('button[onclick="addBatteryPoint()"]');
  if(btn){ btn.disabled = true; btn.textContent = '⏳ Capturing fresh…'; }
  try{
    var r = await fetch('/api/battery-calibration/add', {method:'POST', headers:{'Content-Type':'application/json','X-Requested-With':'XMLHttpRequest'}, body: JSON.stringify({actual_v:v})});
    var d = await r.json();
    if(d.ok){
      var c = d.captured || {};
      var freshNote = c.fresh ? '' : ' (cached — ESP32 didn\\'t re-sample in time)';
      toast('Added: actual ' + Number(c.actual_v).toFixed(2) + 'V @ raw ' + Number(c.raw_v).toFixed(2) + 'V' + freshNote);
      inp.value='';
      renderBattery(d.snapshot);
    } else { toast(d.error || 'Add failed', true); }
  }catch(e){ toast('Add failed', true); }
  if(btn){ btn.disabled = false; btn.textContent = '➕ Add reading'; }
}

async function deleteBatteryPoint(ts){
  try{
    var r = await fetch('/api/battery-calibration/delete', {method:'POST', headers:{'Content-Type':'application/json','X-Requested-With':'XMLHttpRequest'}, body: JSON.stringify({ts:ts})});
    var d = await r.json();
    if(d.ok){ toast('Removed point'); renderBattery(d.snapshot); }
    else { toast('Remove failed', true); }
  }catch(e){ toast('Remove failed', true); }
}

async function resetBattery(){
  if(!confirm('Clear all battery calibration points and revert to the default correction?')) return;
  try{
    var r = await fetch('/api/battery-calibration/reset', {method:'POST', headers:{'Content-Type':'application/json','X-Requested-With':'XMLHttpRequest'}, body: '{}'});
    var d = await r.json();
    if(d.ok){ toast('Reset to default'); renderBattery(d.snapshot); }
    else { toast('Reset failed', true); }
  }catch(e){ toast('Reset failed', true); }
}

function restartPoll(){ if(pollTimer) clearInterval(pollTimer); pollTimer = setInterval(load, POLL_MS); }

// Sidebar footer connectivity dot (mirrors the other pages).
async function loadStatus(){
  try{
    var r = await fetch('/api/dashboard');
    var d = await r.json();
    var online = (d.esp32_online !== undefined) ? !!d.esp32_online : !!d.esp32;
    var dot = document.getElementById('sb-dot');
    var txt = document.getElementById('sb-status');
    if(dot) dot.className = 'status-dot ' + (online ? 'online' : 'offline');
    if(txt) txt.textContent = online ? 'ESP32 online' : 'ESP32 offline';
  }catch(e){
    var dot = document.getElementById('sb-dot');
    if(dot) dot.className = 'status-dot offline';
  }
}

load();
loadBattery();
loadStatus();
restartPoll();</script>
</div><!-- /.main -->

<!-- ═══ Mobile bottom nav ═══ -->
<div class="mobile-nav">
  <div class="mobile-nav-inner">
    <a href="/" class="mob-nav-item"><span class="mob-icon">🏠</span>Home</a>
    <a href="/#zones" class="mob-nav-item"><span class="mob-icon">🌿</span>Zones</a>
    <a href="/#history" class="mob-nav-item"><span class="mob-icon">📊</span>History</a>
    <a href="/forecast" class="mob-nav-item"><span class="mob-icon">🌧️</span>Forecast</a>
    <a href="/moisture-sim" class="mob-nav-item"><span class="mob-icon">💧</span>Schedule</a>
    <a href="/calibrate" class="mob-nav-item active"><span class="mob-icon">🎛️</span>Calibrate</a>
  </div>
</div>
</body></html>"""
        return Response(html, mimetype="text/html")

    return app
