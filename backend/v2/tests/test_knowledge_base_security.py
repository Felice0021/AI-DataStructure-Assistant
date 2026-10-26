from uuid import uuid4

from fastapi.testclient import TestClient
import pytest
from sqlalchemy.exc import OperationalError

from backend.v2.core.config import Settings
from backend.v2.dependencies.auth import require_active_user
from backend.v2.dependencies.database import get_session
from backend.v2.main import create_app
from backend.v2.models import User


def app():
    return create_app(Settings(_env_file=None, db_password="unit-test-only-no-real-password", allowed_origins=["https://frontend.example.com"]))


@pytest.mark.parametrize("path", ["/api/v2/knowledge-bases", "/api/v2/knowledge-bases/"+str(uuid4())])
def test_database_errors_are_sanitized(path, caplog):
    application = app()
    application.dependency_overrides[require_active_user] = lambda: User(id=uuid4(), role="student", is_active=True)

    class BrokenSession:
        def scalar(self, statement):
            raise OperationalError("SELECT", {}, RuntimeError("private-sql-and-database-secret"))

    application.dependency_overrides[get_session] = lambda: BrokenSession()
    with TestClient(application, base_url="https://api.example.com") as client:
        response = client.get(path)
        assert response.status_code == 503
        assert response.json() == {"error": {"code": "service_unavailable", "message": "Service temporarily unavailable"}}
        assert "private-sql-and-database-secret" not in response.text + caplog.text
        assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("method", ["PATCH", "DELETE"])
def test_cors_supports_writes_only_from_explicit_origin(method):
    with TestClient(app(), base_url="https://api.example.com") as client:
        headers = {"Origin": "https://frontend.example.com", "Access-Control-Request-Method": method, "Access-Control-Request-Headers": "content-type,x-csrf-token"}
        response = client.options("/api/v2/knowledge-bases/"+str(uuid4()), headers=headers)
        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == headers["Origin"]
        assert response.headers["access-control-allow-credentials"] == "true"
        rejected = client.options("/api/v2/knowledge-bases/"+str(uuid4()), headers={**headers, "Origin": "https://evil.example.com"})
        assert rejected.status_code == 400 and "access-control-allow-origin" not in rejected.headers


def test_unexpected_error_is_sanitized(caplog):
    application = app()

    def broken_dependency():
        raise RuntimeError("private-unexpected-detail")

    application.dependency_overrides[require_active_user] = broken_dependency
    with TestClient(application, base_url="https://api.example.com", raise_server_exceptions=False) as client:
        response = client.get("/api/v2/knowledge-bases")
        assert response.status_code == 500
        assert response.json() == {"error": {"code": "internal_error", "message": "Internal server error"}}
        assert response.headers["cache-control"] == "no-store"
        assert "private-unexpected-detail" not in response.text + caplog.text
