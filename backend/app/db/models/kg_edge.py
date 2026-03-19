from __future__ import annotations

from sqlalchemy import Integer, String, ForeignKey, Float
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base
from ..types import json_type


class KGEdge(Base):
    __tablename__ = "kg_edges"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    src: Mapped[int] = mapped_column(Integer, index=True)
    dst: Mapped[int] = mapped_column(Integer, index=True)
    rel: Mapped[str] = mapped_column(String(32), index=True)
    weight: Mapped[float | None] = mapped_column(Float, nullable=True)
    props_json = mapped_column(json_type(), nullable=True)
