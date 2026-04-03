from functools import lru_cache
from pathlib import Path

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

    heartbeat_ttl_seconds: int = 60
    lease_ttl_seconds: int = 90
    queue_name: str = "aurora:jobs:queued"

    plugins_dir: Path = Path("plugins")
    agent_poll_seconds: int = 3


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
