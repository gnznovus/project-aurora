from __future__ import annotations

from pathlib import Path
import uuid

from aurora_core.config import Settings
from aurora_core.services.schema_guard import _build_alembic_config


def test_build_alembic_config_points_to_project_root_artifacts():
    local_tmp = Path("d:/Code/Python/Project_Aurora/.testdata") / uuid.uuid4().hex
    local_tmp.mkdir(parents=True, exist_ok=True)
    settings = Settings(
        database_url=f"sqlite:///{(local_tmp / 'aurora.db').as_posix()}",
        redis_url="redis://localhost:6379/15",
    )

    cfg = _build_alembic_config(settings)
    script_location = Path(cfg.get_main_option("script_location")).resolve()
    alembic_ini = Path(cfg.config_file_name).resolve()

    project_root = Path("d:/Code/Python/Project_Aurora").resolve()
    assert script_location == (project_root / "migrations").resolve()
    assert alembic_ini == (project_root / "alembic.ini").resolve()

