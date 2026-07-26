from __future__ import annotations

from aurora_core.services.llm_execution import build_execution_plan, normalize_execution_policy


def test_execution_policy_normalization_defaults_to_suggest_only():
    assert normalize_execution_policy(None) == "suggest_only"
    assert normalize_execution_policy("PLAN_ONLY") == "plan_only"
    assert normalize_execution_policy("unknown") == "suggest_only"


def test_free_form_command_cannot_approve_execution():
    plan = build_execution_plan(
        {
            "name": "backup.restore",
            "endpoint": "/superadmin/backups/{backup_id}/restore",
            "execution_kind": "aurora_api",
            "risk_level": "destructive",
            "requires_confirmation": True,
            "required_role": "superadmin",
            "executable": False,
        },
        execution_policy="allowlisted_execute",
        payload={"confirm": "BKP_123"},
        actor_role="superadmin",
        confirmation_token="cfm_123",
    )

    assert plan.approved is False
    assert plan.status == "blocked"
    assert "command not marked executable" in plan.blockers


def test_execution_plan_requires_confirmation_for_destructive_command():
    plan = build_execution_plan(
        {
            "name": "backup.restore",
            "endpoint": "/superadmin/backups/{backup_id}/restore",
            "execution_kind": "aurora_api",
            "risk_level": "destructive",
            "requires_confirmation": True,
            "required_role": "superadmin",
            "executable": True,
        },
        execution_policy="allowlisted_execute",
        payload={"confirm": "BKP_123"},
        actor_role="superadmin",
        confirmation_token="cfm_123",
    )

    assert plan.approved is True
    assert plan.status == "validated"
    assert plan.blockers == []


def test_execution_plan_blocks_missing_confirmation_token():
    plan = build_execution_plan(
        {
            "name": "backup.restore",
            "endpoint": "/superadmin/backups/{backup_id}/restore",
            "execution_kind": "aurora_api",
            "risk_level": "destructive",
            "requires_confirmation": True,
            "required_role": "superadmin",
            "executable": True,
        },
        execution_policy="allowlisted_execute",
        payload={"confirm": "BKP_123"},
        actor_role="superadmin",
        confirmation_token="",
    )

    assert plan.approved is False
    assert "confirmation token required" in plan.blockers
