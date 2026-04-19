from __future__ import annotations

import logging
import random
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response, status
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from aurora_core.auth_utils import hash_password
from aurora_core.backup_scheduler import BackupScheduler
from aurora_core.backup_service import BackupService
from aurora_core.config import Settings, get_settings
from aurora_core.db import create_session_factory
from aurora_core.maintenance import ensure_not_maintenance_mode
from aurora_core.models import (
    Agent,
    AuditLog,
    BackupRecord,
    BackupStatus,
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
from aurora_core.routes.auth import router as auth_router
from aurora_core.routes.operations import router as operations_router
from aurora_core.routing import DefaultStaticRoutingStrategy
from aurora_core.schemas import (
    EnqueueJobRequest,
    EnqueueJobResponse,
)
from aurora_core.security import get_db
from aurora_core.schema_guard import ensure_schema_ready
from aurora_core.timeutils import utc_now_naive
from aurora_core.web_auth import (
    get_dashboard_user,
    request_ip,
    require_superadmin_session,
    write_audit_log,
)

logger = logging.getLogger("aurora-core")


def create_app(settings: Settings | None = None) -> FastAPI:
    effective_settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app_ref: FastAPI):
        ensure_schema_ready(app_ref.state.settings, auto_repair=app_ref.state.settings.schema_auto_repair_on_startup)
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
    app.include_router(auth_router)
    app.include_router(operations_router)

    @app.get("/dashboard/api/overview")
    def dashboard_overview(
        request: Request,
        db: Annotated[Session, Depends(get_db)],
        x_admin_token: Annotated[str | None, Header(alias="X-Admin-Token")] = None,
    ) -> dict:
        actor = get_dashboard_user(request)
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
        actor = require_superadmin_session(request)
        ensure_not_maintenance_mode(request, "user.create")
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

        write_audit_log(
            request.app.state.session_factory(),
            actor_username=actor["username"],
            actor_role=actor["role"],
            action="user.create",
            resource_type="user",
            resource_id=username,
            details={"role": role},
            ip_address=request_ip(request),
            user_agent=request.headers.get("user-agent"),
        )
        return {"status": "created", "username": username, "role": role}

    @app.post("/superadmin/debug/enqueue-random")
    def superadmin_debug_enqueue_random(
        request: Request,
        db: Annotated[Session, Depends(get_db)],
    ) -> dict:
        actor = require_superadmin_session(request)
        ensure_not_maintenance_mode(request, "debug.enqueue_random")
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

        write_audit_log(
            request.app.state.session_factory(),
            actor_username=actor["username"],
            actor_role=actor["role"],
            action="debug.job.enqueue_random",
            resource_type="job",
            resource_id=job.id,
            details={"mode": mode},
            ip_address=request_ip(request),
            user_agent=request.headers.get("user-agent"),
        )
        return {"status": "queued", "job_id": job.id, "mode": mode}

    @app.get("/superadmin/audit/logs")
    def superadmin_audit_logs(request: Request, limit: int = 100) -> dict:
        require_superadmin_session(request)
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
        require_superadmin_session(request)
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
        actor = require_superadmin_session(request)
        service: BackupService = request.app.state.backup_service
        result = service.create_backup(created_by=actor["username"])
        validation = result.get("validation") if isinstance(result.get("validation"), dict) else {}
        write_audit_log(
            request.app.state.session_factory(),
            actor_username=actor["username"],
            actor_role=actor["role"],
            action="backup.create",
            resource_type="backup",
            resource_id=result["backup_id"],
            details={
                "size_bytes": result["size_bytes"],
                "status": result.get("status"),
                "valid": bool(validation.get("valid")) if validation else None,
                "offsite_synced": bool((result.get("offsite") or {}).get("synced")),
            },
            ip_address=request_ip(request),
            user_agent=request.headers.get("user-agent"),
        )
        return result

    @app.get("/superadmin/backups")
    def superadmin_backup_list(request: Request, limit: int = 100) -> dict:
        require_superadmin_session(request)
        service: BackupService = request.app.state.backup_service
        return {"backups": service.list_backups(limit=limit)}

    @app.post("/superadmin/backups/{backup_id}/validate")
    def superadmin_backup_validate(request: Request, backup_id: str) -> dict:
        actor = require_superadmin_session(request)
        service: BackupService = request.app.state.backup_service
        result = service.validate_backup(backup_id)
        if not result.get("found"):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="backup not found")
        write_audit_log(
            request.app.state.session_factory(),
            actor_username=actor["username"],
            actor_role=actor["role"],
            action="backup.validate",
            resource_type="backup",
            resource_id=backup_id,
            details={"valid": result.get("valid"), "issues": result.get("issues", [])},
            ip_address=request_ip(request),
            user_agent=request.headers.get("user-agent"),
        )
        return result

    @app.post("/superadmin/backups/prune")
    def superadmin_backup_prune(request: Request) -> dict:
        actor = require_superadmin_session(request)
        service: BackupService = request.app.state.backup_service
        result = service.prune_backups()
        write_audit_log(
            request.app.state.session_factory(),
            actor_username=actor["username"],
            actor_role=actor["role"],
            action="backup.prune",
            resource_type="backup",
            resource_id="policy",
            details=result,
            ip_address=request_ip(request),
            user_agent=request.headers.get("user-agent"),
        )
        return result

    @app.get("/superadmin/backups/policy")
    def superadmin_backup_policy(request: Request) -> dict:
        require_superadmin_session(request)
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
                "min_keep_count": settings_obj.backup_prune_min_keep_count,
            },
            "scheduler": {
                "enabled": settings_obj.backup_scheduler_enabled,
                "create_minutes": settings_obj.backup_schedule_create_minutes,
                "validate_minutes": settings_obj.backup_schedule_validate_minutes,
                "prune_minutes": settings_obj.backup_schedule_prune_minutes,
                "restore_drill_minutes": settings_obj.backup_schedule_restore_drill_minutes,
            },
            "defaults": {
                "validate_after_create": settings_obj.backup_validate_after_create,
            },
            "offsite_dir": str(settings_obj.backup_offsite_dir) if settings_obj.backup_offsite_dir else None,
            "non_pruned_count": int(non_pruned),
            "maintenance_mode": service.get_maintenance_mode(),
        }

    @app.get("/superadmin/backups/health")
    def superadmin_backup_health(request: Request) -> dict:
        require_superadmin_session(request)
        service: BackupService = request.app.state.backup_service
        return {"health": service.backup_summary()}

    @app.post("/superadmin/backups/{backup_id}/offsite-sync")
    def superadmin_backup_offsite_sync(request: Request, backup_id: str) -> dict:
        actor = require_superadmin_session(request)
        service: BackupService = request.app.state.backup_service
        result = service.sync_backup_offsite(backup_id)
        if not result.get("found"):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="backup not found")
        write_audit_log(
            request.app.state.session_factory(),
            actor_username=actor["username"],
            actor_role=actor["role"],
            action="backup.offsite_sync",
            resource_type="backup",
            resource_id=backup_id,
            details=result,
            ip_address=request_ip(request),
            user_agent=request.headers.get("user-agent"),
        )
        return result

    @app.get("/superadmin/backups/{backup_id}/manifest/download")
    def superadmin_backup_manifest_download(request: Request, backup_id: str) -> FileResponse:
        require_superadmin_session(request)
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
        actor = require_superadmin_session(request)
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
        write_audit_log(
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
            ip_address=request_ip(request),
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

