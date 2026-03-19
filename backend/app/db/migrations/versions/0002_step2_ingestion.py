"""step2 ingestion models and region geometry

Revision ID: 0002_step2
Revises: 0001_initial
Create Date: 2025-01-01 01:00:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0002_step2"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Regions geometry additions
    op.add_column("regions", sa.Column("code", sa.String(length=64), nullable=True))
    op.create_index("ix_regions_code", "regions", ["code"], unique=False)
    op.execute("ALTER TABLE regions ADD COLUMN IF NOT EXISTS bounds_geom geometry(MultiPolygon,4326)")
    op.execute("ALTER TABLE regions ADD COLUMN IF NOT EXISTS center geometry(Point,4326)")
    op.add_column("regions", sa.Column("parent_id", sa.Integer(), nullable=True))
    op.create_foreign_key("fk_regions_parent", "regions", "regions", ["parent_id"], ["id"])
    op.execute("CREATE INDEX IF NOT EXISTS regions_bounds_gix ON regions USING GIST (bounds_geom)")

    # Datasets
    op.create_table(
        "datasets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=100), nullable=False, unique=True),
        sa.Column("source", sa.String(length=50), nullable=True),
        sa.Column("license", sa.String(length=100), nullable=True),
        sa.Column("spatial", sa.String(length=50), nullable=True),
        sa.Column("temporal", sa.String(length=50), nullable=True),
        sa.Column("freshness", sa.DateTime(timezone=True), nullable=True),
        sa.Column("meta_json", postgresql.JSONB, nullable=True),
    )

    # Dataset versions
    op.create_table(
        "dataset_versions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("dataset_id", sa.Integer(), sa.ForeignKey("datasets.id"), index=True),
        sa.Column("version", sa.String(length=64), nullable=False),
        sa.Column("hash", sa.String(length=128), nullable=True),
        sa.Column("coverage_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("coverage_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    # Ingest runs
    op.create_table(
        "ingest_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("dataset_id", sa.Integer(), sa.ForeignKey("datasets.id"), index=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("rows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_text", sa.String(length=500), nullable=True),
        sa.Column("meta_json", postgresql.JSONB, nullable=True),
    )

    # Observations
    op.create_table(
        "observations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("region_id", sa.Integer(), sa.ForeignKey("regions.id"), index=True),
        sa.Column("dataset_id", sa.Integer(), sa.ForeignKey("datasets.id"), index=True),
        sa.Column("ts", sa.DateTime(timezone=True), index=True, nullable=False),
        sa.Column("value", sa.Float(), nullable=False),
        sa.Column("unit", sa.String(length=20), nullable=True),
        sa.Column("quality_flags", postgresql.JSONB, nullable=True),
    )
    op.create_index("ix_observations_region_ts", "observations", ["region_id", "ts"], unique=False)
    # Create hypertable safely (avoid async double-run issue)
    op.execute("""
    DO $$
    DECLARE
        lock_acquired BOOLEAN;
    BEGIN
        SELECT pg_try_advisory_lock(12345) INTO lock_acquired;
        IF lock_acquired THEN
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM timescaledb_information.hypertables
                    WHERE hypertable_name = 'observations'
                ) THEN
                    PERFORM create_hypertable('observations','ts', if_not_exists => TRUE);
                END IF;
            EXCEPTION WHEN others THEN
                RAISE NOTICE 'Hypertable creation skipped: %', SQLERRM;
            END;
            PERFORM pg_advisory_unlock(12345);
        END IF;
    END $$;
    """)


    # Features
    op.create_table(
        "features",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("region_id", sa.Integer(), sa.ForeignKey("regions.id"), index=True),
        sa.Column("feature_key", sa.String(length=64), index=True),
        sa.Column("ts", sa.DateTime(timezone=True), index=True, nullable=False),
        sa.Column("value", sa.Float(), nullable=False),
        sa.Column("unit", sa.String(length=20), nullable=True),
        sa.Column("p05", sa.Float(), nullable=True),
        sa.Column("p95", sa.Float(), nullable=True),
        sa.Column("meta_json", postgresql.JSONB, nullable=True),
    )
    op.create_index("ix_features_region_ts", "features", ["region_id", "ts"], unique=False)
    op.execute("""
    DO $$
    DECLARE
        lock_acquired BOOLEAN;
    BEGIN
        SELECT pg_try_advisory_lock(12346) INTO lock_acquired;
        IF lock_acquired THEN
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM timescaledb_information.hypertables
                    WHERE hypertable_name = 'features'
                ) THEN
                    PERFORM create_hypertable('features','ts', if_not_exists => TRUE);
                END IF;
            EXCEPTION WHEN others THEN
                RAISE NOTICE 'Hypertable creation skipped: %', SQLERRM;
            END;
            PERFORM pg_advisory_unlock(12346);
        END IF;
    END $$;
    """)


    # Data quality issues
    op.create_table(
        "dq_issues",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("dataset_id", sa.Integer(), sa.ForeignKey("datasets.id"), index=True),
        sa.Column("check", sa.String(length=100), nullable=False),
        sa.Column("region_id", sa.Integer(), sa.ForeignKey("regions.id"), nullable=True),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=True),
        sa.Column("severity", sa.String(length=20), nullable=False),
        sa.Column("details_json", postgresql.JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("dq_issues")
    op.drop_table("features")
    op.drop_index("ix_observations_region_ts", table_name="observations")
    op.drop_table("observations")
    op.drop_table("ingest_runs")
    op.drop_table("dataset_versions")
    op.drop_table("datasets")
    op.drop_constraint("fk_regions_parent", "regions", type_="foreignkey")
    op.drop_column("regions", "parent_id")
    op.drop_column("regions", "center")
    op.drop_column("regions", "bounds_geom")
    op.drop_index("ix_regions_code", table_name="regions")
    op.drop_column("regions", "code")
