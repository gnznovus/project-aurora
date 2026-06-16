from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path

from aurora_agent.executor import execute_plugin

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_llm_plugin_mock_response_and_checkpoint():
    plugin_path = REPO_ROOT / "plugins" / "llm_plugin.py"
    root = REPO_ROOT / ".testdata" / uuid.uuid4().hex
    root.mkdir(parents=True, exist_ok=True)
    try:
        checkpoint_path = root / "llm_checkpoint.json"
        result = execute_plugin(
            plugin_path=plugin_path,
            timeout_seconds=5,
            job_payload={
                "query": "restore backup safely",
                "mode": "answer",
                "provider": "mock",
                "max_results": 3,
                "trace_enabled": True,
            },
            checkpoint_path=checkpoint_path,
            resume_checkpoint=None,
        )

        assert result["status"] == "completed"
        assert result["exit_code"] == 0
        payload = json.loads(result["stdout"])
        assert payload["plugin"] == "llm_plugin"
        assert payload["provider"] == "mock"
        assert payload["matched_commands"]
        assert payload["matched_commands"][0]["name"] == "backup.restore"
        assert any(step["stage"] == "retrieval_completed" for step in payload["work_trace"])

        checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        assert checkpoint["stage"] == "result_ready"
        assert checkpoint["provider"] == "mock"
    finally:
        shutil.rmtree(root, ignore_errors=True)
