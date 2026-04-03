from __future__ import annotations

import hashlib
from pathlib import Path


class PluginStore:
    def __init__(self, plugins_dir: Path) -> None:
        self.plugins_dir = plugins_dir
        self.plugins_dir.mkdir(parents=True, exist_ok=True)

    def resolve(self, filename: str) -> Path:
        candidate = (self.plugins_dir / filename).resolve()
        if self.plugins_dir.resolve() not in candidate.parents:
            raise ValueError("invalid plugin filename")
        return candidate

    def digest_file(self, filename: str) -> str:
        path = self.resolve(filename)
        if not path.exists():
            raise FileNotFoundError(filename)
        hasher = hashlib.sha256()
        with path.open("rb") as handle:
            while True:
                block = handle.read(8192)
                if not block:
                    break
                hasher.update(block)
        return hasher.hexdigest()

