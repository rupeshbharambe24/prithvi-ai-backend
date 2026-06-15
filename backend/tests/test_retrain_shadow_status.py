import pytest
from sqlalchemy import text
from backend.app.db.session import AsyncSessionLocal
from backend.app.services.ml.registry import register_model


@pytest.mark.asyncio
async def test_register_model_defaults_to_shadow():
    async with AsyncSessionLocal() as db:
        mv = await register_model(
            db, target="test_shadow", algo="gbr", params={}, metrics={"skill_score": 0.1},
            model_obj={"x": 1}, status="shadow",
        )
        row_status = (await db.execute(text("SELECT status FROM model_versions WHERE id=:i"), {"i": mv.id})).scalar()
        assert row_status == "shadow"
