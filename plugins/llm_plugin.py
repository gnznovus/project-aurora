from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from aurora_core.services.llm_commands import load_command_metadata, retrieve_commands


def _commands_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "plugins" / "shared_assets" / "knowledge" / "cmd"


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


def _build_mock_answer(query: str, matches: list[dict[str, Any]], mode: str) -> str:
    if not matches:
        return f"No command metadata matched: {query}"
    top = matches[0]
    if mode == "command_suggest":
        return f"Suggest {top['method']} {top['endpoint']} using {top['name']}."
    return (
        f"Use {top['name']} at {top['endpoint']}. "
        f"Top match confidence {top['confidence']:.2f}. "
        f"Review confirmation requirements before any destructive action."
    )


def main() -> int:
    payload = _job_payload()
    resume = _resume_checkpoint()
    query = str(payload.get("query") or payload.get("message") or "").strip()
    mode = str(payload.get("mode") or "answer").strip()
    provider = str(payload.get("provider") or "mock").strip()
    max_results = int(payload.get("max_results") or 5)
    trace_enabled = bool(payload.get("trace_enabled", True))

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

    output = {
        "schema_version": "v1",
        "plugin": "llm_plugin",
        "provider": provider,
        "status": "completed",
        "mode": mode,
        "query": query,
        "answer": _build_mock_answer(query, matches, mode),
        "matched_commands": matches,
        "work_trace": trace,
        "usage": {
            "provider": provider,
            "model": "mock-llm-v1",
            "input_tokens": 0,
            "output_tokens": 0,
            "estimated_cost_usd": 0,
        },
    }

    trace.append(
        {
            "stage": "provider_response_generated",
            "message": "Mock provider generated structured response",
            "selected_commands": [item["name"] for item in matches],
        }
    )
    final_checkpoint = {
        "stage": "result_ready",
        "message": "LLM plugin finished",
        "selected_commands": [item["name"] for item in matches],
        "confidence": matches[0]["confidence"] if matches else 0.0,
        "provider": provider,
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


if __name__ == "__main__":
    raise SystemExit(main())
