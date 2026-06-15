import pytest
from sqlalchemy import text
from backend.app.db.session import AsyncSessionLocal


@pytest.mark.asyncio
async def test_model_versions_has_status_column():
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(text("PRAGMA table_info(model_versions)"))).fetchall()
        col_names = {r[1] for r in rows}
        assert "status" in col_names
