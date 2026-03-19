import pytest
from httpx import AsyncClient

from backend.app.main import app


@pytest.mark.asyncio
async def test_kg_import_embed_search_and_evidence():
    async with AsyncClient(app=app, base_url="http://test") as client:
        r = await client.post(
            "/api/v1/auth/login",
            json={"email": "admin@example.com", "password": "Admin123!"},
        )
        cookies = r.cookies
        # Import
        res = await client.post("/api/v1/kg/import", cookies=cookies)
        assert res.status_code == 200
        # Embed
        res = await client.post("/api/v1/kg/embed", cookies=cookies)
        assert res.status_code == 200
        # Search
        res = await client.get("/api/v1/kg/search?q=heat", cookies=cookies)
        assert res.status_code == 200
        data = res.json()
        assert len(data.get("nodes", [])) >= 1
        # Evidence cards
        evid = await client.get("/api/v1/evidence?riskId=2", cookies=cookies)
        assert evid.status_code == 200
        ejson = evid.json()
        assert "items" in ejson and isinstance(ejson["items"], list)
        if ejson["items"]:
            item = ejson["items"][0]
            assert any([item.get("doi"), item.get("url")])
            assert "summaryMd" in item

