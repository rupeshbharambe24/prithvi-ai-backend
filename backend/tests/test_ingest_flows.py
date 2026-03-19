import pytest
from backend.app.db.session import AsyncSessionLocal
from backend.app.services.etl.era5 import flow_era5_ingest
from backend.app.services.etl.population import flow_population_vulnerability
from backend.app.services.etl.who_gho import flow_who_gho_ingest
from sqlalchemy import text
from datetime import datetime, timezone


@pytest.mark.asyncio
async def test_ingest_flows_write_rows():
    async with AsyncSessionLocal() as db:
        await flow_era5_ingest(db, datetime(2024, 7, 1, tzinfo=timezone.utc), datetime(2024, 7, 3, tzinfo=timezone.utc))
        await flow_who_gho_ingest(db)
        await flow_population_vulnerability(db)

        obs = (await db.execute(text("SELECT COUNT(*) FROM observations"))).scalar()
        feats = (await db.execute(text("SELECT COUNT(*) FROM features"))).scalar()
        assert obs >= 30
        assert feats >= 30
        # Include heat_index rows
        hi = (await db.execute(text("SELECT COUNT(*) FROM features WHERE feature_key='heat_index'"))).scalar()
        assert hi >= 1
        # Ingest runs and versions exist
        runs = (await db.execute(text("SELECT COUNT(*) FROM ingest_runs WHERE status='success'"))).scalar()
        vers = (await db.execute(text("SELECT COUNT(*) FROM dataset_versions"))).scalar()
        assert runs >= 1 and vers >= 1

