from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import requests


@dataclass
class AgentCredentials:
    agent_id: str
    api_key: str


class AuroraClient:
    def __init__(self, base_url: str, credentials: AgentCredentials | None = None, timeout: int = 20) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.credentials = credentials

    def _auth_headers(self) -> dict[str, str]:
        if not self.credentials:
            raise RuntimeError("agent credentials are required")
        return {
            "X-Agent-Id": self.credentials.agent_id,
            "X-Agent-Key": self.credentials.api_key,
        }

    def register(self, bootstrap_token: str, agent_name: str, tags: list[str], max_concurrency: int) -> AgentCredentials:
        response = requests.post(
            f"{self.base_url}/agents/register",
            json={
                "bootstrap_token": bootstrap_token,
                "agent_name": agent_name,
                "tags": tags,
                "max_concurrency": max_concurrency,
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        data = response.json()
        credentials = AgentCredentials(agent_id=data["agent_id"], api_key=data["api_key"])
        self.credentials = credentials
        return credentials

    def heartbeat(self, running_jobs: int = 0, capacity_hint: int = 1) -> dict[str, Any]:
        response = requests.post(
            f"{self.base_url}/agents/heartbeat",
            headers=self._auth_headers(),
            json={"running_jobs": running_jobs, "capacity_hint": capacity_hint},
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()

    def next_job(self) -> dict[str, Any]:
        response = requests.post(
            f"{self.base_url}/agents/jobs/next",
            headers=self._auth_headers(),
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()

    def plugin_manifest(self, name: str, version: str) -> dict[str, Any]:
        response = requests.get(
            f"{self.base_url}/plugins/{name}/manifest",
            params={"version": version},
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()

    def download_plugin(self, download_url: str) -> bytes:
        if download_url.startswith("/"):
            full_url = f"{self.base_url}{download_url}"
        else:
            full_url = download_url
        response = requests.get(full_url, timeout=self.timeout)
        response.raise_for_status()
        return response.content

    def report_result(self, execution_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        response = requests.post(
            f"{self.base_url}/executions/{execution_id}/result",
            headers=self._auth_headers(),
            json=payload,
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()

    def upsert_checkpoint(self, execution_id: str, checkpoint_payload: dict[str, Any]) -> dict[str, Any]:
        response = requests.post(
            f"{self.base_url}/executions/{execution_id}/checkpoint",
            headers=self._auth_headers(),
            json={"schema_version": "v1", "payload": checkpoint_payload},
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()
