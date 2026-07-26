from __future__ import annotations

import json

from aurora_core.config import Settings
from plugins.LLM.providers import (
    MockProviderAdapter,
    OllamaLocalProviderAdapter,
    ProviderRequest,
    get_provider_adapter,
)


def test_mock_provider_is_default_adapter():
    adapter = get_provider_adapter("mock")
    assert isinstance(adapter, MockProviderAdapter)


def test_ollama_provider_uses_local_config():
    adapter = get_provider_adapter(
        "ollama_local",
        ollama_base_url="http://127.0.0.1:11434",
        ollama_model="llama3.2:3b",
        ollama_timeout_seconds=45,
        ollama_keep_alive="10m",
    )
    assert isinstance(adapter, OllamaLocalProviderAdapter)
    assert adapter.base_url == "http://127.0.0.1:11434"
    assert adapter.model == "llama3.2:3b"
    assert adapter.timeout_seconds == 45
    assert adapter.keep_alive == "10m"


def test_llm_settings_defaults_present():
    settings = Settings(
        database_url="sqlite:///d:/Code/Python/Project_Aurora/.testdata/llm_config.db",
        redis_url="redis://localhost:6379/15",
    )
    assert settings.llm_provider_default == "mock"
    assert settings.ollama_base_url.startswith("http://127.0.0.1")
    assert settings.ollama_model
    assert settings.ollama_timeout_seconds > 0
    assert settings.ollama_keep_alive


def test_ollama_provider_parses_local_json_response(monkeypatch):
    captured = {}

    class _Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "message": {
                    "content": json.dumps(
                        {
                            "answer": "Use backup restore safely.",
                            "summary": "Restore guidance",
                            "selected_commands": ["backup.restore"],
                            "confidence": 0.91,
                        }
                    )
                },
                "usage": {
                    "prompt_eval_count": 11,
                    "eval_count": 7,
                    "total_duration": 123456,
                },
            }

    def _fake_post(url, json=None, timeout=None):  # noqa: A002
        captured["url"] = url
        captured["json"] = json
        captured["timeout"] = timeout
        return _Response()

    monkeypatch.setattr("plugins.LLM.providers.requests.post", _fake_post)
    adapter = OllamaLocalProviderAdapter(
        base_url="http://127.0.0.1:11434",
        model="llama3.2:3b",
        timeout_seconds=45,
        keep_alive="10m",
    )
    result = adapter.generate(
        ProviderRequest(
            query="restore backup safely",
            mode="answer",
            matches=[
                {
                    "name": "backup.restore",
                    "method": "POST",
                    "endpoint": "/superadmin/backups/{backup_id}/restore",
                    "auth": "superadmin_session",
                    "description": "Safely dry-run or apply a backup restore.",
                    "tags": ["backup", "restore"],
                    "risk_level": "destructive",
                    "requires_confirmation": True,
                    "executable": False,
                    "execution_kind": "aurora_api",
                    "confidence": 0.99,
                }
            ],
            provider="ollama_local",
            trace_enabled=True,
        )
    )

    assert captured["url"] == "http://127.0.0.1:11434/api/chat"
    assert captured["timeout"] == 45
    assert captured["json"]["model"] == "llama3.2:3b"
    assert result.answer == "Use backup restore safely."
    assert result.model == "llama3.2:3b"
    assert result.input_tokens == 11
    assert result.output_tokens == 7
    assert result.extra["provider"] == "ollama_local"
    assert result.extra["selected_commands"] == ["backup.restore"]
    assert result.extra["response_valid_json"] is True
    assert result.extra["response_summary"] == "Restore guidance"
    assert result.extra["response_confidence"] == 0.91


def test_ollama_provider_normalizes_fenced_json_and_filters_commands(monkeypatch):
    class _Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "message": {
                    "content": "```json\n"
                    + json.dumps(
                        {
                            "answer": "Use health ready first.",
                            "summary": "Readiness guidance",
                            "selected_commands": ["health.ready", "not.allowed"],
                            "confidence": 1.2,
                        }
                    )
                    + "\n```"
                }
            }

    def _fake_post(url, json=None, timeout=None):  # noqa: A002
        return _Response()

    monkeypatch.setattr("plugins.LLM.providers.requests.post", _fake_post)
    adapter = OllamaLocalProviderAdapter(
        base_url="http://127.0.0.1:11434",
        model="llama3.2:3b",
        timeout_seconds=45,
        keep_alive="10m",
    )
    result = adapter.generate(
        ProviderRequest(
            query="check readiness",
            mode="answer",
            matches=[
                {
                    "name": "health.ready",
                    "method": "GET",
                    "endpoint": "/health/ready",
                    "auth": "public",
                    "description": "Readiness probe.",
                    "tags": ["health"],
                    "risk_level": "low",
                    "requires_confirmation": False,
                    "executable": False,
                    "execution_kind": "aurora_api",
                    "confidence": 0.77,
                }
            ],
            provider="ollama_local",
            trace_enabled=True,
        )
    )

    assert result.answer == "Use health ready first."
    assert result.extra["selected_commands"] == ["health.ready"]
    assert result.extra["response_valid_json"] is True
    assert result.extra["response_confidence"] == 1.0


def test_ollama_provider_falls_back_when_response_is_not_json(monkeypatch):
    class _Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"message": {"content": "I think you should run backup restore."}}

    def _fake_post(url, json=None, timeout=None):  # noqa: A002
        return _Response()

    monkeypatch.setattr("plugins.LLM.providers.requests.post", _fake_post)
    adapter = OllamaLocalProviderAdapter(
        base_url="http://127.0.0.1:11434",
        model="llama3.2:3b",
        timeout_seconds=45,
        keep_alive="10m",
    )
    result = adapter.generate(
        ProviderRequest(
            query="restore backup safely",
            mode="answer",
            matches=[
                {
                    "name": "backup.restore",
                    "method": "POST",
                    "endpoint": "/superadmin/backups/{backup_id}/restore",
                    "auth": "superadmin_session",
                    "description": "Safely dry-run or apply a backup restore.",
                    "tags": ["backup", "restore"],
                    "risk_level": "destructive",
                    "requires_confirmation": True,
                    "executable": False,
                    "execution_kind": "aurora_api",
                    "confidence": 0.99,
                }
            ],
            provider="ollama_local",
            trace_enabled=True,
        )
    )

    assert (
        result.answer
        == "Use backup.restore at /superadmin/backups/{backup_id}/restore. "
        "Top match confidence 0.99. Review confirmation requirements before any destructive action."
    )
    assert result.extra["response_valid_json"] is False
    assert result.extra["selected_commands"] == ["backup.restore"]
    assert result.extra["response_confidence"] == 0.99
