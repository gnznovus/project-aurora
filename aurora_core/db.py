from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from aurora_core.config import Settings


def create_session_factory(settings: Settings) -> sessionmaker:
    connect_args = {}
    if settings.database_url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
    engine = create_engine(settings.database_url, future=True, connect_args=connect_args)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
