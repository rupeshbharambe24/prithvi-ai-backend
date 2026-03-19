from __future__ import annotations

from typing import Dict

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from ...config import get_settings


async def search(db: AsyncSession, q: str, type_filter: str | None = None, limit: int = 10) -> Dict:
    settings = get_settings()
    params: dict = {"q": f"%{q}%", "limit": limit}
    type_clause = " AND type=:type" if type_filter else ""
    if type_filter:
        params["type"] = type_filter

    if settings.local_mode:
        # SQLite: use LIKE (case-insensitive by default for ASCII)
        sql = f"""
            SELECT id, type, label, props_json, 1.0 as score FROM kg_nodes
            WHERE (label LIKE :q OR CAST(props_json AS TEXT) LIKE :q){type_clause}
            ORDER BY score DESC
            LIMIT :limit
        """
        res = await db.execute(text(sql), params)
    else:
        # PostgreSQL: ILIKE + optional vector search
        from .embed import pseudo_embed
        vec = pseudo_embed(q)
        sql = f"""
            SELECT id, type, label, props_json, 1.0 as score FROM kg_nodes
            WHERE (label ILIKE :q OR props_json::text ILIKE :q){type_clause}
            UNION ALL
            SELECT id, type, label, props_json, 1.0 - (embedding <-> :vec::vector) as score FROM kg_nodes
            WHERE embedding IS NOT NULL{type_clause}
            ORDER BY score DESC
            LIMIT :limit
        """
        try:
            res = await db.execute(text(sql), {**params, "vec": f"[{','.join(str(v) for v in vec)}]"})
        except Exception:
            # fallback text-only
            res = await db.execute(text(f"SELECT id,type,label,props_json,1.0 as score FROM kg_nodes WHERE (label ILIKE :q OR props_json::text ILIKE :q){type_clause} LIMIT :limit"), params)

    nodes = [dict(id=r[0], type=r[1], label=r[2], props=r[3], score=r[4]) for r in res.fetchall()]

    # Load edges among returned nodes
    ids = [n["id"] for n in nodes]
    if not ids:
        return {"nodes": [], "edges": []}

    if settings.local_mode:
        # SQLite: no ANY(), filter in Python
        placeholders = ",".join(str(i) for i in ids)
        edge_sql = f"SELECT id, src, dst, rel, weight FROM kg_edges WHERE src IN ({placeholders}) OR dst IN ({placeholders}) LIMIT 50"
        edges = (await db.execute(text(edge_sql))).fetchall()
    else:
        edge_sql = "SELECT id, src, dst, rel, weight FROM kg_edges WHERE src = ANY(:ids) OR dst = ANY(:ids) LIMIT 50"
        edges = (await db.execute(text(edge_sql), {"ids": ids})).fetchall()

    edges_out = [dict(id=e[0], src=e[1], dst=e[2], rel=e[3], weight=e[4]) for e in edges]
    return {"nodes": nodes, "edges": edges_out}
