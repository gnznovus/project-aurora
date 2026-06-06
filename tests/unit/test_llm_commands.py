from __future__ import annotations

from pathlib import Path

from aurora_core.services.llm_commands import load_command_metadata, retrieve_commands


def test_load_command_metadata_reads_command_files():
    root = Path("d:/Code/Python/Project_Aurora/plugins/shared_assets/knowledge/cmd")
    records = load_command_metadata(root)
    names = {record.name for record in records}
    assert "backup.restore" in names
    assert "health.ready" in names
    assert "jobs.enqueue" in names


def test_retrieve_commands_prioritizes_backup_restore():
    root = Path("d:/Code/Python/Project_Aurora/plugins/shared_assets/knowledge/cmd")
    matches = retrieve_commands("How do I restore a backup safely?", root, max_results=3)
    assert matches
    assert matches[0]["name"] == "backup.restore"
    assert matches[0]["confidence"] > 0
