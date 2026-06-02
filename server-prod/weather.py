"""Open-Meteo weather client for Smart Garden Server.

Fetches ET₀, temperature, humidity, wind, precipitation, and solar radiation
for Duvall, WA. No API key required — free tier allows 10,000 requests/day.
"""

import logging
import threading
import requests
from datetime import datetime, timedelta

log = logging.getLogger("smart-garden.weather")

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
REQUEST_TIMEOUT = 5


class WeatherClient:

    def __init__(self, lat: float, lon: float, timezone: str):
        self.lat = lat
        self.lon = lon
        self.timezone = timezone
        self._cache = {}
        self._cache_ts = None
        self._cache_ttl = timedelta(minutes=30)
        self._last_failure_ts = None
        self._failure_ttl = timedelta(minutes=5)
        self._fetch_lock = threading.Lock()

    def fetch(self, allow_block: bool = True) -> dict:
        """Fetch hourly + daily weather data. Returns parsed response dict.
        Uses a 30-minute cache to avoid hammering the API."""
        now = datetime.now()
        if self._cache_ts and (now - self._cache_ts) < self._cache_ttl:
            return self._cache
        if not allow_block:
            return self._cache or {}
        if (self._last_failure_ts and not self._cache
                and (now - self._last_failure_ts) < self._failure_ttl):
            return {}
        if not self._fetch_lock.acquire(blocking=False):
            return self._cache or {}

        params = {
            "latitude": self.lat,
            "longitude": self.lon,
            "hourly": ",".join([
                "temperature_2m",
                "relative_humidity_2m",
                "wind_speed_10m",
                "precipitation_probability",
                "precipitation",
                "shortwave_radiation",
            ]),
            "daily": ",".join([
                "et0_fao_evapotranspiration",
                "precipitation_sum",
                "temperature_2m_max",
                "temperature_2m_min",
                "wind_speed_10m_max",
                "weather_code",
            ]),
            "temperature_unit": "fahrenheit",
            "wind_speed_unit": "mph",
            "precipitation_unit": "mm",
            "timezone": self.timezone,
            "forecast_days": 7,
            "past_days": 1,
        }

        try:
            resp = requests.get(OPEN_METEO_URL, params=params,
                                timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            data = resp.json()
            self._cache = data
            self._cache_ts = now
            log.info("Weather data fetched successfully")
            return data
        except requests.RequestException as e:
            self._last_failure_ts = now
            log.error("Weather fetch failed: %s", e)
            if self._cache:
                log.warning("Using cached weather data")
                return self._cache
            return {}
        finally:
            self._fetch_lock.release()

    def get_current(self, allow_fetch: bool = True) -> dict:
        """Get current conditions (nearest hour from hourly data)."""
        data = self.fetch(allow_block=allow_fetch)
        if not data or "hourly" not in data:
            return {}

        hourly = data["hourly"]
        times = hourly.get("time", [])
        now = datetime.now()
        now_str = now.strftime("%Y-%m-%dT%H:00")

        # Find the index of the current or most recent hour
        idx = 0
        for i, t in enumerate(times):
            if t <= now_str:
                idx = i

        return {
            "temp_f": hourly["temperature_2m"][idx],
            "humidity": hourly["relative_humidity_2m"][idx],
            "wind_mph": hourly["wind_speed_10m"][idx],
            "precip_prob": hourly["precipitation_probability"][idx],
            "precip_mm": hourly["precipitation"][idx],
            "solar_rad": hourly["shortwave_radiation"][idx],
            "time": times[idx],
        }

    def get_today_et0(self, allow_fetch: bool = True) -> float:
        """Get today's ET₀ in mm (FAO Penman-Monteith, calculated by Open-Meteo)."""
        data = self.fetch(allow_block=allow_fetch)
        if not data or "daily" not in data:
            return 0.0

        daily = data["daily"]
        today_str = datetime.now().strftime("%Y-%m-%d")
        times = daily.get("time", [])

        for i, t in enumerate(times):
            if t == today_str:
                val = daily["et0_fao_evapotranspiration"][i]
                return val if val is not None else 0.0
        return 0.0

    def get_rain_forecast_24h(self, allow_fetch: bool = True) -> dict:
        """Get total precipitation and max probability in the next 24 hours."""
        data = self.fetch(allow_block=allow_fetch)
        if not data or "hourly" not in data:
            return {"total_mm": 0, "max_probability": 0}

        hourly = data["hourly"]
        times = hourly.get("time", [])
        now = datetime.now()
        end = now + timedelta(hours=24)
        now_str = now.strftime("%Y-%m-%dT%H:00")
        end_str = end.strftime("%Y-%m-%dT%H:00")

        total_mm = 0.0
        max_prob = 0

        for i, t in enumerate(times):
            if now_str <= t <= end_str:
                precip = hourly["precipitation"][i]
                prob = hourly["precipitation_probability"][i]
                if precip is not None:
                    total_mm += precip
                if prob is not None and prob > max_prob:
                    max_prob = prob

        return {"total_mm": total_mm, "max_probability": max_prob}

    def get_rain_last_24h(self, allow_fetch: bool = True) -> float:
        """Get total precipitation in the last 24 hours."""
        data = self.fetch(allow_block=allow_fetch)
        if not data or "hourly" not in data:
            return 0.0

        hourly = data["hourly"]
        times = hourly.get("time", [])
        now = datetime.now()
        start = now - timedelta(hours=24)
        start_str = start.strftime("%Y-%m-%dT%H:00")
        now_str = now.strftime("%Y-%m-%dT%H:00")

        total_mm = 0.0
        for i, t in enumerate(times):
            if start_str <= t <= now_str:
                precip = hourly["precipitation"][i]
                if precip is not None:
                    total_mm += precip
        return total_mm

    _WMO = {
        0: "Clear", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
        45: "Fog", 48: "Icy fog",
        51: "Light drizzle", 53: "Drizzle", 55: "Heavy drizzle",
        61: "Light rain", 63: "Rain", 65: "Heavy rain",
        71: "Light snow", 73: "Snow", 75: "Heavy snow", 77: "Snow grains",
        80: "Rain showers", 81: "Showers", 82: "Heavy showers",
        85: "Snow showers", 86: "Heavy snow showers",
        95: "Thunderstorm", 96: "Thunderstorm w/ hail", 99: "Thunderstorm w/ hail",
    }

    def get_7day_forecast(self, allow_fetch: bool = True) -> list[dict]:
        """Get 7-day daily summary for dashboard."""
        data = self.fetch(allow_block=allow_fetch)
        if not data or "daily" not in data:
            return []

        daily = data["daily"]
        codes = daily.get("weather_code", [])
        days = []
        for i, t in enumerate(daily.get("time", [])):
            code = codes[i] if i < len(codes) else None
            days.append({
                "date": t,
                "et0": daily["et0_fao_evapotranspiration"][i],
                "rain": daily["precipitation_sum"][i],
                "temp_max": daily["temperature_2m_max"][i],
                "temp_min": daily["temperature_2m_min"][i],
                "wind_max": daily["wind_speed_10m_max"][i],
                "condition": WeatherClient._WMO.get(code, str(code) if code is not None else None),
            })
        return days

    def get_season(self) -> str:
        """Get current Duvall growing season for Kc index selection.
        Returns: 'spring', 'early_summer', 'peak', 'fall'"""
        month = datetime.now().month
        if month in (3, 4, 5):
            return "spring"          # index 0
        elif month in (6,):
            return "early_summer"    # index 1
        elif month in (7, 8):
            return "peak"            # index 2
        elif month in (9, 10):
            return "fall"            # index 3
        else:
            return "dormant"         # no irrigation

    def get_season_index(self) -> int:
        """Get Kc array index for current season. Returns -1 for dormant."""
        season_map = {"spring": 0, "early_summer": 1, "peak": 2, "fall": 3}
        return season_map.get(self.get_season(), -1)
