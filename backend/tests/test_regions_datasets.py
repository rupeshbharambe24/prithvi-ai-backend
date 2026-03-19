import pytest
from httpx import AsyncClient

from backend.app.main import app


@pytest.mark.asyncio
async def test_regions_and_datasets_seeded():
    async with AsyncClient(app=app, base_url="http://test") as client:
        # Login as viewer
        r = await client.post(
            "/api/v1/auth/login",
            json={"email": "viewer@example.com", "password": "Viewer123!"},
        )
        assert r.status_code == 200
        cookies = r.cookies

        # Regions
        res = await client.get("/api/v1/regions/", cookies=cookies)
        assert res.status_code == 200
        regions = res.json()
        assert isinstance(regions, list) and len(regions) >= 1
        item = regions[0]
        assert "center" in item and isinstance(item["center"], dict)
        assert "lat" in item["center"] and "lng" in item["center"]
        assert "bounds" in item and isinstance(item["bounds"], list)

        # Datasets
        res2 = await client.get("/api/v1/datasets/", cookies=cookies)
        assert res2.status_code == 200
        datasets = res2.json()
        assert isinstance(datasets, list) and len(datasets) >= 1
        first_id = datasets[0]["id"]
        res3 = await client.get(f"/api/v1/datasets/{first_id}/lineage", cookies=cookies)
        assert res3.status_code == 200
        lin = res3.json()
        assert "versions" in lin and "ingestRuns" in lin

