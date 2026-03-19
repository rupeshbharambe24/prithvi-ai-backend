"""Paper discovery from OpenAlex API.

OpenAlex: Free, no API key, ~260M papers, 10 req/s.
Searches for climate-health research papers relevant to India.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ...db.models import Evidence

logger = logging.getLogger(__name__)

OPENALEX_BASE = "https://api.openalex.org"

# Climate-health search queries for India
SEARCH_QUERIES = [
    "climate heat mortality India",
    "dengue climate temperature India",
    "PM2.5 respiratory hospital India",
    "heat wave public health South Asia",
    "malaria climate change India",
    "air pollution health outcomes urban India",
    "wet bulb temperature heat stress",
    "flood waterborne disease India",
    "climate adaptation health infrastructure",
    "extreme weather emergency department visits",
]


async def discover_papers(
    db: AsyncSession,
    max_papers: int = 50,
    min_year: int = 2015,
) -> Dict[str, Any]:
    """Discover and store relevant papers from OpenAlex.

    Returns dict with counts of papers found and stored.
    """
    # Check existing DOIs to avoid duplicates
    existing_dois = set()
    res = await db.execute(text("SELECT doi FROM evidence WHERE doi IS NOT NULL"))
    for row in res.fetchall():
        if row[0]:
            existing_dois.add(row[0].lower())

    papers_stored = 0
    papers_found = 0

    async with httpx.AsyncClient(timeout=30) as client:
        for query in SEARCH_QUERIES:
            if papers_stored >= max_papers:
                break

            logger.info("OpenAlex search: %s", query)
            try:
                results = await _search_openalex(client, query, min_year)
                papers_found += len(results)

                for paper in results:
                    if papers_stored >= max_papers:
                        break

                    doi = paper.get("doi", "")
                    if doi and doi.lower() in existing_dois:
                        continue

                    # Extract abstract from inverted index
                    abstract = _reconstruct_abstract(paper.get("abstract_inverted_index", {}))

                    # Compute strength from citation count
                    cited_by = paper.get("cited_by_count", 0)
                    strength = min(1.0, cited_by / 100)

                    # Extract concepts/topics
                    concepts = [c.get("display_name", "") for c in paper.get("concepts", [])[:5]]
                    topics = [t.get("display_name", "") for t in paper.get("topics", [])[:3]]
                    tags = list(set(concepts + topics))[:8]

                    # Get publication year
                    year = paper.get("publication_year")
                    title = paper.get("title", "")

                    if not title or not abstract:
                        continue

                    # Store in evidence table
                    evidence = Evidence(
                        doi=doi or None,
                        url=paper.get("id", ""),  # OpenAlex URL
                        title=title,
                        abstract=abstract[:2000],  # Truncate very long abstracts
                        year=year,
                        source="openalex",
                        strength=round(strength, 3),
                        quality="peer-reviewed" if paper.get("type") == "article" else "preprint",
                        summary_md=f"**{title}** ({year}). Cited by {cited_by}.",
                        tags=tags,
                        meta_json={
                            "openalex_id": paper.get("id"),
                            "cited_by_count": cited_by,
                            "type": paper.get("type"),
                            "authors": [a.get("author", {}).get("display_name", "")
                                        for a in paper.get("authorships", [])[:5]],
                            "processed": False,
                        },
                    )
                    db.add(evidence)
                    papers_stored += 1
                    if doi:
                        existing_dois.add(doi.lower())

                # Rate limiting courtesy
                await asyncio.sleep(0.5)

            except Exception as e:
                logger.warning("openalex_search_failed for '%s': %s", query, e)
                continue

    await db.commit()
    logger.info("Paper discovery complete: found=%d, stored=%d", papers_found, papers_stored)
    return {"papers_found": papers_found, "papers_stored": papers_stored}


async def _search_openalex(
    client: httpx.AsyncClient,
    query: str,
    min_year: int,
) -> List[Dict]:
    """Search OpenAlex works API."""
    params = {
        "search": query,
        "filter": f"publication_year:>{min_year-1},has_abstract:true",
        "per_page": 15,
        "sort": "cited_by_count:desc",
        "mailto": "research@example.org",  # polite pool
    }
    resp = await client.get(f"{OPENALEX_BASE}/works", params=params)
    resp.raise_for_status()
    return resp.json().get("results", [])


def _reconstruct_abstract(inverted_index: Dict[str, List[int]] | None) -> str:
    """Reconstruct abstract text from OpenAlex inverted index format."""
    if not inverted_index:
        return ""
    # inverted_index: {"word": [positions], ...}
    word_positions = []
    for word, positions in inverted_index.items():
        for pos in positions:
            word_positions.append((pos, word))
    word_positions.sort(key=lambda x: x[0])
    return " ".join(w for _, w in word_positions)
