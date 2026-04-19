from __future__ import annotations

from fastapi import HTTPException, Request, status
from sqlalchemy.orm import Session

from aurora_core.models import AuditLog, UserRole
from aurora_core.timeutils import utc_now_naive


def get_dashboard_user(request: Request) -> dict | None:
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


def require_superadmin_session(request: Request) -> dict:
    actor = get_dashboard_user(request)
    if not actor:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="login required")
    if actor.get("role") != UserRole.superadmin.value:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="superadmin required")
    return actor


def request_ip(request: Request) -> str | None:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client:
        return request.client.host
    return None


def write_audit_log(
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


def audit_important_action(
    request: Request,
    db_factory,
    action: str,
    resource_type: str | None,
    resource_id: str | None,
    details: dict,
) -> None:
    actor = get_dashboard_user(request)
    if actor:
        actor_username = actor["username"]
        actor_role = actor["role"]
    else:
        actor_username = "token_admin"
        actor_role = UserRole.superadmin.value
    write_audit_log(
        db_factory(),
        actor_username=actor_username,
        actor_role=actor_role,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        details=details,
        ip_address=request_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
