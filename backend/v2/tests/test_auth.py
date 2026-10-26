from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timedelta, timezone
import multiprocessing
import os
from uuid import uuid4

from alembic import command
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import func, select, text, update
from sqlalchemy.orm import Session

from backend.v2.core.errors import AuthError
from backend.v2.core.security import new_token, token_digest
from backend.v2.manage import create_admin
from backend.v2.models import AuthSession, LoginLimit, User
from backend.v2.tests.support import create_probe_app, isolated_database
from backend.v2.tests.test_database import database, migration_config

pytestmark = [pytest.mark.integration, pytest.mark.skipif(
    os.environ.get("DS_V2_RUN_DB_TESTS") != "1", reason="Opt in to isolated PostgreSQL tests",
)]
ORIGIN = "http://127.0.0.1:5173"


def local_settings(settings, **overrides):
    return settings.model_copy(update={
        "environment": "development", "allow_insecure_loopback": True,
        "allowed_origins": [ORIGIN], "login_ip_max_failures": 1000, **overrides,
    })


def client_for(settings, ip="127.0.0.1"):
    return TestClient(create_probe_app(settings), base_url="http://127.0.0.1:8001", client=(ip, 45000))


def csrf_headers(client):
    result = client.get("/api/v2/auth/csrf", headers={"Origin": ORIGIN})
    assert result.status_code == 200
    return {"Origin": ORIGIN, "X-CSRF-Token": result.json()["csrf_token"]}


def post(client, endpoint, body=None):
    return client.post("/api/v2/auth/" + endpoint, json=body, headers=csrf_headers(client))


def register(client, email=None, password=None):
    credentials = {"email": email or f"{uuid4().hex}@example.com", "password": password or new_token()}
    response = post(client, "register", credentials)
    assert response.status_code == 201
    assert "password_hash" not in response.text and "token_hash" not in response.text
    assert response.json()["user"]["role"] == "student"
    return credentials, response.json()["user"]


@pytest.fixture
def config(database):
    return local_settings(database[1])


def test_registration_login_logout_and_cookie(config, database):
    engine, _ = database
    with client_for(config) as client:
        credentials, user = register(client)
        assert client.cookies.get(config.session_cookie) is None
        assert client.get("/api/v2/auth/me").status_code == 401
        response = post(client, "login", credentials)
        assert response.status_code == 200
        cookie = response.headers["set-cookie"]
        assert all(x in cookie for x in ["HttpOnly", "SameSite=lax", "Path=/", "Max-Age=28800", "expires="])
        assert "Secure" not in cookie and "Domain=" not in cookie
        raw = client.cookies.get(config.session_cookie)
        assert len(raw) == 43 and raw not in response.text
        with Session(engine) as session:
            account = session.get(User, user["id"])
            assert account.password_hash.startswith("$argon2id$")
            assert credentials["password"] not in account.password_hash
            record = session.scalar(select(AuthSession).where(AuthSession.user_id == account.id))
            assert record.token_hash == token_digest(raw) and record.token_hash != raw
        assert client.get("/api/v2/auth/me").json()["user"]["id"] == user["id"]
        logout = post(client, "logout")
        assert logout.status_code == 204 and not logout.content
        assert "Max-Age=0" in logout.headers["set-cookie"]
        assert client.cookies.get(config.session_cookie) is None
        assert client.get("/api/v2/auth/me").status_code == 401
        assert post(client, "logout").status_code == 204  # Fresh anonymous CSRF, idempotent.
        client.cookies.set(config.session_cookie, raw)
        assert client.get("/api/v2/auth/me").status_code == 401
        assert post(client, "logout").status_code == 204  # Replay of revoked session is also idempotent.


def test_normalization_duplicate_and_admin_injection(config):
    email = f"{uuid4().hex}@example.com"
    with client_for(config) as client:
        credentials, user = register(client, email="  " + email.upper() + "  ")
        assert user["email"] == email
        duplicate = post(client, "register", {**credentials, "email": email})
        assert duplicate.status_code == 409 and duplicate.json()["error"]["code"] == "email_exists"
        assert post(client, "login", credentials).status_code == 200
        assert client.get("/test/admin", headers={"X-Role": "admin", "X-User-Id": str(uuid4())}).status_code == 403
        injected = post(client, "register", {"email": f"{uuid4().hex}@example.com", "password": new_token(), "role": "admin"})
        assert injected.status_code == 422
        assert post(client, "login", {**credentials, "user_id": str(uuid4())}).status_code == 422


