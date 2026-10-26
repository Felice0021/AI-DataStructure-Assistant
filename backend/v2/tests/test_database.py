"""Real PostgreSQL tests; opt in with DS_V2_RUN_DB_TESTS=1.

Creates only a random test database, never truncates/downgrades the development DB.
"""
from datetime import datetime, timedelta, timezone
import hashlib
import os
import secrets
from uuid import uuid4

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine, delete, func, inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.v2.core.config import REPOSITORY_ROOT, Settings
from backend.v2.main import create_app
from backend.v2.models import AuthSession, User

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(os.environ.get("DS_V2_RUN_DB_TESTS") != "1", reason="Set DS_V2_RUN_DB_TESTS=1 for disposable real-DB tests"),
]


def migration_config(connection):
    cfg = Config(str(REPOSITORY_ROOT / "backend/v2/alembic.ini"))
    cfg.attributes["connection"] = connection
    return cfg


@pytest.fixture(scope="module")
def database():
    settings = Settings()
    name = "ds_v2_test_" + uuid4().hex
    admin = create_engine(settings.database_url, isolation_level="AUTOCOMMIT")
    engine = None
    created = False
    try:
        with admin.connect() as connection:
            connection.execute(text(f'CREATE DATABASE "{name}"'))
            created = True
        test_settings = settings.model_copy(update={"db_name": name})
        engine = create_engine(test_settings.database_url)
        assert inspect(engine).get_table_names() == []
        with engine.begin() as connection:
            command.upgrade(migration_config(connection), "head")
        yield engine, test_settings
    finally:
        if engine is not None:
            engine.dispose()
        if created:
            with admin.connect() as connection:
                # Identifier is generated here, never accepted from user input.
                connection.execute(text(f'DROP DATABASE "{name}"'))
        admin.dispose()


@pytest.fixture
def session(database):
    engine, _ = database
    with engine.connect() as connection:
        transaction = connection.begin()
        with Session(connection) as session:
            yield session
        transaction.rollback()


def add_user(session):
    user = User(email=f"{uuid4().hex}@example.test", password_hash="test-hash-placeholder")
    session.add(user)
    session.flush()
    return user


def add_auth_session(session, user, **overrides):
    values = {
        "user_id": user.id,
        "token_hash": hashlib.sha256(secrets.token_bytes(32)).hexdigest(),
        "expires_at": datetime.now(timezone.utc) + timedelta(hours=1),
    }
    values.update(overrides)
    auth_session = AuthSession(**values)
    session.add(auth_session)
    session.flush()
    return auth_session


def test_schema_and_vector(database):
    engine, _ = database
    inspector = inspect(engine)
    assert set(inspector.get_table_names()) == {"users", "auth_sessions", "auth_login_limits", "knowledge_bases", "alembic_version"}
    assert inspector.get_pk_constraint("users")["constrained_columns"] == ["id"]
    fk = inspector.get_foreign_keys("auth_sessions")[0]
    assert fk["referred_table"] == "users"
    assert fk["options"]["ondelete"] == "CASCADE"
    assert {i["name"] for i in inspector.get_indexes("users")} >= {"uq_users_email_ci"}
    assert {i["name"] for i in inspector.get_indexes("auth_sessions")} >= {
        "ix_auth_sessions_user_id", "ix_auth_sessions_expires_at", "uq_auth_sessions_token_hash",
    }
    with engine.connect() as connection:
        assert connection.scalar(text("SHOW server_version_num"))[:2] == "17"
        assert connection.scalar(text("SELECT extversion FROM pg_extension WHERE extname='vector'"))
        assert connection.scalar(text("SELECT '[1,0,0]'::vector <-> '[0,1,0]'::vector")) == pytest.approx(2 ** 0.5)
        assert connection.scalar(text("SELECT '[1,0,0]'::vector <=> '[0,1,0]'::vector")) == pytest.approx(1)
    with engine.begin() as connection:
        command.check(migration_config(connection))


def test_repeated_upgrade_keeps_rows(database):
    engine, _ = database
    with Session(engine) as session:
        user = add_user(session)
        auth_session = add_auth_session(session, user)
        user_id, session_id = user.id, auth_session.id
        session.commit()
    try:
        for _ in range(2):
            with engine.begin() as connection:
                command.upgrade(migration_config(connection), "head")
        with Session(engine) as session:
            assert session.get(User, user_id).is_active is True
            assert session.get(AuthSession, session_id).user_id == user_id
    finally:
        with engine.begin() as connection:
            connection.execute(delete(User).where(User.id == user_id))


@pytest.mark.parametrize("overrides", [
    {"role": "teacher"}, {"email": " "}, {"password_hash": ""},
])
def test_invalid_user_is_rejected(session, overrides):
    with pytest.raises(IntegrityError), session.begin_nested():
        session.add(User(**{
            "email": "valid@example.test", "password_hash": "test-hash", **overrides,
        }))
        session.flush()


def test_email_case_insensitive_uniqueness(session):
    user = add_user(session)
    with pytest.raises(IntegrityError), session.begin_nested():
        session.add(User(email=user.email.upper(), password_hash="test-hash"))
        session.flush()


@pytest.mark.parametrize("overrides", [
    {"user_id": uuid4()},
    {"token_hash": "plaintext-token"},
    {"expires_at": datetime(2000, 1, 1, tzinfo=timezone.utc)},
    {"revoked_at": datetime(2000, 1, 1, tzinfo=timezone.utc)},
])
def test_invalid_auth_session_is_rejected(session, overrides):
    user = add_user(session)
    with pytest.raises(IntegrityError), session.begin_nested():
        add_auth_session(session, user, **overrides)


def test_unique_token_and_cascade_delete(session):
    user = add_user(session)
    auth_session = add_auth_session(session, user)
    with pytest.raises(IntegrityError), session.begin_nested():
        add_auth_session(session, user, token_hash=auth_session.token_hash)
    session.delete(user)
    session.flush()
    assert session.scalar(select(func.count()).select_from(AuthSession).where(AuthSession.user_id == user.id)) == 0


def test_defaults_and_updated_at(session):
    old = datetime(2000, 1, 1, tzinfo=timezone.utc)
    user = User(email=f"{uuid4().hex}@example.test", password_hash="test-hash", updated_at=old)
    session.add(user)
    session.flush()
    assert user.id.version == 4
    assert user.role == "student" and user.is_active is True
    assert user.created_at.tzinfo is not None
    user.role = "admin"
    session.flush()
    session.refresh(user)
    assert user.updated_at > old


def test_api_with_real_database(database):
    _, settings = database
    with TestClient(create_app(settings)) as client:
        assert client.get("/api/v2/health").status_code == 200
        response = client.get("/api/v2/health/db")
        assert response.status_code == 200
        assert response.json() == {"status": "ok", "database": "ok"}
