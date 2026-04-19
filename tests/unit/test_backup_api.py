from __future__ import annotations

from pathlib import Path


def _login_superadmin(client) -> None:
    response = client.post("/login", json={"username": "superadmin", "password": "superadmin"})
    assert response.status_code == 200


def test_superadmin_backup_requires_auth(client):
    response = client.post("/superadmin/backups/create")
    assert response.status_code == 401


def test_backup_create_list_validate_flow(client):
    _login_superadmin(client)

    create_response = client.post("/superadmin/backups/create")
    assert create_response.status_code == 200
    create_payload = create_response.json()
    backup_id = create_payload["backup_id"]
    assert create_payload["status"] in {"validated", "created"}
    if create_payload.get("validation"):
        assert create_payload["validation"]["valid"] is True

    list_response = client.get("/superadmin/backups")
    assert list_response.status_code == 200
    backups = list_response.json()["backups"]
    assert any(row["backup_id"] == backup_id for row in backups)

    validate_response = client.post(f"/superadmin/backups/{backup_id}/validate")
    assert validate_response.status_code == 200
    assert validate_response.json()["valid"] is True


def test_backup_prune_prunes_old_backups(client):
    _login_superadmin(client)

    client.app.state.settings.backup_prune_min_keep_count = 1
    client.app.state.settings.backup_retention_daily = 1
    client.app.state.settings.backup_retention_weekly = 1
    client.app.state.settings.backup_retention_monthly = 1
    client.app.state.settings.backup_max_storage_gb = 0.00001

    first = client.post("/superadmin/backups/create")
    second = client.post("/superadmin/backups/create")
    third = client.post("/superadmin/backups/create")
    assert first.status_code == 200
    assert second.status_code == 200
    assert third.status_code == 200

    prune_response = client.post("/superadmin/backups/prune")
    assert prune_response.status_code == 200
    payload = prune_response.json()
    assert payload["pruned_count"] >= 1

    list_response = client.get("/superadmin/backups")
    assert list_response.status_code == 200
    rows = list_response.json()["backups"]
    statuses = {row["backup_id"]: row["status"] for row in rows}
    assert statuses[first.json()["backup_id"]] in {"created", "validated", "pruned"}
    assert statuses[second.json()["backup_id"]] in {"created", "validated", "pruned"}


def test_backup_prune_keeps_at_least_one_validated_backup(client):
    _login_superadmin(client)

    client.app.state.settings.backup_retention_daily = 0
    client.app.state.settings.backup_retention_weekly = 0
    client.app.state.settings.backup_retention_monthly = 0
    client.app.state.settings.backup_prune_min_keep_count = 1
    client.app.state.settings.backup_max_storage_gb = 0.0000001

    for _ in range(3):
        response = client.post("/superadmin/backups/create")
        assert response.status_code == 200

    prune_response = client.post("/superadmin/backups/prune")
    assert prune_response.status_code == 200

    rows = client.get("/superadmin/backups").json()["backups"]
    remaining = [row for row in rows if row["status"] != "pruned"]
    assert remaining
    assert any(row["status"] == "validated" for row in remaining)


def test_backup_validate_detects_corruption(client):
    _login_superadmin(client)
    create_response = client.post("/superadmin/backups/create")
    assert create_response.status_code == 200
    backup_id = create_response.json()["backup_id"]
    backup_path = Path(create_response.json()["storage_path"])
    (backup_path / "db.json").write_text("{}", encoding="utf-8")

    validate_response = client.post(f"/superadmin/backups/{backup_id}/validate")
    assert validate_response.status_code == 200
    body = validate_response.json()
    assert body["valid"] is False
    assert body["issues"]


def test_backup_restore_dry_run_preview(client):
    _login_superadmin(client)
    created = client.post("/superadmin/backups/create")
    assert created.status_code == 200
    backup_id = created.json()["backup_id"]

    response = client.post(f"/superadmin/backups/{backup_id}/restore?dry_run=true")
    assert response.status_code == 200
    payload = response.json()
    assert payload["dry_run"] is True
    assert "steps" in payload
    assert "database_preview" in payload
    assert "plugins_preview" in payload


def test_backup_restore_not_found(client):
    _login_superadmin(client)
    response = client.post("/superadmin/backups/bkp_missing/restore?dry_run=true")
    assert response.status_code == 404


def test_backup_restore_apply_reverts_state(client):
    _login_superadmin(client)
    created = client.post("/superadmin/backups/create")
    assert created.status_code == 200
    backup_id = created.json()["backup_id"]

    create_user = client.post(
        "/superadmin/users",
        json={"username": "restore_target", "password": "secret123", "role": "operator"},
    )
    assert create_user.status_code == 200

    response = client.post(
        f"/superadmin/backups/{backup_id}/restore?dry_run=false",
        json={"confirm": backup_id},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["dry_run"] is False

    create_again = client.post(
        "/superadmin/users",
        json={"username": "restore_target", "password": "secret123", "role": "operator"},
    )
    assert create_again.status_code == 200


def test_maintenance_mode_blocks_mutation_endpoints(client):
    _login_superadmin(client)
    service = client.app.state.backup_service
    service.set_maintenance_mode(enabled=True, actor="test", reason="unit-test")
    try:
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
        assert response.status_code == 503
    finally:
        service.set_maintenance_mode(enabled=False, actor="test", reason="unit-test-finished")


def test_backup_offsite_sync_endpoint(client):
    _login_superadmin(client)
    created = client.post("/superadmin/backups/create")
    assert created.status_code == 200
    backup_id = created.json()["backup_id"]

    response = client.post(f"/superadmin/backups/{backup_id}/offsite-sync")
    assert response.status_code == 200
    payload = response.json()
    assert payload["enabled"] is True
    assert payload["found"] is True
    assert payload["synced"] is True


def test_dashboard_overview_contains_backup_summary(client):
    _login_superadmin(client)
    client.post("/superadmin/backups/create")
    response = client.get("/dashboard/api/overview")
    assert response.status_code == 200
    payload = response.json()
    assert "backup_summary" in payload
    assert "count" in payload["backup_summary"]
    assert "latest_validated" in payload["backup_summary"]


def test_backup_health_endpoint(client):
    _login_superadmin(client)
    client.post("/superadmin/backups/create")
    response = client.get("/superadmin/backups/health")
    assert response.status_code == 200
    payload = response.json()["health"]
    assert "storage_utilization_pct" in payload
    assert "latest_validated" in payload


def test_audit_logs_export_csv(client):
    _login_superadmin(client)
    response = client.get("/superadmin/audit/logs/export?limit=200")
    assert response.status_code == 200
    assert "text/csv" in response.headers.get("content-type", "")
    assert "attachment;" in response.headers.get("content-disposition", "")
    assert "action" in response.text


def test_backup_manifest_download(client):
    _login_superadmin(client)
    created = client.post("/superadmin/backups/create")
    assert created.status_code == 200
    backup_id = created.json()["backup_id"]
    response = client.get(f"/superadmin/backups/{backup_id}/manifest/download")
    assert response.status_code == 200
    assert "application/json" in response.headers.get("content-type", "")
    assert "backup_id" in response.text


def test_debug_enqueue_random_requires_auth(client):
    response = client.post("/superadmin/debug/enqueue-random")
    assert response.status_code == 401


def test_debug_enqueue_random_job(client):
    _login_superadmin(client)
    response = client.post("/superadmin/debug/enqueue-random")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "queued"
    assert payload["job_id"].startswith("JOB_")
    assert payload["mode"] in {"echo", "sleep", "fail"}
