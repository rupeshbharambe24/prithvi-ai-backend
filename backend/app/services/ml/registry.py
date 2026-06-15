from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Dict

from joblib import dump, load
from sqlalchemy.ext.asyncio import AsyncSession

from ...db.models import ModelVersion
from ...config import get_settings


def _artifacts_root() -> str:
    return get_settings().ml_artifacts_root


async def register_model(
    db: AsyncSession, target: str, algo: str, params: Dict[str, Any], metrics: Dict[str, Any], model_obj: Any
) -> ModelVersion:
    root = _artifacts_root()
    os.makedirs(root, exist_ok=True)
    version = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    path = os.path.join(root, target, version)
    os.makedirs(path, exist_ok=True)
    model_path = os.path.join(path, "model.joblib")
    dump(model_obj, model_path)
    mv = ModelVersion(
        target=target,
        algo=algo,
        params_json=params,
        created_at=datetime.now(timezone.utc),
        path=model_path,
        metrics_json=metrics,
    )
    db.add(mv)
    await db.flush()
    await db.commit()
    return mv


async def latest_model(db: AsyncSession, target: str) -> ModelVersion | None:
    from sqlalchemy import select, desc

    res = await db.execute(
        select(ModelVersion).where(ModelVersion.target == target).order_by(desc(ModelVersion.created_at)).limit(1)
    )
    return res.scalars().first()


def load_artifact(path: str):
    return load(path)


async def active_model(db: AsyncSession, target: str) -> ModelVersion | None:
    """Return the live model for a target.

    Prefers the newest status='active' row; falls back to the newest row of any
    status (back-compat with versions created before the status column existed).
    """
    from sqlalchemy import select, desc

    res = await db.execute(
        select(ModelVersion)
        .where(ModelVersion.target == target, ModelVersion.status == "active")
        .order_by(desc(ModelVersion.created_at))
        .limit(1)
    )
    mv = res.scalars().first()
    if mv is not None:
        return mv
    return await latest_model(db, target)


def _skill(mv: ModelVersion | None) -> float:
    if mv is None or not isinstance(mv.metrics_json, dict):
        return float("-inf")
    val = mv.metrics_json.get("skill_score")
    return float(val) if val is not None else float("-inf")


async def promote_if_better(db: AsyncSession, target: str) -> bool:
    """Champion/challenger: promote newest shadow model only if its skill_score
    is >= the current active model. Otherwise reject the challenger.

    Returns True if a promotion happened. Fail-safe: on any error, keeps the
    current champion and returns False.
    """
    from sqlalchemy import select, desc

    try:
        chall = (await db.execute(
            select(ModelVersion)
            .where(ModelVersion.target == target, ModelVersion.status == "shadow")
            .order_by(desc(ModelVersion.created_at))
            .limit(1)
        )).scalars().first()
        if chall is None:
            return False

        champ = (await db.execute(
            select(ModelVersion)
            .where(ModelVersion.target == target, ModelVersion.status == "active")
            .order_by(desc(ModelVersion.created_at))
            .limit(1)
        )).scalars().first()

        if _skill(chall) >= _skill(champ):
            if champ is not None:
                champ.status = "archived"
            chall.status = "active"
            await db.commit()
            return True
        else:
            chall.status = "rejected"
            await db.commit()
            return False
    except Exception:
        await db.rollback()
        return False
