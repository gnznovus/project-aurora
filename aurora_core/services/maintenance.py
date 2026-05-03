from __future__ import annotations

from fastapi import HTTPException, Request, status
from sqlalchemy import select

from aurora_core.services.models import SystemFlag


def is_maintenance_mode(request: Request) -> dict:
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


def ensure_not_maintenance_mode(request: Request, action: str) -> None:
    maintenance = is_maintenance_mode(request)
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

