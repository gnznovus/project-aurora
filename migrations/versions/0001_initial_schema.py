"""initial schema

Revision ID: 0001_initial_schema
Revises: 
Create Date: 2026-04-04
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


job_status_enum = sa.Enum("queued", "leased", "completed", "failed", name="jobstatus")
execution_status_enum = sa.Enum("leased", "completed", "failed", "timeout", name="executionstatus")


def upgrade() -> None:
    op.create_table(
        "agents",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("api_key", sa.String(length=128), nullable=False),
        sa.Column("tags", sa.JSON(), nullable=False),
        sa.Column("max_concurrency", sa.Integer(), nullable=False),
        sa.Column("active_leases", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("last_heartbeat_at", sa.DateTime(timezone=False), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=False), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("api_key"),
    )

    op.create_table(
        "plugins",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=False), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )

    op.create_table(
        "plugin_versions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("plugin_id", sa.Integer(), nullable=False),
        sa.Column("version", sa.String(length=64), nullable=False),
        sa.Column("digest", sa.String(length=64), nullable=False),
        sa.Column("filename", sa.String(length=512), nullable=False),
        sa.Column("entrypoint", sa.String(length=255), nullable=False),
        sa.Column("timeout_seconds", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=False), nullable=False),
        sa.ForeignKeyConstraint(["plugin_id"], ["plugins.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("plugin_id", "version", name="uq_plugin_version"),
    )
    op.create_index("ix_plugin_versions_plugin_id", "plugin_versions", ["plugin_id"], unique=False)

    op.create_table(
        "jobs",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("plugin_id", sa.Integer(), nullable=False),
        sa.Column("plugin_version_id", sa.Integer(), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("required_tags", sa.JSON(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("retry_backoff_seconds", sa.Integer(), nullable=False),
        sa.Column("next_retry_at", sa.DateTime(timezone=False), nullable=True),
        sa.Column("status", job_status_enum, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=False), nullable=False),
        sa.Column("leased_at", sa.DateTime(timezone=False), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=False), nullable=True),
        sa.ForeignKeyConstraint(["plugin_id"], ["plugins.id"]),
        sa.ForeignKeyConstraint(["plugin_version_id"], ["plugin_versions.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_jobs_plugin_id", "jobs", ["plugin_id"], unique=False)
    op.create_index("ix_jobs_status", "jobs", ["status"], unique=False)

    op.create_table(
        "executions",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("job_id", sa.String(length=64), nullable=False),
        sa.Column("agent_id", sa.String(length=64), nullable=False),
        sa.Column("status", execution_status_enum, nullable=False),
        sa.Column("lease_expires_at", sa.DateTime(timezone=False), nullable=False),
        sa.Column("result_payload", sa.JSON(), nullable=True),
        sa.Column("stdout", sa.Text(), nullable=True),
        sa.Column("stderr", sa.Text(), nullable=True),
        sa.Column("exit_code", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=False), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=False), nullable=True),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"]),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_executions_agent_id", "executions", ["agent_id"], unique=False)
    op.create_index("ix_executions_job_id", "executions", ["job_id"], unique=False)

    op.create_table(
        "execution_checkpoints",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("execution_id", sa.String(length=64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=False), nullable=False),
        sa.ForeignKeyConstraint(["execution_id"], ["executions.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_execution_checkpoints_execution_id", "execution_checkpoints", ["execution_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_execution_checkpoints_execution_id", table_name="execution_checkpoints")
    op.drop_table("execution_checkpoints")

    op.drop_index("ix_executions_job_id", table_name="executions")
    op.drop_index("ix_executions_agent_id", table_name="executions")
    op.drop_table("executions")

    op.drop_index("ix_jobs_status", table_name="jobs")
    op.drop_index("ix_jobs_plugin_id", table_name="jobs")
    op.drop_table("jobs")

    op.drop_index("ix_plugin_versions_plugin_id", table_name="plugin_versions")
    op.drop_table("plugin_versions")

    op.drop_table("plugins")
    op.drop_table("agents")

    execution_status_enum.drop(op.get_bind(), checkfirst=True)
    job_status_enum.drop(op.get_bind(), checkfirst=True)

