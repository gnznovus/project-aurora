from __future__ import annotations

from pathlib import Path


class PluginCache:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def get_path(self, plugin_name: str, digest: str) -> Path:
        safe_name = plugin_name.replace("/", "_")
        return self.root / f"{safe_name}-{digest}.py"

    def has(self, plugin_name: str, digest: str) -> bool:
        return self.get_path(plugin_name, digest).exists()

    def save(self, plugin_name: str, digest: str, content: bytes) -> Path:
        target = self.get_path(plugin_name, digest)
        target.write_bytes(content)
        return target

