"""add agent cpu/ram metrics

Revision ID: 0005_agent_resource_metrics
Revises: 0004_system_flags
Create Date: 2026-04-12
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0005_agent_resource_metrics"
down_revision = "0004_system_flags"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("agents", sa.Column("cpu_load_pct", sa.Integer(), nullable=True))
    op.add_column("agents", sa.Column("ram_load_pct", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("agents", "ram_load_pct")
    op.drop_column("agents", "cpu_load_pct")
