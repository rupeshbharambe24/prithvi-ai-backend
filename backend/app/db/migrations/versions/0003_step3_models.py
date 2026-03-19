"""step3 models registry and forecasts

Revision ID: 0003_step3
Revises: 0002_step2
Create Date: 2025-01-01 02:00:00

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0003_step3"
down_revision = "0002_step2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Model registry tables
    op.create_table(
        "model_versions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("target", sa.String(length=50), index=True),
        sa.Column("algo", sa.String(length=50), nullable=False),
        sa.Column("params_json", sa.dialects.postgresql.JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("path", sa.String(length=255), nullable=False),
        sa.Column("metrics_json", sa.dialects.postgresql.JSONB, nullable=True),
    )
    op.create_table(
        "model_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("model_version_id", sa.Integer(), sa.ForeignKey("model_versions.id"), index=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("data_window_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("data_window_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metrics_json", sa.dialects.postgresql.JSONB, nullable=True),
    )
    op.create_table(
        "backtest_scores",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("target", sa.String(length=50), index=True),
        sa.Column("region_id", sa.Integer(), index=True),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("metrics_json", sa.dialects.postgresql.JSONB, nullable=True),
    )

    # Forecasts table
    op.create_table(
        "forecasts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("region_id", sa.Integer(), sa.ForeignKey("regions.id"), index=True),
        sa.Column("type", sa.String(length=50), index=True),
        sa.Column("target_date", sa.DateTime(timezone=True), index=True),
        sa.Column("horizon", sa.Integer(), nullable=False),
        sa.Column("value", sa.Float(), nullable=False),
        sa.Column("p05", sa.Float(), nullable=True),
        sa.Column("p95", sa.Float(), nullable=True),
        sa.Column("drivers_json", sa.dialects.postgresql.JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
    )
    op.create_index("ix_forecasts_region_date", "forecasts", ["region_id", "target_date"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_forecasts_region_date", table_name="forecasts")
    op.drop_table("forecasts")
    op.drop_table("backtest_scores")
    op.drop_table("model_runs")
    op.drop_table("model_versions")

