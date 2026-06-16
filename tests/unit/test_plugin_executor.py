from __future__ import annotations

from pathlib import Path

from aurora_agent.executor import execute_plugin

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_plugin_executor_success():
    plugin = REPO_ROOT / "plugins" / "echo_plugin.py"
    result = execute_plugin(
        plugin,
        timeout_seconds=2,
        job_payload={"message": "ok"},
        checkpoint_path=REPO_ROOT / ".agent-cache" / "checkpoints" / "test-success.json",
        resume_checkpoint=None,
    )
    assert result["status"] == "completed"
    assert result["exit_code"] == 0
    assert "ok" in result["stdout"]


def test_plugin_executor_failure():
    plugin = REPO_ROOT / "plugins" / "echo_plugin.py"
    result = execute_plugin(
        plugin,
        timeout_seconds=2,
        job_payload={"action": "fail", "code": 3},
        checkpoint_path=REPO_ROOT / ".agent-cache" / "checkpoints" / "test-failure.json",
        resume_checkpoint=None,
    )
    assert result["status"] == "failed"
    assert result["exit_code"] == 3
    assert "forced failure" in result["stderr"]


def test_plugin_executor_timeout():
    plugin = REPO_ROOT / "plugins" / "echo_plugin.py"
    result = execute_plugin(
        plugin,
        timeout_seconds=1,
        job_payload={"action": "sleep", "seconds": 2},
        checkpoint_path=REPO_ROOT / ".agent-cache" / "checkpoints" / "test-timeout.json",
        resume_checkpoint=None,
    )
    assert result["status"] == "timeout"
    assert result["metrics"]["timed_out"] is True