@pytest.mark.parametrize("data,code", [
    ({"email": "invalid", "password": "long-enough-unique-test-password"}, "invalid_email"),
    ({"email": "person@example.com", "password": "short"}, "weak_password"),
])
def test_invalid_registration(config, data, code):
    with client_for(config) as client:
        response = post(client, "register", data)
        assert response.status_code == 422 and response.json()["error"]["code"] == code
        assert data["password"] not in response.text


def test_wrong_unknown_and_disabled_login_match(config, database):
    engine, _ = database
    with client_for(config) as client:
        credentials, user = register(client)
        wrong = post(client, "login", {**credentials, "password": new_token()})
        unknown = post(client, "login", {"email": f"{uuid4().hex}@example.com", "password": new_token()})
        with Session(engine) as session:
            session.execute(update(User).where(User.id == user["id"]).values(is_active=False))
            session.commit()
        disabled = post(client, "login", credentials)
        assert wrong.status_code == unknown.status_code == disabled.status_code == 401
        assert wrong.json() == unknown.json() == disabled.json()


@pytest.mark.parametrize("state", ["expired", "revoked", "disabled", "forged"])
def test_invalid_session(config, database, state):
    engine, _ = database
    with client_for(config) as client:
        credentials, user = register(client)
        assert post(client, "login", credentials).status_code == 200
        raw = client.cookies.get(config.session_cookie)
        now = datetime.now(timezone.utc)
        with Session(engine) as session:
            if state == "expired":
                session.execute(update(AuthSession).where(AuthSession.token_hash == token_digest(raw)).values(created_at=now-timedelta(hours=2), expires_at=now-timedelta(hours=1)))
            elif state == "revoked":
                session.execute(update(AuthSession).where(AuthSession.token_hash == token_digest(raw)).values(revoked_at=now))
            elif state == "disabled":
                session.execute(update(User).where(User.id == user["id"]).values(is_active=False))
            session.commit()
        if state == "forged":
            client.cookies.clear()
            client.cookies.set(config.session_cookie, new_token())
        assert client.get("/api/v2/auth/me").status_code == 401


def test_user_and_same_account_sessions_are_independent(config):
    with client_for(config) as first, client_for(config) as second, client_for(config) as third:
        credentials, user = register(first)
        other_credentials, other_user = register(second)
        assert post(first, "login", credentials).status_code == 200
        assert post(second, "login", other_credentials).status_code == 200
        assert post(third, "login", credentials).status_code == 200
        assert first.cookies.get(config.session_cookie) != third.cookies.get(config.session_cookie)
        assert first.get("/api/v2/auth/me", params={"user_id": other_user["id"]}).json()["user"]["id"] == user["id"]
        assert first.get("/test/student").status_code == 200
        assert first.get("/test/admin").status_code == 403
        assert post(first, "logout").status_code == 204
        assert second.get("/api/v2/auth/me").json()["user"]["id"] == other_user["id"]
        assert third.get("/api/v2/auth/me").json()["user"]["id"] == user["id"]


def test_anonymous_permissions_and_cross_session_csrf(config):
    with client_for(config) as first, client_for(config) as second:
        assert first.get("/test/student").status_code == 401
        assert first.get("/test/admin").status_code == 401
        credentials, _ = register(first)
        assert post(first, "login", credentials).status_code == 200
        old_headers = csrf_headers(first)
        assert post(first, "login", credentials).status_code == 200
        assert first.post("/api/v2/auth/logout", headers=old_headers).status_code == 403
        assert first.post("/api/v2/auth/logout", headers=csrf_headers(second)).status_code == 403
        good = csrf_headers(first)
        assert first.post("/api/v2/auth/logout", headers={**good, "Origin": "http://evil.example.com"}).status_code == 403
        assert first.post("/api/v2/auth/logout", headers={"Origin": ORIGIN}).status_code == 403
        assert first.get("/api/v2/auth/me").status_code == 200


