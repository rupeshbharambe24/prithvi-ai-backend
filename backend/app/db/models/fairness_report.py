from __future__ import annotations

from datetime import datetime
from sqlalchemy import Integer, String, DateTime
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base
from ..types import json_type


class FairnessReport(Base):
    __tablename__ = "fairness_reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    target: Mapped[str] = mapped_column(String(50), index=True)
    region_scope: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    metrics_json = mapped_column(json_type(), nullable=True)
