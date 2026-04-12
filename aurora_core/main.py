from __future__ import annotations

import logging
import random
import secrets
import uuid
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response, status
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session

from aurora_core.auth_utils import hash_password, verify_password
from aurora_core.backup_scheduler import BackupScheduler
from aurora_core.backup_service import BackupService
from aurora_core.config import Settings, get_settings
from aurora_core.dashboard_html import DASHBOARD_HTML, LOGIN_HTML
from aurora_core.db import create_session_factory
from aurora_core.models import (
    Agent,
    AuditLog,
    BackupRecord,
    BackupStatus,
    Base,
    Execution,
    ExecutionCheckpoint,
    ExecutionStatus,
    Job,
    JobStatus,
    Plugin,
    PluginVersion,
    SystemFlag,
    User,
    UserRole,
)
from aurora_core.plugin_store import PluginStore
from aurora_core.queue import InMemoryQueue, QueueAdapter, RedisQueue
from aurora_core.routing import DefaultStaticRoutingStrategy
from aurora_core.schemas import (
    AgentInfo,
    EnqueueJobRequest,
    EnqueueJobResponse,
    ExecutionResult,
    ExecutionCheckpointResponse,
    ExecutionCheckpointUpsert,
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
from aurora_core.security import get_db, new_agent_id, new_api_key, require_admin_token, require_agent_auth
from aurora_core.timeutils import utc_now_naive

logger = logging.getLogger("aurora-core")


def create_app(settings: Settings | None = None) -> FastAPI:
    effective_settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app_ref: FastAPI):
        session_factory = app_ref.state.session_factory
        engine = session_factory.kw["bind"]
        Base.metadata.create_all(bind=engine)
        _bootstrap_superadmin(app_ref)
        scheduler: BackupScheduler = app_ref.state.backup_scheduler
        scheduler.start()
        try:
            yield
        finally:
            scheduler.stop()

    app = FastAPI(title="Aurora Core", version="0.1.0", lifespan=lifespan)
    app.state.settings = effective_settings
    app.state.session_factory = create_session_factory(effective_settings)
    app.state.queue = _build_queue(effective_settings)
    app.state.router_strategy = DefaultStaticRoutingStrategy(effective_settings.heartbeat_ttl_seconds)
    app.state.plugin_store = PluginStore(Path(effective_settings.plugins_dir))
    app.state.backup_service = BackupService(effective_settings, app.state.session_factory)
    app.state.backup_scheduler = BackupScheduler(effective_settings, app.state.backup_service, app.state.session_factory)
    app.state.dashboard_sessions = {}
    app.state.dashboard_session_ttl_seconds = 60 * 60 * 8

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok", "service": "aurora-core"}

    @app.get("/dashboard", response_class=HTMLResponse)
    def dashboard() -> HTMLResponse:
        return HTMLResponse(content=DASHBOARD_HTML)

    @app.get("/login", response_class=HTMLResponse)
    def login_page() -> HTMLResponse:
        return HTMLResponse(content=LOGIN_HTML)

    @app.get("/dashboard/login")
    def dashboard_login_redirect() -> RedirectResponse:
        return RedirectResponse(url="/login", status_code=307)

    @app.post("/login")
    async def login_submit(request: Request) -> JSONResponse:
        payload = await request.json()
        username = (payload.get("username") or "").strip()
        password = (payload.get("password") or "").strip()
        db = request.app.state.session_factory()
        try:
            user = db.scalar(select(User).where(User.username == username, User.is_active.is_(True)))
            if not user or not verify_password(password, user.password_hash):
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid credentials")
            user.last_login_at = utc_now_naive()
            db.commit()
            actor_username = user.username
            actor_role = user.role
        finally:
            db.close()
        session_id = secrets.token_urlsafe(32)
        expires_at = utc_now_naive() + timedelta(seconds=request.app.state.dashboard_session_ttl_seconds)
        request.app.state.dashboard_sessions[session_id] = {
            "expires_at": expires_at,
            "username": actor_username,
            "role": actor_role,
        }
        _write_audit_log(
            request.app.state.session_factory(),
            actor_username=actor_username,
            actor_role=actor_role,
            action="auth.login",
            resource_type="session",
            resource_id=session_id[:12],
            details={"message": "dashboard login success"},
            ip_address=_request_ip(request),
            user_agent=request.headers.get("user-agent"),
        )
        response = JSONResponse({"status": "ok", "redirect_to": "/dashboard"})
        response.set_cookie(
            key="aurora_dashboard_session",
            value=session_id,
            httponly=True,
            samesite="lax",
            secure=False,
            path="/",
        )
        return response

    @app.post("/dashboard/logout")
    def dashboard_logout(request: Request) -> JSONResponse:
        session_id = request.cookies.get("aurora_dashboard_session")
        actor = _get_dashboard_user(request)
        if session_id:
            request.app.state.dashboard_sessions.pop(session_id, None)
        if actor:
            _write_audit_log(
                request.app.state.session_factory(),
                actor_username=actor["username"],
                actor_role=actor["role"],
                action="auth.logout",
                resource_type="session",
                resource_id=(session_id or "")[:12],
                details={},
                ip_address=_request_ip(request),
                user_agent=request.headers.get("user-agent"),
            )
        response = JSONResponse({"status": "ok"})
        response.delete_cookie("aurora_dashboard_session", path="/")
        return response

    @app.get("/dashboard/auth/status")
    def dashboard_auth_status(request: Request) -> dict:
        actor = _get_dashboard_user(request)
        if not actor:
            return {"authenticated": False}
        return {
            "authenticated": True,
            "username": actor["username"],
            "role": actor["role"],
            "is_superadmin": actor["role"] == UserRole.superadmin.value,
        }

    @app.post("/plugins/register", response_model=RegisterPluginResponse)
    def register_plugin(
        payload: RegisterPluginRequest,
        request: Request,
        db: Annotated[Session, Depends(get_db)],
        _: Annotated[None, Depends(require_admin_token)],
    ) -> RegisterPluginResponse:
        _ensure_not_maintenance_mode(request, "plugin.register")
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
            logger.info(
                "plugin.register.existing name=%s version=%s digest=%s",
                payload.name,
                existing.version,
                existing.digest,
            )
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
        _audit_important_action(
            request=request,
            db_factory=request.app.state.session_factory,
            action="plugin.register",
            resource_type="plugin_version",
            resource_id=f"{payload.name}:{payload.version}",
            details={"filename": payload.filename},
        )
        return RegisterPluginResponse(name=payload.name, version=payload.version, digest=digest)

    @app.post("/jobs", response_model=EnqueueJobResponse)
    def enqueue_job(
        payload: EnqueueJobRequest,
        request: Request,
        db: Annotated[Session, Depends(get_db)],
        _: Annotated[None, Depends(require_admin_token)],
    ) -> EnqueueJobResponse:
        _ensure_not_maintenance_mode(request, "job.enqueue")
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
        _audit_important_action(
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

    @app.post("/agents/register", response_model=RegisterAgentResponse)
    def register_agent(payload: RegisterAgentRequest, request: Request, db: Annotated[Session, Depends(get_db)]) -> RegisterAgentResponse:
        _ensure_not_maintenance_mode(request, "agent.register")
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

    @app.post("/agents/heartbeat", response_model=AgentInfo)
    def heartbeat(
        request: Request,
        payload: HeartbeatRequest,
        db: Annotated[Session, Depends(get_db)],
        agent: Annotated[Agent, Depends(require_agent_auth)],
    ) -> AgentInfo:
        _ensure_not_maintenance_mode(request, "agent.heartbeat")
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
        logger.debug(
            "agent.heartbeat agent_id=%s active_leases=%s max_concurrency=%s",
            agent.id,
            agent.active_leases,
            agent.max_concurrency,
        )
        return AgentInfo(
            agent_id=agent.id,
            tags=agent.tags,
            active_leases=agent.active_leases,
            max_concurrency=agent.max_concurrency,
            status=agent.status,
            cpu_load_pct=agent.cpu_load_pct,
            ram_load_pct=agent.ram_load_pct,
        )

    @app.post("/agents/jobs/next", response_model=NextJobResponse)
    def next_job(
        request: Request,
        db: Annotated[Session, Depends(get_db)],
        agent: Annotated[Agent, Depends(require_agent_auth)],
    ) -> NextJobResponse:
        _ensure_not_maintenance_mode(request, "job.lease")
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

        job = db.scalar(
            select(Job).where(Job.id == lease_job.id).options()
        )
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

    @app.get("/plugins/{name}/manifest", response_model=PluginManifest)
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

    @app.get("/plugins/{name}/download")
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
        path = store.resolve(plugin_version.filename)
        if not path.exists():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="artifact missing on disk")
        logger.info("plugin.download.requested name=%s version=%s file=%s", plugin.name, plugin_version.version, path.name)
        return FileResponse(path, filename=path.name, media_type="application/octet-stream")

    @app.post("/executions/{execution_id}/result")
    def report_result(
        execution_id: str,
        payload: ExecutionResult,
        request: Request,
        db: Annotated[Session, Depends(get_db)],
        agent: Annotated[Agent, Depends(require_agent_auth)],
    ) -> dict:
        _ensure_not_maintenance_mode(request, "execution.result")
        execution = db.scalar(select(Execution).where(Execution.id == execution_id))
        if not execution:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="execution not found")
        if execution.agent_id != agent.id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="execution does not belong to agent")
        if execution.status != ExecutionStatus.leased:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="execution already finalized")
        if utc_now_naive() > execution.lease_expires_at:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="stale lease")

        job = db.scalar(select(Job).where(Job.id == execution.job_id))
        if not job:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="job missing for execution")

        mapped_status = ExecutionStatus(payload.status.value)
        execution.status = mapped_status
        execution.result_payload = payload.metrics
        execution.exit_code = payload.exit_code
        execution.stdout = payload.stdout
        execution.stderr = payload.stderr
        execution.completed_at = utc_now_naive()

        if payload.status == payload.status.completed:
            job.status = JobStatus.completed
            job.completed_at = utc_now_naive()
            job.next_retry_at = None
        else:
            queue: QueueAdapter = request.app.state.queue
            if job.attempt_count < job.max_attempts:
                job.status = JobStatus.queued
                job.next_retry_at = utc_now_naive() + timedelta(seconds=job.retry_backoff_seconds)
                queue.enqueue(job.id)
                logger.info(
                    "job.retry.scheduled job_id=%s attempt=%s/%s next_retry_at=%s",
                    job.id,
                    job.attempt_count,
                    job.max_attempts,
                    job.next_retry_at.isoformat(),
                )
            else:
                job.status = JobStatus.failed
                job.completed_at = utc_now_naive()
                job.next_retry_at = None
        if agent.active_leases > 0:
            agent.active_leases -= 1
        db.commit()
        logger.info(
            "execution.result.accepted execution_id=%s job_id=%s agent_id=%s status=%s exit_code=%s",
            execution.id,
            execution.job_id,
            agent.id,
            execution.status.value,
            execution.exit_code,
        )
        return {"status": "accepted", "execution_id": execution_id}

    @app.post("/executions/{execution_id}/checkpoint", response_model=ExecutionCheckpointResponse)
    def upsert_checkpoint(
        execution_id: str,
        payload: ExecutionCheckpointUpsert,
        request: Request,
        db: Annotated[Session, Depends(get_db)],
        agent: Annotated[Agent, Depends(require_agent_auth)],
    ) -> ExecutionCheckpointResponse:
        _ensure_not_maintenance_mode(request, "execution.checkpoint")
        execution = db.scalar(select(Execution).where(Execution.id == execution_id))
        if not execution:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="execution not found")
        if execution.agent_id != agent.id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="execution does not belong to agent")
        checkpoint = ExecutionCheckpoint(execution_id=execution.id, payload=payload.payload)
        db.add(checkpoint)
        db.commit()
        logger.info("execution.checkpoint.saved execution_id=%s keys=%s", execution.id, sorted(payload.payload.keys()))
        return ExecutionCheckpointResponse(execution_id=execution.id, checkpoint_payload=payload.payload)

    @app.get("/executions/{execution_id}/checkpoint/latest", response_model=ExecutionCheckpointResponse)
    def latest_checkpoint(
        execution_id: str,
        db: Annotated[Session, Depends(get_db)],
        agent: Annotated[Agent, Depends(require_agent_auth)],
    ) -> ExecutionCheckpointResponse:
        execution = db.scalar(select(Execution).where(Execution.id == execution_id))
        if not execution:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="execution not found")
        if execution.agent_id != agent.id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="execution does not belong to agent")
        checkpoint = db.scalar(
            select(ExecutionCheckpoint)
            .where(ExecutionCheckpoint.execution_id == execution.id)
            .order_by(ExecutionCheckpoint.created_at.desc(), ExecutionCheckpoint.id.desc())
        )
        return ExecutionCheckpointResponse(
            execution_id=execution.id,
            checkpoint_payload=checkpoint.payload if checkpoint else None,
        )

    @app.get("/jobs/{job_id}/progress", response_model=JobProgressResponse)
    def job_progress(
        job_id: str,
        db: Annotated[Session, Depends(get_db)],
        _: Annotated[None, Depends(require_admin_token)],
    ) -> JobProgressResponse:
        job = db.scalar(select(Job).where(Job.id == job_id))
        if not job:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="job not found")
        latest_execution = db.scalar(
            select(Execution).where(Execution.job_id == job.id).order_by(Execution.created_at.desc())
        )
        checkpoint_payload = _latest_checkpoint_for_job(db, job.id)
        return JobProgressResponse(
            job_id=job.id,
            status=job.status.value,
            attempt_count=job.attempt_count,
            max_attempts=job.max_attempts,
            latest_execution_id=latest_execution.id if latest_execution else None,
            checkpoint_payload=checkpoint_payload,
        )

    @app.get("/dashboard/api/overview")
    def dashboard_overview(
        request: Request,
        db: Annotated[Session, Depends(get_db)],
        x_admin_token: Annotated[str | None, Header(alias="X-Admin-Token")] = None,
    ) -> dict:
        actor = _get_dashboard_user(request)
        backup_service: BackupService = request.app.state.backup_service
        if actor is None:
            settings_obj: Settings = request.app.state.settings
            if x_admin_token != settings_obj.admin_token:
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="dashboard auth required")
            actor = {"username": "token_admin", "role": UserRole.superadmin.value}

        settings_obj: Settings = request.app.state.settings
        now = utc_now_naive()
        total_agents = db.scalar(select(func.count(Agent.id))) or 0
        queued_jobs = db.scalar(select(func.count(Job.id)).where(Job.status == JobStatus.queued)) or 0
        running_jobs = db.scalar(select(func.count(Job.id)).where(Job.status == JobStatus.leased)) or 0
        completed_jobs = db.scalar(select(func.count(Job.id)).where(Job.status == JobStatus.completed)) or 0
        failed_jobs = db.scalar(select(func.count(Job.id)).where(Job.status == JobStatus.failed)) or 0

        agents_all = list(db.scalars(select(Agent).order_by(Agent.last_heartbeat_at.desc(), Agent.created_at.desc())))
        running_by_agent = {
            agent_id: int(count)
            for agent_id, count in db.execute(
                select(Execution.agent_id, func.count(Execution.id))
                .where(Execution.status == ExecutionStatus.leased, Execution.lease_expires_at > now)
                .group_by(Execution.agent_id)
            )
        }
        deduped_agents: list[Agent] = []
        seen_names: set[str] = set()
        for agent in agents_all:
            key = (agent.name or "").strip().lower()
            if key and key in seen_names:
                continue
            if key:
                seen_names.add(key)
            deduped_agents.append(agent)
            if len(deduped_agents) >= 30:
                break
        jobs = list(db.scalars(select(Job).order_by(Job.created_at.desc()).limit(50)))
        executions = list(db.scalars(select(Execution).order_by(Execution.created_at.desc()).limit(50)))

        plugin_name_map: dict[int, str] = {p.id: p.name for p in db.scalars(select(Plugin))}
        plugin_version_map: dict[int, str] = {pv.id: pv.version for pv in db.scalars(select(PluginVersion))}

        jobs_payload: list[dict] = []
        for job in jobs:
            latest_execution = db.scalar(
                select(Execution).where(Execution.job_id == job.id).order_by(Execution.created_at.desc())
            )
            jobs_payload.append(
                {
                    "job_id": job.id,
                    "status": job.status.value,
                    "attempt_count": job.attempt_count,
                    "max_attempts": job.max_attempts,
                    "plugin_name": plugin_name_map.get(job.plugin_id, "unknown"),
                    "plugin_version": plugin_version_map.get(job.plugin_version_id, "unknown"),
                    "latest_execution_id": latest_execution.id if latest_execution else None,
                    "checkpoint_payload": _latest_checkpoint_for_job(db, job.id),
                }
            )

        job_progression = []
        for job_data in jobs_payload:
            cp = job_data.get("checkpoint_payload") or {}
            if isinstance(cp, dict) and isinstance(cp.get("step"), int) and isinstance(cp.get("total"), int) and cp.get("total", 0) > 0:
                pct = max(0, min(100, int((cp["step"] / cp["total"]) * 100)))
            else:
                pct = 0
            job_progression.append(
                {
                    "job_id": job_data["job_id"],
                    "status": job_data["status"],
                    "attempts": f"{job_data['attempt_count']}/{job_data['max_attempts']}",
                    "progress_pct": pct,
                }
            )
        job_progression.sort(key=lambda row: row["progress_pct"], reverse=True)

        latest_logs = []
        for execution in executions[:20]:
            raw = (execution.stderr or "").strip() or (execution.stdout or "").strip()
            if not raw:
                continue
            first_line = raw.splitlines()[0][:180]
            latest_logs.append(
                {
                    "execution_id": execution.id,
                    "job_id": execution.job_id,
                    "status": execution.status.value,
                    "line": first_line,
                }
            )

        return {
            "schema_version": "v1",
            "auth": {
                "username": actor["username"],
                "role": actor["role"],
                "is_superadmin": actor["role"] == UserRole.superadmin.value,
            },
            "metrics": {
                "total_agents": total_agents,
                "queued_jobs": queued_jobs,
                "running_jobs": running_jobs,
                "completed_jobs": completed_jobs,
                "failed_jobs": failed_jobs,
            },
            "agents": [
                {
                    "agent_id": agent.id,
                    "name": agent.name,
                    "status": (
                        "online"
                        if agent.last_heartbeat_at
                        and (now - agent.last_heartbeat_at).total_seconds() <= settings_obj.heartbeat_ttl_seconds
                        else "offline"
                    ),
                    "active_leases": running_by_agent.get(agent.id, max(0, int(agent.active_leases or 0))),
                    "max_concurrency": agent.max_concurrency,
                    "load_pct": min(
                        100,
                        max(
                            0,
                            int(
                                (
                                    running_by_agent.get(agent.id, max(0, int(agent.active_leases or 0)))
                                    / max(1, int(agent.max_concurrency or 1))
                                )
                                * 100
                            ),
                        ),
                    ),
                    "cpu_load_pct": agent.cpu_load_pct,
                    "ram_load_pct": agent.ram_load_pct,
                    "tags": agent.tags,
                }
                for agent in deduped_agents
            ],
            "jobs": jobs_payload,
            "job_progression": job_progression[:8],
            "latest_logs": latest_logs[:12],
            "backup_summary": backup_service.backup_summary(),
            "executions": [
                {
                    "execution_id": execution.id,
                    "job_id": execution.job_id,
                    "agent_id": execution.agent_id,
                    "status": execution.status.value,
                    "exit_code": execution.exit_code,
                    "created_at": execution.created_at.isoformat() if execution.created_at else None,
                }
                for execution in executions
            ],
        }

    @app.post("/superadmin/users")
    async def superadmin_create_user(request: Request) -> dict:
        actor = _require_superadmin_session(request)
        _ensure_not_maintenance_mode(request, "user.create")
        payload = await request.json()
        username = (payload.get("username") or "").strip()
        password = (payload.get("password") or "").strip()
        role = (payload.get("role") or UserRole.operator.value).strip()
        if role not in {UserRole.superadmin.value, UserRole.admin.value, UserRole.operator.value}:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid role")
        if len(username) < 3 or len(password) < 6:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="username/password too short")

        db = request.app.state.session_factory()
        existing = db.scalar(select(User).where(User.username == username))
        if existing:
            db.close()
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="username already exists")
        user = User(username=username, password_hash=hash_password(password), role=role, is_active=True)
        db.add(user)
        db.commit()
        db.close()

        _write_audit_log(
            request.app.state.session_factory(),
            actor_username=actor["username"],
            actor_role=actor["role"],
            action="user.create",
            resource_type="user",
            resource_id=username,
            details={"role": role},
            ip_address=_request_ip(request),
            user_agent=request.headers.get("user-agent"),
        )
        return {"status": "created", "username": username, "role": role}

    @app.post("/superadmin/debug/enqueue-random")
    def superadmin_debug_enqueue_random(
        request: Request,
        db: Annotated[Session, Depends(get_db)],
    ) -> dict:
        actor = _require_superadmin_session(request)
        _ensure_not_maintenance_mode(request, "debug.enqueue_random")
        queue: QueueAdapter = request.app.state.queue
        store: PluginStore = request.app.state.plugin_store

        plugin_name = "echo"
        plugin_version_value = "1.0.0"
        plugin_filename = "echo_plugin.py"

        plugin = db.scalar(select(Plugin).where(Plugin.name == plugin_name))
        if not plugin:
            plugin = Plugin(name=plugin_name)
            db.add(plugin)
            db.flush()

        plugin_version = db.scalar(
            select(PluginVersion).where(
                PluginVersion.plugin_id == plugin.id,
                PluginVersion.version == plugin_version_value,
            )
        )
        if not plugin_version:
            digest = store.digest_file(plugin_filename)
            plugin_version = PluginVersion(
                plugin_id=plugin.id,
                version=plugin_version_value,
                digest=digest,
                filename=plugin_filename,
                timeout_seconds=30,
                entrypoint="python",
            )
            db.add(plugin_version)
            db.flush()

        mode_roll = random.random()
        if mode_roll < 0.12:
            payload = {"action": "fail", "code": random.choice([1, 2, 3]), "message": "debug fail sample"}
            mode = "fail"
        elif mode_roll < 0.82:
            secs = random.choice([4, 5, 6, 7, 8, 10])
            payload = {"action": "sleep", "seconds": secs, "message": f"debug sleep {secs}s"}
            mode = "sleep"
        else:
            phrase = random.choice(
                [
                    "quick health check",
                    "latency probe",
                    "worker load sample",
                    "dashboard debug event",
                    "pipeline smoke ping",
                ]
            )
            payload = {"action": "echo", "message": phrase}
            mode = "echo"

        job_id = _new_job_id()
        job = Job(
            id=job_id,
            plugin_id=plugin.id,
            plugin_version_id=plugin_version.id,
            payload=payload,
            required_tags=["default"],
            max_attempts=2,
            attempt_count=0,
            retry_backoff_seconds=2,
            next_retry_at=utc_now_naive(),
            status=JobStatus.queued,
        )
        db.add(job)
        db.commit()
        queue.enqueue(job.id)

        _write_audit_log(
            request.app.state.session_factory(),
            actor_username=actor["username"],
            actor_role=actor["role"],
            action="debug.job.enqueue_random",
            resource_type="job",
            resource_id=job.id,
            details={"mode": mode},
            ip_address=_request_ip(request),
            user_agent=request.headers.get("user-agent"),
        )
        return {"status": "queued", "job_id": job.id, "mode": mode}

    @app.get("/superadmin/audit/logs")
    def superadmin_audit_logs(request: Request, limit: int = 100) -> dict:
        _require_superadmin_session(request)
        safe_limit = max(1, min(limit, 200))
        db = request.app.state.session_factory()
        rows = list(db.scalars(select(AuditLog).order_by(AuditLog.created_at.desc(), AuditLog.id.desc()).limit(safe_limit)))
        db.close()
        return {
            "logs": [
                {
                    "id": row.id,
                    "at": row.created_at.isoformat(),
                    "actor_username": row.actor_username,
                    "actor_role": row.actor_role,
                    "action": row.action,
                    "resource_type": row.resource_type,
                    "resource_id": row.resource_id,
                    "ip_address": row.ip_address,
                    "user_agent": row.user_agent,
                    "details": row.details,
                }
                for row in rows
            ]
        }

    @app.get("/superadmin/audit/logs/export")
    def superadmin_audit_logs_export(request: Request, limit: int = 1000) -> Response:
        _require_superadmin_session(request)
        safe_limit = max(1, min(limit, 5000))
        db = request.app.state.session_factory()
        rows = list(db.scalars(select(AuditLog).order_by(AuditLog.created_at.desc(), AuditLog.id.desc()).limit(safe_limit)))
        db.close()
        csv_lines = [
            "id,at,actor_username,actor_role,action,resource_type,resource_id,ip_address,user_agent,details_json"
        ]
        for row in rows:
            def _q(v):
                raw = "" if v is None else str(v)
                return '"' + raw.replace('"', '""') + '"'
            csv_lines.append(
                ",".join(
                    [
                        _q(row.id),
                        _q(row.created_at.isoformat() if row.created_at else ""),
                        _q(row.actor_username),
                        _q(row.actor_role),
                        _q(row.action),
                        _q(row.resource_type),
                        _q(row.resource_id),
                        _q(row.ip_address),
                        _q(row.user_agent),
                        _q(row.details),
                    ]
                )
            )
        content = "\n".join(csv_lines) + "\n"
        filename = f"aurora_audit_logs_{utc_now_naive().strftime('%Y%m%d_%H%M%S')}.csv"
        headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
        return Response(content=content, media_type="text/csv; charset=utf-8", headers=headers)

    @app.post("/superadmin/backups/create")
    def superadmin_backup_create(request: Request) -> dict:
        actor = _require_superadmin_session(request)
        service: BackupService = request.app.state.backup_service
        result = service.create_backup(created_by=actor["username"])
        _write_audit_log(
            request.app.state.session_factory(),
            actor_username=actor["username"],
            actor_role=actor["role"],
            action="backup.create",
            resource_type="backup",
            resource_id=result["backup_id"],
            details={"size_bytes": result["size_bytes"]},
            ip_address=_request_ip(request),
            user_agent=request.headers.get("user-agent"),
        )
        return result

    @app.get("/superadmin/backups")
    def superadmin_backup_list(request: Request, limit: int = 100) -> dict:
        _require_superadmin_session(request)
        service: BackupService = request.app.state.backup_service
        return {"backups": service.list_backups(limit=limit)}

    @app.post("/superadmin/backups/{backup_id}/validate")
    def superadmin_backup_validate(request: Request, backup_id: str) -> dict:
        actor = _require_superadmin_session(request)
        service: BackupService = request.app.state.backup_service
        result = service.validate_backup(backup_id)
        if not result.get("found"):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="backup not found")
        _write_audit_log(
            request.app.state.session_factory(),
            actor_username=actor["username"],
            actor_role=actor["role"],
            action="backup.validate",
            resource_type="backup",
            resource_id=backup_id,
            details={"valid": result.get("valid"), "issues": result.get("issues", [])},
            ip_address=_request_ip(request),
            user_agent=request.headers.get("user-agent"),
        )
        return result

    @app.post("/superadmin/backups/prune")
    def superadmin_backup_prune(request: Request) -> dict:
        actor = _require_superadmin_session(request)
        service: BackupService = request.app.state.backup_service
        result = service.prune_backups()
        _write_audit_log(
            request.app.state.session_factory(),
            actor_username=actor["username"],
            actor_role=actor["role"],
            action="backup.prune",
            resource_type="backup",
            resource_id="policy",
            details=result,
            ip_address=_request_ip(request),
            user_agent=request.headers.get("user-agent"),
        )
        return result

    @app.get("/superadmin/backups/policy")
    def superadmin_backup_policy(request: Request) -> dict:
        _require_superadmin_session(request)
        settings_obj: Settings = request.app.state.settings
        service: BackupService = request.app.state.backup_service
        db = request.app.state.session_factory()
        non_pruned = (
            db.scalar(select(func.count()).select_from(BackupRecord).where(BackupRecord.status != BackupStatus.pruned))
            or 0
        )
        db.close()
        return {
            "backup_dir": str(settings_obj.backup_dir),
            "max_storage_gb": settings_obj.backup_max_storage_gb,
            "retention": {
                "daily": settings_obj.backup_retention_daily,
                "weekly": settings_obj.backup_retention_weekly,
                "monthly": settings_obj.backup_retention_monthly,
            },
            "scheduler": {
                "enabled": settings_obj.backup_scheduler_enabled,
                "create_minutes": settings_obj.backup_schedule_create_minutes,
                "validate_minutes": settings_obj.backup_schedule_validate_minutes,
                "prune_minutes": settings_obj.backup_schedule_prune_minutes,
                "restore_drill_minutes": settings_obj.backup_schedule_restore_drill_minutes,
            },
            "offsite_dir": str(settings_obj.backup_offsite_dir) if settings_obj.backup_offsite_dir else None,
            "non_pruned_count": int(non_pruned),
            "maintenance_mode": service.get_maintenance_mode(),
        }

    @app.post("/superadmin/backups/{backup_id}/offsite-sync")
    def superadmin_backup_offsite_sync(request: Request, backup_id: str) -> dict:
        actor = _require_superadmin_session(request)
        service: BackupService = request.app.state.backup_service
        result = service.sync_backup_offsite(backup_id)
        if not result.get("found"):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="backup not found")
        _write_audit_log(
            request.app.state.session_factory(),
            actor_username=actor["username"],
            actor_role=actor["role"],
            action="backup.offsite_sync",
            resource_type="backup",
            resource_id=backup_id,
            details=result,
            ip_address=_request_ip(request),
            user_agent=request.headers.get("user-agent"),
        )
        return result

    @app.get("/superadmin/backups/{backup_id}/manifest/download")
    def superadmin_backup_manifest_download(request: Request, backup_id: str) -> FileResponse:
        _require_superadmin_session(request)
        db = request.app.state.session_factory()
        row = db.scalar(select(BackupRecord).where(BackupRecord.id == backup_id))
        db.close()
        if not row:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="backup not found")
        manifest_path = Path(row.storage_path) / "manifest.json"
        if not manifest_path.exists():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="manifest file missing")
        return FileResponse(
            manifest_path,
            filename=f"{backup_id}_manifest.json",
            media_type="application/json",
        )

    @app.post("/superadmin/backups/{backup_id}/restore")
    async def superadmin_backup_restore(request: Request, backup_id: str, dry_run: bool = True) -> dict:
        actor = _require_superadmin_session(request)
        service: BackupService = request.app.state.backup_service
        payload = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
        confirm = (payload.get("confirm") or "").strip() if isinstance(payload, dict) else ""
        if not dry_run and confirm != backup_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="confirmation required: provide JSON body {\"confirm\":\"<backup_id>\"}",
            )

        if dry_run:
            result = service.restore_backup(backup_id=backup_id, dry_run=True)
        else:
            service.set_maintenance_mode(
                enabled=True,
                actor=actor["username"],
                reason=f"restore backup {backup_id}",
            )
            try:
                result = service.restore_backup(backup_id=backup_id, dry_run=False)
            finally:
                service.set_maintenance_mode(
                    enabled=False,
                    actor=actor["username"],
                    reason=f"restore backup {backup_id} finished",
                )
        if not result.get("found"):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="backup not found")
        _write_audit_log(
            request.app.state.session_factory(),
            actor_username=actor["username"],
            actor_role=actor["role"],
            action="backup.restore.dry_run" if dry_run else "backup.restore",
            resource_type="backup",
            resource_id=backup_id,
            details={
                "dry_run": dry_run,
                "ok": result.get("ok"),
                "message": result.get("message"),
            },
            ip_address=_request_ip(request),
            user_agent=request.headers.get("user-agent"),
        )
        if not result.get("ok"):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=result.get("message", "restore failed"))
        return result

    return app


