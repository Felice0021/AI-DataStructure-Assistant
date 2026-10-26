"""Real multipart and authenticated download against two temporary Uvicorn workers."""
import hashlib
import json
import os
from pathlib import Path
import socket
import tempfile
from urllib.error import HTTPError
from urllib.request import Request
from uuid import uuid4

from backend.v2.core.security import new_token
from backend.v2.manage import create_admin
from backend.v2.tests.document_samples import PDF, TXT, DOCX_MIME, docx
from backend.v2.tests.http_smoke import BASE, ORIGIN, Client, running_server
from backend.v2.tests.support import isolated_database


def multipart(client, path, name, data, mime):
    status, csrf = client.call("GET", "/api/v2/auth/csrf")
    assert status == 200
    boundary = "test" + uuid4().hex
    body = (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{name}"\r\nContent-Type: {mime}\r\n\r\n'.encode()
            + data + f"\r\n--{boundary}--\r\n".encode())
    request = Request(BASE + path, data=body, method="POST", headers={
        "Origin": ORIGIN, "X-CSRF-Token": csrf["csrf_token"], "Content-Type": "multipart/form-data; boundary=" + boundary,
    })
    try:
        response = client.opener.open(request, timeout=15)
    except HTTPError as error:
        response = error
    with response:
        return response.status, json.loads(response.read())


def download(client, path):
    try:
        response = client.opener.open(Request(BASE + path, headers={"Origin": ORIGIN}), timeout=15)
    except HTTPError as error:
        response = error
    with response:
        return response.status, response.read(), response.headers


def main():
    with socket.socket() as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        probe.bind(("127.0.0.1", 8001))
    with isolated_database() as (_, settings), tempfile.TemporaryDirectory(prefix="ds-v2-document-http-") as directory, tempfile.TemporaryFile() as logs:
        root = Path(directory).resolve() / "objects"
        env = os.environ.copy()
        env.update({
            "DS_V2_DB_NAME": settings.db_name, "DS_V2_DB_HOST": settings.db_host,
            "DS_V2_DB_PORT": str(settings.db_port), "DS_V2_DB_USER": settings.db_user,
            "DS_V2_DB_PASSWORD": settings.db_password.get_secret_value(),
            "DS_V2_ENVIRONMENT": "development", "DS_V2_ALLOW_INSECURE_LOOPBACK": "true",
            "DS_V2_ALLOWED_ORIGINS": json.dumps([ORIGIN]), "DS_V2_FILE_STORAGE_ROOT": str(root),
        })
        with running_server(env, logs):
            first, second, admin = Client(), Client(), Client()
            for client in (first, second):
                credentials = {"email": uuid4().hex + "@example.com", "password": new_token()}
                assert client.call("POST", "/api/v2/auth/register", credentials)[0] == 201
                assert client.call("POST", "/api/v2/auth/login", credentials)[0] == 200
            credentials = {"email": uuid4().hex + "@example.com", "password": new_token()}
            create_admin(**credentials, settings=settings)
            assert admin.call("POST", "/api/v2/auth/login", credentials)[0] == 200
            status, kb = first.call("POST", "/api/v2/knowledge-bases", {"name": uuid4().hex})
            assert status == 201
            base = "/api/v2/knowledge-bases/" + kb["knowledge_base"]["id"] + "/documents"
            for name, data, mime in [("notes.pdf", PDF, "application/pdf"), ("notes.docx", docx(), DOCX_MIME), ("notes.txt", TXT, "text/plain")]:
                status, payload = multipart(first, base, name, data, mime)
                assert status == 201, "Real multipart upload failed"
                record = payload["document"]
                assert record["status"] == "uploaded" and record["sha256"] == hashlib.sha256(data).hexdigest()
                assert "storage_key" not in record
                path = base + "/" + record["id"]
                status, content, headers = download(first, path + "/download")
                assert status == 200 and content == data
                assert headers["Content-Disposition"].startswith("attachment;")
                for outsider in (second, admin):
                    assert outsider.call("GET", base)[0] == 404
                    assert outsider.call("GET", path)[0] == 404
                    assert download(outsider, path + "/download")[0] == 404
                    assert outsider.call("DELETE", path)[0] == 404
                assert first.call("DELETE", path, csrf=False)[0] == 403
                assert first.call("DELETE", path)[0] == 204
                assert download(first, path + "/download")[0] == 404
            status, public = admin.call("POST", "/api/v2/admin/knowledge-bases", {"name": uuid4().hex})
            assert status == 201
            public_base = "/api/v2/knowledge-bases/" + public["knowledge_base"]["id"] + "/documents"
            assert multipart(first, public_base, "x.txt", TXT, "text/plain")[0] == 403
            status, payload = multipart(admin, public_base, "x.txt", TXT, "text/plain")
            assert status == 201
            public_path = public_base + "/" + payload["document"]["id"]
            assert download(second, public_path + "/download")[1] == TXT
            assert admin.call("DELETE", public_path)[0] == 204
            assert not list(root.iterdir())
            print("Real HTTP: PDF/DOCX/TXT upload, SHA-256, exact download, delete PASS")
            print("Real HTTP: two students and admin private isolation; public permissions; CSRF PASS")
        print("Temporary API, isolated database and upload directory cleaned; development data retained")


if __name__ == "__main__":
    main()
