from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Protocol

import requests

_OLLAMA_SYSTEM_PROMPT = (
    "You are Aurora LLM. Return exactly one JSON object with keys "
    '"answer", "summary", "selected_commands", and "confidence". '
    "Do not emit markdown, prose, or code fences."
)


@dataclass(slots=True)
class ProviderRequest:
    query: str
    mode: str
    matches: list[dict[str, Any]]
    provider: str
    trace_enabled: bool = True


@dataclass(slots=True)
class ProviderResult:
    answer: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    estimated_cost_usd: float = 0.0
    extra: dict[str, Any] = field(default_factory=dict)


class ProviderAdapter(Protocol):
    name: str

    def generate(self, request: ProviderRequest) -> ProviderResult:
        raise NotImplementedError


class MockProviderAdapter:
    name = "mock"
    model = "mock-llm-v1"

    def generate(self, request: ProviderRequest) -> ProviderResult:
        answer = _build_mock_answer(request.query, request.matches, request.mode)
        return ProviderResult(
            answer=answer,
            model=self.model,
            input_tokens=0,
            output_tokens=0,
            estimated_cost_usd=0.0,
            extra={
                "provider": self.name,
                "selected_commands": [item["name"] for item in request.matches],
            },
        )


class OllamaLocalProviderAdapter:
    name = "ollama_local"

    def __init__(self, base_url: str, model: str, timeout_seconds: int, keep_alive: str) -> None:
        self.base_url = base_url
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.keep_alive = keep_alive

    def generate(self, request: ProviderRequest) -> ProviderResult:
        prompt = _build_ollama_prompt(request)
        payload = {
            "model": self.model,
            "stream": False,
            "keep_alive": self.keep_alive,
            "format": "json",
            "messages": [
                {
                    "role": "system",
                    "content": _OLLAMA_SYSTEM_PROMPT,
                },
                {
                    "role": "user",
                    "content": prompt,
                },
            ],
        }
        response = requests.post(
            f"{self.base_url.rstrip('/')}/api/chat",
            json=payload,
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        data = response.json()
        content = _extract_ollama_content(data)
        parsed = _parse_json_object(content)
        normalized = _normalize_ollama_response(parsed, request, content)
        extra = {
            "provider": self.name,
            "selected_commands": normalized["selected_commands"],
            "raw_model": self.model,
            "response_valid_json": normalized["response_valid_json"],
            "response_summary": normalized["summary"],
            "response_confidence": normalized["confidence"],
        }
        usage = data.get("usage") if isinstance(data, dict) else {}
        if isinstance(usage, dict):
            prompt_tokens = usage.get("prompt_eval_count") or usage.get("prompt_tokens") or 0
            output_tokens = usage.get("eval_count") or usage.get("completion_tokens") or 0
            extra["duration_ms"] = usage.get("total_duration", 0)
        else:
            prompt_tokens = 0
            output_tokens = 0
        return ProviderResult(
            answer=normalized["answer"],
            model=self.model,
            input_tokens=int(prompt_tokens or 0),
            output_tokens=int(output_tokens or 0),
            estimated_cost_usd=0.0,
            extra=extra,
        )


def get_provider_adapter(
    provider: str,
    *,
    ollama_base_url: str | None = None,
    ollama_model: str | None = None,
    ollama_timeout_seconds: int | None = None,
    ollama_keep_alive: str | None = None,
) -> ProviderAdapter:
    value = (provider or "mock").strip().lower()
    if value == "ollama_local":
        return OllamaLocalProviderAdapter(
            base_url=ollama_base_url or "http://127.0.0.1:11434",
            model=ollama_model or "llama3.2:3b",
            timeout_seconds=int(ollama_timeout_seconds or 60),
            keep_alive=ollama_keep_alive or "5m",
        )
    return MockProviderAdapter()


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


def _build_ollama_prompt(request: ProviderRequest) -> str:
    command_lines = []
    for item in request.matches:
        command_lines.append(
            f"- {item['name']} [{item['method']} {item['endpoint']}] "
            f"auth={item['auth']} risk={item['risk_level']} confirm={item['requires_confirmation']} "
            f"desc={item['description']}"
        )
    commands_block = "\n".join(command_lines) if command_lines else "- none"
    return (
        "Task: answer the user by using only the matched Aurora command metadata.\n"
        "Return exactly one JSON object and no extra prose.\n"
        'JSON schema: {"answer": string, "summary": string, "selected_commands": [string], "confidence": number}\n'
        "Rules:\n"
        "- Use only command names from the matched list.\n"
        "- If no match is suitable, return an empty selected_commands array.\n"
        "- Keep answer concise and actionable.\n"
        "- Confidence must be a number between 0 and 1.\n"
        "- Do not emit markdown, code fences, or commentary.\n"
        f"Mode: {request.mode}\n"
        f"User query: {request.query}\n"
        f"Matched commands:\n{commands_block}\n"
    )


def _extract_ollama_content(data: dict[str, Any]) -> str:
    message = data.get("message") if isinstance(data, dict) else None
    if isinstance(message, dict):
        content = message.get("content")
        if isinstance(content, str):
            return content.strip()
    response = data.get("response") if isinstance(data, dict) else None
    if isinstance(response, str):
        return response.strip()
    return json.dumps(data, sort_keys=True)


def _parse_json_object(content: str) -> dict[str, Any] | None:
    raw = (content or "").strip()
    if not raw:
        return None
    try:
        payload = json.loads(raw)
        return payload if isinstance(payload, dict) else None
    except json.JSONDecodeError:
        start = raw.find("{")
        end = raw.rfind("}")
        if start >= 0 and end > start:
            try:
                payload = json.loads(raw[start : end + 1])
                return payload if isinstance(payload, dict) else None
            except json.JSONDecodeError:
                return None
        return None


def _normalize_ollama_response(
    parsed: dict[str, Any] | None,
    request: ProviderRequest,
    raw_content: str,
) -> dict[str, Any]:
    valid_json = parsed is not None
    parsed = parsed or {}
    allowed_names = set(_selected_command_names(request.matches))
    selected_commands = _normalize_selected_commands(parsed.get("selected_commands"), allowed_names)
    summary = _coerce_text(parsed.get("summary")) or _coerce_text(parsed.get("answer"))
    confidence = _coerce_confidence(parsed.get("confidence"))
    if confidence is None and request.matches:
        confidence = float(request.matches[0].get("confidence") or 0.0)
    if not summary:
        summary = _fallback_answer(request)
    answer = _coerce_text(parsed.get("answer")) or summary
    if not valid_json:
        answer = _fallback_answer(request)
        summary = answer
        selected_commands = _selected_command_names(request.matches)
        confidence = float(request.matches[0].get("confidence") or 0.0) if request.matches else 0.0
    return {
        "answer": answer,
        "summary": summary,
        "selected_commands": selected_commands,
        "confidence": confidence if confidence is not None else 0.0,
        "response_valid_json": valid_json,
        "raw_content": raw_content,
    }


def _normalize_selected_commands(
    value: Any,
    allowed_names: set[str],
) -> list[str]:
    if not isinstance(value, list):
        return []
    selected: list[str] = []
    for item in value:
        name = _coerce_text(item)
        if name and name in allowed_names and name not in selected:
            selected.append(name)
    return selected


def _coerce_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if value is None:
        return ""
    return str(value).strip()


def _coerce_confidence(value: Any) -> float | None:
    if value is None:
        return None
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        return None
    if confidence < 0:
        return 0.0
    if confidence > 1:
        return 1.0
    return confidence


def _fallback_answer(request: ProviderRequest) -> str:
    return _build_mock_answer(request.query, request.matches, request.mode)


def _selected_command_names(matches: list[dict[str, Any]]) -> list[str]:
    return [item.get("name", "") for item in matches if item.get("name")]
