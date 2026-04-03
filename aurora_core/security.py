from __future__ import annotations

import secrets
import uuid
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from aurora_core.config import Settings
from aurora_core.models import Agent


def new_agent_id() -> str:
    return f"ag_{uuid.uuid4().hex[:16]}"


def new_api_key() -> str:
    return secrets.token_urlsafe(32)


def require_admin_token(
    request: Request,
    x_admin_token: Annotated[str | None, Header(alias="X-Admin-Token")] = None,
) -> None:
    settings: Settings = request.app.state.settings
    if x_admin_token != settings.admin_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid admin token")


def get_db(request: Request):
    session_factory = request.app.state.session_factory
    db = session_factory()
    try:
        yield db
    finally:
        db.close()


def require_agent_auth(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    x_agent_id: Annotated[str | None, Header(alias="X-Agent-Id")] = None,
    x_agent_key: Annotated[str | None, Header(alias="X-Agent-Key")] = None,
) -> Agent:
    if not x_agent_id or not x_agent_key:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="missing agent auth headers")
    agent = db.scalar(select(Agent).where(Agent.id == x_agent_id))
    if not agent or agent.api_key != x_agent_key:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid agent credentials")
    return agent

