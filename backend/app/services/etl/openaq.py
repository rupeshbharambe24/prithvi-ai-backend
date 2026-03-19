"""OpenAQ v3 API client for real air quality data ingestion.

Free registration required for API key. 60 requests/min limit.
Aggregates India's CPCB data with hundreds of stations.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...config import get_settings
from ...db.models import Dataset, DatasetVersion, IngestRun, Observation, Feature, Region

logger = logging.getLogger(__name__)

OPENAQ_BASE = "https://api.openaq.org/v3"
DATASET_NAME = "openaq"


async def ensure_dataset(db: AsyncSession) -> Dataset:
    res = await db.execute(select(Dataset).where(Dataset.name == DATASET_NAME))
    ds = res.scalar_one_or_none()
    if not ds:
        ds = Dataset(name=DATASET_NAME, source="openaq-v3", license="cc-by", spatial="station", temporal="hourly")
        db.add(ds)
        await db.flush()
    return ds


async def _find_nearest_station(
    client: httpx.AsyncClient, lat: float, lon: float, headers: dict
) -> Optional[int]:
    """Find nearest PM2.5 monitoring station within 25km."""
    try:
        resp = await client.get(
            f"{OPENAQ_BASE}/locations",
            params={"coordinates": f"{lat},{lon}", "radius": 25000, "limit": 5},
            headers=headers,
        )
        resp.raise_for_status()
        results = resp.json().get("results", [])
        # Find a station that has PM2.5 parameter
        for loc in results:
            params = loc.get("parameters", [])
            for p in params:
                if isinstance(p, dict) and p.get("name", "").lower() in ("pm25", "pm2.5"):
                    return loc["id"]
            # Also check by parameter list structure
            if any(isinstance(p, dict) and "pm25" in str(p).lower() for p in params):
                return loc["id"]
        # If no PM2.5 specific, return first station
        if results:
            return results[0]["id"]
    except Exception as e:
        logger.warning("openaq_find_station_failed: %s", e)
    return None


async def _fetch_measurements(
    client: httpx.AsyncClient, location_id: int, start: str, end: str, headers: dict
) -> List[Dict]:
    """Fetch PM2.5 measurements from a station."""
    try:
        resp = await client.get(
            f"{OPENAQ_BASE}/locations/{location_id}/measurements",
            params={
                "parameter": "pm25",
                "date_from": start,
                "date_to": end,
                "limit": 1000,
            },
            headers=headers,
        )
        resp.raise_for_status()
        return resp.json().get("results", [])
    except Exception as e:
        logger.warning("openaq_fetch_measurements_failed: %s", e)
        return []


async def flow_openaq_ingest(db: AsyncSession, start: datetime, end: datetime) -> dict:
    """Ingest real PM2.5 data from OpenAQ for all regions."""
    settings = get_settings()
    ds = await ensure_dataset(db)
    run = IngestRun(dataset_id=ds.id, started_at=datetime.now(timezone.utc), status="running", rows=0)
    db.add(run)
    await db.flush()

    regions = (await db.execute(select(Region))).scalars().all()
    rows_inserted = 0

    headers = {}
    if settings.openaq_api_key:
        headers["X-API-Key"] = settings.openaq_api_key

    start_str = start.strftime("%Y-%m-%dT%H:%M:%SZ")
    end_str = end.strftime("%Y-%m-%dT%H:%M:%SZ")

    async with httpx.AsyncClient(timeout=30) as client:
        for reg in regions:
            center = reg.center if isinstance(reg.center, dict) else {}
            lat = center.get("lat", 19.076)
            lon = center.get("lng", 72.877)

            logger.info("Fetching OpenAQ data for %s (%.2f, %.2f)", reg.name, lat, lon)

            station_id = await _find_nearest_station(client, lat, lon, headers)
            if not station_id:
                logger.warning("No OpenAQ station found near %s, using AQICN fallback", reg.name)
                rows_inserted += await _fallback_aqicn(db, ds, reg, start, end)
                continue

            measurements = await _fetch_measurements(client, station_id, start_str, end_str, headers)

            # Aggregate hourly measurements to daily averages
            daily_pm25: Dict[str, List[float]] = {}
            for m in measurements:
                val = m.get("value")
                period = m.get("period", {})
                dt_str = period.get("datetimeFrom", {}).get("utc", "")[:10]
                if val is not None and dt_str:
                    daily_pm25.setdefault(dt_str, []).append(float(val))

            for date_str, values in sorted(daily_pm25.items()):
                avg_pm25 = sum(values) / len(values)
                day = datetime(int(date_str[:4]), int(date_str[5:7]), int(date_str[8:10]), tzinfo=timezone.utc)

                db.add(Observation(region_id=reg.id, dataset_id=ds.id, ts=day, value=avg_pm25, unit="ug/m3"))
                db.add(Feature(
                    region_id=reg.id, feature_key="pm25_obs", ts=day,
                    value=avg_pm25, unit="ug/m3", p05=None, p95=None,
                ))
                rows_inserted += 2

            # Rate limit courtesy
            await asyncio.sleep(1.0)

    # Versioning
    dv = DatasetVersion(
        dataset_id=ds.id,
        version=f"{start.strftime('%Y-%m-%d')}_{end.strftime('%Y-%m-%d')}",
        hash="openaq",
        coverage_start=start,
        coverage_end=end,
        created_at=datetime.now(timezone.utc),
    )
    db.add(dv)

    run.rows = rows_inserted
    run.status = "success"
    run.ended_at = datetime.now(timezone.utc)
    await db.commit()

    logger.info("OpenAQ ingestion complete: %d rows", rows_inserted)
    return {"rows": rows_inserted, "dataset_id": ds.id}


async def _fallback_aqicn(db: AsyncSession, ds: Dataset, reg: Region, start: datetime, end: datetime) -> int:
    """Fallback: fetch current AQI from AQICN (free token, real-time only)."""
    center = reg.center if isinstance(reg.center, dict) else {}
    lat = center.get("lat", 19.076)
    lon = center.get("lng", 72.877)
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"https://api.waqi.info/feed/geo:{lat};{lon}/",
                params={"token": "demo"},  # demo token for testing
            )
            resp.raise_for_status()
            data = resp.json().get("data", {})
            pm25 = data.get("iaqi", {}).get("pm25", {}).get("v")
            if pm25 is not None:
                now = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
                db.add(Observation(region_id=reg.id, dataset_id=ds.id, ts=now, value=float(pm25), unit="ug/m3"))
                db.add(Feature(
                    region_id=reg.id, feature_key="pm25_obs", ts=now,
                    value=float(pm25), unit="ug/m3", p05=None, p95=None,
                ))
                return 2
    except Exception as e:
        logger.warning("aqicn_fallback_failed: %s", e)
    return 0
