from __future__ import annotations

from aurora_core.config import Settings
from aurora_core.main import create_app


def test_create_app_allows_default_superadmin_in_dev():
    settings = Settings(
        database_url="sqlite:///d:/Code/Python/Project_Aurora/.testdata/startup_dev.db",
        redis_url="redis://localhost:6379/15",
        use_inmemory_queue=True,
        backup_scheduler_enabled=False,
        deployment_env="dev",
        superadmin_username="superadmin",
        superadmin_password="superadmin",
    )
    app = create_app(settings)
    assert app.title == "Aurora Core"


def test_create_app_rejects_default_superadmin_in_production():
    settings = Settings(
        database_url="sqlite:///d:/Code/Python/Project_Aurora/.testdata/startup_prod.db",
        redis_url="redis://localhost:6379/15",
        use_inmemory_queue=True,
        backup_scheduler_enabled=False,
        deployment_env="production",
        superadmin_username="superadmin",
        superadmin_password="superadmin",
    )
    try:
        create_app(settings)
        assert False, "expected startup validation to reject default credentials"
    except RuntimeError as exc:
        assert "unsafe production configuration" in str(exc)

