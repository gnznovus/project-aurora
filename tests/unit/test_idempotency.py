from __future__ import annotations


def _register_plugin(client, *, idem_key: str | None = None, version: str = "1.0.0"):
    headers = {"X-Admin-Token": "test-admin"}
    if idem_key:
        headers["Idempotency-Key"] = idem_key
    return client.post(
        "/plugins/register",
        headers=headers,
        json={
            "name": "echo",
            "version": version,
            "filename": "echo_plugin.py",
            "timeout_seconds": 2,
        },
    )


def _enqueue_job(client, *, idem_key: str | None = None, message: str = "hello"):
    headers = {"X-Admin-Token": "test-admin"}
    if idem_key:
        headers["Idempotency-Key"] = idem_key
    return client.post(
        "/jobs",
        headers=headers,
        json={
            "plugin_name": "echo",
            "plugin_version": "1.0.0",
            "payload": {"message": message},
            "required_tags": ["default"],
            "max_attempts": 2,
            "retry_backoff_seconds": 0,
        },
    )


def test_plugin_register_idempotency_replay(client):
    first = _register_plugin(client, idem_key="idem-plugin-1", version="1.0.0")
    second = _register_plugin(client, idem_key="idem-plugin-1", version="1.0.0")

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json() == second.json()


def test_plugin_register_idempotency_conflict(client):
    first = _register_plugin(client, idem_key="idem-plugin-2", version="1.0.0")
    conflict = _register_plugin(client, idem_key="idem-plugin-2", version="2.0.0")

    assert first.status_code == 200
    assert conflict.status_code == 409
    assert "idempotency key reused" in conflict.json()["detail"]


def test_enqueue_job_idempotency_replay_prevents_duplicate(client):
    plugin_resp = _register_plugin(client, version="1.0.0")
    assert plugin_resp.status_code == 200

    first = _enqueue_job(client, idem_key="idem-job-1", message="same-message")
    second = _enqueue_job(client, idem_key="idem-job-1", message="same-message")

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["job_id"] == second.json()["job_id"]

    overview = client.get("/dashboard/api/overview", headers={"X-Admin-Token": "test-admin"})
    assert overview.status_code == 200
    assert overview.json()["metrics"]["queued_jobs"] == 1


def test_enqueue_job_idempotency_conflict(client):
    plugin_resp = _register_plugin(client, version="1.0.0")
    assert plugin_resp.status_code == 200

    first = _enqueue_job(client, idem_key="idem-job-2", message="alpha")
    conflict = _enqueue_job(client, idem_key="idem-job-2", message="beta")

    assert first.status_code == 200
    assert conflict.status_code == 409
    assert "idempotency key reused" in conflict.json()["detail"]
