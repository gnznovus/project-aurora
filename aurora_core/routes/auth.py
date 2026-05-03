from __future__ import annotations

import secrets
from datetime import timedelta

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy import select

from aurora_core.utils.auth_utils import verify_password
from aurora_core.services.dashboard_html import DASHBOARD_HTML, LOGIN_HTML
from aurora_core.services.models import User, UserRole
from aurora_core.utils.timeutils import utc_now_naive
from aurora_core.services.web_auth import get_dashboard_user, request_ip, write_audit_log


router = APIRouter()


@router.get("/dashboard", response_class=HTMLResponse)
def dashboard() -> HTMLResponse:
    return HTMLResponse(content=DASHBOARD_HTML)


@router.get("/login", response_class=HTMLResponse)
def login_page() -> HTMLResponse:
    return HTMLResponse(content=LOGIN_HTML)


@router.get("/dashboard/login")
def dashboard_login_redirect() -> RedirectResponse:
    return RedirectResponse(url="/login", status_code=307)


@router.post("/login")
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
    write_audit_log(
        request.app.state.session_factory(),
        actor_username=actor_username,
        actor_role=actor_role,
        action="auth.login",
        resource_type="session",
        resource_id=session_id[:12],
        details={"message": "dashboard login success"},
        ip_address=request_ip(request),
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


@router.post("/dashboard/logout")
def dashboard_logout(request: Request) -> JSONResponse:
    session_id = request.cookies.get("aurora_dashboard_session")
    actor = get_dashboard_user(request)
    if session_id:
        request.app.state.dashboard_sessions.pop(session_id, None)
    if actor:
        write_audit_log(
            request.app.state.session_factory(),
            actor_username=actor["username"],
            actor_role=actor["role"],
            action="auth.logout",
            resource_type="session",
            resource_id=(session_id or "")[:12],
            details={},
            ip_address=request_ip(request),
            user_agent=request.headers.get("user-agent"),
        )
    response = JSONResponse({"status": "ok"})
    response.delete_cookie("aurora_dashboard_session", path="/")
    return response


@router.get("/dashboard/auth/status")
def dashboard_auth_status(request: Request) -> dict:
    actor = get_dashboard_user(request)
    if not actor:
        return {"authenticated": False}
    return {
        "authenticated": True,
        "username": actor["username"],
        "role": actor["role"],
        "is_superadmin": actor["role"] == UserRole.superadmin.value,
    }

