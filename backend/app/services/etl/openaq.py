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
from sqlalchemy import select, text
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


async def _get_json(
    client: httpx.AsyncClient, url: str, params: Optional[dict], headers: dict, attempts: int = 4
) -> Optional[dict]:
    """GET JSON with exponential backoff.

    OpenAQ's free tier intermittently returns transient 401/403/429/5xx under
    load or quota pressure even with a valid key. Treat those (and network
    errors) as retryable so a momentary blip doesn't blank the whole ingest and
    force an unnecessary fallback.
    """
    delay = 1.0
    last_body = ""
    for i in range(attempts):
        try:
            resp = await client.get(url, params=params, headers=headers)
            if resp.status_code == 200:
                return resp.json()
            last_body = resp.text[:200]
            if resp.status_code == 429 or resp.status_code >= 500:
                # Genuine rate-limit / server error: wait for the reset and retry.
                ra = resp.headers.get("retry-after") or resp.headers.get("x-ratelimit-reset")
                wait = float(ra) if (ra and str(ra).isdigit()) else delay
                logger.warning(
                    "openaq_retry status=%s url=%s wait=%.1fs (attempt %d/%d)",
                    resp.status_code, url, wait, i + 1, attempts,
                )
                await asyncio.sleep(min(wait, 30.0))
                delay = min(delay * 2, 10.0)
                continue
            # 401/403/other 4xx: auth/permission/quota block. Retrying won't help
            # and only adds load to an already-rejecting key — fail fast to fallback.
            logger.warning("openaq_auth_failed status=%s url=%s body=%s", resp.status_code, url, last_body)
            return None
        except httpx.HTTPError as e:
            logger.warning("openaq_http_error url=%s: %s (attempt %d/%d)", url, e, i + 1, attempts)
            await asyncio.sleep(delay)
            delay = min(delay * 2, 10.0)
    logger.warning("openaq_get_failed after %d attempts: %s | last_body=%s", attempts, url, last_body)
    return None


async def _find_pm25_sensor(
    client: httpx.AsyncClient, lat: float, lon: float, headers: dict, max_age_days: int = 45
) -> Optional[tuple[int, int]]:
    """Find the nearest location whose *active* PM2.5 sensor has recent data.

    OpenAQ v3 stores measurements under sensors, and a single location can expose
    several PM2.5 sensors (a decommissioned one plus a live one), so we pick the
    sensor with the most recent ``datetimeLast``. Locations are returned
    nearest-first; we take the first whose freshest PM2.5 sensor is within
    ``max_age_days``. Returns ``(location_id, sensor_id)`` or ``None``.
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(days=max_age_days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    data = await _get_json(
        client,
        f"{OPENAQ_BASE}/locations",
        {"coordinates": f"{lat},{lon}", "radius": 25000, "limit": 50},
        headers,
    )
    if not data:
        return None
    locations = data.get("results", [])

    for loc in locations[:12]:  # nearest-first
        loc_id = loc.get("id")
        if loc_id is None:
            continue
        sdata = await _get_json(client, f"{OPENAQ_BASE}/locations/{loc_id}/sensors", None, headers)
        if not sdata:
            continue
        sensors = sdata.get("results", [])
        best: Optional[tuple[str, int]] = None  # (datetimeLast_utc, sensor_id)
        for s in sensors:
            if (s.get("parameter") or {}).get("name", "").lower() not in ("pm25", "pm2.5"):
                continue
            dl = s.get("datetimeLast")
            dl_utc = dl.get("utc") if isinstance(dl, dict) else dl
            sid = s.get("id")
            if not dl_utc or sid is None:
                continue
            if best is None or dl_utc > best[0]:
                best = (dl_utc, sid)
        if best and best[0] >= cutoff:
            logger.info("openaq pm25 sensor=%s loc=%s last=%s", best[1], loc_id, best[0])
            return loc_id, best[1]
    return None


async def _fetch_daily_pm25(
    client: httpx.AsyncClient, sensor_id: int, headers: dict, recent_days: int = 120, max_pages: int = 5
) -> List[tuple[str, float]]:
    """Fetch daily PM2.5 for a sensor via ``/sensors/{id}/days``.

    The v3 ``/days`` endpoint returns oldest-first and ignores date filters, so we
    paginate (limit 1000) up to ``max_pages`` and keep the most recent
    ``recent_days`` days. Returns a list of ``(YYYY-MM-DD, value)``.
    """
    collected: List[tuple[str, float]] = []
    for page in range(1, max_pages + 1):
        data = await _get_json(
            client,
            f"{OPENAQ_BASE}/sensors/{sensor_id}/days",
            {"limit": 1000, "page": page},
            headers,
        )
        if not data:
            break
        results = data.get("results", [])
        for rec in results:
            val = rec.get("value")
            period = rec.get("period", {}) or {}
            dt_str = (period.get("datetimeFrom", {}) or {}).get("utc", "")[:10]
            if val is not None and dt_str:
                collected.append((dt_str, float(val)))
        if len(results) < 1000:
            break
        await asyncio.sleep(0.3)

    # De-dupe by date (last value wins), keep the most recent days
    by_date: Dict[str, float] = {}
    for d, v in collected:
        by_date[d] = v
    return sorted(by_date.items())[-recent_days:]


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
    _key = settings.openaq_api_key or ""
    if _key:
        headers["X-API-Key"] = _key
    logger.info(
        "openaq key fingerprint: present=%s first4=%s last4=%s len=%d",
        bool(_key), _key[:4], _key[-4:], len(_key),
    )

    async with httpx.AsyncClient(timeout=30) as client:
        for reg in regions:
            center = reg.center if isinstance(reg.center, dict) else {}
            lat = center.get("lat", 19.076)
            lon = center.get("lng", 72.877)

            logger.info("Fetching OpenAQ data for %s (%.2f, %.2f)", reg.name, lat, lon)

            found = await _find_pm25_sensor(client, lat, lon, headers)
            if not found:
                logger.warning("No fresh OpenAQ PM2.5 sensor near %s, using AQICN fallback", reg.name)
                rows_inserted += await _fallback_aqicn(db, ds, reg, start, end)
                continue

            _loc_id, sensor_id = found
            daily = await _fetch_daily_pm25(client, sensor_id, headers)
            if not daily:
                logger.warning("No daily PM2.5 for %s (sensor %s), using AQICN fallback", reg.name, sensor_id)
                rows_inserted += await _fallback_aqicn(db, ds, reg, start, end)
                continue

            # Idempotent refresh: clear existing rows in the window we're re-ingesting
            min_day = daily[0][0]
            await db.execute(
                text("DELETE FROM features WHERE region_id=:r AND feature_key='pm25_obs' AND ts >= :mn"),
                {"r": reg.id, "mn": min_day},
            )
            await db.execute(
                text("DELETE FROM observations WHERE region_id=:r AND dataset_id=:d AND ts >= :mn"),
                {"r": reg.id, "d": ds.id, "mn": min_day},
            )

            for date_str, value in daily:
                day = datetime(int(date_str[:4]), int(date_str[5:7]), int(date_str[8:10]), tzinfo=timezone.utc)
                db.add(Observation(region_id=reg.id, dataset_id=ds.id, ts=day, value=value, unit="ug/m3"))
                db.add(Feature(
                    region_id=reg.id, feature_key="pm25_obs", ts=day,
                    value=value, unit="ug/m3", p05=None, p95=None,
                ))
                rows_inserted += 2

            # Rate limit courtesy
            await asyncio.sleep(0.5)

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