def test_local_admin_creation_and_no_implicit_promotion(config):
    credentials = {"email": f"{uuid4().hex}@example.com", "password": new_token()}
    create_admin(**credentials, settings=config)
    with client_for(config) as client:
        assert post(client, "login", credentials).status_code == 200
        assert client.get("/test/admin").status_code == 200
        assert client.get("/api/v2/auth/me").json()["user"]["role"] == "admin"
        student, _ = register(client)
        with pytest.raises(AuthError):
            create_admin(**student, settings=config)
        assert post(client, "login", student).status_code == 200
        assert client.get("/test/admin").status_code == 403


def test_production_session_cookie(database):
    config = database[1].model_copy(update={"allowed_origins": ["https://api.example.com"]})
    with TestClient(create_probe_app(config), base_url="https://api.example.com") as client:
        def send(endpoint, body):
            token = client.get("/api/v2/auth/csrf").json()["csrf_token"]
            return client.post("/api/v2/auth/"+endpoint, json=body, headers={"Origin": "https://api.example.com", "X-CSRF-Token": token})
        credentials = {"email": f"{uuid4().hex}@example.com", "password": new_token()}
        assert send("register", credentials).status_code == 201
        response = send("login", credentials)
        assert response.status_code == 200
        assert "__Host-ds_v2_session=" in response.headers["set-cookie"]
        assert "Secure" in response.headers["set-cookie"]
        assert "HttpOnly" in response.headers["set-cookie"]


def test_account_limit_shared_across_clients_and_window_reset(config, database):
    config = config.model_copy(update={"login_max_failures": 2})
    with client_for(config, "127.0.0.3") as first, client_for(config, "127.0.0.4") as second:
        credentials, _ = register(first)
        for _ in range(2):
            assert post(first, "login", {**credentials, "password": new_token()}).status_code == 401
        limited = post(second, "login", credentials)
        assert limited.status_code == 429 and int(limited.headers["retry-after"]) > 0
        with Session(database[0]) as session:
            session.execute(update(LoginLimit).where(LoginLimit.key == token_digest("email:"+credentials["email"])).values(window_started_at=datetime.now(timezone.utc)-timedelta(hours=2)))
            session.commit()
        assert post(second, "login", credentials).status_code == 200


def test_ip_limit_ignores_spoofed_forwarding_headers(config):
    config = config.model_copy(update={"login_ip_max_failures": 2})
    with client_for(config, "127.0.0.5") as client:
        for _ in range(2):
            assert post(client, "login", {"email": f"{uuid4().hex}@example.com", "password": new_token()}).status_code == 401
        response = client.post("/api/v2/auth/login", json={"email": f"{uuid4().hex}@example.com", "password": new_token()}, headers={**csrf_headers(client), "X-Forwarded-For": "203.0.113.10"})
        assert response.status_code == 429


def _process_login(arguments):
    config, credentials = arguments
    with client_for(config, "127.0.0.9") as client:
        return post(client, "login", credentials).status_code


def test_login_limit_atomic_across_processes(config):
    config = config.model_copy(update={"login_max_failures": 2})
    credentials = {"email": f"{uuid4().hex}@example.com", "password": new_token()}
    with ProcessPoolExecutor(max_workers=2, mp_context=multiprocessing.get_context("spawn")) as pool:
        statuses = list(pool.map(_process_login, [(config, credentials)] * 4))
    assert sorted(statuses) == [401, 401, 429, 429]


def test_upgrade_from_0001_preserves_existing_users_and_sessions():
    with isolated_database("0001_auth_foundation") as (engine, _):
        with engine.begin() as connection:
            user_id = connection.scalar(text("INSERT INTO users(email,password_hash) VALUES (:email,:hash) RETURNING id"), {"email": f"{uuid4().hex}@example.com", "hash": "migration-placeholder"})
            connection.execute(text("INSERT INTO auth_sessions(user_id,token_hash,expires_at) VALUES (:id,:hash,now()+interval '1 hour')"), {"id": user_id, "hash": token_digest(new_token())})
        for _ in range(2):
            with engine.begin() as connection:
                command.upgrade(migration_config(connection), "head")
        with Session(engine) as session:
            assert session.get(User, user_id) is not None
            assert session.scalar(select(func.count()).select_from(AuthSession)) == 1
        with engine.begin() as connection:
            command.check(migration_config(connection))
