from __future__ import annotations

import random
import secrets
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, Response, status
from fastapi.responses import FileResponse
from sqlalchemy import func, select

from aurora_core.utils.auth_utils import hash_password
from aurora_core.services.backup_service import BackupService
from aurora_core.config import Settings
from aurora_core.services.maintenance import ensure_not_maintenance_mode
from aurora_core.services.models import BackupRecord, BackupStatus, Job, JobStatus, Plugin, PluginVersion, User, UserRole, AuditLog
from aurora_core.services.plugin_store import PluginStore
from aurora_core.services.queue import QueueAdapter
from aurora_core.utils.timeutils import utc_now_naive
from aurora_core.services.web_auth import request_ip, require_superadmin_session, write_audit_log

router = APIRouter()


@router.post("/superadmin/users")
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


@router.post("/superadmin/debug/enqueue-random")
def superadmin_debug_enqueue_random(request: Request) -> dict:
    actor = require_superadmin_session(request)
    ensure_not_maintenance_mode(request, "debug.enqueue_random")
    db = request.app.state.session_factory()
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
    db.close()
    queue.enqueue(job_id)

    write_audit_log(
        request.app.state.session_factory(),
        actor_username=actor["username"],
        actor_role=actor["role"],
        action="debug.job.enqueue_random",
        resource_type="job",
        resource_id=job_id,
        details={"mode": mode},
        ip_address=request_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    return {"status": "queued", "job_id": job_id, "mode": mode}


@router.get("/superadmin/audit/logs")
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


@router.get("/superadmin/audit/logs/export")
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


@router.post("/superadmin/backups/create")
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


@router.get("/superadmin/backups")
def superadmin_backup_list(request: Request, limit: int = 100) -> dict:
    require_superadmin_session(request)
    service: BackupService = request.app.state.backup_service
    return {"backups": service.list_backups(limit=limit)}


@router.post("/superadmin/backups/{backup_id}/validate")
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


@router.post("/superadmin/backups/prune")
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


@router.get("/superadmin/backups/policy")
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


@router.get("/superadmin/backups/health")
def superadmin_backup_health(request: Request) -> dict:
    require_superadmin_session(request)
    service: BackupService = request.app.state.backup_service
    return {"health": service.backup_summary()}


@router.post("/superadmin/backups/{backup_id}/offsite-sync")
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


@router.get("/superadmin/backups/{backup_id}/manifest/download")
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


@router.post("/superadmin/backups/{backup_id}/restore")
async def superadmin_backup_restore(request: Request, backup_id: str, dry_run: bool = True) -> dict:
    actor = require_superadmin_session(request)
    service: BackupService = request.app.state.backup_service
    payload = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
    confirm = (payload.get("confirm") or "").strip() if isinstance(payload, dict) else ""
    if not dry_run and confirm != backup_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail='confirmation required: provide JSON body {"confirm":"<backup_id>"}',
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


def _new_job_id() -> str:
    ts = utc_now_naive().strftime("%Y%m%d_%H%M%S")
    suffix = secrets.token_hex(2).upper()
    return f"JOB_{ts}_{suffix}"

