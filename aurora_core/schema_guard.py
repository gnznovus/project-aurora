from __future__ import annotations

import logging
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import inspect
from sqlalchemy.engine import Engine

from aurora_core.config import Settings
from aurora_core.models import Base

logger = logging.getLogger("aurora-core")


def ensure_schema_ready(settings: Settings, *, auto_repair: bool = True) -> None:
    """Verify database revision and optionally repair common drift cases."""
    if settings.database_url.startswith("sqlite"):
        engine = _engine_from_url(settings.database_url)
        Base.metadata.create_all(bind=engine)
        logger.info("schema.guard.sqlite_bootstrap")
        return

    alembic_cfg = _build_alembic_config(settings)
    script = ScriptDirectory.from_config(alembic_cfg)
    expected_head = script.get_current_head()

    engine = _engine_from_url(settings.database_url)
    with engine.connect() as conn:
        migration_ctx = MigrationContext.configure(conn)
        current_rev = migration_ctx.get_current_revision()

    if current_rev == expected_head:
        logger.info("schema.guard.ok current=%s", current_rev)
        return

    if not auto_repair:
        raise RuntimeError(
            "database schema revision mismatch "
            f"(current={current_rev or 'none'}, expected={expected_head}). "
            "Run: alembic upgrade head"
        )

    logger.warning(
        "schema.guard.mismatch current=%s expected=%s; attempting automatic repair",
        current_rev or "none",
        expected_head,
    )
    _repair_schema(alembic_cfg, engine, current_rev=current_rev)

    with engine.connect() as conn:
        current_after = MigrationContext.configure(conn).get_current_revision()
    if current_after != expected_head:
        raise RuntimeError(
            "automatic schema repair failed "
            f"(current={current_after or 'none'}, expected={expected_head}). "
            "Run: alembic current && alembic history --verbose"
        )
    logger.info("schema.guard.recovered current=%s", current_after)


def _repair_schema(alembic_cfg: Config, engine: Engine, *, current_rev: str | None) -> None:
    if current_rev:
        command.upgrade(alembic_cfg, "head")
        return

    inferred = _infer_revision(engine)
    if inferred:
        logger.warning("schema.guard.inferred_revision=%s; stamping before upgrade", inferred)
        command.stamp(alembic_cfg, inferred)
    command.upgrade(alembic_cfg, "head")


def _infer_revision(engine: Engine) -> str | None:
    insp = inspect(engine)
    if not insp.has_table("agents"):
        return None
    if not insp.has_table("users") or not insp.has_table("audit_logs"):
        return "0001_initial_schema"
    if not insp.has_table("backups"):
        return "0002_users_and_audit_logs"
    if not insp.has_table("system_flags"):
        return "0003_backups"

    agent_cols = {col["name"] for col in insp.get_columns("agents")}
    if "cpu_load_pct" not in agent_cols or "ram_load_pct" not in agent_cols:
        return "0004_system_flags"
    return "0005_agent_resource_metrics"


def _build_alembic_config(settings: Settings) -> Config:
    project_root = Path(__file__).resolve().parents[1]
    config = Config(str(project_root / "alembic.ini"))
    config.set_main_option("script_location", str(project_root / "migrations"))
    config.set_main_option("sqlalchemy.url", settings.database_url)
    return config


def _engine_from_url(database_url: str) -> Engine:
    from sqlalchemy import create_engine

    return create_engine(database_url, future=True)
