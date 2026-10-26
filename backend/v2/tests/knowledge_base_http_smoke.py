"""Real two-worker knowledge-base isolation checks; no credentials are printed."""
import json
import os
import socket
import tempfile
from uuid import uuid4

from backend.v2.core.security import new_token
from backend.v2.manage import create_admin
from backend.v2.tests.http_smoke import Client, ORIGIN, running_server
from backend.v2.tests.support import isolated_database

BASE = "/api/v2/knowledge-bases"
ADMIN = "/api/v2/admin/knowledge-bases"


def main():
    with isolated_database() as (_, settings), tempfile.TemporaryFile() as logs:
        env = {**os.environ,
            "DS_V2_DB_NAME": settings.db_name,
            "DS_V2_DB_HOST": settings.db_host,
            "DS_V2_DB_PORT": str(settings.db_port),
            "DS_V2_DB_USER": settings.db_user,
            "DS_V2_DB_PASSWORD": settings.db_password.get_secret_value(),
            "DS_V2_ENVIRONMENT": "development",
            "DS_V2_ALLOW_INSECURE_LOOPBACK": "true",
            "DS_V2_ALLOWED_ORIGINS": json.dumps([ORIGIN]),
        }
        with running_server(env, logs):
            first, second, admin = Client(), Client(), Client()
            for client in (first, second):
                credentials = {"email": f"{uuid4().hex}@example.com", "password": new_token()}
                assert client.call("POST", "/api/v2/auth/register", credentials)[0] == 201
                assert client.call("POST", "/api/v2/auth/login", credentials)[0] == 200
            admin_credentials = {"email": f"{uuid4().hex}@example.com", "password": new_token()}
            create_admin(**admin_credentials, settings=settings)
            assert admin.call("POST", "/api/v2/auth/login", admin_credentials)[0] == 200
            name, description = "Private " + uuid4().hex, "isolated knowledge base description"
            code, result = first.call("POST", BASE, {"name": name, "description": description})
            assert code == 201 and result["knowledge_base"]["visibility"] == "private"
            kb = result["knowledge_base"]
            path = BASE + "/" + kb["id"]
            assert first.call("GET", path)[0] == 200
            for client in (second, admin):
                code, listing = client.call("GET", BASE)
                assert code == 200 and kb["id"] not in {item["id"] for item in listing["items"]}
                for method in ("GET", "PATCH", "DELETE"):
                    code, error = client.call(method, path, {"description": "forbidden"} if method == "PATCH" else None)
                    assert code == 404 and error == {"error": {"code": "knowledge_base_not_found", "message": "Knowledge base not found"}}
                    assert name not in json.dumps(error) and description not in json.dumps(error)
            assert first.call("GET", path)[1]["knowledge_base"] == kb
            assert second.call("POST", BASE, {"name": name})[0] == 201
            assert first.call("POST", BASE, {"name": name.upper()})[0] == 409
            assert first.call("PATCH", path, {"owner_id": str(uuid4())})[0] == 422
            assert first.call("POST", BASE, {"name": "forged", "visibility": "public"})[0] == 422
            assert first.call("POST", ADMIN, {"name": "forged public"})[0] == 403
            assert first.call("PATCH", path, {"description": "missing CSRF"}, csrf=False)[0] == 403
            assert first.call("DELETE", path, csrf=False)[0] == 403
            assert first.call("PATCH", path, {"description": "owner updated"})[0] == 200
            code, result = admin.call("POST", ADMIN, {"name": "Public " + uuid4().hex})
            assert code == 201 and result["knowledge_base"]["owner_id"] is None
            public_id = result["knowledge_base"]["id"]
            public_path = BASE + "/" + public_id
            for client in (first, second):
                assert client.call("GET", public_path)[0] == 200
                assert public_id in {item["id"] for item in client.call("GET", BASE)[1]["items"]}
                assert client.call("PATCH", public_path, {"name": "forbidden"})[0] == 403
                assert client.call("DELETE", public_path)[0] == 403
            assert admin.call("PATCH", public_path, {"description": "admin updated"})[0] == 200
            assert admin.call("DELETE", public_path)[0] == 204
            assert first.call("GET", public_path)[0] == 404
            assert first.call("DELETE", path)[0] == 204
            assert first.call("GET", path)[0] == 404
            assert kb["id"] not in {item["id"] for item in first.call("GET", BASE)[1]["items"]}
            code, recreated = first.call("POST", BASE, {"name": name})
            assert code == 201 and recreated["knowledge_base"]["id"] != kb["id"]
            for client in (first, second, admin):
                assert client.call("POST", "/api/v2/auth/logout")[0] == 204
            print("Real HTTP: two independent students; own CRUD and cross-user GET/PATCH/DELETE rejection PASS")
            print("Real HTTP: admin public management without private-data bypass; CSRF, duplicates, tombstone filtering PASS")
        with socket.socket() as unavailable:
            unavailable.bind(("127.0.0.1", 0))
            failing_env = {**env, "DS_V2_DB_PORT": str(unavailable.getsockname()[1])}
            with running_server(failing_env, logs):
                client = Client()
                code, error = client.call("GET", BASE, headers={"Cookie": "ds_v2_session="+new_token()})
                assert code == 503 and error == {"error": {"code": "service_unavailable", "message": "Service temporarily unavailable"}}
                assert client.call("GET", "/api/v2/health")[0] == 200
                print("Real HTTP: database unavailable fails closed with sanitized knowledge-base 503 PASS")
    print("Temporary API stopped and isolated knowledge-base test database removed")


if __name__ == "__main__":
    main()
