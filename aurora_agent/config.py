from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class AgentSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="AURORA_AGENT_", extra="ignore")

    core_url: str = "http://127.0.0.1:8000"
    bootstrap_token: str = "aurora-bootstrap-token"
    agent_name: str = "agent-local-01"
    tags: str = "default,linux"
    max_concurrency: int = 1
    poll_seconds: int = 3
    cache_dir: Path = Path(".agent-cache/plugins")
    checkpoint_dir: Path = Path(".agent-cache/checkpoints")

    agent_id: str | None = None
    agent_api_key: str | None = None

    @property
    def parsed_tags(self) -> list[str]:
        return [t.strip() for t in self.tags.split(",") if t.strip()]
