from __future__ import annotations

import csv
import json
import os
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from ...config import get_settings


async def import_fixtures(db: AsyncSession, base_path: str) -> dict:
    nodes_path = os.path.join(base_path, "kg_nodes.json")
    edges_path = os.path.join(base_path, "kg_edges.json")
    evidence_path = os.path.join(base_path, "evidence.csv")

    settings = get_settings()
    counts = {"evidence": 0, "nodes": 0, "edges": 0}

    # Evidence
    if os.path.exists(evidence_path):
        with open(evidence_path, "r", encoding="utf-8") as f:
            rdr = csv.DictReader(f)
            for row in rdr:
                if settings.local_mode:
                    await db.execute(
                        text("""
                            INSERT INTO evidence (doi,url,title,abstract,year,source,strength,quality,summary_md,tags,meta_json)
                            VALUES (:doi,:url,:title,:abstract,:year,:source,:strength,:quality,:summary_md,:tags,:meta)
                        """),
                        {
                            "doi": row.get("doi"),
                            "url": row.get("url"),
                            "title": row.get("title"),
                            "abstract": row.get("abstract"),
                            "year": int(row["year"]) if row.get("year") else None,
                            "source": row.get("source"),
                            "strength": float(row["strength"]) if row.get("strength") else None,
                            "quality": row.get("quality"),
                            "summary_md": row.get("summary_md"),
                            "tags": json.dumps(row.get("tags", "").split("|") if row.get("tags") else []),
                            "meta": json.dumps({}),
                        },
                    )
                else:
                    await db.execute(
                        text("""
                            INSERT INTO evidence (doi,url,title,abstract,year,source,strength,quality,summary_md,tags,meta_json)
                            VALUES (:doi,:url,:title,:abstract,:year,:source,:strength,:quality,:summary_md,:tags, cast(:meta as jsonb))
                        """),
                        {
                            "doi": row.get("doi"),
                            "url": row.get("url"),
                            "title": row.get("title"),
                            "abstract": row.get("abstract"),
                            "year": int(row["year"]) if row.get("year") else None,
                            "source": row.get("source"),
                            "strength": float(row["strength"]) if row.get("strength") else None,
                            "quality": row.get("quality"),
                            "summary_md": row.get("summary_md"),
                            "tags": (row.get("tags", " ").split("|") if row.get("tags") else None),
                            "meta": json.dumps({}),
                        },
                    )
                counts["evidence"] += 1

    # KG Nodes
    if os.path.exists(nodes_path):
        nodes = json.load(open(nodes_path, "r", encoding="utf-8"))
        for n in nodes:
            if settings.local_mode:
                await db.execute(
                    text("INSERT OR IGNORE INTO kg_nodes (id, type, label, props_json) VALUES (:id,:type,:label,:props)"),
                    {"id": n["id"], "type": n["type"], "label": n["label"], "props": json.dumps(n.get("props", {}))},
                )
            else:
                await db.execute(
                    text("INSERT INTO kg_nodes (id, type, label, props_json) VALUES (:id,:type,:label,cast(:props as jsonb)) ON CONFLICT (id) DO NOTHING"),
                    {"id": n["id"], "type": n["type"], "label": n["label"], "props": json.dumps(n.get("props", {}))},
                )
            counts["nodes"] += 1

    # KG Edges
    if os.path.exists(edges_path):
        edges = json.load(open(edges_path, "r", encoding="utf-8"))
        for e in edges:
            if settings.local_mode:
                await db.execute(
                    text("INSERT INTO kg_edges (src,dst,rel,weight,props_json) VALUES (:src,:dst,:rel,:weight,:props)"),
                    {
                        "src": e["src"],
                        "dst": e["dst"],
                        "rel": e.get("rel", "ASSOCIATED_WITH"),
                        "weight": float(e.get("weight", 1.0)),
                        "props": json.dumps(e.get("props", {})),
                    },
                )
            else:
                await db.execute(
                    text("INSERT INTO kg_edges (src,dst,rel,weight,props_json) VALUES (:src,:dst,:rel,:weight,cast(:props as jsonb))"),
                    {
                        "src": e["src"],
                        "dst": e["dst"],
                        "rel": e.get("rel", "ASSOCIATED_WITH"),
                        "weight": float(e.get("weight", 1.0)),
                        "props": json.dumps(e.get("props", {})),
                    },
                )
            counts["edges"] += 1

    await db.commit()
    return {"imported": counts}
