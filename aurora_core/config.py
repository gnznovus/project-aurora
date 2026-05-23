from functools import lru_cache
from pathlib import Path
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="AURORA_", extra="ignore")

    database_url: str = "postgresql+psycopg://aurora:aurora@localhost:5432/aurora"
    redis_url: str = "redis://localhost:6379/0"
    use_inmemory_queue: bool = False

    bootstrap_token: str = "aurora-bootstrap-token"
    admin_token: str = "aurora-admin-token"
    superadmin_username: str = "superadmin"
    superadmin_password: str = "superadmin"
    deployment_env: str = "dev"
    backup_dir: Path = Path("backups")
    backup_max_storage_gb: float = 20.0
    backup_retention_daily: int = 7
    backup_retention_weekly: int = 4
    backup_retention_monthly: int = 3
    backup_offsite_dir: Optional[Path] = None
    backup_scheduler_enabled: bool = True
    backup_schedule_create_minutes: int = 1440
    backup_schedule_validate_minutes: int = 1440
    backup_schedule_prune_minutes: int = 1440
    backup_schedule_restore_drill_minutes: int = 10080
    backup_validate_after_create: bool = True
    backup_prune_min_keep_count: int = 2
    schema_auto_repair_on_startup: bool = True

    heartbeat_ttl_seconds: int = 60
    lease_ttl_seconds: int = 90
    queue_name: str = "aurora:jobs:queued"

    plugins_dir: Path = Path("plugins")
    agent_poll_seconds: int = 3

    login_rate_limit_enabled: bool = False
    login_rate_limit_max_attempts: int = 5
    login_rate_limit_window_seconds: int = 60

    token_rate_limit_enabled: bool = False
    token_rate_limit_max_attempts: int = 120
    token_rate_limit_window_seconds: int = 60

    idempotency_ttl_seconds: int = 3600
    destructive_action_token_ttl_seconds: int = 300


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
