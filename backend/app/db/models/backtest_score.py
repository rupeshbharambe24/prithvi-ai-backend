from __future__ import annotations

from datetime import datetime
from sqlalchemy import Integer, String, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base
from ..types import json_type


class BacktestScore(Base):
    __tablename__ = "backtest_scores"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    target: Mapped[str] = mapped_column(String(50), index=True)
    region_id: Mapped[int] = mapped_column(Integer, index=True)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    metrics_json = mapped_column(json_type(), nullable=True)
