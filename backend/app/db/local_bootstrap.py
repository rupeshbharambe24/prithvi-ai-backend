from __future__ import annotations

from sqlalchemy import text

from .base import Base
from . import models as _models  # noqa: F401
from .session import engine
from ..config import get_settings


async def init_local_database() -> None:
    settings = get_settings()
    if not settings.local_mode:
        return

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS forecasts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    region_id INTEGER NOT NULL,
                    type TEXT NOT NULL,
                    target_date DATETIME NOT NULL,
                    horizon INTEGER NOT NULL,
                    value REAL NOT NULL,
                    p05 REAL,
                    p95 REAL,
                    drivers_json JSON,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        )
