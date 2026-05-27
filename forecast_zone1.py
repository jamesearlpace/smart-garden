"""Forecast next watering for zone 1."""
import json, urllib.request

resp = urllib.request.urlopen("http://localhost:5125/api/dashboard", timeout=10)
d = json.loads(resp.read().decode())

# Weather
w = d.get("weather") or {}
et0 = d.get("et0_today", 0)
print("=== Weather ===")
print(f"  Temp: {w.get('temp_f', '?')}F, Humidity: {w.get('humidity_pct', '?')}%")
print(f"  Wind: {w.get('wind_mph', '?')} mph")
print(f"  Rain forecast: {w.get('rain_forecast_mm', '?')} mm, prob: {w.get('rain_probability_pct', '?')}%")
print(f"  ET0 today: {et0} mm")

# Zone 0 (valve 1)
zones = d.get("zones", [])
for z in zones:
    if z["id"] == 0:
        print(f"\n=== Zone 1 ({z['name']}) ===")
        print(f"  Soil moisture: {z.get('soil_pct', 'no sensor')}")
        print(f"  Dry trigger: {z['dry_trigger']}%")
        print(f"  Wet target: {z['wet_target']}%")
        print(f"  Currently watering: {z.get('watering', False)}")
        print(f"  Max runtime: {z['max_runtime_min']} min")
        print(f"  Cycle soak: {z.get('cycle_soak', False)}")
        if z.get("cycle_soak"):
            print(f"    Run: {z.get('cycle_run_min')} min, Soak: {z.get('cycle_soak_min')} min, Cycles: {z.get('cycle_count')}")
        break

# Soil balances
sb = d.get("soil_balances", [])
for b in sb:
    if b.get("zone_id") == 0:
        print(f"  Soil balance: {b}")
        break

# Skip rules
print(f"\n=== Skip Rules ===")
skip = d.get("config", {}).get("skip_rules", {})
for k, v in skip.items():
    print(f"  {k}: {v}")

# Check if any skip would fire
will_skip = False
reasons = []
if w.get("rain_forecast_mm", 0) and float(w.get("rain_forecast_mm", 0)) > float(skip.get("rain_forecast_mm", 999)):
    will_skip = True
    reasons.append(f"rain forecast {w['rain_forecast_mm']}mm > {skip['rain_forecast_mm']}mm")
if w.get("rain_probability_pct", 0) and float(w.get("rain_probability_pct", 0)) > float(skip.get("rain_probability_pct", 999)):
    will_skip = True
    reasons.append(f"rain probability {w['rain_probability_pct']}% > {skip['rain_probability_pct']}%")
if w.get("wind_mph", 0) and float(w.get("wind_mph", 0)) > float(skip.get("wind_speed_mph", 999)):
    will_skip = True
    reasons.append(f"wind {w['wind_mph']}mph > {skip['wind_speed_mph']}mph")
if w.get("temp_f", 99) and float(w.get("temp_f", 99)) < float(skip.get("freeze_temp_f", 0)):
    will_skip = True
    reasons.append(f"temp {w['temp_f']}F < {skip['freeze_temp_f']}F")

# Watering window
ww = d.get("config", {}).get("watering_window", {})
print(f"\n=== Watering Window ===")
print(f"  Morning: {ww.get('start')} - {ww.get('end')}")
print(f"  Evening: {ww.get('evening_start')} - {ww.get('evening_end')} (zones {ww.get('evening_zones')})")

# Forecast
print(f"\n=== FORECAST ===")
if will_skip:
    print(f"  SKIP likely — {', '.join(reasons)}")
    print(f"  Zone 1 will NOT water at next window")
else:
    # Check soil
    soil = None
    for z in zones:
        if z["id"] == 0:
            soil = z.get("soil_pct")
            dry = z["dry_trigger"]
            break
    if soil is not None and float(soil) > float(dry):
        print(f"  Soil at {soil}% > dry trigger {dry}% — NO watering needed yet")
    elif soil is not None:
        print(f"  Soil at {soil}% <= dry trigger {dry}% — WILL WATER at next morning window ({ww.get('start')})")
    else:
        print(f"  No soil sensor data — scheduling depends on ET-based checkbook method")
        print(f"  Next window: tomorrow {ww.get('start')} AM")
