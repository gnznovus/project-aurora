from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from aurora_core.services.backup_service import BackupService
from aurora_core.config import Settings
from aurora_core.services.models import Agent, Execution, ExecutionCheckpoint, ExecutionStatus, Job, JobStatus, Plugin, PluginVersion, UserRole
from aurora_core.services.security import get_db
from aurora_core.utils.timeutils import utc_now_naive
from aurora_core.services.web_auth import get_dashboard_user

router = APIRouter()


@router.get("/dashboard/api/overview")
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


def _latest_checkpoint_for_job(db: Session, job_id: str) -> dict | None:
    checkpoint = db.scalar(
        select(ExecutionCheckpoint)
        .join(Execution, Execution.id == ExecutionCheckpoint.execution_id)
        .where(Execution.job_id == job_id)
        .order_by(ExecutionCheckpoint.created_at.desc(), ExecutionCheckpoint.id.desc())
    )
    return checkpoint.payload if checkpoint else None

