from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timedelta

from aurora_core.backup_service import BackupService
from aurora_core.config import Settings
from aurora_core.models import AuditLog
from aurora_core.timeutils import utc_now_naive

logger = logging.getLogger("aurora-core")


class BackupScheduler:
    def __init__(self, settings: Settings, backup_service: BackupService, session_factory) -> None:
        self._settings = settings
        self._backup_service = backup_service
        self._session_factory = session_factory
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._next_create_at = utc_now_naive() + timedelta(minutes=max(1, settings.backup_schedule_create_minutes))
        self._next_validate_at = utc_now_naive() + timedelta(minutes=max(1, settings.backup_schedule_validate_minutes))
        self._next_prune_at = utc_now_naive() + timedelta(minutes=max(1, settings.backup_schedule_prune_minutes))
        self._next_drill_at = utc_now_naive() + timedelta(minutes=max(1, settings.backup_schedule_restore_drill_minutes))

    def start(self) -> None:
        if not self._settings.backup_scheduler_enabled:
            logger.info("backup.scheduler.disabled")
            return
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, name="aurora-backup-scheduler", daemon=True)
        self._thread.start()
        logger.info("backup.scheduler.started")

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=3)
        logger.info("backup.scheduler.stopped")

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            now = utc_now_naive()
            try:
                self._tick(now)
            except Exception as exc:
                logger.exception("backup.scheduler.tick_failed error=%s", exc)
            self._stop_event.wait(30)

    def _tick(self, now: datetime) -> None:
        if now >= self._next_create_at:
            result = self._backup_service.create_backup(created_by="system:scheduler")
            self._audit("backup.schedule.create", {"backup_id": result.get("backup_id"), "ok": True})
            self._next_create_at = now + timedelta(minutes=max(1, self._settings.backup_schedule_create_minutes))

        if now >= self._next_validate_at:
            latest = self._backup_service.list_backups(limit=1)
            if latest:
                result = self._backup_service.validate_backup(latest[0]["backup_id"])
                self._audit("backup.schedule.validate", {"backup_id": latest[0]["backup_id"], "ok": result.get("valid", False)})
            self._next_validate_at = now + timedelta(minutes=max(1, self._settings.backup_schedule_validate_minutes))

        if now >= self._next_prune_at:
            result = self._backup_service.prune_backups()
            self._audit("backup.schedule.prune", result)
            self._next_prune_at = now + timedelta(minutes=max(1, self._settings.backup_schedule_prune_minutes))

        if now >= self._next_drill_at:
            latest = self._backup_service.list_backups(limit=1)
            if latest:
                result = self._backup_service.restore_backup(latest[0]["backup_id"], dry_run=True)
                self._audit(
                    "backup.schedule.restore_dry_run",
                    {"backup_id": latest[0]["backup_id"], "ok": result.get("ok", False), "message": result.get("message")},
                )
            self._next_drill_at = now + timedelta(minutes=max(1, self._settings.backup_schedule_restore_drill_minutes))

    def _audit(self, action: str, details: dict) -> None:
        db = self._session_factory()
        try:
            db.add(
                AuditLog(
                    actor_username="system",
                    actor_role="superadmin",
                    action=action,
                    resource_type="backup",
                    resource_id="scheduler",
                    details=details,
                    ip_address=None,
                    user_agent="aurora-backup-scheduler",
                )
            )
            db.commit()
        finally:
            db.close()
