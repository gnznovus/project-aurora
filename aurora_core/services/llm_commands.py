from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re
from typing import Any


_TOKEN_RE = re.compile(r"[a-z0-9]+")


@dataclass(slots=True)
class CommandMetadata:
    name: str
    method: str
    endpoint: str
    auth: str
    description: str
    tags: list[str] = field(default_factory=list)
    risk_level: str = "normal"
    requires_confirmation: bool = False
    executable: bool = False
    execution_kind: str = "aurora_api"
    payload_schema: dict[str, Any] | None = None
    examples: list[dict[str, Any]] = field(default_factory=list)
    source_path: str = ""

    def searchable_text(self) -> str:
        parts = [
            self.name,
            self.method,
            self.endpoint,
            self.auth,
            self.description,
            " ".join(self.tags),
            self.risk_level,
            self.execution_kind,
        ]
        return " ".join(part for part in parts if part).lower()


def load_command_metadata(commands_dir: Path | str) -> list[CommandMetadata]:
    root = Path(commands_dir)
    if not root.exists():
        return []
    records: list[CommandMetadata] = []
    for path in sorted(root.glob("*.cmd.md")):
        parsed = _parse_command_file(path)
        if parsed:
            records.append(parsed)
    return records


def retrieve_commands(query: str, commands_dir: Path | str, max_results: int = 5) -> list[dict[str, Any]]:
    records = load_command_metadata(commands_dir)
    query_tokens = _tokenize(query)
    if not query_tokens:
        return []

    scored: list[tuple[float, CommandMetadata]] = []
    for record in records:
        score = _score_record(record, query_tokens)
        if score > 0:
            scored.append((score, record))

    scored.sort(key=lambda item: (item[0], item[1].name), reverse=True)
    result: list[dict[str, Any]] = []
    for score, record in scored[: max(1, max_results)]:
        result.append(
            {
                "name": record.name,
                "method": record.method,
                "endpoint": record.endpoint,
                "auth": record.auth,
                "description": record.description,
                "tags": list(record.tags),
                "risk_level": record.risk_level,
                "requires_confirmation": record.requires_confirmation,
                "executable": record.executable,
                "execution_kind": record.execution_kind,
                "confidence": round(min(0.99, score / 10.0), 2),
                "source_path": record.source_path,
            }
        )
    return result


def _parse_command_file(path: Path) -> CommandMetadata | None:
    raw = path.read_text(encoding="utf-8")
    frontmatter, body = _split_frontmatter(raw)
    if not frontmatter:
        return None

    name = str(frontmatter.get("name", "")).strip()
    method = str(frontmatter.get("method", "")).strip().upper()
    endpoint = str(frontmatter.get("endpoint", "")).strip()
    auth = str(frontmatter.get("auth", "")).strip()
    tags = [str(item).strip() for item in _ensure_list(frontmatter.get("tags")) if str(item).strip()]
    risk_level = str(frontmatter.get("risk_level", "normal")).strip() or "normal"
    requires_confirmation = _as_bool(frontmatter.get("requires_confirmation"))
    executable = _as_bool(frontmatter.get("executable"))
    execution_kind = str(frontmatter.get("execution_kind", "aurora_api")).strip() or "aurora_api"
    payload_schema = frontmatter.get("payload_schema") if isinstance(frontmatter.get("payload_schema"), dict) else None
    examples_raw = _ensure_list(frontmatter.get("examples"))
    examples: list[dict[str, Any]] = []
    for item in examples_raw:
        if isinstance(item, dict):
            examples.append(item)

    description = _extract_description(body)
    if not (name and method and endpoint and auth):
        return None

    return CommandMetadata(
        name=name,
        method=method,
        endpoint=endpoint,
        auth=auth,
        description=description,
        tags=tags,
        risk_level=risk_level,
        requires_confirmation=requires_confirmation,
        executable=executable,
        execution_kind=execution_kind,
        payload_schema=payload_schema,
        examples=examples,
        source_path=path.name,
    )


def _split_frontmatter(raw: str) -> tuple[dict[str, Any], str]:
    lines = raw.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, raw

    header: list[str] = []
    body_start = None
    for idx in range(1, len(lines)):
        if lines[idx].strip() == "---":
            body_start = idx + 1
            break
        header.append(lines[idx])
    if body_start is None:
        return {}, raw
    return _parse_simple_frontmatter(header), "\n".join(lines[body_start:])


def _parse_simple_frontmatter(lines: list[str]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    current_key: str | None = None
    for raw in lines:
        line = raw.rstrip()
        if not line.strip():
            continue
        if line.startswith("  - ") and current_key:
            result.setdefault(current_key, [])
            result[current_key].append(_parse_scalar(line[4:]))
            continue
        if line.startswith("- ") and current_key:
            result.setdefault(current_key, [])
            result[current_key].append(_parse_scalar(line[2:]))
            continue
        if ":" in line:
            key, value = line.split(":", 1)
            key = key.strip()
            value = value.strip()
            current_key = key
            if value:
                result[key] = _parse_scalar(value)
            else:
                result[key] = []
        elif current_key and isinstance(result.get(current_key), list):
            result[current_key].append(_parse_scalar(line.strip()))
    return result


def _parse_scalar(value: str) -> Any:
    text = value.strip()
    if text.lower() in {"true", "false"}:
        return text.lower() == "true"
    if text.isdigit():
        return int(text)
    return text.strip('"').strip("'")


def _ensure_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes", "y"}
    return bool(value)


def _extract_description(body: str) -> str:
    lines = [line.strip() for line in body.splitlines()]
    for idx, line in enumerate(lines):
        if line.startswith("#"):
            for next_line in lines[idx + 1 :]:
                if next_line:
                    return next_line
    for line in lines:
        if line:
            return line
    return ""


def _tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall((text or "").lower())


def _score_record(record: CommandMetadata, query_tokens: list[str]) -> float:
    haystack = record.searchable_text()
    score = 0.0
    for token in query_tokens:
        if token in haystack:
            score += 1.0
        if token in record.name.lower():
            score += 1.5
        if token in record.endpoint.lower():
            score += 1.25
        if token in " ".join(record.tags).lower():
            score += 1.0
    return score
