from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from aurora_core.services.llm_commands import load_command_metadata, retrieve_commands
from aurora_core.services.llm_execution import build_execution_plan, normalize_execution_policy
from plugins.LLM.providers import ProviderRequest, get_provider_adapter


def _commands_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "shared_assets" / "knowledge" / "cmd"


def _checkpoint_path() -> Path | None:
    raw = (os.environ.get("AURORA_CHECKPOINT_PATH") or "").strip()
    if not raw:
        return None
    return Path(raw)


def _resume_checkpoint() -> dict[str, Any]:
    raw = os.environ.get("AURORA_RESUME_CHECKPOINT") or "{}"
    try:
        payload = json.loads(raw)
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _job_payload() -> dict[str, Any]:
    raw = os.environ.get("AURORA_JOB_PAYLOAD") or "{}"
    try:
        payload = json.loads(raw)
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _write_checkpoint(path: Path | None, payload: dict[str, Any]) -> None:
    if not path:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def main() -> int:
    payload = _job_payload()
    resume = _resume_checkpoint()
    query = str(payload.get("query") or payload.get("message") or "").strip()
    mode = str(payload.get("mode") or "answer").strip()
    provider = str(payload.get("provider") or "mock").strip()
    max_results = int(payload.get("max_results") or 5)
    execution_policy = normalize_execution_policy(str(payload.get("execution_policy") or "suggest_only"))
    actor_role = str(payload.get("actor_role") or "").strip()
    confirmation_token = str(payload.get("confirmation_token") or "").strip()
    command_payload = payload.get("command_payload") if isinstance(payload.get("command_payload"), dict) else {}
    trace_enabled = bool(payload.get("trace_enabled", True))

    provider_adapter = get_provider_adapter(
        provider,
        ollama_base_url=os.environ.get("AURORA_OLLAMA_BASE_URL"),
        ollama_model=os.environ.get("AURORA_OLLAMA_MODEL"),
        ollama_timeout_seconds=_int_env("AURORA_OLLAMA_TIMEOUT_SECONDS", 60),
        ollama_keep_alive=os.environ.get("AURORA_OLLAMA_KEEP_ALIVE"),
    )

    trace: list[dict[str, Any]] = []
    trace.append(
        {
            "stage": "input_received",
            "message": "LLM plugin received query payload",
            "query": query,
            "mode": mode,
            "provider": provider,
        }
    )
    if resume:
        trace.append(
            {
                "stage": "resumed",
                "message": "Resumed from previous checkpoint",
                "checkpoint_keys": sorted(resume.keys()),
            }
        )

    metadata = load_command_metadata(_commands_dir())
    trace.append(
        {
            "stage": "metadata_loaded",
            "message": "Loaded command metadata files",
            "command_count": len(metadata),
        }
    )

    matches = retrieve_commands(query, _commands_dir(), max_results=max_results)
    trace.append(
        {
            "stage": "retrieval_completed",
            "message": "Command retrieval completed",
            "selected_commands": [item["name"] for item in matches],
            "confidence": matches[0]["confidence"] if matches else 0.0,
        }
    )

    provider_result = provider_adapter.generate(
        ProviderRequest(
            query=query,
            mode=mode,
            matches=matches,
            provider=provider,
            trace_enabled=trace_enabled,
        )
    )
    execution_plan = None
    if matches:
        execution_plan = build_execution_plan(
            matches[0],
            execution_policy=execution_policy,
            payload=command_payload,
            actor_role=actor_role or None,
            confirmation_token=confirmation_token or None,
        ).to_dict()
        trace.append(
            {
                "stage": "execution_plan_validated",
                "message": "Validated command execution plan",
                "execution_policy": execution_policy,
                "approved": execution_plan["approved"],
                "blockers": execution_plan["blockers"],
                "command_name": execution_plan["command_name"],
            }
        )
    trace.append(
        {
            "stage": "provider_selected",
            "message": f"Selected provider adapter: {provider_adapter.name}",
            "provider": provider_adapter.name,
            "model": provider_result.model,
        }
    )
    trace.append(
        {
            "stage": "provider_response_generated",
            "message": "Provider generated structured response",
            "selected_commands": [item["name"] for item in matches],
        }
    )

    output = {
        "schema_version": "v1",
        "plugin": "llm_plugin",
        "provider": provider_adapter.name,
        "status": "completed",
        "mode": mode,
        "execution_policy": execution_policy,
        "query": query,
        "answer": provider_result.answer,
        "matched_commands": matches,
        "execution_plan": execution_plan,
        "work_trace": trace,
        "usage": {
            "provider": provider_adapter.name,
            "model": provider_result.model,
            "input_tokens": provider_result.input_tokens,
            "output_tokens": provider_result.output_tokens,
            "estimated_cost_usd": provider_result.estimated_cost_usd,
        },
    }
    final_checkpoint = {
        "stage": "result_ready",
        "message": "LLM plugin finished",
        "selected_commands": [item["name"] for item in matches],
        "confidence": matches[0]["confidence"] if matches else 0.0,
        "provider": provider_adapter.name,
        "execution_policy": execution_policy,
    }
    if trace_enabled:
        _write_checkpoint(
            _checkpoint_path(),
            {
                **final_checkpoint,
                "work_trace": trace + [final_checkpoint],
            },
        )
    output["work_trace"].append(final_checkpoint)
    print(json.dumps(output, indent=2, sort_keys=True))
    return 0


def _int_env(name: str, default: int) -> int:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


if __name__ == "__main__":
    raise SystemExit(main())
