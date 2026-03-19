"""Knowledge Graph builder pipeline.

Orchestrates: paper discovery -> NER -> relation extraction -> KG nodes/edges.
Processes evidence papers to extract entities and build the knowledge graph.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, Set

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from .paper_discovery import discover_papers
from .ner_extractor import extract_entities, extract_relations, ALL_ENTITIES

logger = logging.getLogger(__name__)


async def build_kg_from_papers(
    db: AsyncSession,
    max_papers: int = 50,
) -> Dict[str, Any]:
    """Full KG building pipeline: discover papers, extract entities, build graph.

    Returns counts of nodes and edges created.
    """
    # Step 1: Discover papers from OpenAlex
    discovery = await discover_papers(db, max_papers=max_papers)
    logger.info("Discovery: %s", discovery)

    # Step 2: Process unprocessed evidence papers
    results = await process_evidence_papers(db)

    return {
        "discovery": discovery,
        "processing": results,
    }


async def process_evidence_papers(db: AsyncSession) -> Dict[str, Any]:
    """Process evidence papers: extract entities, relations, build KG."""
    # Get unprocessed papers
    rows = (await db.execute(text(
        "SELECT id, title, abstract, meta_json FROM evidence WHERE abstract IS NOT NULL"
    ))).fetchall()

    if not rows:
        return {"papers_processed": 0, "nodes_created": 0, "edges_created": 0}

    # Get existing KG node labels to avoid duplicates
    existing_nodes: Set[str] = set()
    node_rows = (await db.execute(text("SELECT label FROM kg_nodes"))).fetchall()
    for r in node_rows:
        existing_nodes.add(r[0].lower())

    # Get max node ID
    max_id_row = (await db.execute(text("SELECT COALESCE(MAX(id), 0) FROM kg_nodes"))).scalar()
    next_id = (max_id_row or 0) + 1

    # Get max edge ID
    max_edge_row = (await db.execute(text("SELECT COALESCE(MAX(id), 0) FROM kg_edges"))).scalar()
    next_edge_id = (max_edge_row or 0) + 1

    nodes_created = 0
    edges_created = 0
    papers_processed = 0
    entity_to_node_id: Dict[str, int] = {}

    # Map existing nodes
    existing_node_rows = (await db.execute(text("SELECT id, label FROM kg_nodes"))).fetchall()
    for r in existing_node_rows:
        entity_to_node_id[r[1].lower()] = r[0]

    for row in rows:
        evidence_id, title, abstract, meta_json = row

        # Check if already processed
        meta = meta_json if isinstance(meta_json, dict) else {}
        if isinstance(meta_json, str):
            try:
                meta = json.loads(meta_json)
            except (json.JSONDecodeError, TypeError):
                meta = {}
        if meta.get("processed"):
            continue

        # Combine title + abstract for NER
        full_text = f"{title}. {abstract}" if abstract else title

        # Extract entities
        entities = extract_entities(full_text)
        if not entities:
            continue

        # Create KG nodes for new entities
        for entity_text, entity_type in entities:
            if entity_text.lower() not in entity_to_node_id:
                await db.execute(text(
                    "INSERT INTO kg_nodes (id, type, label, props_json) VALUES (:id, :type, :label, :props)"
                ), {
                    "id": next_id,
                    "type": entity_type,
                    "label": entity_text.title(),
                    "props": json.dumps({"source": "ner", "from_evidence": evidence_id}),
                })
                entity_to_node_id[entity_text.lower()] = next_id
                existing_nodes.add(entity_text.lower())
                next_id += 1
                nodes_created += 1

        # Create Evidence node for this paper
        evidence_node_id = next_id
        await db.execute(text(
            "INSERT INTO kg_nodes (id, type, label, props_json) VALUES (:id, :type, :label, :props)"
        ), {
            "id": evidence_node_id,
            "type": "Evidence",
            "label": title[:100],
            "props": json.dumps({"evidence_id": evidence_id, "source": "openalex"}),
        })
        next_id += 1
        nodes_created += 1

        # Extract relations
        relations = extract_relations(full_text, entities)

        # Create KG edges for relations
        for src_text, rel, dst_text in relations:
            src_id = entity_to_node_id.get(src_text.lower())
            dst_id = entity_to_node_id.get(dst_text.lower())
            if src_id and dst_id:
                await db.execute(text(
                    "INSERT INTO kg_edges (id, src, dst, rel, weight, props_json) VALUES (:id, :src, :dst, :rel, :weight, :props)"
                ), {
                    "id": next_edge_id,
                    "src": src_id,
                    "dst": dst_id,
                    "rel": rel,
                    "weight": 0.7,
                    "props": json.dumps({"evidence_id": evidence_id}),
                })
                next_edge_id += 1
                edges_created += 1

        # Link evidence node to entity nodes via SUPPORTED_BY
        for entity_text, entity_type in entities:
            entity_node_id = entity_to_node_id.get(entity_text.lower())
            if entity_node_id:
                await db.execute(text(
                    "INSERT INTO kg_edges (id, src, dst, rel, weight, props_json) VALUES (:id, :src, :dst, :rel, :weight, :props)"
                ), {
                    "id": next_edge_id,
                    "src": entity_node_id,
                    "dst": evidence_node_id,
                    "rel": "SUPPORTED_BY",
                    "weight": 0.5,
                    "props": json.dumps({}),
                })
                next_edge_id += 1
                edges_created += 1

        # Mark paper as processed
        meta["processed"] = True
        await db.execute(text(
            "UPDATE evidence SET meta_json = :meta WHERE id = :id"
        ), {"meta": json.dumps(meta), "id": evidence_id})

        papers_processed += 1

    await db.commit()

    logger.info("KG built: %d papers -> %d nodes, %d edges", papers_processed, nodes_created, edges_created)
    return {
        "papers_processed": papers_processed,
        "nodes_created": nodes_created,
        "edges_created": edges_created,
    }