def _build_queue(settings: Settings) -> QueueAdapter:
    if settings.use_inmemory_queue:
        return InMemoryQueue()
    return RedisQueue(settings.redis_url, settings.queue_name)


app = create_app()


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
    adjectives = (
        "North",
        "South",
        "East",
        "West",
        "Swift",
        "Bright",
        "Calm",
        "Solid",
    )
    nouns = (
        "Falcon",
        "Otter",
        "Raven",
        "Panda",
        "Lynx",
        "Cedar",
        "Comet",
        "Harbor",
    )
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


def _is_dashboard_session_valid(request: Request) -> bool:
    return _get_dashboard_user(request) is not None


def _get_dashboard_user(request: Request) -> dict | None:
    session_id = request.cookies.get("aurora_dashboard_session")
    if not session_id:
        return None
    sessions = request.app.state.dashboard_sessions
    session = sessions.get(session_id)
    if not session:
        return None
    expiry = session.get("expires_at")
    now = utc_now_naive()
    if not expiry or expiry < now:
        sessions.pop(session_id, None)
        return None
    return {"username": session.get("username"), "role": session.get("role")}


def _require_superadmin_session(request: Request) -> dict:
    actor = _get_dashboard_user(request)
    if not actor:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="login required")
    if actor.get("role") != UserRole.superadmin.value:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="superadmin required")
    return actor


