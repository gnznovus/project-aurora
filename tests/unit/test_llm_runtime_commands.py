from __future__ import annotations

from aurora_agent.runtime_commands import execute_allowlisted_runtime_command, parse_plugin_output


def test_parse_plugin_output_rejects_non_json():
    assert parse_plugin_output("not json") is None


def test_runtime_command_executes_health_ready_when_enabled():
    calls = {}

    class _Client:
        def health_ready(self):
            calls["health_ready"] = True
            return {
                "status": "ready",
                "service": "aurora-core",
                "degraded_components": [],
            }

    plugin_output = {
        "execution_policy": "allowlisted_execute",
        "execution_plan": {
            "approved": True,
            "command_name": "health.ready",
        },
    }
    result = execute_allowlisted_runtime_command(_Client(), plugin_output, enabled=True)

    assert calls["health_ready"] is True
    assert result["status"] == "completed"
    assert result["allowed"] is True
    assert result["response_status"] == "ready"


def test_runtime_command_executes_health_live_when_enabled():
    calls = {}

    class _Client:
        def health_live(self):
            calls["health_live"] = True
            return {
                "status": "ok",
                "service": "aurora-core",
            }

    plugin_output = {
        "execution_policy": "allowlisted_execute",
        "execution_plan": {
            "approved": True,
            "command_name": "health.live",
        },
    }
    result = execute_allowlisted_runtime_command(_Client(), plugin_output, enabled=True)

    assert calls["health_live"] is True
    assert result["status"] == "completed"
    assert result["allowed"] is True
    assert result["response_status"] == "ok"


def test_runtime_command_stays_disabled_by_default():
    plugin_output = {
        "execution_policy": "allowlisted_execute",
        "execution_plan": {
            "approved": True,
            "command_name": "health.ready",
        },
    }
    result = execute_allowlisted_runtime_command(object(), plugin_output, enabled=False)
    assert result is None


def test_runtime_command_executes_dashboard_overview_when_enabled():
    calls = {}

    class _Client:
        def runtime_overview(self):
            calls["runtime_overview"] = True
            return {
                "status": "ok",
                "service": "aurora-core",
                "metrics": {"queued_jobs": 1},
            }

    plugin_output = {
        "execution_policy": "allowlisted_execute",
        "execution_plan": {
            "approved": True,
            "command_name": "dashboard.overview",
        },
    }
    result = execute_allowlisted_runtime_command(_Client(), plugin_output, enabled=True)

    assert calls["runtime_overview"] is True
    assert result["status"] == "completed"
    assert result["allowed"] is True
    assert result["response_status"] == "ok"
    assert result["metrics"] == {"queued_jobs": 1}
