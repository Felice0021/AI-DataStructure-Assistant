import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy.exc import OperationalError

from backend.v2.core.config import Settings
from backend.v2.core.security import PASSWORD_HASHER, csrf_token, new_token, verify_password
from backend.v2.dependencies.database import get_session
from backend.v2.main import create_app
from backend.v2.schemas.auth import Registration


def settings(**overrides):
    return Settings(_env_file=None, db_password="unit-test-only-no-real-password", **overrides)


def test_argon2id_hash_and_validation():
    password = new_token()
    first, second = PASSWORD_HASHER.hash(password), PASSWORD_HASHER.hash(password)
    assert first.startswith("$argon2id$v=19$m=65536,t=3,p=1$")
    assert first != second and password not in first
    assert verify_password(password, first)[0]
    assert not verify_password(new_token(), first)[0]
    assert not verify_password(password, None)[0]
    assert not verify_password(password, "invalid-legacy-hash")[0]


@pytest.mark.parametrize("password", ["short", " " * 20, "a" * 20, "123456789012345", "passwordpassword", "abcd" * 40, "abcde1234567890\x00"])
def test_password_policy(password):
    with pytest.raises(ValidationError):
        Registration(email="person@example.com", password=password)


@pytest.mark.parametrize("overrides", [
    {"allow_insecure_loopback": True},
    {"allowed_origins": ["*"]},
    {"allowed_origins": ["http://127.0.0.1:5173"]},
    {"environment": "development", "allow_insecure_loopback": True, "allowed_origins": ["http://192.168.1.2:5173"]},
    {"allowed_origins": ["https://example.com/path"]},
])
def test_unsafe_configuration_fails_closed(overrides):
    with pytest.raises(ValidationError):
        settings(**overrides)


def test_production_http_is_rejected():
    with TestClient(create_app(settings())) as client:
        assert client.get("/api/v2/auth/csrf").status_code == 403
        assert client.get("/api/v2/health").status_code == 200


def test_secure_csrf_cookie_and_cors():
    config = settings(allowed_origins=["https://frontend.example.com"])
    with TestClient(create_app(config), base_url="https://api.example.com") as client:
        response = client.get("/api/v2/auth/csrf", headers={"Origin": config.allowed_origins[0]})
        cookie = response.headers["set-cookie"]
        assert response.status_code == 200
        assert all(part in cookie for part in ["__Host-ds_v2_preauth=", "HttpOnly", "Secure", "SameSite=lax", "Path=/", "Max-Age=1800"])
        assert "Domain=" not in cookie
        assert client.cookies.get(config.csrf_cookie) not in response.text
        assert response.headers["cache-control"] == "no-store"
        assert response.headers["access-control-allow-origin"] == config.allowed_origins[0]
        assert response.headers["access-control-allow-credentials"] == "true"
        rejected = client.get("/api/v2/auth/csrf", headers={"Origin": "https://evil.example.com"})
        assert rejected.status_code == 403 and "access-control-allow-origin" not in rejected.headers
        preflight = client.options("/api/v2/auth/login", headers={
            "Origin": config.allowed_origins[0], "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type,x-csrf-token",
        })
        assert preflight.status_code == 200


@pytest.mark.parametrize("origin,token", [(None, None), ("https://frontend.example.com", None), ("https://evil.example.com", "valid"), ("null", "valid"), ("https://frontend.example.com", "f" * 64)])
def test_csrf_rejected_before_database(origin, token):
    config = settings(allowed_origins=["https://frontend.example.com"])
    with TestClient(create_app(config), base_url="https://api.example.com") as client:
        csrf = client.get("/api/v2/auth/csrf").json()["csrf_token"]
        headers = {}
        if origin: headers["Origin"] = origin
        if token: headers["X-CSRF-Token"] = csrf if token == "valid" else token
        response = client.post("/api/v2/auth/register", json={"email": "person@example.com", "password": new_token()}, headers=headers)
        assert response.status_code == 403


def test_request_validation_does_not_echo_secrets():
    config = settings(allowed_origins=["https://frontend.example.com"])
    with TestClient(create_app(config), base_url="https://api.example.com") as client:
        csrf = client.get("/api/v2/auth/csrf").json()["csrf_token"]
        response = client.post("/api/v2/auth/register", headers={"Origin": config.allowed_origins[0], "X-CSRF-Token": csrf}, json={"email": "invalid", "password": "private-short"})
        assert response.status_code == 422
        assert "private-short" not in response.text and "input" not in response.text


def test_auth_database_failure_is_sanitized(caplog):
    config = settings(allowed_origins=["https://frontend.example.com"])
    app = create_app(config)
    raw = new_token()

    class BrokenSession:
        def scalar(self, statement):
            raise OperationalError("SELECT", {}, RuntimeError("private-database-detail"))

    app.dependency_overrides[get_session] = lambda: BrokenSession()
    with TestClient(app, base_url="https://api.example.com") as client:
        client.cookies.set(config.session_cookie, raw)
        response = client.get("/api/v2/auth/me")
        assert response.status_code == 503
        assert response.json() == {"error": {"code": "service_unavailable", "message": "Service temporarily unavailable"}}
        assert "private-database-detail" not in response.text + caplog.text
        assert raw not in response.text + caplog.text


def test_insecure_mode_rejects_remote_client_and_host():
    config = settings(environment="development", allow_insecure_loopback=True)
    for base, client_ip in [("http://127.0.0.1", "192.0.2.1"), ("http://example.com", "127.0.0.1")]:
        with TestClient(create_app(config), base_url=base, client=(client_ip, 40000)) as client:
            assert client.get("/api/v2/auth/csrf").status_code == 403


def test_csrf_token_bound_to_cookie():
    assert csrf_token(new_token()) != csrf_token(new_token())


def test_unexpected_auth_failure_is_sanitized(caplog):
    app = create_app(settings())

    def broken_session():
        raise RuntimeError("private-unexpected-internal-detail")

    app.dependency_overrides[get_session] = broken_session
    with TestClient(app, base_url="https://api.example.com", raise_server_exceptions=False) as client:
        response = client.get("/api/v2/auth/me")
        assert response.status_code == 500
        assert response.json() == {"error": {"code": "internal_error", "message": "Internal server error"}}
        assert response.headers["cache-control"] == "no-store"
        assert "private-unexpected-internal-detail" not in response.text + caplog.text
