"""Semantic embeddings for Knowledge Graph nodes.

Uses fastembed (ONNX-based) for real semantic embeddings.
Falls back to TF-IDF hashing if fastembed is unavailable.
"""
from __future__ import annotations

import hashlib
import logging
import math
from typing import List, Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text, select

from ...db.models import KGNode

logger = logging.getLogger(__name__)

DIM = 384
_model = None


def _get_model():
    """Lazy-load fastembed model (downloads ~33MB on first use)."""
    global _model
    if _model is not None:
        return _model
    try:
        from fastembed import TextEmbedding
        _model = TextEmbedding("BAAI/bge-small-en-v1.5")
        logger.info("Loaded fastembed BAAI/bge-small-en-v1.5 for semantic embeddings")
        return _model
    except Exception as e:
        logger.warning("fastembed unavailable (%s), using TF-IDF fallback", e)
        return None


def _tfidf_embed(text_in: str) -> List[float]:
    """TF-IDF inspired fallback: character n-gram hashing into a fixed vector.

    Not as good as a real model, but captures some lexical similarity
    (unlike the old SHA256 approach which was purely random).
    """
    vec = [0.0] * DIM
    text_lower = text_in.lower().strip()
    if not text_lower:
        return vec

    # Character trigram hashing with TF weighting
    trigrams = [text_lower[i:i+3] for i in range(len(text_lower) - 2)]
    if not trigrams:
        trigrams = [text_lower]

    for gram in trigrams:
        h = int(hashlib.md5(gram.encode()).hexdigest(), 16)
        idx = h % DIM
        vec[idx] += 1.0

    # L2 normalize
    norm = math.sqrt(sum(v * v for v in vec))
    if norm > 0:
        vec = [v / norm for v in vec]

    return vec


def embed_text(text_in: str) -> List[float]:
    """Generate a semantic embedding for the given text.

    Uses fastembed (real transformer model) if available,
    falls back to character n-gram TF-IDF hashing.
    """
    model = _get_model()
    if model is not None:
        try:
            embeddings = list(model.embed([text_in]))
            return embeddings[0].tolist()
        except Exception as e:
            logger.debug("fastembed failed for text, falling back: %s", e)

    return _tfidf_embed(text_in)


async def embed_all_nodes(db: AsyncSession) -> int:
    """Embed all KG nodes with semantic vectors."""
    nodes = (await db.execute(select(KGNode))).scalars().all()
    count = 0
    for n in nodes:
        label_text = f"{n.type}: {n.label}"
        vec = embed_text(label_text)
        await db.execute(
            text("UPDATE kg_nodes SET embedding = :vec::vector WHERE id=:id"),
            {"vec": f"[{','.join(str(v) for v in vec)}]", "id": n.id},
        )
        count += 1
    await db.commit()
    logger.info("Embedded %d KG nodes with semantic vectors", count)
    return count


def similarity(a: List[float], b: List[float]) -> float:
    """Cosine similarity between two embedding vectors."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)
