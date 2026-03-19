"""Open-Meteo API client for real climate data ingestion.

Free, no API key required. 10,000 requests/day limit.
Historical: ERA5-based reanalysis (1940-present)
Forecast: up to 16 days ahead
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

DAILY_VARS = (
    "temperature_2m_max,temperature_2m_min,temperature_2m_mean,"
    "relative_humidity_2m_mean,precipitation_sum,wind_speed_10m_max"
)

# NASA POWER fallback
NASA_POWER_URL = "https://power.larc.nasa.gov/api/temporal/daily/point"
NASA_POWER_PARAMS = "T2M,T2M_MAX,T2M_MIN,RH2M,PRECTOTCORR,WS10M"


async def fetch_historical(
    lat: float, lon: float, start_date: str, end_date: str, retries: int = 3
) -> Dict[str, Any]:
    """Fetch historical daily weather from Open-Meteo archive API.

    Args:
        lat, lon: coordinates
        start_date, end_date: "YYYY-MM-DD" strings
        retries: number of retry attempts

    Returns:
        JSON dict with 'daily' key containing arrays of values.
    """
    params = {
        "latitude": lat,
        "longitude": lon,
        "start_date": start_date,
        "end_date": end_date,
        "daily": DAILY_VARS,
        "timezone": "UTC",
    }
    for attempt in range(retries):
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(ARCHIVE_URL, params=params)
                resp.raise_for_status()
                return resp.json()
        except (httpx.HTTPError, httpx.TimeoutException) as e:
            logger.warning("open_meteo_archive_attempt_%d_failed: %s", attempt + 1, e)
            if attempt < retries - 1:
                await asyncio.sleep(2 ** attempt)
    # Fallback to NASA POWER
    logger.info("Falling back to NASA POWER API")
    return await _fetch_nasa_power(lat, lon, start_date, end_date)


async def fetch_forecast(lat: float, lon: float, days: int = 16) -> Dict[str, Any]:
    """Fetch weather forecast from Open-Meteo forecast API."""
    params = {
        "latitude": lat,
        "longitude": lon,
        "daily": DAILY_VARS,
        "forecast_days": min(days, 16),
        "timezone": "UTC",
    }
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(FORECAST_URL, params=params)
            resp.raise_for_status()
            return resp.json()
    except (httpx.HTTPError, httpx.TimeoutException) as e:
        logger.warning("open_meteo_forecast_failed: %s", e)
        return {"daily": {}}


async def _fetch_nasa_power(
    lat: float, lon: float, start_date: str, end_date: str
) -> Dict[str, Any]:
    """Fallback: NASA POWER API (free, no key, coarser resolution)."""
    start_compact = start_date.replace("-", "")
    end_compact = end_date.replace("-", "")
    params = {
        "parameters": NASA_POWER_PARAMS,
        "community": "AG",
        "longitude": lon,
        "latitude": lat,
        "start": start_compact,
        "end": end_compact,
        "format": "JSON",
    }
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.get(NASA_POWER_URL, params=params)
            resp.raise_for_status()
            data = resp.json()

        # Convert NASA POWER format to Open-Meteo-like format
        props = data.get("properties", {}).get("parameter", {})
        dates = sorted(props.get("T2M", {}).keys())

        daily: Dict[str, List] = {
            "time": [],
            "temperature_2m_max": [],
            "temperature_2m_min": [],
            "temperature_2m_mean": [],
            "relative_humidity_2m_mean": [],
            "precipitation_sum": [],
            "wind_speed_10m_max": [],
        }
        for d in dates:
            daily["time"].append(f"{d[:4]}-{d[4:6]}-{d[6:8]}")
            daily["temperature_2m_max"].append(props.get("T2M_MAX", {}).get(d))
            daily["temperature_2m_min"].append(props.get("T2M_MIN", {}).get(d))
            daily["temperature_2m_mean"].append(props.get("T2M", {}).get(d))
            daily["relative_humidity_2m_mean"].append(props.get("RH2M", {}).get(d))
            daily["precipitation_sum"].append(props.get("PRECTOTCORR", {}).get(d))
            daily["wind_speed_10m_max"].append(props.get("WS10M", {}).get(d))

        return {"daily": daily}
    except Exception as e:
        logger.error("nasa_power_fallback_failed: %s", e)
        return {"daily": {}}
