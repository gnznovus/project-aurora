from __future__ import annotations

import logging
import secrets
import uuid
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, Request, status
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session

from aurora_core.auth_utils import hash_password, verify_password
from aurora_core.config import Settings, get_settings
from aurora_core.dashboard_html import DASHBOARD_HTML, LOGIN_HTML
from aurora_core.db import create_session_factory
from aurora_core.models import (
    Agent,
    AuditLog,
    Base,
    Execution,
    ExecutionCheckpoint,
    ExecutionStatus,
    Job,
    JobStatus,
    Plugin,
    PluginVersion,
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
        yield

    app = FastAPI(title="Aurora Core", version="0.1.0", lifespan=lifespan)
    app.state.settings = effective_settings
    app.state.session_factory = create_session_factory(effective_settings)
    app.state.queue = _build_queue(effective_settings)
    app.state.router_strategy = DefaultStaticRoutingStrategy(effective_settings.heartbeat_ttl_seconds)
    app.state.plugin_store = PluginStore(Path(effective_settings.plugins_dir))
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

        job_id = f"job_{uuid.uuid4().hex[:16]}"
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
        settings_obj: Settings = request.app.state.settings
        if payload.bootstrap_token != settings_obj.bootstrap_token:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid bootstrap token")

        agent = Agent(
            id=new_agent_id(),
            name=payload.agent_name,
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
        db: Annotated[Session, Depends(get_db)],
        agent: Annotated[Agent, Depends(require_agent_auth)],
    ) -> AgentInfo:
        db.execute(
            update(Agent)
            .where(Agent.id == agent.id)
            .values(last_heartbeat_at=utc_now_naive(), status="online")
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
        )

    @app.post("/agents/jobs/next", response_model=NextJobResponse)
    def next_job(
        request: Request,
        db: Annotated[Session, Depends(get_db)],
        agent: Annotated[Agent, Depends(require_agent_auth)],
    ) -> NextJobResponse:
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
        db: Annotated[Session, Depends(get_db)],
        agent: Annotated[Agent, Depends(require_agent_auth)],
    ) -> ExecutionCheckpointResponse:
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
        if actor is None:
            settings_obj: Settings = request.app.state.settings
            if x_admin_token != settings_obj.admin_token:
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="dashboard auth required")
            actor = {"username": "token_admin", "role": UserRole.superadmin.value}

        total_agents = db.scalar(select(func.count(Agent.id))) or 0
        queued_jobs = db.scalar(select(func.count(Job.id)).where(Job.status == JobStatus.queued)) or 0
        running_jobs = db.scalar(select(func.count(Job.id)).where(Job.status == JobStatus.leased)) or 0
        failed_jobs = db.scalar(select(func.count(Job.id)).where(Job.status == JobStatus.failed)) or 0

        agents = list(db.scalars(select(Agent).order_by(Agent.created_at.desc()).limit(30)))
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
                "failed_jobs": failed_jobs,
            },
            "agents": [
                {
                    "agent_id": agent.id,
                    "name": agent.name,
                    "status": agent.status,
                    "active_leases": agent.active_leases,
                    "max_concurrency": agent.max_concurrency,
                    "tags": agent.tags,
                }
                for agent in agents
            ],
            "jobs": jobs_payload,
            "job_progression": job_progression[:8],
            "latest_logs": latest_logs[:12],
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
