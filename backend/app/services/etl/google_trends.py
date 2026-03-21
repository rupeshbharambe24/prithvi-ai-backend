"""Google Trends health search data ingestion.

Uses pytrends to fetch search volume for health-related queries.
These are proven epidemiological proxies for disease surveillance
(Ginsberg et al. 2009, Nature; Yang et al. 2015, PLoS Comp Bio).

Free, no API key required.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...db.models import Dataset, Feature, Region

logger = logging.getLogger(__name__)

GT_DATASET_NAME = "google_trends_health"

# Health search queries by city — proven disease surveillance proxies
CITY_QUERIES = {
    "Mumbai": {
        "dengue_search": "dengue symptoms",
        "heatstroke_search": "heat stroke treatment",
        "hospital_search": "nearest hospital emergency",
        "respiratory_search": "breathing difficulty pollution",
    },
    "Delhi": {
        "dengue_search": "dengue symptoms",
        "heatstroke_search": "heat stroke treatment",
        "hospital_search": "nearest hospital emergency",
        "respiratory_search": "breathing difficulty pollution",
    },
    "Chennai": {
        "dengue_search": "dengue symptoms",
        "heatstroke_search": "heat stroke treatment",
        "hospital_search": "nearest hospital emergency",
        "respiratory_search": "breathing difficulty pollution",
    },
}

# Geo codes for Google Trends
CITY_GEO = {
    "Mumbai": "IN-MH",  # Maharashtra
    "Delhi": "IN-DL",
    "Chennai": "IN-TN",  # Tamil Nadu
}


async def _ensure_dataset(db: AsyncSession) -> Dataset:
    res = await db.execute(select(Dataset).where(Dataset.name == GT_DATASET_NAME))
    ds = res.scalar_one_or_none()
    if not ds:
        ds = Dataset(
            name=GT_DATASET_NAME, source="google-trends",
            license="public", spatial="city", temporal="weekly",
        )
        db.add(ds)
        await db.flush()
    return ds


async def flow_google_trends_ingest(db: AsyncSession, lookback_weeks: int = 12) -> dict:
    """Fetch Google Trends health search data for Indian cities.

    Returns weekly search interest (0-100) for health-related queries.
    These serve as real-time disease surveillance proxies.
    """
    try:
        from pytrends.request import TrendReq
    except ImportError:
        logger.warning("pytrends not installed, skipping Google Trends ingestion")
        return {"rows": 0, "error": "pytrends not installed"}

    ds = await _ensure_dataset(db)
    regions = (await db.execute(select(Region))).scalars().all()
    region_map = {r.name: r for r in regions}

    rows = 0
    timeframe = f"today {lookback_weeks * 7}-d"

    try:
        pytrends = TrendReq(hl="en-US", tz=330)  # IST = UTC+5:30

        for city_name, queries in CITY_QUERIES.items():
            region = region_map.get(city_name)
            if not region:
                continue

            geo = CITY_GEO.get(city_name, "IN")

            for feature_key, query_text in queries.items():
                try:
                    pytrends.build_payload(
                        [query_text],
                        timeframe=timeframe,
                        geo=geo,
                    )
                    df = pytrends.interest_over_time()

                    if df.empty:
                        logger.debug("No trends data for %s/%s", city_name, query_text)
                        continue

                    for ts_idx, row in df.iterrows():
                        val = float(row[query_text])
                        ts = ts_idx.to_pydatetime().replace(tzinfo=timezone.utc)

                        db.add(Feature(
                            region_id=region.id,
                            dataset_id=ds.id,
                            feature_key=feature_key,
                            ts=ts,
                            value=val,
                        ))
                        rows += 1

                    logger.info("Google Trends %s/%s: %d data points",
                                city_name, feature_key, len(df))

                except Exception as e:
                    logger.warning("Trends fetch failed for %s/%s: %s",
                                   city_name, query_text, e)
                    continue

    except Exception as e:
        logger.warning("Google Trends ingestion failed: %s", e)
        return {"rows": rows, "error": str(e)}

    if rows > 0:
        ds.freshness = datetime.now(timezone.utc)
        await db.commit()

    logger.info("Google Trends ingestion complete: %d rows", rows)
    return {"rows": rows, "dataset_id": ds.id}
