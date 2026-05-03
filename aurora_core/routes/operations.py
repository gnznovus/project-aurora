from __future__ import annotations

import logging
import secrets
import uuid
from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import FileResponse
from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from aurora_core.config import Settings
from aurora_core.services.maintenance import ensure_not_maintenance_mode
from aurora_core.services.models import (
    Agent,
    Execution,
    ExecutionCheckpoint,
    ExecutionStatus,
    Job,
    JobStatus,
    Plugin,
    PluginVersion,
)
from aurora_core.services.plugin_store import PluginStore
from aurora_core.services.queue import QueueAdapter
from aurora_core.services.routing import DefaultStaticRoutingStrategy
from aurora_core.services.schemas import (
    AgentInfo,
    EnqueueJobRequest,
    EnqueueJobResponse,
    ExecutionCheckpointResponse,
    ExecutionCheckpointUpsert,
    ExecutionResult,
    HeartbeatRequest,
    JobLease,
    JobProgressResponse,
    NextJobResponse,
    PluginManifest,
    RegisterAgentRequest,
    RegisterAgentResponse,
    RegisterPluginRequest,
    RegisterPluginResponse,
)
from aurora_core.services.security import get_db, new_agent_id, new_api_key, require_admin_token, require_agent_auth
from aurora_core.utils.timeutils import utc_now_naive
from aurora_core.services.web_auth import audit_important_action

logger = logging.getLogger("aurora-core")
router = APIRouter()


@router.post("/plugins/register", response_model=RegisterPluginResponse)
def register_plugin(
    payload: RegisterPluginRequest,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[None, Depends(require_admin_token)],
) -> RegisterPluginResponse:
    ensure_not_maintenance_mode(request, "plugin.register")
    store: PluginStore = request.app.state.plugin_store
    try:
        digest = store.digest_file(payload.filename)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"plugin file not found: {exc}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    plugin = db.scalar(select(Plugin).where(Plugin.name == payload.name))
    if not plugin:
        plugin = Plugin(name=payload.name)
        db.add(plugin)
        db.flush()

    existing = db.scalar(
        select(PluginVersion).where(
            PluginVersion.plugin_id == plugin.id,
            PluginVersion.version == payload.version,
        )
    )
    if existing:
        logger.info("plugin.register.existing name=%s version=%s digest=%s", payload.name, existing.version, existing.digest)
        return RegisterPluginResponse(name=payload.name, version=existing.version, digest=existing.digest)

    plugin_version = PluginVersion(
        plugin_id=plugin.id,
        version=payload.version,
        digest=digest,
        filename=payload.filename,
        timeout_seconds=payload.timeout_seconds,
        entrypoint=payload.entrypoint,
    )
    db.add(plugin_version)
    db.commit()
    logger.info("plugin.registered name=%s version=%s digest=%s", payload.name, payload.version, digest)
    audit_important_action(
        request=request,
        db_factory=request.app.state.session_factory,
        action="plugin.register",
        resource_type="plugin_version",
        resource_id=f"{payload.name}:{payload.version}",
        details={"filename": payload.filename},
    )
    return RegisterPluginResponse(name=payload.name, version=payload.version, digest=digest)


