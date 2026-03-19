from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from ...deps.auth import require_roles
from ...db.models.user import UserRole
from ...db.session import get_db
from ...config import get_settings


router = APIRouter(prefix="/evidence", tags=["evidence"])


@router.get("")
async def list_evidence(riskId: int | None = None, _=Depends(require_roles(UserRole.VIEWER)), db: AsyncSession = Depends(get_db)):
    settings = get_settings()

    if riskId is None:
        # Return all evidence
        rows = (await db.execute(text("""
            SELECT id, doi, url, title, summary_md, strength, quality, year, tags
            FROM evidence ORDER BY id
        """))).fetchall()
        items = [
            {
                "id": r[0], "doi": r[1], "url": r[2], "title": r[3],
                "year": r[7], "strength": r[5], "quality": r[6],
                "summaryMd": r[4], "tags": _parse_tags(r[8]),
            }
            for r in rows
        ]
        return {"items": items}

    # Find Evidence nodes connected via SUPPORTED_BY edges
    if settings.local_mode:
        rows = (await db.execute(text("""
            SELECT e.id, e.doi, e.url, e.title, e.summary_md, e.strength, e.quality, e.year, e.tags
            FROM kg_edges ke
            JOIN kg_nodes kn ON kn.id = ke.dst AND kn.type='Evidence'
            JOIN evidence e ON e.id = CAST(json_extract(kn.props_json, '$.evidence_id') AS INTEGER)
            WHERE ke.src=:rid AND ke.rel='SUPPORTED_BY'
        """), {"rid": riskId})).fetchall()
    else:
        rows = (await db.execute(text("""
            SELECT e.id, e.doi, e.url, e.title, e.summary_md, e.strength, e.quality, e.year, e.tags
            FROM kg_edges ke
            JOIN kg_nodes kn ON kn.id = ke.dst AND kn.type='Evidence'
            JOIN evidence e ON e.id = (kn.props_json->>'evidence_id')::int
            WHERE ke.src=:rid AND ke.rel='SUPPORTED_BY'
        """), {"rid": riskId})).fetchall()

    items = [
        {
            "id": r[0], "doi": r[1], "url": r[2], "title": r[3],
            "year": r[7], "strength": r[5], "quality": r[6],
            "summaryMd": r[4], "tags": _parse_tags(r[8]),
        }
        for r in rows
    ]
    return {"items": items}


@router.get("/list")
async def evidence_list(_=Depends(require_roles(UserRole.VIEWER)), db: AsyncSession = Depends(get_db)):
    """Return all evidence rows without any filter."""
    rows = (await db.execute(text("""
        SELECT id, doi, url, title, summary_md, strength, quality, year, tags
        FROM evidence ORDER BY id
    """))).fetchall()
    items = [
        {
            "id": r[0], "doi": r[1], "url": r[2], "title": r[3],
            "year": r[7], "strength": r[5], "quality": r[6],
            "summaryMd": r[4], "tags": _parse_tags(r[8]),
        }
        for r in rows
    ]
    return {"items": items}


def _parse_tags(tags_val) -> list:
    if tags_val is None:
        return []
    if isinstance(tags_val, list):
        return tags_val
    if isinstance(tags_val, str):
        import json
        try:
            return json.loads(tags_val)
        except Exception:
            return []
    return []
