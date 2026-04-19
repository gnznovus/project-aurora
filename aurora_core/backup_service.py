from __future__ import annotations

import enum
import hashlib
import json
import secrets
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.sql.sqltypes import DateTime, Enum as SqlEnum

from aurora_core.config import Settings
from aurora_core.models import (
    Agent,
    AuditLog,
    BackupRecord,
    BackupStatus,
    Execution,
    ExecutionCheckpoint,
    Job,
    Plugin,
    PluginVersion,
    SystemFlag,
    User,
)
from aurora_core.timeutils import utc_now_naive


_MODEL_DUMP_ORDER = (
    Agent,
    Plugin,
    PluginVersion,
    Job,
    Execution,
    ExecutionCheckpoint,
    User,
    AuditLog,
)

_MODEL_BY_TABLE = {model.__tablename__: model for model in _MODEL_DUMP_ORDER}


class BackupService:
    def __init__(self, settings: Settings, session_factory) -> None:
        self._settings = settings
        self._session_factory = session_factory
        self._backup_root = Path(settings.backup_dir)
        self._backup_root.mkdir(parents=True, exist_ok=True)
        self._offsite_root = Path(settings.backup_offsite_dir) if settings.backup_offsite_dir else None
        if self._offsite_root:
            self._offsite_root.mkdir(parents=True, exist_ok=True)

    def create_backup(self, created_by: str | None) -> dict[str, Any]:
        backup_id = self._new_backup_id()
        backup_dir = self._backup_root / backup_id
        backup_dir.mkdir(parents=True, exist_ok=False)
        now = utc_now_naive()

        db = self._session_factory()
        try:
            db_payload = self._dump_database(db)
        finally:
            db.close()

        db_path = backup_dir / "db.json"
        db_path.write_text(json.dumps(db_payload, indent=2, sort_keys=True), encoding="utf-8")

        plugins_manifest = self._snapshot_plugins(backup_dir)
        manifest = {
            "backup_id": backup_id,
            "created_at": now.isoformat(),
            "created_by": created_by,
            "database_file": "db.json",
            "plugins": plugins_manifest,
        }
        manifest_path = backup_dir / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")

        checksums = self._build_checksums(backup_dir)
        checksums_path = backup_dir / "checksums.sha256"
        checksums_path.write_text("\n".join(f"{digest}  {relative}" for relative, digest in checksums) + "\n", encoding="utf-8")

        size_bytes = self._directory_size(backup_dir)
        db = self._session_factory()
        try:
            row = BackupRecord(
                id=backup_id,
                created_by=created_by,
                status=BackupStatus.created,
                storage_path=str(backup_dir),
                size_bytes=size_bytes,
                manifest_json=manifest,
            )
            db.add(row)
            db.commit()
        finally:
            db.close()

        validation_result: dict[str, Any] | None = None
        if self._settings.backup_validate_after_create:
            validation_result = self.validate_backup(backup_id)

        db = self._session_factory()
        try:
            refreshed = db.scalar(select(BackupRecord).where(BackupRecord.id == backup_id))
        finally:
            db.close()

        offsite_payload: dict[str, Any]
        if self._offsite_root and validation_result and validation_result.get("valid"):
            offsite_payload = self.sync_backup_offsite(backup_id)
        elif self._offsite_root:
            offsite_payload = {"enabled": True, "found": True, "synced": False, "reason": "skipped: backup not validated"}
        else:
            offsite_payload = {"enabled": False}

        return {
            "backup_id": backup_id,
            "created_at": now.isoformat(),
            "size_bytes": size_bytes,
            "storage_path": str(backup_dir),
            "status": refreshed.status.value if refreshed else BackupStatus.created.value,
            "validation": validation_result,
            "offsite": offsite_payload,
        }

    def list_backups(self, limit: int = 100) -> list[dict[str, Any]]:
        safe_limit = max(1, min(limit, 200))
        db = self._session_factory()
        try:
            rows = list(db.scalars(select(BackupRecord).order_by(BackupRecord.created_at.desc()).limit(safe_limit)))
            return [self._serialize_backup_row(row) for row in rows]
        finally:
            db.close()

    def validate_backup(self, backup_id: str) -> dict[str, Any]:
        db = self._session_factory()
        try:
            row = db.scalar(select(BackupRecord).where(BackupRecord.id == backup_id))
            if not row:
                return {"found": False, "backup_id": backup_id}

            backup_dir = Path(row.storage_path)
            issues: list[str] = []
            if not backup_dir.exists():
                issues.append("backup directory missing")
            else:
                required = (backup_dir / "db.json", backup_dir / "manifest.json", backup_dir / "checksums.sha256")
                for required_path in required:
                    if not required_path.exists():
                        issues.append(f"missing required file: {required_path.name}")

                if not issues:
                    for digest, relative_path in self._read_checksum_lines(backup_dir / "checksums.sha256"):
                        target = backup_dir / relative_path
                        if not target.exists():
                            issues.append(f"missing file from checksum list: {relative_path}")
                            continue
                        current = self._sha256_file(target)
                        if current != digest:
                            issues.append(f"checksum mismatch: {relative_path}")

            row.validated_at = utc_now_naive()
            if issues:
                row.status = BackupStatus.invalid
                row.validation_message = "; ".join(issues)[:512]
            else:
                row.status = BackupStatus.validated
                row.validation_message = None
            db.commit()

            return {
                "found": True,
                "backup_id": backup_id,
                "valid": len(issues) == 0,
                "issues": issues,
                "status": row.status.value,
                "validated_at": row.validated_at.isoformat() if row.validated_at else None,
            }
        finally:
            db.close()

    def prune_backups(self) -> dict[str, Any]:
        db = self._session_factory()
        try:
            rows = list(
                db.scalars(
                    select(BackupRecord)
                    .where(BackupRecord.status != BackupStatus.pruned)
                    .order_by(BackupRecord.created_at.desc())
                )
            )
            if len(rows) <= 1:
                return {"pruned_count": 0, "pruned_ids": [], "reclaimed_bytes": 0}

            keep_ids = self._select_keep_ids(rows)
            total_bytes = sum(max(0, row.size_bytes) for row in rows)
            max_bytes = int(max(0.0, self._settings.backup_max_storage_gb) * 1024 * 1024 * 1024)

            prunable = [row for row in reversed(rows) if row.id not in keep_ids]
            pruned_ids: list[str] = []
            reclaimed = 0
            remaining_validated = sum(1 for row in rows if row.status == BackupStatus.validated)

            for row in prunable:
                if row.status == BackupStatus.validated and remaining_validated <= 1:
                    continue
                should_prune_for_retention = True
                should_prune_for_size = total_bytes > max_bytes
                if not should_prune_for_retention and not should_prune_for_size:
                    continue
                was_validated = row.status == BackupStatus.validated
                target = Path(row.storage_path)
                if target.exists():
                    shutil.rmtree(target, ignore_errors=True)
                reclaimed += max(0, row.size_bytes)
                total_bytes = max(0, total_bytes - max(0, row.size_bytes))
                row.status = BackupStatus.pruned
                row.validation_message = "pruned by retention policy"
                pruned_ids.append(row.id)
                if was_validated:
                    remaining_validated = max(0, remaining_validated - 1)

            db.commit()
            return {
                "pruned_count": len(pruned_ids),
                "pruned_ids": pruned_ids,
                "reclaimed_bytes": reclaimed,
                "remaining_bytes": total_bytes,
                "remaining_validated": remaining_validated,
            }
        finally:
            db.close()

    def restore_backup(self, backup_id: str, dry_run: bool = True) -> dict[str, Any]:
        validation = self.validate_backup(backup_id)
        if not validation.get("found"):
            return {"found": False, "backup_id": backup_id}
        if not validation.get("valid"):
            return {
                "found": True,
                "backup_id": backup_id,
                "dry_run": dry_run,
                "ok": False,
                "message": "backup validation failed",
                "issues": validation.get("issues", []),
            }

        db = self._session_factory()
        try:
            row = db.scalar(select(BackupRecord).where(BackupRecord.id == backup_id))
        finally:
            db.close()
        if not row:
            return {"found": False, "backup_id": backup_id}

        backup_dir = Path(row.storage_path)
        manifest = json.loads((backup_dir / "manifest.json").read_text(encoding="utf-8"))
        db_payload = json.loads((backup_dir / "db.json").read_text(encoding="utf-8"))
        plugin_report = self._plugin_restore_report(backup_dir, manifest)
        table_counts = {
            table_name: len(rows) for table_name, rows in db_payload.items() if isinstance(rows, list)
        }
        total_rows = sum(table_counts.values())

        steps = [
            "validate backup checksum and required files",
            "enter maintenance mode (planned)",
            "restore database payload",
            "restore plugin artifacts",
            "run post-restore integrity checks",
            "exit maintenance mode",
        ]

        if dry_run:
            return {
                "found": True,
                "backup_id": backup_id,
                "dry_run": True,
                "ok": plugin_report["missing_count"] == 0,
                "steps": steps,
                "database_preview": {
                    "table_counts": table_counts,
                    "total_rows": total_rows,
                },
                "plugins_preview": plugin_report,
                "message": "dry-run completed; no data was modified",
            }

        if plugin_report["missing_count"] > 0:
            return {
                "found": True,
                "backup_id": backup_id,
                "dry_run": False,
                "ok": False,
                "message": "restore blocked: backup plugin files are incomplete",
                "issues": plugin_report["missing_files"],
            }

        db = self._session_factory()
        try:
            self._restore_database_payload(db, db_payload)
            db.commit()
        except Exception as exc:
            db.rollback()
            return {
                "found": True,
                "backup_id": backup_id,
                "dry_run": False,
                "ok": False,
                "message": f"database restore failed: {exc}",
            }
        finally:
            db.close()

        plugin_apply = self._restore_plugins_from_manifest(backup_dir, manifest)
        if not plugin_apply["ok"]:
            return {
                "found": True,
                "backup_id": backup_id,
                "dry_run": False,
                "ok": False,
                "message": "database restored but plugin restore failed",
                "plugins_restore": plugin_apply,
            }

        return {
            "found": True,
            "backup_id": backup_id,
            "dry_run": False,
            "ok": True,
            "steps": steps,
            "database_preview": {
                "table_counts": table_counts,
                "total_rows": total_rows,
            },
            "plugins_restore": plugin_apply,
            "message": "restore apply completed",
        }

    def sync_backup_offsite(self, backup_id: str) -> dict[str, Any]:
        if not self._offsite_root:
            return {"enabled": False, "found": False, "synced": False}
        db = self._session_factory()
        try:
            row = db.scalar(select(BackupRecord).where(BackupRecord.id == backup_id))
        finally:
            db.close()
        if not row:
            return {"enabled": True, "found": False, "synced": False}

        source = Path(row.storage_path)
        if not source.exists():
            return {"enabled": True, "found": True, "synced": False, "reason": "source backup path missing"}
        target = self._offsite_root / backup_id
        if target.exists():
            shutil.rmtree(target, ignore_errors=True)
        shutil.copytree(source, target)
        source_checksums = (source / "checksums.sha256").read_text(encoding="utf-8")
        target_checksums = (target / "checksums.sha256").read_text(encoding="utf-8")
        ok = source_checksums == target_checksums
        return {
            "enabled": True,
            "found": True,
            "synced": ok,
            "offsite_path": str(target),
        }

    def backup_summary(self) -> dict[str, Any]:
        db = self._session_factory()
        try:
            rows = list(
                db.scalars(
                    select(BackupRecord)
                    .where(BackupRecord.status != BackupStatus.pruned)
                    .order_by(BackupRecord.created_at.desc())
                )
            )
            recent_backup_events = list(
                db.scalars(
                    select(AuditLog)
                    .where(AuditLog.action.like("backup.%"))
                    .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
                    .limit(30)
                )
            )
        finally:
            db.close()
        total_size = sum(max(0, row.size_bytes) for row in rows)
        latest = rows[0] if rows else None
        latest_validated = next((row for row in rows if row.status == BackupStatus.validated), None)
        latest_invalid = next((row for row in rows if row.status in {BackupStatus.invalid, BackupStatus.failed}), None)
        util_denominator = int(max(0.0, self._settings.backup_max_storage_gb) * 1024 * 1024 * 1024)
        utilization_pct = 0
        if util_denominator > 0:
            utilization_pct = int(min(100, round((total_size / util_denominator) * 100)))
        last_failure_event = next((e for e in recent_backup_events if self._is_backup_event_failure(e)), None)
        last_success_event = next((e for e in recent_backup_events if self._is_backup_event_success(e)), None)
        return {
            "count": len(rows),
            "total_size_bytes": total_size,
            "max_storage_bytes": util_denominator,
            "storage_utilization_pct": utilization_pct,
            "latest": self._serialize_backup_row(latest) if latest else None,
            "latest_validated": self._serialize_backup_row(latest_validated) if latest_validated else None,
            "latest_issue": self._serialize_backup_row(latest_invalid) if latest_invalid else None,
            "last_success_event": self._serialize_audit_event(last_success_event) if last_success_event else None,
            "last_failure_event": self._serialize_audit_event(last_failure_event) if last_failure_event else None,
            "offsite_enabled": self._offsite_root is not None,
            "offsite_path": str(self._offsite_root) if self._offsite_root else None,
        }

    def set_maintenance_mode(self, enabled: bool, actor: str | None, reason: str | None = None) -> dict[str, Any]:
        now = utc_now_naive()
        db = self._session_factory()
        try:
            row = db.scalar(select(SystemFlag).where(SystemFlag.key == "maintenance_mode"))
            payload = {
                "enabled": bool(enabled),
                "updated_by": actor,
                "reason": reason,
                "updated_at": now.isoformat(),
            }
            if row:
                row.value_json = payload
                row.updated_at = now
            else:
                db.add(SystemFlag(key="maintenance_mode", value_json=payload, updated_at=now))
            db.commit()
            return payload
        finally:
            db.close()

    def get_maintenance_mode(self) -> dict[str, Any]:
        db = self._session_factory()
        try:
            row = db.scalar(select(SystemFlag).where(SystemFlag.key == "maintenance_mode"))
            if not row:
                return {"enabled": False}
            payload = row.value_json or {}
            payload.setdefault("enabled", False)
            return payload
        finally:
            db.close()

    def _select_keep_ids(self, rows_desc: list[BackupRecord]) -> set[str]:
        keep_ids: set[str] = set()
        min_keep = max(1, int(self._settings.backup_prune_min_keep_count))
        for row in rows_desc[:min_keep]:
            keep_ids.add(row.id)

        latest_validated = next((row for row in rows_desc if row.status == BackupStatus.validated), None)
        if latest_validated:
            keep_ids.add(latest_validated.id)

        daily_slots: set[str] = set()
        weekly_slots: set[str] = set()
        monthly_slots: set[str] = set()

        for row in rows_desc:
            created_at = row.created_at
            day_slot = created_at.strftime("%Y-%m-%d")
            iso = created_at.isocalendar()
            week_slot = f"{iso.year}-W{iso.week:02d}"
            month_slot = created_at.strftime("%Y-%m")

            if len(daily_slots) < self._settings.backup_retention_daily and day_slot not in daily_slots:
                daily_slots.add(day_slot)
                keep_ids.add(row.id)
            if len(weekly_slots) < self._settings.backup_retention_weekly and week_slot not in weekly_slots:
                weekly_slots.add(week_slot)
                keep_ids.add(row.id)
            if len(monthly_slots) < self._settings.backup_retention_monthly and month_slot not in monthly_slots:
                monthly_slots.add(month_slot)
                keep_ids.add(row.id)

        return keep_ids

    def _snapshot_plugins(self, backup_dir: Path) -> dict[str, Any]:
        source_root = Path(self._settings.plugins_dir)
        target_root = backup_dir / "plugins"
        store_dir = target_root / "store"
        store_dir.mkdir(parents=True, exist_ok=True)

        files: list[dict[str, str]] = []
        if not source_root.exists():
            return {"source_path": str(source_root), "files": files}

        digest_to_store_name: dict[str, str] = {}
        for path in sorted(source_root.rglob("*")):
            if not path.is_file():
                continue
            rel_source = path.relative_to(source_root).as_posix()
            digest = self._sha256_file(path)
            if digest not in digest_to_store_name:
                store_name = f"{digest}.bin"
                digest_to_store_name[digest] = store_name
                shutil.copy2(path, store_dir / store_name)
            files.append(
                {
                    "source_relative_path": rel_source,
                    "digest": digest,
                    "stored_as": f"plugins/store/{digest_to_store_name[digest]}",
                }
            )
        return {"source_path": str(source_root), "files": files}

    def _plugin_restore_report(self, backup_dir: Path, manifest: dict[str, Any]) -> dict[str, Any]:
        plugins_info = manifest.get("plugins", {})
        files = plugins_info.get("files", [])
        missing: list[str] = []
        for item in files:
            stored_as = item.get("stored_as")
            if not stored_as:
                continue
            stored_path = backup_dir / Path(stored_as)
            if not stored_path.exists():
                missing.append(str(stored_as))
        return {
            "files_listed": len(files),
            "missing_count": len(missing),
            "missing_files": missing[:50],
        }

    def _dump_database(self, db: Session) -> dict[str, list[dict[str, Any]]]:
        payload: dict[str, list[dict[str, Any]]] = {}
        for model in _MODEL_DUMP_ORDER:
            rows = list(db.scalars(select(model)))
            payload[model.__tablename__] = [self._serialize_row(model, row) for row in rows]
        return payload

    def _restore_database_payload(self, db: Session, db_payload: dict[str, list[dict[str, Any]]]) -> None:
        for model in reversed(_MODEL_DUMP_ORDER):
            db.query(model).delete(synchronize_session=False)
        db.flush()

        for model in _MODEL_DUMP_ORDER:
            rows = db_payload.get(model.__tablename__, [])
            if not isinstance(rows, list):
                continue
            for row_data in rows:
                if not isinstance(row_data, dict):
                    continue
                db.add(model(**self._deserialize_row(model, row_data)))

    def _restore_plugins_from_manifest(self, backup_dir: Path, manifest: dict[str, Any]) -> dict[str, Any]:
        plugins_info = manifest.get("plugins", {})
        files = plugins_info.get("files", [])
        target_root = Path(self._settings.plugins_dir)
        target_root.mkdir(parents=True, exist_ok=True)

        for existing in sorted(target_root.rglob("*"), reverse=True):
            try:
                if existing.is_file():
                    existing.unlink(missing_ok=True)
                elif existing.is_dir():
                    existing.rmdir()
            except OSError:
                pass

        restored = 0
        missing: list[str] = []
        for item in files:
            rel_path = item.get("source_relative_path")
            stored_as = item.get("stored_as")
            if not rel_path or not stored_as:
                continue
            src = backup_dir / Path(stored_as)
            if not src.exists():
                missing.append(stored_as)
                continue
            dst = target_root / Path(rel_path)
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            restored += 1

        return {
            "ok": len(missing) == 0,
            "restored_files": restored,
            "missing_files": missing[:50],
        }

    def _serialize_row(self, model, row) -> dict[str, Any]:
        data: dict[str, Any] = {}
        for column in model.__table__.columns:
            value = getattr(row, column.name)
            data[column.name] = self._json_safe_value(value)
        return data

    def _deserialize_row(self, model, data: dict[str, Any]) -> dict[str, Any]:
        parsed: dict[str, Any] = {}
        for column in model.__table__.columns:
            name = column.name
            if name not in data:
                continue
            value = data[name]
            if value is None:
                parsed[name] = None
                continue
            if isinstance(column.type, DateTime) and isinstance(value, str):
                parsed[name] = datetime.fromisoformat(value)
                continue
            if isinstance(column.type, SqlEnum):
                parsed[name] = value
                continue
            parsed[name] = value
        return parsed

    def _json_safe_value(self, value: Any) -> Any:
        if isinstance(value, datetime):
            return value.isoformat()
        if isinstance(value, enum.Enum):
            return value.value
        if isinstance(value, Path):
            return str(value)
        if isinstance(value, dict):
            return {str(k): self._json_safe_value(v) for k, v in value.items()}
        if isinstance(value, list):
            return [self._json_safe_value(v) for v in value]
        return value

    def _build_checksums(self, backup_dir: Path) -> list[tuple[str, str]]:
        checksum_rows: list[tuple[str, str]] = []
        for file_path in sorted(backup_dir.rglob("*")):
            if not file_path.is_file():
                continue
            if file_path.name == "checksums.sha256":
                continue
            relative_path = file_path.relative_to(backup_dir).as_posix()
            checksum_rows.append((relative_path, self._sha256_file(file_path)))
        return checksum_rows

    def _read_checksum_lines(self, checksum_path: Path) -> list[tuple[str, str]]:
        result: list[tuple[str, str]] = []
        for raw in checksum_path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line:
                continue
            parts = line.split("  ", 1)
            if len(parts) != 2:
                continue
            result.append((parts[0].strip(), parts[1].strip()))
        return result

    def _directory_size(self, path: Path) -> int:
        total = 0
        for file_path in path.rglob("*"):
            if file_path.is_file():
                total += file_path.stat().st_size
        return total

    def _serialize_backup_row(self, row: BackupRecord) -> dict[str, Any]:
        return {
            "backup_id": row.id,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "created_by": row.created_by,
            "status": row.status.value,
            "storage_path": row.storage_path,
            "size_bytes": row.size_bytes,
            "validated_at": row.validated_at.isoformat() if row.validated_at else None,
            "validation_message": row.validation_message,
            "manifest": row.manifest_json,
        }

    def _serialize_audit_event(self, row: AuditLog) -> dict[str, Any]:
        return {
            "at": row.created_at.isoformat() if row.created_at else None,
            "action": row.action,
            "resource_id": row.resource_id,
            "details": row.details or {},
        }

    def _is_backup_event_success(self, row: AuditLog) -> bool:
        details = row.details or {}
        if row.action in {"backup.create", "backup.validate", "backup.offsite_sync", "backup.prune", "backup.restore.dry_run", "backup.restore"}:
            if isinstance(details.get("ok"), bool):
                return bool(details.get("ok"))
            if isinstance(details.get("valid"), bool):
                return bool(details.get("valid"))
            if row.action == "backup.create":
                return True
            return True
        return False

    def _is_backup_event_failure(self, row: AuditLog) -> bool:
        details = row.details or {}
        if row.action in {"backup.validate", "backup.restore", "backup.restore.dry_run", "backup.offsite_sync"}:
            if isinstance(details.get("ok"), bool):
                return not bool(details.get("ok"))
            if isinstance(details.get("valid"), bool):
                return not bool(details.get("valid"))
        if row.action == "backup.create":
            status = str(details.get("status", "")).lower()
            if status in {"invalid", "failed"}:
                return True
        return False

    def _sha256_file(self, path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            while True:
                chunk = handle.read(1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
        return digest.hexdigest()

    def _new_backup_id(self) -> str:
        ts = utc_now_naive().strftime("%Y%m%d_%H%M%S")
        suffix = secrets.token_hex(2).upper()
        return f"BKP_{ts}_{suffix}"