@router.post("/jobs", response_model=EnqueueJobResponse)
def enqueue_job(
    payload: EnqueueJobRequest,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[None, Depends(require_admin_token)],
) -> EnqueueJobResponse:
    ensure_not_maintenance_mode(request, "job.enqueue")
    queue: QueueAdapter = request.app.state.queue
    plugin = db.scalar(select(Plugin).where(Plugin.name == payload.plugin_name))
    if not plugin:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="plugin not found")

    version_query = select(PluginVersion).where(PluginVersion.plugin_id == plugin.id).order_by(PluginVersion.created_at.desc())
    if payload.plugin_version:
        version_query = select(PluginVersion).where(
            PluginVersion.plugin_id == plugin.id,
            PluginVersion.version == payload.plugin_version,
        )
    plugin_version = db.scalar(version_query)
    if not plugin_version:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="plugin version not found")

    job_id = _new_job_id()
    job = Job(
        id=job_id,
        plugin_id=plugin.id,
        plugin_version_id=plugin_version.id,
        payload=payload.payload,
        required_tags=payload.required_tags,
        max_attempts=payload.max_attempts,
        attempt_count=0,
        retry_backoff_seconds=payload.retry_backoff_seconds,
        next_retry_at=utc_now_naive(),
        status=JobStatus.queued,
    )
    db.add(job)
    db.commit()
    queue.enqueue(job.id)
    logger.info(
        "job.enqueued job_id=%s plugin=%s version=%s required_tags=%s max_attempts=%s backoff=%ss",
        job.id,
        payload.plugin_name,
        plugin_version.version,
        payload.required_tags,
        job.max_attempts,
        job.retry_backoff_seconds,
    )
    audit_important_action(
        request=request,
        db_factory=request.app.state.session_factory,
        action="job.enqueue",
        resource_type="job",
        resource_id=job.id,
        details={
            "plugin_name": payload.plugin_name,
            "plugin_version": payload.plugin_version,
            "max_attempts": job.max_attempts,
        },
    )
    return EnqueueJobResponse(job_id=job.id, status=job.status.value)


@router.post("/agents/register", response_model=RegisterAgentResponse)
def register_agent(payload: RegisterAgentRequest, request: Request, db: Annotated[Session, Depends(get_db)]) -> RegisterAgentResponse:
    ensure_not_maintenance_mode(request, "agent.register")
    settings_obj: Settings = request.app.state.settings
    if payload.bootstrap_token != settings_obj.bootstrap_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid bootstrap token")

    agent = Agent(
        id=new_agent_id(),
        name=_friendly_agent_name(payload.agent_name),
        api_key=new_api_key(),
        tags=payload.tags,
        max_concurrency=payload.max_concurrency,
        active_leases=0,
        status="online",
        last_heartbeat_at=utc_now_naive(),
    )
    db.add(agent)
    db.commit()
    logger.info(
        "agent.registered agent_id=%s name=%s tags=%s max_concurrency=%s",
        agent.id,
        agent.name,
        agent.tags,
        agent.max_concurrency,
    )
    return RegisterAgentResponse(
        agent_id=agent.id,
        api_key=agent.api_key,
        heartbeat_ttl_seconds=settings_obj.heartbeat_ttl_seconds,
        poll_seconds=settings_obj.agent_poll_seconds,
    )


@router.post("/agents/heartbeat", response_model=AgentInfo)
def heartbeat(
    request: Request,
    payload: HeartbeatRequest,
    db: Annotated[Session, Depends(get_db)],
    agent: Annotated[Agent, Depends(require_agent_auth)],
) -> AgentInfo:
    ensure_not_maintenance_mode(request, "agent.heartbeat")
    cpu_load = payload.cpu_load_pct
    ram_load = payload.ram_load_pct
    capacity_hint = payload.capacity_hint or agent.max_concurrency
    db.execute(
        update(Agent)
        .where(Agent.id == agent.id)
        .values(
            last_heartbeat_at=utc_now_naive(),
            status="online",
            max_concurrency=capacity_hint,
            cpu_load_pct=cpu_load,
            ram_load_pct=ram_load,
        )
    )
    db.commit()
    db.refresh(agent)
    logger.debug("agent.heartbeat agent_id=%s active_leases=%s max_concurrency=%s", agent.id, agent.active_leases, agent.max_concurrency)
    return AgentInfo(
        agent_id=agent.id,
        tags=agent.tags,
        active_leases=agent.active_leases,
        max_concurrency=agent.max_concurrency,
        status=agent.status,
        cpu_load_pct=agent.cpu_load_pct,
        ram_load_pct=agent.ram_load_pct,
    )


