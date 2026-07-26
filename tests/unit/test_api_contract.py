from __future__ import annotations

import time

from sqlalchemy import func, select

from aurora_core.services.models import AuditLog


def _register_agent(client):
    response = client.post(
        "/agents/register",
        json={
            "bootstrap_token": "test-bootstrap",
            "agent_name": "agent-a",
            "tags": ["default", "linux"],
            "max_concurrency": 1,
        },
    )
    assert response.status_code == 200
    return response.json()


def _auth_headers(agent_data: dict) -> dict[str, str]:
    return {"X-Agent-Id": agent_data["agent_id"], "X-Agent-Key": agent_data["api_key"]}


def _register_plugin(client):
    response = client.post(
        "/plugins/register",
        headers={"X-Admin-Token": "test-admin"},
        json={
            "name": "echo",
            "version": "1.0.0",
            "filename": "echo_plugin.py",
            "timeout_seconds": 1,
        },
    )
    assert response.status_code == 200


def _enqueue_job(client, payload: dict | None = None):
    response = client.post(
        "/jobs",
        headers={"X-Admin-Token": "test-admin"},
        json={
            "plugin_name": "echo",
            "plugin_version": "1.0.0",
            "payload": payload or {"message": "hi"},
            "required_tags": ["linux"],
            "max_attempts": 2,
            "retry_backoff_seconds": 0,
        },
    )
    assert response.status_code == 200
    return response.json()["job_id"]


def test_register_agent_contract(client):
    data = _register_agent(client)
    assert data["schema_version"] == "v1"
    assert data["agent_id"].startswith("AGT_")
    assert data["api_key"]


def test_auth_failure_for_heartbeat(client):
    response = client.post("/agents/heartbeat", json={"running_jobs": 0, "capacity_hint": 1})
    assert response.status_code == 401


def test_manifest_and_download(client):
    _register_plugin(client)
    manifest = client.get("/plugins/echo/manifest", params={"version": "1.0.0"})
    assert manifest.status_code == 200
    manifest_data = manifest.json()
    assert manifest_data["digest"]
    download = client.get(manifest_data["download_url"])
    assert download.status_code == 200
    assert b"hello from aurora plugin" in download.content


def test_stale_lease_returns_conflict(client):
    _register_plugin(client)
    agent = _register_agent(client)
    _enqueue_job(client)
    lease_resp = client.post("/agents/jobs/next", headers=_auth_headers(agent))
    assert lease_resp.status_code == 200
    lease = lease_resp.json()["lease"]
    assert lease is not None
    time.sleep(2.2)
    result_resp = client.post(
        f"/executions/{lease['execution_id']}/result",
        headers=_auth_headers(agent),
        json={
            "schema_version": "v1",
            "status": "completed",
            "exit_code": 0,
            "stdout": "ok",
            "stderr": "",
            "duration_ms": 5,
            "metrics": {},
        },
    )
    assert result_resp.status_code == 409


def test_checkpoint_roundtrip(client):
    _register_plugin(client)
    agent = _register_agent(client)
    _enqueue_job(client, {"action": "sleep", "seconds": 1})
    lease_resp = client.post("/agents/jobs/next", headers=_auth_headers(agent))
    assert lease_resp.status_code == 200
    lease = lease_resp.json()["lease"]
    assert lease is not None

    checkpoint_resp = client.post(
        f"/executions/{lease['execution_id']}/checkpoint",
        headers=_auth_headers(agent),
        json={"schema_version": "v1", "payload": {"step": 1, "total": 5}},
    )
    assert checkpoint_resp.status_code == 200
    assert checkpoint_resp.json()["checkpoint_payload"]["step"] == 1

    latest_resp = client.get(
        f"/executions/{lease['execution_id']}/checkpoint/latest",
        headers=_auth_headers(agent),
    )
    assert latest_resp.status_code == 200
    data = latest_resp.json()
    assert data["execution_id"] == lease["execution_id"]
    assert data["checkpoint_payload"] == {"step": 1, "total": 5}


