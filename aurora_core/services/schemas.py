from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


SCHEMA_VERSION = "v1"


class ExecutionTerminalStatus(str, Enum):
    completed = "completed"
    failed = "failed"
    timeout = "timeout"


class RegisterAgentRequest(BaseModel):
    bootstrap_token: str
    agent_name: str = Field(min_length=1, max_length=255)
    tags: list[str] = Field(default_factory=list)
    max_concurrency: int = Field(default=1, ge=1, le=64)


class RegisterAgentResponse(BaseModel):
    schema_version: str = SCHEMA_VERSION
    agent_id: str
    api_key: str
    heartbeat_ttl_seconds: int
    poll_seconds: int


class AgentInfo(BaseModel):
    schema_version: str = SCHEMA_VERSION
    agent_id: str
    tags: list[str]
    active_leases: int
    max_concurrency: int
    status: str
    cpu_load_pct: int | None = None
    ram_load_pct: int | None = None


class HeartbeatRequest(BaseModel):
    running_jobs: int = Field(ge=0, le=512)
    capacity_hint: int = Field(ge=1, le=64)
    cpu_load_pct: int | None = Field(default=None, ge=0, le=100)
    ram_load_pct: int | None = Field(default=None, ge=0, le=100)


class EnqueueJobRequest(BaseModel):
    plugin_name: str
    plugin_version: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    required_tags: list[str] = Field(default_factory=list)
    max_attempts: int = Field(default=1, ge=1, le=20)
    retry_backoff_seconds: int = Field(default=5, ge=0, le=3600)


class EnqueueJobResponse(BaseModel):
    schema_version: str = SCHEMA_VERSION
    job_id: str
    status: str


class RegisterPluginRequest(BaseModel):
    name: str
    version: str
    filename: str
    timeout_seconds: int = Field(default=30, ge=1, le=600)
    entrypoint: str = "python"


class RegisterPluginResponse(BaseModel):
    schema_version: str = SCHEMA_VERSION
    name: str
    version: str
    digest: str


class PluginManifest(BaseModel):
    schema_version: str = SCHEMA_VERSION
    name: str
    version: str
    digest: str
    timeout_seconds: int
    entrypoint: str
    download_url: str


class JobLease(BaseModel):
    schema_version: str = SCHEMA_VERSION
    execution_id: str
    lease_expires_at: str
    job_id: str
    plugin_name: str
    plugin_version: str
    plugin_digest: str
    payload: dict[str, Any]
    resume_checkpoint: dict[str, Any] | None = None


class NextJobResponse(BaseModel):
    schema_version: str = SCHEMA_VERSION
    lease: JobLease | None


class ExecutionResult(BaseModel):
    schema_version: str = SCHEMA_VERSION
    status: ExecutionTerminalStatus
    exit_code: int | None = None
    stdout: str | None = None
    stderr: str | None = None
    duration_ms: int | None = Field(default=None, ge=0)
    metrics: dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(extra="ignore")


class ExecutionCheckpointUpsert(BaseModel):
    schema_version: str = SCHEMA_VERSION
    payload: dict[str, Any] = Field(default_factory=dict)


class ExecutionCheckpointResponse(BaseModel):
    schema_version: str = SCHEMA_VERSION
    execution_id: str
    checkpoint_payload: dict[str, Any] | None


class JobProgressResponse(BaseModel):
    schema_version: str = SCHEMA_VERSION
    job_id: str
    status: str
    attempt_count: int
    max_attempts: int
    latest_execution_id: str | None = None
    checkpoint_payload: dict[str, Any] | None = None
