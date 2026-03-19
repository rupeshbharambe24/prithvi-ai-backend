from __future__ import annotations

from sqlalchemy import Integer, String, DateTime, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base
from ..types import json_type


class Feature(Base):
    __tablename__ = "features"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    region_id: Mapped[int] = mapped_column(ForeignKey("regions.id"), index=True)
    feature_key: Mapped[str] = mapped_column(String(64), index=True)
    ts: Mapped[object] = mapped_column(DateTime(timezone=True), index=True)
    value: Mapped[float] = mapped_column()
    unit: Mapped[str | None] = mapped_column(String(20))
    p05: Mapped[float | None] = mapped_column()
    p95: Mapped[float | None] = mapped_column()
    meta_json = mapped_column(json_type(), nullable=True)

    __table_args__ = (
        Index("ix_features_region_ts", "region_id", "ts"),
    )
