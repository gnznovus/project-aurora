import json
import os
import sys
import time
from pathlib import Path


def _checkpoint_path() -> Path | None:
    raw = os.environ.get("AURORA_CHECKPOINT_PATH")
    if not raw:
        return None
    return Path(raw)


def _resume_checkpoint() -> dict:
    raw = os.environ.get("AURORA_RESUME_CHECKPOINT", "{}")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _write_checkpoint(payload: dict) -> None:
    path = _checkpoint_path()
    if not path:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def main() -> int:
    raw = os.environ.get("AURORA_JOB_PAYLOAD", "{}")
    payload = json.loads(raw)
    action = payload.get("action", "echo")
    resume = _resume_checkpoint()

    if action == "sleep":
        seconds = int(payload.get("seconds", 1))
        step = int(resume.get("step", 0))
        while step < seconds:
            time.sleep(1)
            step += 1
            _write_checkpoint({"step": step, "total": seconds})
        print(f"slept={seconds}")
        return 0
    if action == "fail":
        print("forced failure", file=sys.stderr)
        return int(payload.get("code", 1))

    print(json.dumps({"message": payload.get("message", "hello from aurora plugin")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
