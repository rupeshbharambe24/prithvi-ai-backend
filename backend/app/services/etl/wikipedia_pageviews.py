"""Wikipedia pageviews health-interest ingestion.

A free, reliable, no-API-key behavioral disease-surveillance proxy and a robust
alternative to Google Trends (which Google blocks via pytrends). Validated in the
epidemiology literature — Wikipedia article pageviews nowcast disease activity
(McIver & Brownstein, 2014, PLoS Comp Bio).

Uses the Wikimedia REST pageviews API. Pageviews are national (en.wikipedia), so
the same daily series is applied to every region as a national covariate.
Writes the same feature keys the disease/surge targets already consume
(dengue_search, heatstroke_search, hospital_search, respiratory_search).
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import List, Tuple

import httpx
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ...db.models import Dataset, Feature, Region

logger = logging.getLogger(__name__)

WIKI_DATASET_NAME = "wikipedia_pageviews"
WIKI_BASE = (
    "https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/"
    "en.wikipedia.org/all-access/user"
)
# Wikimedia policy requires a descriptive User-Agent.
USER_AGENT = "PRITHVI-AI/1.0 (climate-health research; software@biopanscientific.com)"

# feature_key -> Wikipedia article title (same keys disease/surge targets read).
ARTICLE_MAP = {
    "dengue_search": "Dengue_fever",
    "heatstroke_search": "Heat_stroke",
    "hospital_search": "Emergency_department",
    "respiratory_search": "Air_pollution",
}


async def _ensure_dataset(db: AsyncSession) -> Dataset:
    res = await db.execute(select(Dataset).where(Dataset.name == WIKI_DATASET_NAME))
    ds = res.scalar_one_or_none()
    if not ds:
        ds = Dataset(
            name=WIKI_DATASET_NAME, source="wikimedia-pageviews",
            license="CC0", spatial="national", temporal="daily",
        )
        db.add(ds)
        await db.flush()
    return ds


async def _fetch_pageviews(
    client: httpx.AsyncClient, article: str, start: str, end: str, attempts: int = 3
) -> List[Tuple[str, float]]:
    """Daily pageviews for one article. Returns [(YYYY-MM-DD, views)]."""
    url = f"{WIKI_BASE}/{article}/daily/{start}/{end}"
    delay = 1.0
    for i in range(attempts):
        try:
            r = await client.get(url, headers={"User-Agent": USER_AGENT})
            if r.status_code == 200:
                out: List[Tuple[str, float]] = []
                for it in r.json().get("items", []):
                    ts = it.get("timestamp", "")  # YYYYMMDDHH
                    views = it.get("views")
                    if len(ts) >= 8 and views is not None:
                        out.append((f"{ts[0:4]}-{ts[4:6]}-{ts[6:8]}", float(views)))
                return out
            if r.status_code == 404:
                logger.warning("wikipedia_article_not_found: %s", article)
                return []
            logger.warning("wikipedia_status=%s article=%s (attempt %d/%d)", r.status_code, article, i + 1, attempts)
            await asyncio.sleep(delay)
            delay = min(delay * 2, 8.0)
        except httpx.HTTPError as e:
            logger.warning("wikipedia_fetch_error article=%s: %s (attempt %d/%d)", article, e, i + 1, attempts)
            await asyncio.sleep(delay)
            delay = min(delay * 2, 8.0)
    return []


async def flow_wikipedia_pageviews_ingest(db: AsyncSession, lookback_days: int = 120) -> dict:
    """Ingest Wikipedia health-topic pageviews as search-interest proxies."""
    ds = await _ensure_dataset(db)
    regions = (await db.execute(select(Region))).scalars().all()
    if not regions:
        return {"rows": 0, "dataset_id": ds.id}

    end = datetime.now(timezone.utc)
    start = end - timedelta(days=lookback_days)
    start_str, end_str = start.strftime("%Y%m%d"), end.strftime("%Y%m%d")

    rows = 0
    async with httpx.AsyncClient(timeout=30) as client:
        for feature_key, article in ARTICLE_MAP.items():
            series = await _fetch_pageviews(client, article, start_str, end_str)
            if not series:
                continue
            min_day = series[0][0]
            for reg in regions:
                # Idempotent refresh for this region + feature in the window.
                await db.execute(
                    text("DELETE FROM features WHERE region_id=:r AND feature_key=:k AND ts >= :mn"),
                    {"r": reg.id, "k": feature_key, "mn": min_day},
                )
                for date_str, views in series:
                    day = datetime(int(date_str[:4]), int(date_str[5:7]), int(date_str[8:10]), tzinfo=timezone.utc)
                    db.add(Feature(
                        region_id=reg.id,
                        feature_key=feature_key, ts=day, value=views,
                    ))
                    rows += 1
            logger.info("wikipedia %s (%s): %d days x %d regions", feature_key, article, len(series), len(regions))
            await asyncio.sleep(0.3)

    await db.commit()
    logger.info("Wikipedia pageviews ingestion complete: %d rows", rows)
    return {"rows": rows, "dataset_id": ds.id}
