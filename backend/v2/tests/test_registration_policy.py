from fastapi.testclient import TestClient

from backend.v2.core.config import Settings
from backend.v2.core.security import new_token
from backend.v2.dependencies.database import get_session
from backend.v2.main import create_app


def test_disabled_registration_never_creates_user(monkeypatch):
    config = Settings(_env_file=None, db_password="unit-test-only-no-real-password",
                      registration_enabled=False, allowed_origins=["https://frontend.example.com"])
    app = create_app(config)
    app.dependency_overrides[get_session] = lambda: object()

    def unexpected_create(*args, **kwargs):
        raise AssertionError("disabled registration called user creation")

    monkeypatch.setattr("backend.v2.routers.auth.auth_service.create_user", unexpected_create)
    with TestClient(app, base_url="https://api.example.com") as client:
        csrf = client.get("/api/v2/auth/csrf").json()["csrf_token"]
        response = client.post("/api/v2/auth/register",
            headers={"Origin": "https://frontend.example.com", "X-CSRF-Token": csrf},
            json={"email": "person@example.com", "password": new_token()})
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "registration_disabled"
