"""Add /forecast page to the smart-garden dashboard.

Shows a simple watering forecast for all zones based on:
- Current soil water balance (checkbook method)
- Today's ET0 and crop coefficient
- Rain forecast
- Predicted days until MAD threshold triggers watering
"""

import os, sys

DASHBOARD_PATH = "/home/jamesearlpace/smart-garden-server/dashboard.py"
TEMPLATE_DIR = "/home/jamesearlpace/smart-garden-server/templates"

# 1. Create the forecast template
forecast_html = r'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Watering Forecast — Smart Garden</title>
<style>
:root { --bg: #0f172a; --card: #1e293b; --border: #334155; --text: #e2e8f0;
        --text2: #94a3b8; --green: #22c55e; --blue: #3b82f6; --amber: #f59e0b;
        --red: #ef4444; }
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
       background: var(--bg); color: var(--text); padding: 16px; max-width: 700px; margin: 0 auto; }
h1 { font-size: 1.4rem; margin-bottom: 4px; }
.sub { color: var(--text2); font-size: .85rem; margin-bottom: 20px; }
.card { background: var(--card); border-radius: 12px; padding: 16px; margin-bottom: 12px;
        border: 1px solid var(--border); }
.card h2 { font-size: 1rem; margin-bottom: 8px; }
.weather { display: grid; grid-template-columns: repeat(auto-fit, minmax(120px, 1fr)); gap: 8px; }
.stat { text-align: center; }
.stat .val { font-size: 1.3rem; font-weight: 700; }
.stat .lbl { font-size: .7rem; color: var(--text2); }
.zone { display: flex; justify-content: space-between; align-items: center; padding: 10px 0;
        border-bottom: 1px solid var(--border); }
.zone:last-child { border-bottom: none; }
.zone-name { font-weight: 600; font-size: .95rem; }
.zone-detail { font-size: .8rem; color: var(--text2); }
.zone-forecast { text-align: right; }
.days { font-size: 1.2rem; font-weight: 700; }
.days.soon { color: var(--amber); }
.days.now { color: var(--red); }
.days.ok { color: var(--green); }
.next-date { font-size: .75rem; color: var(--text2); }
.bar-wrap { height: 6px; background: #334155; border-radius: 3px; margin-top: 4px; width: 120px; }
.bar { height: 100%; border-radius: 3px; }
a { color: var(--blue); text-decoration: none; }
.nav { margin-bottom: 16px; font-size: .85rem; }
.loading { text-align: center; padding: 40px; color: var(--text2); }
</style>
</head>
<body>
<div class="nav"><a href="/">← Dashboard</a></div>
<h1>🌧️ Watering Forecast</h1>
<div class="sub">When will each zone need water?</div>

<div id="content"><div class="loading">Loading forecast...</div></div>

<script>
async function load() {
  try {
    const r = await fetch('/api/forecast');
    if (r.status === 401) { window.location.href = '/login'; return; }
    const d = await r.json();
    render(d);
  } catch(e) {
    document.getElementById('content').innerHTML = '<div class="card">Error loading forecast: ' + e.message + '</div>';
  }
}

function render(d) {
  let html = '';

  // Weather card
  const w = d.weather || {};
  html += '<div class="card"><h2>Current Conditions</h2><div class="weather">';
  html += stat(w.temp_f ? w.temp_f.toFixed(0) + '°F' : '?', 'Temperature');
  html += stat(w.humidity_pct ? w.humidity_pct + '%' : '?', 'Humidity');
  html += stat(d.et0_today ? d.et0_today.toFixed(1) + 'mm' : '?', 'ET₀ Today');
  html += stat(w.rain_forecast_mm ? w.rain_forecast_mm.toFixed(1) + 'mm' : '0mm', 'Rain Forecast');
  html += stat(w.wind_mph ? w.wind_mph.toFixed(0) + 'mph' : '?', 'Wind');
  html += '</div></div>';

  // Zone forecasts
  html += '<div class="card"><h2>Zone Forecast</h2>';
  if (!d.zones || d.zones.length === 0) {
    html += '<div style="color:var(--text2);padding:12px">No zone data available</div>';
  } else {
    d.zones.forEach(z => {
      const days = z.days_until_water;
      let daysText, daysClass;
      if (days === null || days === undefined) {
        daysText = '?';
        daysClass = 'ok';
      } else if (days <= 0) {
        daysText = 'Today';
        daysClass = 'now';
      } else if (days <= 2) {
        daysText = days.toFixed(0) + 'd';
        daysClass = 'soon';
      } else {
        daysText = days.toFixed(0) + 'd';
        daysClass = 'ok';
      }

      const pct = z.balance_pct !== null ? z.balance_pct : 0;
      const barColor = pct > 60 ? 'var(--green)' : pct > 30 ? 'var(--amber)' : 'var(--red)';

      html += '<div class="zone">';
      html += '<div>';
      html += '<div class="zone-name">' + z.name + '</div>';
      html += '<div class="zone-detail">' + (z.type === 'drip' ? '💧 Drip' : '🌱 Sprinkler') +
              ' · ET: ' + (z.etc_mm ? z.etc_mm.toFixed(1) : '?') + 'mm/day</div>';
      html += '<div class="bar-wrap"><div class="bar" style="width:' + pct + '%;background:' + barColor + '"></div></div>';
      html += '</div>';
      html += '<div class="zone-forecast">';
      html += '<div class="days ' + daysClass + '">' + daysText + '</div>';
      html += z.next_water_date ? '<div class="next-date">' + z.next_water_date + '</div>' : '';
      html += '</div>';
      html += '</div>';
    });
  }
  html += '</div>';

  // Watering window
  html += '<div class="card" style="font-size:.85rem;color:var(--text2)">';
  html += '⏰ Morning window: ' + (d.window_start || '4:00') + ' – ' + (d.window_end || '7:00') + ' AM';
  html += '</div>';

  document.getElementById('content').innerHTML = html;
}

function stat(val, label) {
  return '<div class="stat"><div class="val">' + val + '</div><div class="lbl">' + label + '</div></div>';
}

load();
setInterval(load, 300000); // refresh every 5 min
</script>
</body>
</html>'''

with open(os.path.join(TEMPLATE_DIR, "forecast.html"), "w") as f:
    f.write(forecast_html)
print("Created templates/forecast.html")

# 2. Add /forecast route and /api/forecast endpoint to dashboard.py
with open(DASHBOARD_PATH) as f:
    code = f.read()

if "/api/forecast" in code:
    print("dashboard.py already has /api/forecast — skipping")
    sys.exit(0)

# Find insertion point — before the "# ── Pages ──" comment
forecast_route = '''
    @app.route("/forecast")
    def forecast_page():
        return render_template("forecast.html")

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

'''

# Insert before "# ── Pages ──"
marker = "    # ── Pages ──"
idx = code.find(marker)
if idx == -1:
    # Try alternate
    marker = '    @app.route("/")'
    idx = code.find(marker)

if idx == -1:
    print("ERROR: Could not find insertion point")
    sys.exit(1)

code = code[:idx] + forecast_route + "\n" + code[idx:]

with open(DASHBOARD_PATH, "w") as f:
    f.write(code)
print("Added /forecast and /api/forecast routes to dashboard.py")

# Verify syntax
try:
    compile(code, "dashboard.py", "exec")
    print("Syntax check: PASSED")
except SyntaxError as e:
    print(f"Syntax check: FAILED - {e}")
