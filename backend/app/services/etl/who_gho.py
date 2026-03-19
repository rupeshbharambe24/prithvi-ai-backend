"""WHO Global Health Observatory data ingestion.

Free OData API, no API key required. Returns national-level health indicators for India.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...db.models import Dataset, DatasetVersion, IngestRun, Observation, Region

logger = logging.getLogger(__name__)

GHO_DATASET_NAME = "who_gho"
GHO_API = "https://ghoapi.azureedge.net/api"

# Key health indicators relevant to climate-health system
GHO_INDICATORS = {
    "RS_198": "dengue_cases",           # Dengue cases reported
    "MALARIA_EST_CASES": "malaria_cases",  # Estimated malaria cases
    "WHOSIS_000001": "life_expectancy",    # Life expectancy at birth
    "AIR_41": "pm25_annual_mean",        # PM2.5 annual mean
}


async def ensure_dataset(db: AsyncSession) -> Dataset:
    res = await db.execute(select(Dataset).where(Dataset.name == GHO_DATASET_NAME))
    ds = res.scalar_one_or_none()
    if not ds:
        ds = Dataset(name=GHO_DATASET_NAME, source="who-gho", license="open", spatial="adm", temporal="annual")
        db.add(ds)
        await db.flush()
    return ds


async def _fetch_indicator(client: httpx.AsyncClient, indicator_code: str) -> list[dict]:
    """Fetch a specific indicator for India from WHO GHO OData API."""
    try:
        resp = await client.get(
            f"{GHO_API}/{indicator_code}",
            params={"$filter": "SpatialDim eq 'IND'"},
        )
        resp.raise_for_status()
        return resp.json().get("value", [])
    except Exception as e:
        logger.warning("gho_fetch_%s_failed: %s", indicator_code, e)
        return []


async def flow_who_gho_ingest(db: AsyncSession) -> dict:
    """Ingest real health indicators from WHO GHO API."""
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

    rows = 0

    async with httpx.AsyncClient(timeout=30) as client:
        for gho_code, label in GHO_INDICATORS.items():
            logger.info("Fetching WHO GHO indicator: %s (%s)", label, gho_code)
            records = await _fetch_indicator(client, gho_code)

            for rec in records:
                year = rec.get("TimeDim")
                value = rec.get("NumericValue")
                if year is None or value is None:
                    continue

                try:
                    year_int = int(year)
                    val_float = float(value)
                except (ValueError, TypeError):
                    continue

                ts = datetime(year_int, 1, 1, tzinfo=timezone.utc)

                # WHO data is national level — store for all regions
                # (In a production system, you'd use district-level data)
                for reg in regions:
                    db.add(Observation(
                        region_id=reg.id, dataset_id=ds.id,
                        ts=ts, value=val_float, unit=label,
                    ))
                    rows += 1

            logger.info("  -> %d records for %s", len(records), label)

    # Versioning
    now = datetime.now(timezone.utc)
    dv = DatasetVersion(
        dataset_id=ds.id, version="who-gho-latest", hash="gho-api",
        coverage_start=datetime(2000, 1, 1, tzinfo=timezone.utc),
        coverage_end=now, created_at=now,
    )
    db.add(dv)
    run.rows = rows
    run.status = "success"
    run.ended_at = now
    ds.freshness = now
    await db.commit()

    logger.info("WHO GHO ingestion complete: %d rows", rows)
    return {"rows": rows, "dataset_id": ds.id}
