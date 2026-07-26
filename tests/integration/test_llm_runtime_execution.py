from __future__ import annotations

import shutil
import json
from pathlib import Path
import uuid

import pytest

from aurora_agent.client import AgentCredentials
from aurora_agent.config import AgentSettings
from aurora_agent.worker import AgentWorker


@pytest.mark.integration
def test_worker_executes_allowlisted_runtime_command(monkeypatch):
    root = Path("D:/Code/Python/Project_Aurora/.testdata") / f"runtime_{uuid.uuid4().hex}"
    cache_dir = root / "cache"
    checkpoint_dir = root / "checkpoints"
    root.mkdir(parents=True, exist_ok=True)
    settings = AgentSettings(
        core_url="http://127.0.0.1:1",
        bootstrap_token="unused",
        agent_name="integration-agent",
        tags="integration",
        max_concurrency=1,
        poll_seconds=1,
        cache_dir=cache_dir,
        checkpoint_dir=checkpoint_dir,
        enable_runtime_commands=True,
    )
    worker = AgentWorker(settings)

    class _FakeCache:
        def has(self, _name, _digest):
            return True

        def get_path(self, _name, _digest):
            return Path("D:/Code/Python/Project_Aurora/plugins/LLM/llm_plugin.py")

        def save(self, *_args, **_kwargs):
            raise AssertionError("plugin download should not happen in this test")

    class _FakeClient:
        def __init__(self):
            self.credentials = AgentCredentials(agent_id="agent_test", api_key="key_test")
            self.health_ready_called = False
            self.reported_payload = None
            self.checkpoint_payload = None
            self.runtime_audit_calls = []

        def heartbeat(self, *args, **kwargs):
            return {"status": "ok"}

        def next_job(self):
            return {
                "lease": {
                    "execution_id": "exe_test_1",
                    "job_id": "JOB_test_1",
                    "plugin_name": "llm",
                    "plugin_version": "beta",
                    "plugin_digest": "digest",
                    "payload": {
                        "query": "check readiness",
                        "mode": "answer",
                        "provider": "mock",
                        "execution_policy": "allowlisted_execute",
                        "trace_enabled": True,
                    },
                    "resume_checkpoint": None,
                }
            }

        def plugin_manifest(self, *_args, **_kwargs):
            return {
                "digest": "digest",
                "timeout_seconds": 5,
                "download_url": "/plugins/llm/download?version=beta",
            }

        def download_plugin(self, *_args, **_kwargs):
            raise AssertionError("plugin download should not happen in this test")

        def health_ready(self):
            self.health_ready_called = True
            return {
                "status": "ready",
                "service": "aurora-core",
                "checks": {"database": {"ok": True}},
                "degraded_components": [],
            }

        def upsert_checkpoint(self, execution_id, checkpoint_payload):
            self.checkpoint_payload = (execution_id, checkpoint_payload)
            return {"execution_id": execution_id, "checkpoint_payload": checkpoint_payload}

        def runtime_audit(self, payload, request_id=None):
            self.runtime_audit_calls.append((request_id, payload))
            return {"status": "ok", "event_type": payload["event_type"]}

        def report_result(self, execution_id, payload):
            self.reported_payload = (execution_id, payload)
            return {"status": "ok", "execution_id": execution_id}

    fake_client = _FakeClient()
    worker.client = fake_client
    worker.cache = _FakeCache()
    worker.ensure_registered = lambda: None

    def _fake_execute_plugin(plugin_path, timeout_seconds, job_payload, checkpoint_path, resume_checkpoint):
        checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
        checkpoint_path.write_text(
            json.dumps(
                {
                    "stage": "result_ready",
                    "message": "LLM plugin finished",
                    "selected_commands": ["health.ready"],
                    "confidence": 0.91,
                    "provider": "mock",
                },
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        return {
            "schema_version": "v1",
            "status": "completed",
            "exit_code": 0,
            "stdout": json.dumps(
                {
                    "schema_version": "v1",
                    "plugin": "llm_plugin",
                    "provider": "mock",
                    "status": "completed",
                    "mode": "answer",
                    "query": job_payload["query"],
                    "answer": "Ready check completed.",
                    "matched_commands": [
                        {
                            "name": "health.ready",
                            "endpoint": "/health/ready",
                            "method": "GET",
                            "confidence": 0.91,
                        }
                    ],
                    "execution_policy": "allowlisted_execute",
                    "execution_plan": {
                        "policy": "allowlisted_execute",
                        "status": "validated",
                        "approved": True,
                        "command_name": "health.ready",
                        "command_endpoint": "/health/ready",
                        "execution_kind": "aurora_api",
                        "risk_level": "normal",
                        "requires_confirmation": False,
                        "required_role": "",
                        "blockers": [],
                        "payload": {},
                    },
                    "work_trace": [],
                    "usage": {
                        "provider": "mock",
                        "model": "mock-llm-v1",
                        "input_tokens": 0,
                        "output_tokens": 0,
                        "estimated_cost_usd": 0.0,
                    },
                },
                indent=2,
                sort_keys=True,
            ),
            "stderr": "",
            "duration_ms": 10,
            "metrics": {"timed_out": False},
        }

    monkeypatch.setattr("aurora_agent.worker.execute_plugin", _fake_execute_plugin)
    try:
        worker.run_once()

        assert fake_client.health_ready_called is True
        assert fake_client.checkpoint_payload is not None
        assert fake_client.reported_payload is not None
        assert [payload["event_type"] for _request_id, payload in fake_client.runtime_audit_calls] == [
            "plan_validated",
            "execution_started",
            "execution_completed",
        ]
        assert fake_client.runtime_audit_calls[0][0] == "runtime:exe_test_1"
        reported_execution_id, reported_payload = fake_client.reported_payload
        assert reported_execution_id == "exe_test_1"
        assert reported_payload["metrics"]["runtime_command_executed"] is True
        assert reported_payload["metrics"]["runtime_command"]["command_name"] == "health.ready"
        assert reported_payload["metrics"]["runtime_command"]["response_status"] == "ready"
    finally:
        shutil.rmtree(root, ignore_errors=True)
