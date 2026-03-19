from __future__ import annotations

from datetime import datetime
from sqlalchemy import Integer, String, DateTime
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base
from ..types import json_type


class Dataset(Base):
    __tablename__ = "datasets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    source: Mapped[str | None] = mapped_column(String(50), nullable=True)
    license: Mapped[str | None] = mapped_column(String(100), nullable=True)
    spatial: Mapped[str | None] = mapped_column(String(50), nullable=True)
    temporal: Mapped[str | None] = mapped_column(String(50), nullable=True)
    freshness: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    meta_json = mapped_column(json_type(), nullable=True)
