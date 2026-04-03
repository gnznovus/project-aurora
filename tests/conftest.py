from __future__ import annotations

import shutil
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from aurora_core.config import Settings
from aurora_core.main import create_app


@pytest.fixture()
def test_settings() -> Settings:
    root = Path("d:/Code/Python/Project_Aurora/.testdata") / uuid.uuid4().hex
    plugins_dir = root / "plugins"
    plugins_dir.mkdir(parents=True, exist_ok=True)
    db_path = root / "aurora.db"
    sample_plugin = Path("d:/Code/Python/Project_Aurora/plugins/echo_plugin.py")
    (plugins_dir / "echo_plugin.py").write_text(sample_plugin.read_text(encoding="utf-8"), encoding="utf-8")
    settings = Settings(
        database_url=f"sqlite:///{db_path.as_posix()}",
        redis_url="redis://localhost:6379/15",
        use_inmemory_queue=True,
        bootstrap_token="test-bootstrap",
        admin_token="test-admin",
        plugins_dir=plugins_dir,
        lease_ttl_seconds=2,
        heartbeat_ttl_seconds=60,
        agent_poll_seconds=1,
    )
    yield settings
    shutil.rmtree(root, ignore_errors=True)


@pytest.fixture()
def client(test_settings: Settings) -> TestClient:
    app = create_app(test_settings)
    with TestClient(app) as test_client:
        yield test_client
