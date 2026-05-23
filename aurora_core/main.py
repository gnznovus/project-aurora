from __future__ import annotations

import logging
import secrets
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from sqlalchemy import select, text

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
from aurora_core.services.rate_limit import LocalRateLimiter
from aurora_core.routes.auth import router as auth_router
from aurora_core.routes.dashboard import router as dashboard_router
from aurora_core.routes.operations import router as operations_router
from aurora_core.routes.superadmin import router as superadmin_router
from aurora_core.services.routing import DefaultStaticRoutingStrategy
from aurora_core.services.schema_guard import ensure_schema_ready

logger = logging.getLogger("aurora-core")


def create_app(settings: Settings | None = None) -> FastAPI:
    effective_settings = settings or get_settings()
    _validate_startup_security(effective_settings)

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
    app.state.rate_limiter = LocalRateLimiter()
    app.state.confirmation_tokens = {}
    app.state.dashboard_sessions = {}
    app.state.dashboard_session_ttl_seconds = 60 * 60 * 8

    @app.middleware("http")
    async def request_context_middleware(request, call_next):
        request_id = (request.headers.get("x-request-id") or "").strip() or f"req_{secrets.token_hex(8)}"
        request.state.request_id = request_id
        started = time.perf_counter()
        response = await call_next(request)
        duration_ms = int((time.perf_counter() - started) * 1000)
        response.headers["X-Request-Id"] = request_id
        logger.info(
            "http.request method=%s path=%s status=%s duration_ms=%s request_id=%s",
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
            request_id,
        )
        return response

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok", "service": "aurora-core"}

    @app.get("/health/ready")
    def health_ready():
        checks: dict[str, dict[str, Any]] = {}
        degraded: list[str] = []

        checks["database"] = _readiness_check_db(app)
        if checks["database"]["ok"] is not True:
            degraded.append("database")

        checks["queue"] = _readiness_check_queue(app)
        if checks["queue"]["ok"] is not True:
            degraded.append("queue")

        checks["schema_guard"] = _readiness_check_schema_guard(app)
        if checks["schema_guard"]["ok"] is not True:
            degraded.append("schema_guard")

        checks["backup_scheduler"] = _readiness_check_scheduler(app)
        if checks["backup_scheduler"]["ok"] is not True:
            degraded.append("backup_scheduler")

        ready = len(degraded) == 0
        payload = {
            "status": "ready" if ready else "degraded",
            "service": "aurora-core",
            "checks": checks,
            "degraded_components": degraded,
        }
        if ready:
            return payload
        from fastapi.responses import JSONResponse

        return JSONResponse(status_code=503, content=payload)
    app.include_router(auth_router)
    app.include_router(operations_router)
    app.include_router(superadmin_router)
    app.include_router(dashboard_router)

    return app


def _build_queue(settings: Settings) -> QueueAdapter:
    if settings.use_inmemory_queue:
        return InMemoryQueue()
    return RedisQueue(settings.redis_url, settings.queue_name)


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


def _validate_startup_security(settings: Settings) -> None:
    env = (settings.deployment_env or "dev").strip().lower()
    if env in {"dev", "local", "test"}:
        return

    errors: list[str] = []
    username = settings.superadmin_username.strip()
    password = settings.superadmin_password.strip()
    admin_token = settings.admin_token.strip()
    bootstrap_token = settings.bootstrap_token.strip()

    if username == "superadmin" and password == "superadmin":
        errors.append(
            "default superadmin credentials detected (set AURORA_SUPERADMIN_USERNAME and AURORA_SUPERADMIN_PASSWORD)"
        )

    if admin_token == "aurora-admin-token":
        errors.append("default admin token detected (set AURORA_ADMIN_TOKEN)")

    if bootstrap_token == "aurora-bootstrap-token":
        errors.append("default bootstrap token detected (set AURORA_BOOTSTRAP_TOKEN)")

    if len(password) < 12:
        errors.append("superadmin password must be at least 12 characters in production")

    if len(admin_token) < 20:
        errors.append("admin token must be at least 20 characters in production")

    if len(bootstrap_token) < 20:
        errors.append("bootstrap token must be at least 20 characters in production")

    if errors:
        raise RuntimeError(
            "unsafe production configuration: " + "; ".join(errors)
        )


app = create_app()


def _readiness_check_db(app: FastAPI) -> dict[str, Any]:
    started = time.perf_counter()
    db = app.state.session_factory()
    try:
        db.execute(text("SELECT 1"))
        return {"ok": True, "latency_ms": int((time.perf_counter() - started) * 1000)}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc), "latency_ms": int((time.perf_counter() - started) * 1000)}
    finally:
        db.close()


def _readiness_check_queue(app: FastAPI) -> dict[str, Any]:
    started = time.perf_counter()
    queue = app.state.queue
    try:
        if isinstance(queue, InMemoryQueue):
            return {"ok": True, "mode": "inmemory", "latency_ms": int((time.perf_counter() - started) * 1000)}
        if isinstance(queue, RedisQueue):
            queue._redis.ping()  # intentional direct ping for readiness only
            return {"ok": True, "mode": "redis", "latency_ms": int((time.perf_counter() - started) * 1000)}
        return {"ok": False, "error": "unknown queue adapter", "latency_ms": int((time.perf_counter() - started) * 1000)}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc), "latency_ms": int((time.perf_counter() - started) * 1000)}


def _readiness_check_schema_guard(app: FastAPI) -> dict[str, Any]:
    settings_obj: Settings = app.state.settings
    if settings_obj.database_url.startswith("sqlite"):
        return {"ok": True, "mode": "sqlite-bootstrap"}
    return {"ok": True, "mode": "startup-validated"}


def _readiness_check_scheduler(app: FastAPI) -> dict[str, Any]:
    scheduler = app.state.backup_scheduler
    if not app.state.settings.backup_scheduler_enabled:
        return {"ok": True, "enabled": False}
    is_running = bool(getattr(scheduler, "_thread", None) and scheduler._thread.is_alive())
    if not is_running:
        return {"ok": False, "enabled": True, "error": "scheduler thread not running"}
    return {"ok": True, "enabled": True}
