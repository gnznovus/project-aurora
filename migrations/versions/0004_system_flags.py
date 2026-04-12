"""add system flags table

Revision ID: 0004_system_flags
Revises: 0003_backups
Create Date: 2026-04-12
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0004_system_flags"
down_revision = "0003_backups"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "system_flags",
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("value_json", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=False), nullable=False),
        sa.PrimaryKeyConstraint("key"),
    )


def downgrade() -> None:
    op.drop_table("system_flags")
