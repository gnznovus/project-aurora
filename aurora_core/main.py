from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from sqlalchemy import select

from aurora_core.utils.auth_utils import hash_password
from aurora_core.services.backup_scheduler import BackupScheduler
from aurora_core.services.backup_service import BackupService
from aurora_core.config import Settings, get_settings
from aurora_core.db import create_session_factory
from aurora_core.services.models import (
    User,
    UserRole,
)
from aurora_core.services.plugin_store import PluginStore
from aurora_core.services.queue import InMemoryQueue, QueueAdapter, RedisQueue
from aurora_core.routes.auth import router as auth_router
from aurora_core.routes.dashboard import router as dashboard_router
from aurora_core.routes.operations import router as operations_router
from aurora_core.routes.superadmin import router as superadmin_router
from aurora_core.services.routing import DefaultStaticRoutingStrategy
from aurora_core.services.schema_guard import ensure_schema_ready

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
    app.include_router(superadmin_router)
    app.include_router(dashboard_router)

    return app


def _build_queue(settings: Settings) -> QueueAdapter:
    if settings.use_inmemory_queue:
        return InMemoryQueue()
    return RedisQueue(settings.redis_url, settings.queue_name)


app = create_app()


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


