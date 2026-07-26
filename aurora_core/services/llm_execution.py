from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


ALLOWED_EXECUTION_POLICIES = {"suggest_only", "plan_only", "allowlisted_execute"}


@dataclass(slots=True)
class ExecutionPlanResult:
    policy: str
    status: str
    approved: bool
    command_name: str = ""
    command_endpoint: str = ""
    execution_kind: str = ""
    risk_level: str = ""
    requires_confirmation: bool = False
    required_role: str = ""
    blockers: list[str] = field(default_factory=list)
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "policy": self.policy,
            "status": self.status,
            "approved": self.approved,
            "command_name": self.command_name,
            "command_endpoint": self.command_endpoint,
            "execution_kind": self.execution_kind,
            "risk_level": self.risk_level,
            "requires_confirmation": self.requires_confirmation,
            "required_role": self.required_role,
            "blockers": list(self.blockers),
            "payload": dict(self.payload),
        }


def normalize_execution_policy(value: str | None) -> str:
    normalized = (value or "suggest_only").strip().lower()
    if normalized in ALLOWED_EXECUTION_POLICIES:
        return normalized
    return "suggest_only"


def build_execution_plan(
    command: dict[str, Any] | None,
    *,
    execution_policy: str | None,
    payload: dict[str, Any] | None = None,
    actor_role: str | None = None,
    confirmation_token: str | None = None,
) -> ExecutionPlanResult:
    policy = normalize_execution_policy(execution_policy)
    normalized_payload = payload if isinstance(payload, dict) else {}
    if policy == "suggest_only":
        return ExecutionPlanResult(
            policy=policy,
            status="disabled",
            approved=False,
            blockers=["execution disabled by policy"],
            payload=normalized_payload,
        )

    if not isinstance(command, dict) or not command:
        return ExecutionPlanResult(
            policy=policy,
            status="blocked",
            approved=False,
            blockers=["no command selected"],
            payload=normalized_payload,
        )

    blockers: list[str] = []
    command_name = str(command.get("name") or "").strip()
    command_endpoint = str(command.get("endpoint") or "").strip()
    execution_kind = str(command.get("execution_kind") or "").strip()
    risk_level = str(command.get("risk_level") or "normal").strip()
    requires_confirmation = bool(command.get("requires_confirmation"))
    required_role = str(command.get("required_role") or "").strip()
    executable = bool(command.get("executable"))

    if not command_name:
        blockers.append("command missing name")
    if not executable:
        blockers.append("command not marked executable")
    if execution_kind != "aurora_api":
        blockers.append("unsupported execution kind")
    if required_role and _normalize_text(actor_role) != required_role:
        blockers.append("actor role does not satisfy command requirement")
    if requires_confirmation and not _normalize_text(confirmation_token):
        blockers.append("confirmation token required")

    schema = command.get("payload_schema")
    schema_blocker = _validate_payload_schema(schema, normalized_payload)
    if schema_blocker:
        blockers.extend(schema_blocker)

    approved = not blockers
    status = "validated" if approved else "blocked"
    return ExecutionPlanResult(
        policy=policy,
        status=status,
        approved=approved,
        command_name=command_name,
        command_endpoint=command_endpoint,
        execution_kind=execution_kind,
        risk_level=risk_level,
        requires_confirmation=requires_confirmation,
        required_role=required_role,
        blockers=blockers,
        payload=normalized_payload,
    )


def _validate_payload_schema(schema: Any, payload: dict[str, Any]) -> list[str]:
    if schema is None:
        return []
    if not isinstance(schema, dict):
        return ["payload schema is invalid"]
    if not isinstance(payload, dict):
        return ["payload must be an object"]

    blockers: list[str] = []
    required = schema.get("required")
    if isinstance(required, list):
        for item in required:
            key = _normalize_text(item)
            if key and key not in payload:
                blockers.append(f"missing required payload field: {key}")

    properties = schema.get("properties")
    if isinstance(properties, dict) and schema.get("additionalProperties") is False:
        allowed = {_normalize_text(key) for key in properties.keys() if _normalize_text(key)}
        for key in payload.keys():
            if _normalize_text(key) not in allowed:
                blockers.append(f"unexpected payload field: {key}")

    return blockers


def _normalize_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if value is None:
        return ""
    return str(value).strip()
