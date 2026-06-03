import urllib.request, json
url = ("https://api.open-meteo.com/v1/forecast?"
       "latitude=47.36&longitude=-122.04"
       "&daily=et0_fao_evapotranspiration,precipitation_sum,temperature_2m_max,temperature_2m_min"
       "&temperature_unit=fahrenheit&wind_speed_unit=mph&precipitation_unit=inch"
       "&timezone=America%2FLos_Angeles&past_days=1&forecast_days=7")
d = json.loads(urllib.request.urlopen(url).read())
print("daily_units:", json.dumps(d["daily_units"], indent=2))
print()
daily = d["daily"]
print(f"{'date':<12} {'tmax':<8} {'tmin':<8} {'et0':<8} {'rain':<8}")
for i in range(len(daily["time"])):
    print(f"{daily['time'][i]:<12} {daily['temperature_2m_max'][i]:<8.2f} {daily['temperature_2m_min'][i]:<8.2f} {daily['et0_fao_evapotranspiration'][i]:<8.4f} {daily['precipitation_sum'][i]:<8.3f}")
