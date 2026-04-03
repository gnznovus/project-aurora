from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any


def _build_restricted_env(job_payload: dict[str, Any]) -> dict[str, str]:
    allow = {"PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "PYTHONPATH"}
    env = {key: value for key, value in os.environ.items() if key.upper() in allow}
    env["AURORA_JOB_PAYLOAD"] = json.dumps(job_payload)
    return env


def execute_plugin(
    plugin_path: Path,
    timeout_seconds: int,
    job_payload: dict[str, Any],
    checkpoint_path: Path,
    resume_checkpoint: dict[str, Any] | None,
) -> dict[str, Any]:
    start = time.perf_counter()
    env = _build_restricted_env(job_payload)
    env["AURORA_CHECKPOINT_PATH"] = str(checkpoint_path)
    env["AURORA_RESUME_CHECKPOINT"] = json.dumps(resume_checkpoint or {})
    try:
        completed = subprocess.run(
            ["python", str(plugin_path)],
            capture_output=True,
            text=True,
            env=env,
            timeout=timeout_seconds,
            check=False,
        )
        elapsed = int((time.perf_counter() - start) * 1000)
        status = "completed" if completed.returncode == 0 else "failed"
        return {
            "schema_version": "v1",
            "status": status,
            "exit_code": completed.returncode,
            "stdout": completed.stdout[-8000:],
            "stderr": completed.stderr[-8000:],
            "duration_ms": elapsed,
            "metrics": {"timed_out": False},
        }
    except subprocess.TimeoutExpired as exc:
        elapsed = int((time.perf_counter() - start) * 1000)
        return {
            "schema_version": "v1",
            "status": "timeout",
            "exit_code": None,
            "stdout": (exc.stdout or "")[-8000:],
            "stderr": (exc.stderr or "")[-8000:],
            "duration_ms": elapsed,
            "metrics": {"timed_out": True},
        }
