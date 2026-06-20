import pytest

from backend.app.db.session import AsyncSessionLocal
from backend.app.services.ml.train import train_target


@pytest.mark.asyncio
async def test_pm25_uses_lagged_pm25_without_leakage():
    """pm25 should learn from LAGGED pm25 (autoregressive) but never from the
    contemporaneous value or a current-including rolling mean (that would leak
    the target into the features and produce fake-perfect skill)."""
    async with AsyncSessionLocal() as db:
        ensemble = await train_target(db, "pm25", 1)
        assert ensemble is not None, "pm25 training returned None (insufficient data?)"
        names = ensemble.feature_names

        # Autoregressive signal is present.
        assert any(n.startswith("pm25_obs_lag") for n in names), names

        # Leakage guards: the raw value and current-including rolling are excluded.
        assert "pm25_obs" not in names, "raw contemporaneous pm25_obs leaks the target"
        assert not any(n.startswith("pm25_obs_roll") for n in names), "rolling includes current -> leak"

        # Legitimate model, not a leak (a leak would score ~1.0).
        skill = ensemble.metrics["skill_score"]
        assert skill < 0.999, f"suspiciously perfect skill={skill} (leak?)"


@pytest.mark.asyncio
async def test_pm25_autoregressive_beats_persistence_on_variable_data():
    """Where the test window actually varies (persistence_rmse > 0), the
    autoregressive model should beat the persistence baseline (positive skill)
    for at least one region — confirming the AR features add real value."""
    async with AsyncSessionLocal() as db:
        beat = False
        for rid in (1, 2, 3):
            ens = await train_target(db, "pm25", rid)
            if ens and ens.metrics["persistence_rmse"] > 1.0 and ens.metrics["skill_score"] > 0:
                beat = True
                break
        assert beat, "autoregressive pm25 did not beat persistence on any region with variable data"
