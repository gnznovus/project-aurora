from __future__ import annotations

import os
import uuid

import pytest
import requests

from aurora_agent.config import AgentSettings
from aurora_agent.worker import AgentWorker


@pytest.mark.integration
def test_e2e_single_job_roundtrip():
    base_url = os.getenv("AURORA_INTEGRATION_BASE_URL")
    if not base_url:
        pytest.skip("Set AURORA_INTEGRATION_BASE_URL to run integration test")

    admin_token = os.getenv("AURORA_ADMIN_TOKEN", "aurora-admin-token")
    bootstrap_token = os.getenv("AURORA_BOOTSTRAP_TOKEN", "aurora-bootstrap-token")

    register_plugin_resp = requests.post(
        f"{base_url}/plugins/register",
        headers={"X-Admin-Token": admin_token},
        json={
            "name": "echo",
            "version": f"1.0.{uuid.uuid4().hex[:6]}",
            "filename": "echo_plugin.py",
            "timeout_seconds": 5,
        },
        timeout=10,
    )
    register_plugin_resp.raise_for_status()
    version = register_plugin_resp.json()["version"]

    enqueue_resp = requests.post(
        f"{base_url}/jobs",
        headers={"X-Admin-Token": admin_token},
        json={
            "plugin_name": "echo",
            "plugin_version": version,
            "payload": {"message": "integration-ok"},
            "required_tags": ["integration"],
        },
        timeout=10,
    )
    enqueue_resp.raise_for_status()

    settings = AgentSettings(
        core_url=base_url,
        bootstrap_token=bootstrap_token,
        agent_name="integration-agent",
        tags="integration",
        max_concurrency=1,
    )
    worker = AgentWorker(settings)
    worker.run_once()