def _is_maintenance_mode(request: Request) -> dict:
    db = request.app.state.session_factory()
    try:
        row = db.scalar(select(SystemFlag).where(SystemFlag.key == "maintenance_mode"))
    finally:
        db.close()
    if not row:
        return {"enabled": False}
    payload = row.value_json or {}
    payload.setdefault("enabled", False)
    return payload


def _ensure_not_maintenance_mode(request: Request, action: str) -> None:
    maintenance = _is_maintenance_mode(request)
    if not maintenance.get("enabled"):
        return
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={
            "message": "maintenance mode active",
            "action": action,
            "updated_by": maintenance.get("updated_by"),
            "reason": maintenance.get("reason"),
            "updated_at": maintenance.get("updated_at"),
        },
    )


def _request_ip(request: Request) -> str | None:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client:
        return request.client.host
    return None


def _write_audit_log(
    db: Session,
    actor_username: str | None,
    actor_role: str | None,
    action: str,
    resource_type: str | None,
    resource_id: str | None,
    details: dict,
    ip_address: str | None,
    user_agent: str | None,
) -> None:
    try:
        row = AuditLog(
            actor_username=actor_username,
            actor_role=actor_role,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            details=details or {},
            ip_address=ip_address,
            user_agent=user_agent,
        )
        db.add(row)
        db.commit()
    finally:
        db.close()