@router.post("/agents/jobs/next", response_model=NextJobResponse)
def next_job(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    agent: Annotated[Agent, Depends(require_agent_auth)],
) -> NextJobResponse:
    ensure_not_maintenance_mode(request, "job.lease")
    settings_obj: Settings = request.app.state.settings
    strategy: DefaultStaticRoutingStrategy = request.app.state.router_strategy
    queue: QueueAdapter = request.app.state.queue
    _recover_stale_leases(db, queue)

    agent.last_heartbeat_at = utc_now_naive()
    db.flush()

    if not strategy.is_agent_healthy(agent):
        return NextJobResponse(lease=None)
    if agent.active_leases >= agent.max_concurrency:
        return NextJobResponse(lease=None)

    lease_job: Job | None = None
    queue_ids = queue.pop_many(limit=25)
    if queue_ids:
        candidates = list(
            db.scalars(
                select(Job)
                .where(
                    Job.id.in_(queue_ids),
                    Job.status == JobStatus.queued,
                    or_(Job.next_retry_at.is_(None), Job.next_retry_at <= utc_now_naive()),
                )
                .order_by(Job.created_at.asc())
            )
        )
        for candidate in candidates:
            if strategy.is_eligible(agent, candidate):
                lease_job = candidate
                break

    if lease_job is None:
        for candidate in strategy.list_candidates(db, agent, limit=25):
            lease_job = candidate
            break

    if lease_job is None:
        db.commit()
        logger.debug("job.lease.none agent_id=%s", agent.id)
        return NextJobResponse(lease=None)

    updated = db.execute(
        update(Job)
        .where(Job.id == lease_job.id, Job.status == JobStatus.queued)
        .values(
            status=JobStatus.leased,
            leased_at=utc_now_naive(),
            attempt_count=lease_job.attempt_count + 1,
        )
    )
    if updated.rowcount != 1:
        db.commit()
        logger.info("job.lease.race_lost agent_id=%s job_id=%s", agent.id, lease_job.id)
        return NextJobResponse(lease=None)

    execution_id = f"exe_{uuid.uuid4().hex[:16]}"
    lease_exp = utc_now_naive() + timedelta(seconds=settings_obj.lease_ttl_seconds)
    execution = Execution(
        id=execution_id,
        job_id=lease_job.id,
        agent_id=agent.id,
        status=ExecutionStatus.leased,
        lease_expires_at=lease_exp,
    )
    agent.active_leases += 1
    db.add(execution)
    db.commit()

    job = db.scalar(select(Job).where(Job.id == lease_job.id).options())
    if not job:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="leased job not found")
    plugin = db.scalar(select(Plugin).where(Plugin.id == job.plugin_id))
    plugin_version = db.scalar(select(PluginVersion).where(PluginVersion.id == job.plugin_version_id))
    if not plugin or not plugin_version:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="plugin metadata missing")

    lease = JobLease(
        execution_id=execution.id,
        lease_expires_at=execution.lease_expires_at.isoformat() + "Z",
        job_id=job.id,
        plugin_name=plugin.name,
        plugin_version=plugin_version.version,
        plugin_digest=plugin_version.digest,
        payload=job.payload,
        resume_checkpoint=_latest_checkpoint_for_job(db, job.id),
    )
    logger.info(
        "job.leased agent_id=%s job_id=%s execution_id=%s plugin=%s version=%s",
        agent.id,
        job.id,
        execution.id,
        plugin.name,
        plugin_version.version,
    )
    return NextJobResponse(lease=lease)


@router.get("/plugins/{name}/manifest", response_model=PluginManifest)
def plugin_manifest(name: str, request: Request, version: str | None = None, db: Session = Depends(get_db)):
    plugin = db.scalar(select(Plugin).where(Plugin.name == name))
    if not plugin:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="plugin not found")

    if version:
        plugin_version = db.scalar(
            select(PluginVersion).where(PluginVersion.plugin_id == plugin.id, PluginVersion.version == version)
        )
    else:
        plugin_version = db.scalar(
            select(PluginVersion).where(PluginVersion.plugin_id == plugin.id).order_by(PluginVersion.created_at.desc())
        )
    if not plugin_version:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="plugin version not found")
    logger.info("plugin.manifest.requested name=%s version=%s", plugin.name, plugin_version.version)

    return PluginManifest(
        name=plugin.name,
        version=plugin_version.version,
        digest=plugin_version.digest,
        timeout_seconds=plugin_version.timeout_seconds,
        entrypoint=plugin_version.entrypoint,
        download_url=f"/plugins/{plugin.name}/download?version={plugin_version.version}",
    )


