"""Climate data ingestion using Open-Meteo (real data) with NASA POWER fallback.

Replaces the old hardcoded-values approach with actual API calls to Open-Meteo,
which serves ERA5-derived reanalysis data as JSON — free, no API key required.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .open_meteo import fetch_historical, fetch_forecast
from .utils import daterange, heat_index, stull_wet_bulb, wbgt_approx
from ...db.models import Dataset, DatasetVersion, IngestRun, Observation, Feature, Region

logger = logging.getLogger(__name__)

ERA5_DATASET_NAME = "era5"


async def ensure_dataset(db: AsyncSession) -> Dataset:
    res = await db.execute(select(Dataset).where(Dataset.name == ERA5_DATASET_NAME))
    ds = res.scalar_one_or_none()
    if not ds:
        ds = Dataset(name=ERA5_DATASET_NAME, source="open-meteo", license="cc-by", spatial="adm", temporal="daily")
        db.add(ds)
        await db.flush()
    return ds


async def flow_era5_ingest(db: AsyncSession, start: datetime, end: datetime) -> dict:
    """Ingest real climate data from Open-Meteo for all regions."""
    ds = await ensure_dataset(db)
    run = IngestRun(dataset_id=ds.id, started_at=datetime.now(timezone.utc), status="running", rows=0)
    db.add(run)
    await db.flush()

    regions = (await db.execute(select(Region))).scalars().all()
    if not regions:
        r = Region(name="Pilot Region", code="PILOT")
        db.add(r)
        await db.flush()
        regions = [r]

    rows_inserted = 0
    start_str = start.strftime("%Y-%m-%d")
    end_str = end.strftime("%Y-%m-%d")

    for reg in regions:
        center = reg.center if isinstance(reg.center, dict) else {}
        lat = center.get("lat", 19.076)  # default Mumbai
        lon = center.get("lng", 72.877)

        logger.info("Ingesting climate data for %s (%.2f, %.2f)", reg.name, lat, lon)

        # Fetch real data from Open-Meteo (with NASA POWER fallback)
        data = await fetch_historical(lat, lon, start_str, end_str)
        daily = data.get("daily", {})
        dates = daily.get("time", [])

        if not dates:
            logger.warning("No climate data returned for %s", reg.name)
            continue

        for i, date_str in enumerate(dates):
            day = datetime(int(date_str[:4]), int(date_str[5:7]), int(date_str[8:10]), tzinfo=timezone.utc)

            t2m_max = daily.get("temperature_2m_max", [None])[i]
            t2m_min = daily.get("temperature_2m_min", [None])[i]
            t2m_mean = daily.get("temperature_2m_mean", [None])[i]
            rh_mean = daily.get("relative_humidity_2m_mean", [None])[i]
            prcp_sum = daily.get("precipitation_sum", [None])[i]
            wind_max = daily.get("wind_speed_10m_max", [None])[i]

            # Skip days with missing data
            if t2m_max is None or t2m_mean is None:
                continue

            # Fill defaults for optional fields
            t2m_min = t2m_min if t2m_min is not None else t2m_mean - 5
            rh_mean = rh_mean if rh_mean is not None else 60.0
            prcp_sum = prcp_sum if prcp_sum is not None else 0.0
            wind_max = wind_max if wind_max is not None else 2.0

            # Store raw observations
            for val, unit in [
                (t2m_max, "C"), (t2m_min, "C"), (t2m_mean, "C"),
                (rh_mean, "%"), (prcp_sum, "mm"), (wind_max, "m/s"),
            ]:
                db.add(Observation(region_id=reg.id, dataset_id=ds.id, ts=day, value=float(val), unit=unit))
            rows_inserted += 6

            # Compute derived features using real scientific formulas
            hi = heat_index(t2m_max, rh_mean)
            tw = stull_wet_bulb(t2m_mean, rh_mean)
            wbgt = wbgt_approx(tw)

            for key, value, unit in [
                ("t2m_max", t2m_max, "C"),
                ("t2m_min", t2m_min, "C"),
                ("t2m_mean", t2m_mean, "C"),
                ("rh_mean", rh_mean, "%"),
                ("prcp_sum", prcp_sum, "mm"),
                ("wind_max", wind_max, "m/s"),
                ("heat_index", hi, "C"),
                ("wet_bulb", tw, "C"),
                ("wbgt", wbgt, "C"),
            ]:
                db.add(Feature(
                    region_id=reg.id, feature_key=key, ts=day,
                    value=float(value), unit=unit, p05=None, p95=None,
                ))
            rows_inserted += 9

    # Versioning
    dv = DatasetVersion(
        dataset_id=ds.id,
        version=f"{start_str}_{end_str}",
        hash="open-meteo",
        coverage_start=start,
        coverage_end=end,
        created_at=datetime.now(timezone.utc),
    )
    db.add(dv)

    run.rows = rows_inserted
    run.status = "success"
    run.ended_at = datetime.now(timezone.utc)
    ds.freshness = run.ended_at
    await db.commit()

    logger.info("Climate ingestion complete: %d rows across %d regions", rows_inserted, len(regions))
    return {"rows": rows_inserted, "dataset_id": ds.id}
