"""add backups table

Revision ID: 0003_backups
Revises: 0002_users_and_audit_logs
Create Date: 2026-04-12
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0003_backups"
down_revision = "0002_users_and_audit_logs"
branch_labels = None
depends_on = None


backup_status_enum = sa.Enum("created", "validated", "invalid", "pruned", "failed", name="backupstatus")


def upgrade() -> None:
    op.create_table(
        "backups",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("created_by", sa.String(length=128), nullable=True),
        sa.Column("status", backup_status_enum, nullable=False),
        sa.Column("storage_path", sa.String(length=512), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("manifest_json", sa.JSON(), nullable=False),
        sa.Column("validation_message", sa.String(length=512), nullable=True),
        sa.Column("validated_at", sa.DateTime(timezone=False), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=False), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_backups_status", "backups", ["status"], unique=False)
    op.create_index("ix_backups_created_at", "backups", ["created_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_backups_created_at", table_name="backups")
    op.drop_index("ix_backups_status", table_name="backups")
    op.drop_table("backups")
    backup_status_enum.drop(op.get_bind(), checkfirst=True)
