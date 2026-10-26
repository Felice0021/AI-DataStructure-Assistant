from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from backend.v2.core.config import Settings


def build_engine(settings: Settings):
    return create_engine(
        settings.database_url,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=5,
        connect_args={"connect_timeout": 3, "options": "-c statement_timeout=5000"},
        hide_parameters=True,
    )


def build_session_factory(engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)
