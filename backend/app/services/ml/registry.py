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