def test_job_progress_admin_endpoint(client):
    _register_plugin(client)
    _register_agent(client)
    job_id = _enqueue_job(client, {"message": "progress"})
    progress_resp = client.get(
        f"/jobs/{job_id}/progress",
        headers={"X-Admin-Token": "test-admin"},
    )
    assert progress_resp.status_code == 200
    data = progress_resp.json()
    assert data["job_id"] == job_id
    assert data["attempt_count"] == 0
    assert data["max_attempts"] == 2


def test_dashboard_page_served(client):
    response = client.get("/dashboard")
    assert response.status_code == 200
    assert "Aurora Control Dashboard" in response.text


def test_dashboard_overview_requires_admin(client):
    response = client.get("/dashboard/api/overview")
    assert response.status_code == 401


def test_dashboard_overview_payload(client):
    _register_plugin(client)
    _register_agent(client)
    _enqueue_job(client, {"message": "overview"})
    response = client.get("/dashboard/api/overview", headers={"X-Admin-Token": "test-admin"})
    assert response.status_code == 200
    data = response.json()
    assert data["schema_version"] == "v1"
    assert "metrics" in data
    assert "agents" in data
    assert "jobs" in data
    assert "executions" in data


def test_runtime_overview_payload(client):
    agent = _register_agent(client)
    response = client.get("/agents/runtime/overview", headers=_auth_headers(agent))
    assert response.status_code == 200
    data = response.json()
    assert data["schema_version"] == "v1"
    assert data["service"] == "aurora-core"
    assert data["scope"] == "agent_runtime_overview"
    assert data["agent_id"] == agent["agent_id"]
    assert "metrics" in data
    assert "recent_jobs" in data


def test_runtime_audit_persists_audit_log(client):
    agent = _register_agent(client)
    before_session = client.app.state.session_factory()
    try:
        before_count = before_session.scalar(select(func.count(AuditLog.id))) or 0
    finally:
        before_session.close()
    response = client.post(
        "/agents/runtime/audit",
        headers={**_auth_headers(agent), "X-Request-Id": "req-runtime-audit-1"},
        json={
            "schema_version": "v1",
            "event_type": "plan_validated",
            "execution_id": "exe_test_1",
            "job_id": "JOB_test_1",
            "plugin_name": "llm",
            "command_name": "health.ready",
            "command_endpoint": "/health/ready",
            "execution_policy": "allowlisted_execute",
            "risk_level": "normal",
            "status": "validated",
            "reason": "plan accepted",
            "details": {"approved": True},
        },
    )
    assert response.status_code == 200
    after_session = client.app.state.session_factory()
    try:
        rows = list(
            after_session.scalars(
                select(AuditLog).where(AuditLog.action == "runtime.plan_validated").order_by(AuditLog.id.desc())
            )
        )
    finally:
        after_session.close()
    assert len(rows) >= before_count + 1
    row = rows[-1]
    assert row.actor_role == "agent"
    assert row.resource_id == "exe_test_1"
    assert row.details["request_id"] == "req-runtime-audit-1"
    assert row.details["command_name"] == "health.ready"


def test_request_id_echo_when_header_provided(client):
    response = client.get("/health", headers={"X-Request-Id": "req-test-123"})
    assert response.status_code == 200
    assert response.headers.get("X-Request-Id") == "req-test-123"


def test_request_id_generated_when_missing(client):
    response = client.get("/health")
    assert response.status_code == 200
    request_id = response.headers.get("X-Request-Id")
    assert request_id
    assert request_id.startswith("req_")


def test_health_ready_payload(client):
    response = client.get("/health/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["service"] == "aurora-core"
    assert "checks" in body
    assert body["checks"]["database"]["ok"] is True
    assert body["checks"]["queue"]["ok"] is True
    assert body["checks"]["schema_guard"]["ok"] is True
    assert body["checks"]["backup_scheduler"]["ok"] is True


def test_health_ready_degraded_when_db_unavailable(client):
    class _BrokenSession:
        def execute(self, *_args, **_kwargs):
            raise RuntimeError("db unavailable")

        def close(self):
            return None

    client.app.state.session_factory = lambda: _BrokenSession()
    response = client.get("/health/ready")
    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "degraded"
    assert "database" in body["degraded_components"]
