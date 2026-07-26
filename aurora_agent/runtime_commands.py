from __future__ import annotations

import json
from typing import Any


ALLOWED_RUNTIME_COMMANDS = {"health.ready", "health.live", "dashboard.overview"}


def parse_plugin_output(stdout: str) -> dict[str, Any] | None:
    raw = (stdout or "").strip()
    if not raw:
        return None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def execute_allowlisted_runtime_command(
    client: Any,
    plugin_output: dict[str, Any] | None,
    *,
    enabled: bool,
) -> dict[str, Any] | None:
    if not enabled or not isinstance(plugin_output, dict):
        return None

    execution_policy = str(plugin_output.get("execution_policy") or "").strip().lower()
    if execution_policy != "allowlisted_execute":
        return None

    execution_plan = plugin_output.get("execution_plan")
    if not isinstance(execution_plan, dict):
        return None
    if not execution_plan.get("approved"):
        return None

    command_name = str(execution_plan.get("command_name") or "").strip()
    if command_name not in ALLOWED_RUNTIME_COMMANDS:
        return {
            "status": "blocked",
            "command_name": command_name,
            "reason": "command is not in the runtime allowlist",
            "allowed": False,
        }

    if command_name == "health.ready":
        payload = client.health_ready()
        return {
            "status": "completed",
            "command_name": command_name,
            "allowed": True,
            "response": payload,
            "response_status": payload.get("status") if isinstance(payload, dict) else None,
            "degraded_components": payload.get("degraded_components") if isinstance(payload, dict) else None,
        }
    if command_name == "health.live":
        payload = client.health_live()
        return {
            "status": "completed",
            "command_name": command_name,
            "allowed": True,
            "response": payload,
            "response_status": payload.get("status") if isinstance(payload, dict) else None,
        }
    if command_name == "dashboard.overview":
        payload = client.runtime_overview()
        return {
            "status": "completed",
            "command_name": command_name,
            "allowed": True,
            "response": payload,
            "response_status": payload.get("status") if isinstance(payload, dict) else None,
            "metrics": payload.get("metrics") if isinstance(payload, dict) else None,
        }

    return {
        "status": "blocked",
        "command_name": command_name,
        "reason": "unsupported runtime command",
        "allowed": False,
    }
