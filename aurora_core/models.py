from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from aurora_core.timeutils import utc_now_naive


class Base(DeclarativeBase):
    pass


class JobStatus(str, enum.Enum):
    queued = "queued"
    leased = "leased"
    completed = "completed"
    failed = "failed"


class ExecutionStatus(str, enum.Enum):
    leased = "leased"
    completed = "completed"
    failed = "failed"
    timeout = "timeout"


class UserRole(str, enum.Enum):
    superadmin = "superadmin"
    admin = "admin"
    operator = "operator"


class BackupStatus(str, enum.Enum):
    created = "created"
    validated = "validated"
    invalid = "invalid"
    pruned = "pruned"
    failed = "failed"


class Agent(Base):
    __tablename__ = "agents"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    api_key: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    tags: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    max_concurrency: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    active_leases: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="online", nullable=False)
    cpu_load_pct: Mapped[int | None] = mapped_column(Integer)
    ram_load_pct: Mapped[int | None] = mapped_column(Integer)
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), default=utc_now_naive, nullable=False)

    executions: Mapped[list[Execution]] = relationship(back_populates="agent")


class Plugin(Base):
    __tablename__ = "plugins"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), default=utc_now_naive, nullable=False)

    versions: Mapped[list[PluginVersion]] = relationship(back_populates="plugin")
    jobs: Mapped[list[Job]] = relationship(back_populates="plugin")


class PluginVersion(Base):
    __tablename__ = "plugin_versions"
    __table_args__ = (UniqueConstraint("plugin_id", "version", name="uq_plugin_version"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    plugin_id: Mapped[int] = mapped_column(ForeignKey("plugins.id"), nullable=False, index=True)
    version: Mapped[str] = mapped_column(String(64), nullable=False)
    digest: Mapped[str] = mapped_column(String(64), nullable=False)
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    entrypoint: Mapped[str] = mapped_column(String(255), default="python", nullable=False)
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=30, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), default=utc_now_naive, nullable=False)

    plugin: Mapped[Plugin] = relationship(back_populates="versions")
    jobs: Mapped[list[Job]] = relationship(back_populates="plugin_version")


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    plugin_id: Mapped[int] = mapped_column(ForeignKey("plugins.id"), nullable=False, index=True)
    plugin_version_id: Mapped[int | None] = mapped_column(ForeignKey("plugin_versions.id"))
    payload: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    required_tags: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    retry_backoff_seconds: Mapped[int] = mapped_column(Integer, default=5, nullable=False)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False))
    status: Mapped[JobStatus] = mapped_column(Enum(JobStatus), default=JobStatus.queued, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), default=utc_now_naive, nullable=False)
    leased_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False))

    plugin: Mapped[Plugin] = relationship(back_populates="jobs")
    plugin_version: Mapped[PluginVersion | None] = relationship(back_populates="jobs")
    executions: Mapped[list[Execution]] = relationship(back_populates="job")


class Execution(Base):
    __tablename__ = "executions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id"), nullable=False, index=True)
    agent_id: Mapped[str] = mapped_column(ForeignKey("agents.id"), nullable=False, index=True)
    status: Mapped[ExecutionStatus] = mapped_column(Enum(ExecutionStatus), default=ExecutionStatus.leased, nullable=False)
    lease_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)
    result_payload: Mapped[dict | None] = mapped_column(JSON)
    stdout: Mapped[str | None] = mapped_column(Text)
    stderr: Mapped[str | None] = mapped_column(Text)
    exit_code: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), default=utc_now_naive, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False))

    job: Mapped[Job] = relationship(back_populates="executions")
    agent: Mapped[Agent] = relationship(back_populates="executions")
    checkpoints: Mapped[list[ExecutionCheckpoint]] = relationship(back_populates="execution")


class ExecutionCheckpoint(Base):
    __tablename__ = "execution_checkpoints"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    execution_id: Mapped[str] = mapped_column(ForeignKey("executions.id"), nullable=False, index=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), default=utc_now_naive, nullable=False)

    execution: Mapped[Execution] = relationship(back_populates="checkpoints")


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(128), nullable=False, unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(256), nullable=False)
    role: Mapped[str] = mapped_column(String(32), default=UserRole.operator.value, nullable=False)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), default=utc_now_naive, nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False))


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    actor_username: Mapped[str | None] = mapped_column(String(128))
    actor_role: Mapped[str | None] = mapped_column(String(32))
    action: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    resource_type: Mapped[str | None] = mapped_column(String(64))
    resource_id: Mapped[str | None] = mapped_column(String(128))
    details: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    ip_address: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(512))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), default=utc_now_naive, nullable=False)


class BackupRecord(Base):
    __tablename__ = "backups"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    created_by: Mapped[str | None] = mapped_column(String(128))
    status: Mapped[BackupStatus] = mapped_column(Enum(BackupStatus), default=BackupStatus.created, nullable=False, index=True)
    storage_path: Mapped[str] = mapped_column(String(512), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    manifest_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    validation_message: Mapped[str | None] = mapped_column(String(512))
    validated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), default=utc_now_naive, nullable=False, index=True)


class SystemFlag(Base):
    __tablename__ = "system_flags"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), default=utc_now_naive, nullable=False)
