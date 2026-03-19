from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Tuple

import numpy as np
import pandas as pd
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...db.models import Feature, Region


async def load_region_features(db: AsyncSession, region_id: int, start: datetime, end: datetime) -> pd.DataFrame:
    q = (
        select(Feature)
        .where(and_(Feature.region_id == region_id, Feature.ts >= start, Feature.ts <= end))
    )
    res = await db.execute(q)
    rows = []
    for f in res.scalars():
        # Ensure value is a proper float (SQLite may return strings)
        val = f.value
        if isinstance(val, str):
            val = val.strip("[]")
            try:
                val = float(val)
            except (ValueError, TypeError):
                continue
        elif val is None:
            continue
        else:
            val = float(val)

        # Parse ts (SQLite returns strings)
        ts = f.ts
        if isinstance(ts, str):
            ts = pd.Timestamp(ts[:19], tz="UTC")

        rows.append({"ts": ts, "feature_key": f.feature_key, "value": val})

    if not rows:
        # synthesize minimal set
        dates = pd.date_range(start.date(), end.date(), freq="D", tz=timezone.utc)
        df = pd.DataFrame({"ts": dates})
        for k, v in {"heat_index": 0.5, "t2m_max": 30.0, "prcp_sum": 1.0, "wet_bulb": 20.0, "wbgt": 22.0}.items():
            df[k] = v
        return df

    df = pd.DataFrame(rows)
    # Use last value for duplicates (same ts + feature_key)
    pivot = df.pivot_table(
        index="ts",
        columns="feature_key",
        values="value",
        aggfunc="last",
    ).reset_index().sort_values("ts")

    # Ensure all values are float
    for col in pivot.columns:
        if col != "ts":
            pivot[col] = pd.to_numeric(pivot[col], errors="coerce")

    return pivot


async def get_any_region_id(db: AsyncSession) -> int:
    r = (await db.execute(select(Region))).scalars().first()
    if not r:
        # create a stub region
        stub = Region(name="Stub Region", code="STUB")
        db.add(stub)
        await db.flush()
        await db.commit()
        return stub.id
    return r.id
