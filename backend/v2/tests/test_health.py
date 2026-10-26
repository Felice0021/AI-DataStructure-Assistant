import logging

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from backend.v2.core.config import Settings
from backend.v2.dependencies.database import get_session
from backend.v2.main import create_app


@pytest.fixture
def app():
    return create_app(Settings(_env_file=None, db_password="unit-test-only-not-a-real-password"))


def test_liveness_and_openapi(app):
    with TestClient(app) as client:
        response = client.get("/api/v2/health")
        assert response.status_code == 200
        assert response.json() == {
            "status": "ok", "service": "ds-assistant-v2", "version": "2.0.0",
        }
        paths = client.get("/api/v2/openapi.json").json()["paths"]
        assert set(paths) == {
            "/api/v2/rag/ask",
            "/api/v2/knowledge-bases/{kb_id}/cloud-consents",
            "/api/v2/knowledge-bases/{kb_id}/cloud-consents/audit",
            "/api/v2/knowledge-bases/{kb_id}/cloud-consents/{purpose}",
            "/api/v2/retrieval/search", "/api/v2/retrieval/prepare-context",
            "/api/v2/health", "/api/v2/health/db", "/api/v2/auth/csrf",
            "/api/v2/auth/register", "/api/v2/auth/login", "/api/v2/auth/me", "/api/v2/auth/logout",
            "/api/v2/knowledge-bases", "/api/v2/knowledge-bases/{knowledge_base_id}",
            "/api/v2/admin/knowledge-bases",
            "/api/v2/knowledge-bases/{kb_id}/documents",
            "/api/v2/knowledge-bases/{kb_id}/documents/{doc_id}",
            "/api/v2/knowledge-bases/{kb_id}/documents/{doc_id}/download",
            "/api/v2/knowledge-bases/{kb_id}/documents/{doc_id}/ingestion",
            "/api/v2/knowledge-bases/{kb_id}/documents/{doc_id}/chunks",
            "/api/v2/knowledge-bases/{kb_id}/documents/{doc_id}/embedding",
        }
        assert "503" in paths["/api/v2/health/db"]["get"]["responses"]


def test_database_error_is_sanitized(app, caplog):
    secret = "private-driver-password-and-stack-trace"

    class BrokenSession:
        def execute(self, statement):
            raise OperationalError("SELECT 1", {}, RuntimeError(secret))

    app.dependency_overrides[get_session] = lambda: BrokenSession()
    with TestClient(app) as client, caplog.at_level(logging.WARNING):
        response = client.get("/api/v2/health/db")
    assert response.status_code == 503
    assert response.json() == {"status": "unavailable", "database": "unavailable"}
    assert secret not in response.text + caplog.text
    assert "Traceback" not in response.text


def test_password_redaction_and_url_encoding():
    secret = "a-long-test-password:@/%#"
    settings = Settings(_env_file=None, db_password=secret)
    assert secret not in repr(settings)
    assert secret not in settings.database_url.render_as_string()
    assert settings.database_url.password == secret


def test_unexpected_error_is_sanitized(app, caplog):
    def broken_dependency():
        raise RuntimeError("private-internal-detail")

    app.dependency_overrides[get_session] = broken_dependency
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/api/v2/health/db")
    assert response.status_code == 500
    assert response.json() == {"detail": "Internal server error"}
    assert "private-internal-detail" not in response.text + caplog.text
