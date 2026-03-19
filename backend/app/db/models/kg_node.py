from __future__ import annotations

from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base
from ..types import json_type


class KGNode(Base):
    __tablename__ = "kg_nodes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    type: Mapped[str] = mapped_column(String(32), index=True)
    label: Mapped[str] = mapped_column(String(255))
    props_json = mapped_column(json_type(), nullable=True)
    # embedding stored via raw SQL vector; keep nullable here
    # We won't map vector type in SQLAlchemy; we access via raw SQL when needed
