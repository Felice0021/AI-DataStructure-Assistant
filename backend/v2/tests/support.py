"""Isolated verification helpers. Probe routes exist ONLY in this test module."""
from contextlib import contextmanager
from typing import Annotated
from uuid import uuid4

from alembic import command
from alembic.config import Config
from fastapi import Depends
from sqlalchemy import create_engine, text

from backend.v2.core.config import REPOSITORY_ROOT, Settings
from backend.v2.dependencies.auth import require_role
from backend.v2.main import create_app
from backend.v2.models import User


def create_probe_app(settings=None):
    app = create_app(settings)

    @app.get("/test/student")
    def student(user: Annotated[User, Depends(require_role("student", "admin"))]):
        return {"role": user.role}

    @app.get("/test/admin")
    def admin(user: Annotated[User, Depends(require_role("admin"))]):
        return {"role": user.role}

    return app


@contextmanager
def isolated_database(revision="head"):
    settings = Settings()
    name = "ds_v2_test_" + uuid4().hex
    admin = create_engine(settings.database_url, isolation_level="AUTOCOMMIT", hide_parameters=True)
    created = False
    engine = None
    try:
        with admin.connect() as connection:
            connection.execute(text(f'CREATE DATABASE "{name}"'))
            created = True
        settings = settings.model_copy(update={"db_name": name})
        engine = create_engine(settings.database_url, hide_parameters=True)
        with engine.begin() as connection:
            cfg = Config(str(REPOSITORY_ROOT / "backend/v2/alembic.ini"))
            cfg.attributes["connection"] = connection
            command.upgrade(cfg, revision)
        yield engine, settings
    finally:
        if engine is not None:
            engine.dispose()
        if created:
            with admin.connect() as connection:
                connection.execute(text(f'DROP DATABASE "{name}"'))
        admin.dispose()
