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


def test_create_app_rejects_default_tokens_in_production():
    settings = Settings(
        database_url="sqlite:///d:/Code/Python/Project_Aurora/.testdata/startup_prod_default_tokens.db",
        redis_url="redis://localhost:6379/15",
        use_inmemory_queue=True,
        backup_scheduler_enabled=False,
        deployment_env="production",
        superadmin_username="ops-admin",
        superadmin_password="supersecurepass123",
        admin_token="aurora-admin-token",
        bootstrap_token="aurora-bootstrap-token",
    )
    try:
        create_app(settings)
        assert False, "expected startup validation to reject default tokens"
    except RuntimeError as exc:
        message = str(exc)
        assert "default admin token detected" in message
        assert "default bootstrap token detected" in message


def test_create_app_rejects_weak_secrets_in_production():
    settings = Settings(
        database_url="sqlite:///d:/Code/Python/Project_Aurora/.testdata/startup_prod_weak_secrets.db",
        redis_url="redis://localhost:6379/15",
        use_inmemory_queue=True,
        backup_scheduler_enabled=False,
        deployment_env="production",
        superadmin_username="ops-admin",
        superadmin_password="short",
        admin_token="short-admin",
        bootstrap_token="short-bootstrap",
    )
    try:
        create_app(settings)
        assert False, "expected startup validation to reject weak secrets"
    except RuntimeError as exc:
        message = str(exc)
        assert "superadmin password must be at least 12 characters" in message
        assert "admin token must be at least 20 characters" in message
        assert "bootstrap token must be at least 20 characters" in message
