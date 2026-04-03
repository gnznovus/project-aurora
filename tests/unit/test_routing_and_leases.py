from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor


def _register_agent(client, name: str):
    response = client.post(
        "/agents/register",
        json={
            "bootstrap_token": "test-bootstrap",
            "agent_name": name,
            "tags": ["batch", "linux"],
            "max_concurrency": 1,
        },
    )
    assert response.status_code == 200
    return response.json()


def _auth(agent_data: dict) -> dict[str, str]:
    return {"X-Agent-Id": agent_data["agent_id"], "X-Agent-Key": agent_data["api_key"]}


def _seed_plugin_and_job(client):
    plugin_resp = client.post(
        "/plugins/register",
        headers={"X-Admin-Token": "test-admin"},
        json={
            "name": "echo",
            "version": "1.0.0",
            "filename": "echo_plugin.py",
            "timeout_seconds": 2,
        },
    )
    assert plugin_resp.status_code == 200
    job_resp = client.post(
        "/jobs",
        headers={"X-Admin-Token": "test-admin"},
        json={
            "plugin_name": "echo",
            "plugin_version": "1.0.0",
            "payload": {"message": "lease-test"},
            "required_tags": ["batch"],
            "max_attempts": 2,
            "retry_backoff_seconds": 0,
        },
    )
    assert job_resp.status_code == 200


def test_only_one_agent_gets_single_lease(client):
    _seed_plugin_and_job(client)
    a1 = _register_agent(client, "agent-1")
    a2 = _register_agent(client, "agent-2")

    def ask_next(headers):
        response = client.post("/agents/jobs/next", headers=headers)
        assert response.status_code == 200
        return response.json()["lease"]

    with ThreadPoolExecutor(max_workers=2) as pool:
        leases = list(pool.map(ask_next, [_auth(a1), _auth(a2)]))

    leased_count = sum(1 for lease in leases if lease is not None)
    assert leased_count == 1


def test_tag_mismatch_does_not_lease(client):
    plugin_resp = client.post(
        "/plugins/register",
        headers={"X-Admin-Token": "test-admin"},
        json={"name": "echo", "version": "1.0.0", "filename": "echo_plugin.py", "timeout_seconds": 2},
    )
    assert plugin_resp.status_code == 200
    job_resp = client.post(
        "/jobs",
        headers={"X-Admin-Token": "test-admin"},
        json={
            "plugin_name": "echo",
            "plugin_version": "1.0.0",
            "payload": {"message": "none"},
            "required_tags": ["gpu"],
            "max_attempts": 2,
            "retry_backoff_seconds": 0,
        },
    )
    assert job_resp.status_code == 200
    agent = _register_agent(client, "agent-no-gpu")
    lease_resp = client.post("/agents/jobs/next", headers=_auth(agent))
    assert lease_resp.status_code == 200
    assert lease_resp.json()["lease"] is None


def test_retry_after_failed_result_requeues_job(client):
    _seed_plugin_and_job(client)
    agent = _register_agent(client, "agent-retry")
    headers = _auth(agent)

    lease_resp = client.post("/agents/jobs/next", headers=headers)
    assert lease_resp.status_code == 200
    lease = lease_resp.json()["lease"]
    assert lease is not None

    result_resp = client.post(
        f"/executions/{lease['execution_id']}/result",
        headers=headers,
        json={
            "schema_version": "v1",
            "status": "failed",
            "exit_code": 2,
            "stdout": "",
            "stderr": "boom",
            "duration_ms": 5,
            "metrics": {},
        },
    )
    assert result_resp.status_code == 200

    next_lease_resp = client.post("/agents/jobs/next", headers=headers)
    assert next_lease_resp.status_code == 200
    next_lease = next_lease_resp.json()["lease"]
    assert next_lease is not None
    assert next_lease["job_id"] == lease["job_id"]
