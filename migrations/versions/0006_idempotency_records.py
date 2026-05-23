"""add idempotency records

Revision ID: 0006_idempotency_records
Revises: 0005_agent_resource_metrics
Create Date: 2026-05-23
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0006_idempotency_records"
down_revision = "0005_agent_resource_metrics"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "idempotency_records",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True, nullable=False),
        sa.Column("route", sa.String(length=128), nullable=False),
        sa.Column("idem_key", sa.String(length=128), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=False, server_default="200"),
        sa.Column("response_json", sa.JSON(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=False), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=False), nullable=False),
        sa.UniqueConstraint("route", "idem_key", name="uq_idempotency_route_key"),
    )
    op.create_index("ix_idempotency_records_route", "idempotency_records", ["route"])
    op.create_index("ix_idempotency_records_expires_at", "idempotency_records", ["expires_at"])


def downgrade() -> None:
    op.drop_index("ix_idempotency_records_expires_at", table_name="idempotency_records")
    op.drop_index("ix_idempotency_records_route", table_name="idempotency_records")
    op.drop_table("idempotency_records")
