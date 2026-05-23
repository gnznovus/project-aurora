from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import select

from aurora_core.services.models import Agent, Job, JobStatus


def _register_agent(client, name: str = "agent-c1"):
    response = client.post(
        "/agents/register",
        json={
            "bootstrap_token": "test-bootstrap",
            "agent_name": name,
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
        json={"name": "echo", "version": "1.0.0", "filename": "echo_plugin.py", "timeout_seconds": 2},
    )
    assert response.status_code == 200


def _enqueue_job(client, message: str = "hello"):
    response = client.post(
        "/jobs",
        headers={"X-Admin-Token": "test-admin"},
        json={
            "plugin_name": "echo",
            "plugin_version": "1.0.0",
            "payload": {"message": message},
            "required_tags": ["default"],
            "max_attempts": 2,
            "retry_backoff_seconds": 0,
        },
    )
    assert response.status_code == 200
    return response.json()["job_id"]


def test_parallel_execution_result_only_one_terminalizes(client):
    _register_plugin(client)
    agent = _register_agent(client)
    headers = _auth_headers(agent)
    _enqueue_job(client, "parallel")

    lease_resp = client.post("/agents/jobs/next", headers=headers)
    assert lease_resp.status_code == 200
    lease = lease_resp.json()["lease"]
    assert lease is not None

    payload = {
        "schema_version": "v1",
        "status": "completed",
        "exit_code": 0,
        "stdout": "ok",
        "stderr": "",
        "duration_ms": 5,
        "metrics": {},
    }

    def submit():
        return client.post(f"/executions/{lease['execution_id']}/result", headers=headers, json=payload).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = list(pool.map(lambda _: submit(), [1, 2]))

    assert sorted(statuses) == [200, 409]


def test_stale_lease_recovery_keeps_active_leases_non_negative(client):
    _register_plugin(client)
    agent = _register_agent(client, name="agent-stale")
    headers = _auth_headers(agent)
    _enqueue_job(client, "stale-lease")

    lease_resp = client.post("/agents/jobs/next", headers=headers)
    assert lease_resp.status_code == 200
    assert lease_resp.json()["lease"] is not None

    time.sleep(2.2)
    for _ in range(5):
        next_resp = client.post("/agents/jobs/next", headers=headers)
        assert next_resp.status_code == 200

    db = client.app.state.session_factory()
    try:
        agent_row = db.scalar(select(Agent).where(Agent.id == agent["agent_id"]))
        assert agent_row is not None
        assert agent_row.active_leases >= 0
    finally:
        db.close()


def test_stale_lease_recovery_requeues_or_fails_deterministically(client):
    _register_plugin(client)
    agent = _register_agent(client, name="agent-recover")
    headers = _auth_headers(agent)
    job_id = _enqueue_job(client, "recover")

    lease_resp = client.post("/agents/jobs/next", headers=headers)
    assert lease_resp.status_code == 200
    assert lease_resp.json()["lease"] is not None

    time.sleep(2.2)
    client.post("/agents/jobs/next", headers=headers)

    db = client.app.state.session_factory()
    try:
        job = db.scalar(select(Job).where(Job.id == job_id))
        assert job is not None
        assert job.status in {JobStatus.queued, JobStatus.failed, JobStatus.leased}
    finally:
        db.close()
