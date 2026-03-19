import pytest
from httpx import AsyncClient

from backend.app.main import app


@pytest.mark.asyncio
async def test_fairness_and_drift_endpoints():
    async with AsyncClient(app=app, base_url="http://test") as client:
        r = await client.post(
            "/api/v1/auth/login",
            json={"email": "admin@example.com", "password": "Admin123!"},
        )
        cookies = r.cookies
        csrf = cookies.get("csrf_token")
        # Fairness
        res = await client.post("/api/v1/fairness/evaluate?target=heat", headers={"X-CSRF-Token": csrf}, cookies=cookies)
        assert res.status_code == 200
        # Latest
        res2 = await client.get("/api/v1/fairness/latest?target=heat", cookies=cookies)
        assert res2.status_code == 200
        f = res2.json()
        assert "metrics" in f and "mae" in f["metrics"] and "coverageRate" in f["metrics"]
        # Drift
        res3 = await client.post("/api/v1/qa/drift?featureKey=heat_index", headers={"X-CSRF-Token": csrf}, cookies=cookies)
        assert res3.status_code == 200
        d = res3.json()
        assert 0.0 <= d.get("psi", 0.0) <= 1.0
        res4 = await client.get("/api/v1/qa/drift/latest?featureKey=heat_index", cookies=cookies)
        assert res4.status_code == 200