def _audit_important_action(
    request: Request,
    db_factory,
    action: str,
    resource_type: str | None,
    resource_id: str | None,
    details: dict,
) -> None:
    actor = _get_dashboard_user(request)
    if actor:
        actor_username = actor["username"]
        actor_role = actor["role"]
    else:
        actor_username = "token_admin"
        actor_role = UserRole.superadmin.value
    _write_audit_log(
        db_factory(),
        actor_username=actor_username,
        actor_role=actor_role,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        details=details,
        ip_address=_request_ip(request),
        user_agent=request.headers.get("user-agent"),
    )


def _bootstrap_superadmin(app_ref: FastAPI) -> None:
    settings_obj: Settings = app_ref.state.settings
    db = app_ref.state.session_factory()
    try:
        existing = db.scalar(select(User).where(User.username == settings_obj.superadmin_username))
        if existing:
            return
        user = User(
            username=settings_obj.superadmin_username,
            password_hash=hash_password(settings_obj.superadmin_password),
            role=UserRole.superadmin.value,
            is_active=True,
        )
        db.add(user)
        db.commit()
        logger.warning(
            "superadmin.bootstrap.created username=%s (set AURORA_SUPERADMIN_USERNAME/PASSWORD in production)",
            settings_obj.superadmin_username,
        )
    finally:
        db.close()
