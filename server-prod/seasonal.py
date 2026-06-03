"""Seasonal outlook for Smart Garden.

Pulls ECMWF SEAS5 6-month forecast from Open-Meteo's free seasonal API and
compares it against a 5-year ERA5 historical normal for the same calendar
months. Returns per-month anomalies for temperature, ET0, and precipitation
so the user can see whether the upcoming season is leaning warmer/drier than
typical for Duvall, WA.

Data sources (both free, no key, ECMWF-derived):
- Seasonal forecast: https://seasonal-api.open-meteo.com/v1/seasonal (SEAS5 ensemble mean)
- Historical normal: https://archive-api.open-meteo.com/v1/archive (ERA5 reanalysis)

The result is cached to disk for 24 hours. SEAS5 only updates monthly (on the
5th) and historical data is fixed, so daily refresh is plenty.
"""

import json
import logging
import os
import tempfile
import threading
from datetime import date, datetime, timedelta

import requests

log = logging.getLogger("smart-garden.seasonal")

SEASONAL_URL = "https://seasonal-api.open-meteo.com/v1/seasonal"
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
REQUEST_TIMEOUT = 30
CACHE_TTL = timedelta(hours=24)
NORMAL_YEARS = 5  # number of past years to average for "normal"
FORECAST_DAYS = 180  # ~6 months

_cache_lock = threading.Lock()


def _cache_path() -> str:
    return os.path.join(tempfile.gettempdir(), "smart_garden_seasonal_cache.json")


def _load_cache() -> dict | None:
    p = _cache_path()
    if not os.path.exists(p):
        return None
    try:
        with open(p, "r") as f:
            data = json.load(f)
        ts = datetime.fromisoformat(data.get("cached_at", ""))
        if datetime.now() - ts < CACHE_TTL:
            return data
    except (OSError, ValueError, json.JSONDecodeError) as e:
        log.warning("Seasonal cache read failed: %s", e)
    return None


def _save_cache(data: dict) -> None:
    try:
        with open(_cache_path(), "w") as f:
            json.dump(data, f)
    except OSError as e:
        log.warning("Seasonal cache write failed: %s", e)


