from __future__ import annotations

import shutil
import uuid
from pathlib import Path

from fastapi.testclient import TestClient

from aurora_core.config import Settings
from aurora_core.main import create_app


def _build_settings(
    *,
    deployment_env: str = "dev",
    login_rate_limit_enabled: bool = False,
    login_rate_limit_max_attempts: int = 5,
    login_rate_limit_window_seconds: int = 60,
    token_rate_limit_enabled: bool = False,
    token_rate_limit_max_attempts: int = 120,
    token_rate_limit_window_seconds: int = 60,
) -> tuple[Settings, Path]:
    root = Path("d:/Code/Python/Project_Aurora/.testdata") / uuid.uuid4().hex
    plugins_dir = root / "plugins"
    backup_dir = root / "backups"
    offsite_dir = root / "offsite_backups"
    plugins_dir.mkdir(parents=True, exist_ok=True)
    backup_dir.mkdir(parents=True, exist_ok=True)
    offsite_dir.mkdir(parents=True, exist_ok=True)
    db_path = root / "aurora.db"
    sample_plugin = Path("d:/Code/Python/Project_Aurora/plugins/echo_plugin.py")
    (plugins_dir / "echo_plugin.py").write_text(sample_plugin.read_text(encoding="utf-8"), encoding="utf-8")
    settings = Settings(
        database_url=f"sqlite:///{db_path.as_posix()}",
        redis_url="redis://localhost:6379/15",
        use_inmemory_queue=True,
        bootstrap_token="bootstrap-token-very-secure-123456",
        admin_token="admin-token-very-secure-123456",
        superadmin_username="opsadmin",
        superadmin_password="supersecurepass123",
        deployment_env=deployment_env,
        plugins_dir=plugins_dir,
        backup_dir=backup_dir,
        backup_offsite_dir=offsite_dir,
        backup_scheduler_enabled=False,
        lease_ttl_seconds=2,
        heartbeat_ttl_seconds=60,
        agent_poll_seconds=1,
        login_rate_limit_enabled=login_rate_limit_enabled,
        login_rate_limit_max_attempts=login_rate_limit_max_attempts,
        login_rate_limit_window_seconds=login_rate_limit_window_seconds,
        token_rate_limit_enabled=token_rate_limit_enabled,
        token_rate_limit_max_attempts=token_rate_limit_max_attempts,
        token_rate_limit_window_seconds=token_rate_limit_window_seconds,
    )
    return settings, root


def test_login_cookie_secure_in_production():
    settings, root = _build_settings(deployment_env="production")
    try:
        app = create_app(settings)
        with TestClient(app) as client:
            response = client.post("/login", json={"username": "opsadmin", "password": "supersecurepass123"})
            assert response.status_code == 200
            set_cookie = response.headers.get("set-cookie", "")
            assert "Secure" in set_cookie
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_login_rate_limit_blocks_repeated_failures():
    settings, root = _build_settings(
        login_rate_limit_enabled=True,
        login_rate_limit_max_attempts=2,
        login_rate_limit_window_seconds=60,
    )
    try:
        app = create_app(settings)
        with TestClient(app) as client:
            r1 = client.post("/login", json={"username": "opsadmin", "password": "bad-pass"})
            r2 = client.post("/login", json={"username": "opsadmin", "password": "bad-pass"})
            r3 = client.post("/login", json={"username": "opsadmin", "password": "bad-pass"})
            assert r1.status_code == 401
            assert r2.status_code == 401
            assert r3.status_code == 429
            assert "rate limit" in r3.json()["detail"]
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_admin_token_rate_limit_blocks_sensitive_writes():
    settings, root = _build_settings(
        token_rate_limit_enabled=True,
        token_rate_limit_max_attempts=2,
        token_rate_limit_window_seconds=60,
    )
    try:
        app = create_app(settings)
        with TestClient(app) as client:
            payload = {
                "name": "echo",
                "version": "1.0.0",
                "filename": "echo_plugin.py",
                "timeout_seconds": 1,
            }
            r1 = client.post("/plugins/register", headers={"X-Admin-Token": "wrong-token"}, json=payload)
            r2 = client.post("/plugins/register", headers={"X-Admin-Token": "wrong-token"}, json=payload)
            r3 = client.post("/plugins/register", headers={"X-Admin-Token": "wrong-token"}, json=payload)
            assert r1.status_code == 401
            assert r2.status_code == 401
            assert r3.status_code == 429
            assert "rate limit" in r3.json()["detail"]
    finally:
        shutil.rmtree(root, ignore_errors=True)
