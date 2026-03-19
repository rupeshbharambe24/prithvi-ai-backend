from __future__ import annotations

import hashlib
import math
from typing import List

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text, select

from ...db.models import KGNode


DIM = 384


def pseudo_embed(text_in: str) -> List[float]:
    # Deterministic hash-based embedding in [0,1]
    h = hashlib.sha256(text_in.encode("utf-8")).digest()
    vals = []
    for i in range(DIM):
        b = h[i % len(h)]
        # simple LCG mixing
        val = ((b * (i + 1)) % 251) / 250.0
        vals.append(val)
    return vals


async def embed_all_nodes(db: AsyncSession) -> int:
    nodes = (await db.execute(select(KGNode))).scalars().all()
    count = 0
    for n in nodes:
        vec = pseudo_embed(f"{n.type}:{n.label}")
        # store via pgvector literal
        await db.execute(
            text("UPDATE kg_nodes SET embedding = :vec::vector WHERE id=:id"),
            {"vec": f"[{','.join(str(v) for v in vec)}]", "id": n.id},
        )
        count += 1
    await db.commit()
    return count