def _fetch_seasonal_forecast(lat: float, lon: float, timezone: str) -> dict:
    params = {
        "latitude": lat,
        "longitude": lon,
        "daily": "temperature_2m_max,precipitation_sum,et0_fao_evapotranspiration",
        "temperature_unit": "fahrenheit",
        "precipitation_unit": "inch",
        "timezone": timezone,
        "forecast_days": FORECAST_DAYS,
        "models": "ecmwf_seas5_ensemble_mean",
    }
    resp = requests.get(SEASONAL_URL, params=params, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    return resp.json()


def _fetch_archive(lat: float, lon: float, timezone: str,
                   start: date, end: date) -> dict:
    params = {
        "latitude": lat,
        "longitude": lon,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "daily": "temperature_2m_max,precipitation_sum,et0_fao_evapotranspiration",
        "temperature_unit": "fahrenheit",
        "precipitation_unit": "inch",
        "timezone": timezone,
    }
    resp = requests.get(ARCHIVE_URL, params=params, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    return resp.json()


def _bucket_by_month(times: list[str], values: list[float]) -> dict[str, list[float]]:
    """Group daily values by YYYY-MM key."""
    buckets: dict[str, list[float]] = {}
    for t, v in zip(times, values):
        if v is None:
            continue
        ym = t[:7]
        buckets.setdefault(ym, []).append(v)
    return buckets


def _month_label(ym: str) -> str:
    y, m = ym.split("-")
    return f"{['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'][int(m)-1]} {y}"


def get_seasonal_outlook(lat: float, lon: float, timezone: str,
                         force_refresh: bool = False) -> dict:
    """Return per-month outlook for the next ~6 months with anomalies vs 5-yr normal.

    Each month entry includes:
      - month, label
      - forecast: avg tmax (F), total et0 (in), total precip (in)
      - normal:   avg tmax (F), total et0 (in), total precip (in) — 5-yr ERA5 mean
      - anomaly:  delta_tmax_f, et0_pct (forecast/normal - 1)*100, precip_pct
      - days_forecast: how many days of the month the forecast covers
    """
    if not force_refresh:
        cached = _load_cache()
        if cached and cached.get("lat") == lat and cached.get("lon") == lon:
            log.debug("Using cached seasonal outlook")
            return cached

    with _cache_lock:
        # Double-check inside lock
        if not force_refresh:
            cached = _load_cache()
            if cached and cached.get("lat") == lat and cached.get("lon") == lon:
                return cached

        log.info("Fetching fresh seasonal outlook for %.3f, %.3f", lat, lon)

        # 1. Pull SEAS5 forecast (next ~6 months daily)
        try:
            fc = _fetch_seasonal_forecast(lat, lon, timezone)
        except requests.RequestException as e:
            log.error("Seasonal forecast fetch failed: %s", e)
            return {"error": f"Forecast fetch failed: {e}", "months": []}

        fc_daily = fc.get("daily", {})
        fc_times = fc_daily.get("time", [])
        if not fc_times:
            return {"error": "Empty seasonal forecast response", "months": []}

        fc_tmax = _bucket_by_month(fc_times, fc_daily.get("temperature_2m_max", []))
        fc_et0 = _bucket_by_month(fc_times, fc_daily.get("et0_fao_evapotranspiration", []))
        fc_precip = _bucket_by_month(fc_times, fc_daily.get("precipitation_sum", []))

        # Forecast months in order (skip incomplete current month if fewer than 10 days)
        all_months = sorted(fc_tmax.keys())

        # 2. Pull historical for the same calendar months across past N years.
        # ERA5 has a ~5-day lag, so use this_year-1 back N years. Batch one
        # request per year covering all forecast months at once.
        start_year = date.today().year - 1
        end_year = start_year - NORMAL_YEARS + 1

        normals: dict[str, dict[str, list[float]]] = {
            ym: {"tmax": [], "et0": [], "precip": []} for ym in all_months
        }

        # Compute the date range each year needs (min month → max month of forecast)
        fc_month_ints = sorted({int(ym.split("-")[1]) for ym in all_months})
        if not fc_month_ints:
            range_first_m, range_last_m = 1, 12
        else:
            range_first_m, range_last_m = fc_month_ints[0], fc_month_ints[-1]

        for yr in range(start_year, end_year - 1, -1):
            first = date(yr, range_first_m, 1)
            if range_last_m == 12:
                last = date(yr, 12, 31)
            else:
                last = date(yr, range_last_m + 1, 1) - timedelta(days=1)
            try:
                h = _fetch_archive(lat, lon, timezone, first, last)
            except requests.RequestException as e:
                log.warning("Archive fetch failed for year %d: %s", yr, e)
                continue
            hd = h.get("daily", {})
            h_times = hd.get("time", [])
            yr_tmax = _bucket_by_month(h_times, hd.get("temperature_2m_max", []))
            yr_et0 = _bucket_by_month(h_times, hd.get("et0_fao_evapotranspiration", []))
            yr_precip = _bucket_by_month(h_times, hd.get("precipitation_sum", []))
            # Map yr's months onto the forecast's month keys (same M, different Y)
            for ym in all_months:
                m = ym.split("-")[1]
                hist_ym = f"{yr}-{m}"
                if hist_ym in yr_tmax and yr_tmax[hist_ym]:
                    normals[ym]["tmax"].append(sum(yr_tmax[hist_ym]) / len(yr_tmax[hist_ym]))
                if hist_ym in yr_et0 and yr_et0[hist_ym]:
                    normals[ym]["et0"].append(sum(yr_et0[hist_ym]))
                if hist_ym in yr_precip and yr_precip[hist_ym]:
                    normals[ym]["precip"].append(sum(yr_precip[hist_ym]))

        # 3. Build per-month output
        months_out = []
        for ym in all_months:
            tmax_vals = fc_tmax.get(ym, [])
            et0_vals = fc_et0.get(ym, [])
            precip_vals = fc_precip.get(ym, [])
            if not tmax_vals:
                continue
            days_in_month = len(tmax_vals)
            fc_tmax_avg = sum(tmax_vals) / days_in_month
            fc_et0_total = sum(et0_vals)
            fc_precip_total = sum(precip_vals)

            # Scale forecast to full month if partial (proportional)
            _, m = ym.split("-")
            m_int = int(m)
            y_int = int(ym.split("-")[0])
            if m_int == 12:
                full_days = 31
            else:
                full_days = (date(y_int, m_int + 1, 1) - date(y_int, m_int, 1)).days
            scale = full_days / days_in_month if days_in_month else 1.0
            fc_et0_full = fc_et0_total * scale
            fc_precip_full = fc_precip_total * scale

            norm = normals.get(ym, {})
            norm_tmax = (sum(norm["tmax"]) / len(norm["tmax"])) if norm.get("tmax") else None
            norm_et0 = (sum(norm["et0"]) / len(norm["et0"])) if norm.get("et0") else None
            norm_precip = (sum(norm["precip"]) / len(norm["precip"])) if norm.get("precip") else None

            anomaly_tmax = (fc_tmax_avg - norm_tmax) if norm_tmax is not None else None
            anomaly_et0_pct = ((fc_et0_full / norm_et0 - 1) * 100) if norm_et0 else None
            anomaly_precip_pct = ((fc_precip_full / norm_precip - 1) * 100) if norm_precip else None

            months_out.append({
                "month": ym,
                "label": _month_label(ym),
                "days_forecast": days_in_month,
                "days_in_month": full_days,
                "forecast": {
                    "tmax_avg_f": round(fc_tmax_avg, 1),
                    "et0_total_in": round(fc_et0_full, 2),
                    "precip_total_in": round(fc_precip_full, 2),
                },
                "normal": {
                    "tmax_avg_f": round(norm_tmax, 1) if norm_tmax is not None else None,
                    "et0_total_in": round(norm_et0, 2) if norm_et0 is not None else None,
                    "precip_total_in": round(norm_precip, 2) if norm_precip is not None else None,
                    "years_used": len(norm.get("tmax", [])),
                },
                "anomaly": {
                    "delta_tmax_f": round(anomaly_tmax, 1) if anomaly_tmax is not None else None,
                    "et0_pct": round(anomaly_et0_pct, 1) if anomaly_et0_pct is not None else None,
                    "precip_pct": round(anomaly_precip_pct, 1) if anomaly_precip_pct is not None else None,
                },
            })

        result = {
            "lat": lat,
            "lon": lon,
            "timezone": timezone,
            "cached_at": datetime.now().isoformat(),
            "normal_years_back": NORMAL_YEARS,
            "normal_year_range": f"{end_year}-{start_year}",
            "months": months_out,
        }
        _save_cache(result)
        return result