@router.get("/plugins/{name}/download")
def download_plugin(name: str, request: Request, version: str | None = None, db: Session = Depends(get_db)):
    store: PluginStore = request.app.state.plugin_store
    plugin = db.scalar(select(Plugin).where(Plugin.name == name))
    if not plugin:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="plugin not found")

    query = select(PluginVersion).where(PluginVersion.plugin_id == plugin.id)
    if version:
        query = query.where(PluginVersion.version == version)
    else:
        query = query.order_by(PluginVersion.created_at.desc())
    plugin_version = db.scalar(query)
    if not plugin_version:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="plugin version not found")

    file_path = store.resolve(plugin_version.filename)
    if not file_path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="plugin artifact missing")
    logger.info("plugin.download.requested name=%s version=%s", plugin.name, plugin_version.version)
    return FileResponse(path=file_path, filename=file_path.name, media_type="application/octet-stream")


@router.post("/executions/{execution_id}/result")
def execution_result(
    execution_id: str,
    request: Request,
    payload: ExecutionResult,
    db: Session = Depends(get_db),
    agent: Agent = Depends(require_agent_auth),
) -> dict:
    ensure_not_maintenance_mode(request, "execution.result")
    execution = db.scalar(select(Execution).where(Execution.id == execution_id))
    if not execution:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="execution not found")
    if execution.agent_id != agent.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="execution owned by another agent")
    if execution.status != ExecutionStatus.leased:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="execution is already terminal")
    if utc_now_naive() > execution.lease_expires_at:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="stale lease")

    job = db.scalar(select(Job).where(Job.id == execution.job_id))
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="job not found")

    normalized = payload.status
    execution.status = normalized
    execution.result_payload = payload.metrics
    execution.stdout = payload.stdout
    execution.stderr = payload.stderr
    execution.exit_code = payload.exit_code
    execution.completed_at = utc_now_naive()

    if normalized == ExecutionStatus.completed:
        job.status = JobStatus.completed
        job.completed_at = utc_now_naive()
        job.next_retry_at = None
    else:
        if job.attempt_count < job.max_attempts:
            job.status = JobStatus.queued
            job.next_retry_at = utc_now_naive() + timedelta(seconds=job.retry_backoff_seconds)
            queue: QueueAdapter = request.app.state.queue
            queue.enqueue(job.id)
            logger.info(
                "job.retry_scheduled job_id=%s execution_id=%s attempt=%s/%s backoff=%ss",
                job.id,
                execution.id,
                job.attempt_count,
                job.max_attempts,
                job.retry_backoff_seconds,
            )
        else:
            job.status = JobStatus.failed
            job.completed_at = utc_now_naive()
            job.next_retry_at = None
            logger.info(
                "job.failed_terminal job_id=%s execution_id=%s attempt=%s/%s",
                job.id,
                execution.id,
                job.attempt_count,
                job.max_attempts,
            )

    if agent.active_leases > 0:
        agent.active_leases -= 1

    db.commit()
    logger.info(
        "execution.result.recorded execution_id=%s job_id=%s status=%s exit_code=%s",
        execution.id,
        job.id,
        normalized.value,
        payload.exit_code,
    )
    return {"status": "ok", "execution_id": execution.id, "job_status": job.status.value}


@router.post("/executions/{execution_id}/checkpoint", response_model=ExecutionCheckpointResponse)
def upsert_checkpoint(
    execution_id: str,
    request: Request,
    payload: ExecutionCheckpointUpsert,
    db: Session = Depends(get_db),
    agent: Agent = Depends(require_agent_auth),
) -> ExecutionCheckpointResponse:
    ensure_not_maintenance_mode(request, "execution.checkpoint")
    execution = db.scalar(select(Execution).where(Execution.id == execution_id))
    if not execution:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="execution not found")
    if execution.agent_id != agent.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="execution owned by another agent")
    checkpoint = ExecutionCheckpoint(execution_id=execution.id, payload=payload.payload)
    db.add(checkpoint)
    db.commit()
    db.refresh(checkpoint)
    return ExecutionCheckpointResponse(
        execution_id=execution.id,
        checkpoint_payload=checkpoint.payload,
    )


