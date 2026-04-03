from __future__ import annotations

import json
import logging
import sys
import time
from pathlib import Path

from aurora_agent.client import AgentCredentials, AuroraClient
from aurora_agent.config import AgentSettings
from aurora_agent.executor import execute_plugin
from aurora_agent.plugin_cache import PluginCache

logger = logging.getLogger("aurora-agent")


class AgentWorker:
    def __init__(self, settings: AgentSettings) -> None:
        self.settings = settings
        self.cache = PluginCache(settings.cache_dir)
        self.settings.checkpoint_dir.mkdir(parents=True, exist_ok=True)

        credentials = None
        if settings.agent_id and settings.agent_api_key:
            credentials = AgentCredentials(agent_id=settings.agent_id, api_key=settings.agent_api_key)
        self.client = AuroraClient(settings.core_url, credentials=credentials)

    def ensure_registered(self) -> None:
        if self.client.credentials:
            return
        credentials = self.client.register(
            bootstrap_token=self.settings.bootstrap_token,
            agent_name=self.settings.agent_name,
            tags=self.settings.parsed_tags,
            max_concurrency=self.settings.max_concurrency,
        )
        logger.info("agent registered id=%s", credentials.agent_id)

    def run_once(self) -> None:
        self.ensure_registered()
        logger.debug("agent.step heartbeat")
        self.client.heartbeat(running_jobs=0, capacity_hint=self.settings.max_concurrency)
        logger.debug("agent.step request_next_job")
        response = self.client.next_job()
        lease = response.get("lease")
        if not lease:
            logger.debug("agent.step no_job")
            return
        logger.info(
            "agent.step lease_received execution_id=%s job_id=%s plugin=%s version=%s",
            lease["execution_id"],
            lease["job_id"],
            lease["plugin_name"],
            lease["plugin_version"],
        )
        manifest = self.client.plugin_manifest(lease["plugin_name"], lease["plugin_version"])
        digest = manifest["digest"]
        if not self.cache.has(lease["plugin_name"], digest):
            logger.info("agent.step plugin_download name=%s digest=%s", lease["plugin_name"], digest[:12])
            artifact = self.client.download_plugin(manifest["download_url"])
            self.cache.save(lease["plugin_name"], digest, artifact)
        else:
            logger.info("agent.step plugin_cache_hit name=%s digest=%s", lease["plugin_name"], digest[:12])
        plugin_path = self.cache.get_path(lease["plugin_name"], digest)
        checkpoint_path = self._checkpoint_path(lease["execution_id"])
        resume_checkpoint = lease.get("resume_checkpoint")
        logger.info("agent.step execute execution_id=%s timeout=%s", lease["execution_id"], manifest["timeout_seconds"])
        result = execute_plugin(
            plugin_path,
            timeout_seconds=manifest["timeout_seconds"],
            job_payload=lease["payload"],
            checkpoint_path=checkpoint_path,
            resume_checkpoint=resume_checkpoint,
        )
        latest_checkpoint = self._read_checkpoint(checkpoint_path)
        if latest_checkpoint is not None:
            logger.info(
                "agent.step checkpoint_upload execution_id=%s keys=%s",
                lease["execution_id"],
                sorted(latest_checkpoint.keys()),
            )
            self.client.upsert_checkpoint(lease["execution_id"], latest_checkpoint)
            result["metrics"]["checkpoint_uploaded"] = True
        else:
            result["metrics"]["checkpoint_uploaded"] = False
        logger.info(
            "agent.step report_result execution_id=%s status=%s exit_code=%s",
            lease["execution_id"],
            result["status"],
            result["exit_code"],
        )
        self.client.report_result(lease["execution_id"], result)

    def _checkpoint_path(self, execution_id: str) -> Path:
        return self.settings.checkpoint_dir / f"{execution_id}.json"

    def _read_checkpoint(self, path: Path) -> dict | None:
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            logger.warning("agent.step checkpoint_invalid path=%s", path)
            return None
        if isinstance(payload, dict):
            return payload
        logger.warning("agent.step checkpoint_not_object path=%s", path)
        return None

    def run_forever(self) -> None:
        while True:
            try:
                self.run_once()
            except Exception as exc:  # noqa: BLE001
                logger.exception("agent loop error: %s", exc)
            time.sleep(self.settings.poll_seconds)


if __name__ == "__main__":
    class _MaxLevelFilter(logging.Filter):
        def __init__(self, max_level: int):
            super().__init__()
            self.max_level = max_level

        def filter(self, record: logging.LogRecord) -> bool:
            return record.levelno <= self.max_level

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    root_logger.handlers.clear()

    fmt = logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s")
    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setLevel(logging.INFO)
    stdout_handler.addFilter(_MaxLevelFilter(logging.WARNING))
    stdout_handler.setFormatter(fmt)

    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setLevel(logging.ERROR)
    stderr_handler.setFormatter(fmt)

    root_logger.addHandler(stdout_handler)
    root_logger.addHandler(stderr_handler)

    worker = AgentWorker(AgentSettings())
    worker.run_forever()
