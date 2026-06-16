from __future__ import annotations

from pathlib import Path

from aurora_core.services.llm_commands import load_command_metadata, retrieve_commands

REPO_ROOT = Path(__file__).resolve().parents[2]
CMD_KNOWLEDGE_DIR = REPO_ROOT / "plugins" / "shared_assets" / "knowledge" / "cmd"


def test_load_command_metadata_reads_command_files():
    root = CMD_KNOWLEDGE_DIR
    records = load_command_metadata(root)
    names = {record.name for record in records}
    assert "backup.restore" in names
    assert "health.ready" in names
    assert "jobs.enqueue" in names


def test_retrieve_commands_prioritizes_backup_restore():
    root = CMD_KNOWLEDGE_DIR
    matches = retrieve_commands("How do I restore a backup safely?", root, max_results=3)
    assert matches
    assert matches[0]["name"] == "backup.restore"
    assert matches[0]["confidence"] > 0
