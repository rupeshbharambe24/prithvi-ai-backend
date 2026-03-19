from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from ...deps.auth import require_roles
from ...db.models.user import UserRole
from ...db.session import get_db
from ...services.kg.importer import import_fixtures
from ...services.kg.embed import embed_all_nodes
from ...services.kg.search import search as kg_search


router = APIRouter(prefix="/kg", tags=["kg"])


@router.post("/import")
async def kg_import(_=Depends(require_roles(UserRole.ORG_ADMIN, UserRole.EPIDEMIOLOGIST)), db: AsyncSession = Depends(get_db)):
    base = "backend/backend/tests/fixtures"
    res = await import_fixtures(db, base)
    return res


@router.post("/embed")
async def kg_embed(_=Depends(require_roles(UserRole.ORG_ADMIN, UserRole.EPIDEMIOLOGIST)), db: AsyncSession = Depends(get_db)):
    count = await embed_all_nodes(db)
    return {"embedded": count}


@router.get("/search")
async def kg_search_api(q: str, type: str | None = None, limit: int = 10, _=Depends(require_roles(UserRole.VIEWER)), db: AsyncSession = Depends(get_db)):
    data = await kg_search(db, q, type_filter=type, limit=limit)
    return data


@router.get("/graph")
async def kg_graph(_=Depends(require_roles(UserRole.VIEWER)), db: AsyncSession = Depends(get_db)):
    """Return all KG nodes and edges for initial graph render."""
    node_rows = (await db.execute(text(
        "SELECT id, type, label, props_json FROM kg_nodes LIMIT 500"
    ))).fetchall()
    edge_rows = (await db.execute(text(
        "SELECT id, src, dst, rel, weight FROM kg_edges LIMIT 2000"
    ))).fetchall()

    nodes = [dict(id=r[0], type=r[1], label=r[2], props=r[3]) for r in node_rows]
    edges = [dict(id=e[0], src=e[1], dst=e[2], rel=e[3], weight=e[4]) for e in edge_rows]
    return {"nodes": nodes, "edges": edges}


@router.post("/discover")
async def kg_discover(
    max_papers: int = 50,
    _=Depends(require_roles(UserRole.ORG_ADMIN, UserRole.EPIDEMIOLOGIST)),
    db: AsyncSession = Depends(get_db),
):
    """Trigger paper discovery from OpenAlex + KG building."""
    from ...services.kg.builder import build_kg_from_papers
    result = await build_kg_from_papers(db, max_papers=max_papers)
    return result


@router.get("/stats")
async def kg_stats(_=Depends(require_roles(UserRole.VIEWER)), db: AsyncSession = Depends(get_db)):
    """Return KG node/edge counts by type."""
    node_counts = (await db.execute(text(
        "SELECT type, COUNT(*) FROM kg_nodes GROUP BY type ORDER BY COUNT(*) DESC"
    ))).fetchall()
    edge_counts = (await db.execute(text(
        "SELECT rel, COUNT(*) FROM kg_edges GROUP BY rel ORDER BY COUNT(*) DESC"
    ))).fetchall()
    total_nodes = sum(c[1] for c in node_counts)
    total_edges = sum(c[1] for c in edge_counts)
    evidence_count = (await db.execute(text("SELECT COUNT(*) FROM evidence"))).scalar()

    return {
        "total_nodes": total_nodes,
        "total_edges": total_edges,
        "evidence_papers": evidence_count,
        "nodes_by_type": {r[0]: r[1] for r in node_counts},
        "edges_by_relation": {r[0]: r[1] for r in edge_counts},
    }
