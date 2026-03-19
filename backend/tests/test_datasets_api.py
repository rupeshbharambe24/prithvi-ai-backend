import pytest
from httpx import AsyncClient

from backend.app.main import app


@pytest.mark.asyncio
async def test_datasets_api():
    async with AsyncClient(app=app, base_url="http://test") as client:
        r = await client.post(
            "/api/v1/auth/login",
            json={"email": "viewer@example.com", "password": "Viewer123!"},
        )
        cookies = r.cookies
        res = await client.get("/api/v1/datasets", cookies=cookies)
        assert res.status_code == 200
        data = res.json()
        assert isinstance(data, list) and len(data) >= 3
        ds_id = data[0]["id"]
        res2 = await client.get(f"/api/v1/datasets/{ds_id}/lineage", cookies=cookies)
        assert res2.status_code == 200
        lin = res2.json()
        assert "versions" in lin and isinstance(lin["versions"], list)
        assert "ingestRuns" in lin and isinstance(lin["ingestRuns"], list)

