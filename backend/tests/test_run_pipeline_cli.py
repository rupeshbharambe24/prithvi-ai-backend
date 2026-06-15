import pytest
from backend.app.scripts.run_pipeline import run


@pytest.mark.asyncio
async def test_cli_daily_returns_summary():
    out = await run("daily", do_ingest=False)
    assert isinstance(out, dict)
    assert "forecast" in out


@pytest.mark.asyncio
async def test_cli_score_only():
    out = await run("score")
    assert isinstance(out, dict)