@router.get("/executions/{execution_id}/checkpoint/latest", response_model=ExecutionCheckpointResponse)
def latest_checkpoint(
    execution_id: str,
    db: Session = Depends(get_db),
    agent: Agent = Depends(require_agent_auth),
):
    execution = db.scalar(select(Execution).where(Execution.id == execution_id))
    if not execution:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="execution not found")
    if execution.agent_id != agent.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="execution owned by another agent")
    checkpoint = db.scalar(
        select(ExecutionCheckpoint)
        .where(ExecutionCheckpoint.execution_id == execution.id)
        .order_by(ExecutionCheckpoint.created_at.desc(), ExecutionCheckpoint.id.desc())
    )
    return ExecutionCheckpointResponse(
        execution_id=execution.id,
        checkpoint_payload=checkpoint.payload if checkpoint else None,
    )


@router.get("/jobs/{job_id}/progress", response_model=JobProgressResponse)
def job_progress(job_id: str, db: Session = Depends(get_db), _: Annotated[None, Depends(require_admin_token)] = None):
    job = db.scalar(select(Job).where(Job.id == job_id))
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="job not found")
    checkpoint = _latest_checkpoint_for_job(db, job.id)
    return JobProgressResponse(
        job_id=job.id,
        status=job.status.value,
        attempt_count=job.attempt_count,
        max_attempts=job.max_attempts,
        checkpoint=checkpoint,
    )


def _latest_checkpoint_for_job(db: Session, job_id: str) -> dict | None:
    checkpoint = db.scalar(
        select(ExecutionCheckpoint)
        .join(Execution, Execution.id == ExecutionCheckpoint.execution_id)
        .where(Execution.job_id == job_id)
        .order_by(ExecutionCheckpoint.created_at.desc(), ExecutionCheckpoint.id.desc())
    )
    return checkpoint.payload if checkpoint else None


def _new_job_id() -> str:
    ts = utc_now_naive().strftime("%Y%m%d_%H%M%S")
    suffix = secrets.token_hex(2).upper()
    return f"JOB_{ts}_{suffix}"


def _friendly_agent_name(raw_name: str) -> str:
    value = (raw_name or "").strip()
    if value and not value.lower().startswith("agent-local"):
        return value
    adjectives = ("North", "South", "East", "West", "Swift", "Bright", "Calm", "Solid")
    nouns = ("Falcon", "Otter", "Raven", "Panda", "Lynx", "Cedar", "Comet", "Harbor")
    return f"{secrets.choice(adjectives)} {secrets.choice(nouns)} {secrets.randbelow(90) + 10}"


def _recover_stale_leases(db: Session, queue: QueueAdapter) -> None:
    now = utc_now_naive()
    stale_executions = list(
        db.scalars(
            select(Execution)
            .where(Execution.status == ExecutionStatus.leased, Execution.lease_expires_at < now)
            .order_by(Execution.created_at.asc())
        )
    )
    if not stale_executions:
        return

    for execution in stale_executions:
        execution.status = ExecutionStatus.timeout
        execution.completed_at = now
        job = db.scalar(select(Job).where(Job.id == execution.job_id))
        if job and job.status == JobStatus.leased:
            if job.attempt_count < job.max_attempts:
                job.status = JobStatus.queued
                job.next_retry_at = now + timedelta(seconds=job.retry_backoff_seconds)
                queue.enqueue(job.id)
                logger.info(
                    "job.recovered_for_retry job_id=%s execution_id=%s attempt=%s/%s",
                    job.id,
                    execution.id,
                    job.attempt_count,
                    job.max_attempts,
                )
            else:
                job.status = JobStatus.failed
                job.completed_at = now
                job.next_retry_at = None
                logger.info("job.recovered_terminal_failure job_id=%s execution_id=%s", job.id, execution.id)

        agent = db.scalar(select(Agent).where(Agent.id == execution.agent_id))
        if agent and agent.active_leases > 0:
            agent.active_leases -= 1

    db.commit()

