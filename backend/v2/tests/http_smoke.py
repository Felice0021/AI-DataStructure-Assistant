"""Run real HTTP against two Uvicorn workers and a disposable database.

Run from repository root: python -m backend.v2.tests.http_smoke
No accounts, passwords, cookies or CSRF values are printed.
"""
import http.cookiejar
from contextlib import contextmanager
import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.request import HTTPCookieProcessor, Request, build_opener, urlopen
from uuid import uuid4

from backend.v2.core.config import REPOSITORY_ROOT
from backend.v2.core.security import new_token
from backend.v2.manage import create_admin
from backend.v2.tests.support import isolated_database

BASE = "http://127.0.0.1:8001"
ORIGIN = "http://127.0.0.1:5173"


class Client:
    def __init__(self):
        self.jar = http.cookiejar.CookieJar()
        self.opener = build_opener(HTTPCookieProcessor(self.jar))

    def call(self, method, path, body=None, *, csrf=True, headers=None):
        request_headers = {"Origin": ORIGIN, **(headers or {})}
        if method in {"POST", "PATCH", "DELETE"} and csrf:
            code, data = self.call("GET", "/api/v2/auth/csrf")
            assert code == 200, "CSRF bootstrap failed"
            request_headers["X-CSRF-Token"] = data["csrf_token"]
        encoded = json.dumps(body).encode() if body is not None else None
        if encoded is not None:
            request_headers["Content-Type"] = "application/json"
        request = Request(BASE + path, data=encoded, method=method, headers=request_headers)
        try:
            response = self.opener.open(request, timeout=10)
        except HTTPError as error:
            response = error
        with response:
            payload = response.read()
            return response.status, json.loads(payload) if payload else None


@contextmanager
def running_server(env, logs):
    global BASE
    listener=socket.socket();listener.bind(('127.0.0.1',0));listener.listen(128)
    port=listener.getsockname()[1];BASE=f'http://127.0.0.1:{port}'
    args=[sys.executable,'-m','uvicorn','backend.v2.tests.support:create_probe_app','--factory','--workers','2',
          '--no-proxy-headers','--no-access-log']
    kwargs={}
    if os.name=='posix':
        args+=['--fd',str(listener.fileno())];kwargs['pass_fds']=(listener.fileno(),)
    else:
        # Windows cannot pass POSIX file descriptors. Random port avoids fixed-port collision.
        listener.close();args+=['--host','127.0.0.1','--port',str(port)]
    process=subprocess.Popen(args,cwd=REPOSITORY_ROOT,env=env,stdout=logs,stderr=logs,**kwargs)
    try:
        for _ in range(100):
            if process.poll() is not None:
                raise RuntimeError("Temporary HTTP server failed to start")
            try:
                with urlopen(BASE + "/api/v2/health", timeout=1) as response:
                    if response.status == 200: break
            except (URLError, OSError):
                time.sleep(0.1)
        else:
            raise RuntimeError("Temporary HTTP server readiness timed out")
        yield
    finally:
        listener.close()
        process.send_signal(signal.SIGINT)
        try:
            process.wait(timeout=20)
        except subprocess.TimeoutExpired:
            process.terminate()
            process.wait(timeout=10)


def main():
    # Refuse to interrupt any pre-existing 8001 service.
    with isolated_database() as (_, settings), tempfile.TemporaryFile() as logs:
        env = os.environ.copy()
        env.update({
            "DS_V2_DB_NAME": settings.db_name,
            "DS_V2_DB_HOST": settings.db_host,
            "DS_V2_DB_PORT": str(settings.db_port),
            "DS_V2_DB_USER": settings.db_user,
            "DS_V2_DB_PASSWORD": settings.db_password.get_secret_value(),
            "DS_V2_ENVIRONMENT": "development",
            "DS_V2_ALLOW_INSECURE_LOOPBACK": "true",
            "DS_V2_ALLOWED_ORIGINS": json.dumps([ORIGIN]),
        })
        with running_server(env, logs):
            first, second = Client(), Client()
            users = []
            for client in (first, second):
                credentials = {"email": f"{uuid4().hex}@example.com", "password": new_token()}
                status, data = client.call("POST", "/api/v2/auth/register", credentials)
                assert status == 201 and data["user"]["role"] == "student", "Registration failed"
                user_id = data["user"]["id"]
                assert client.call("GET", "/api/v2/auth/me")[0] == 401, "Registration must not log in"
                status, _ = client.call("POST", "/api/v2/auth/login", credentials)
                assert status == 200, "Login failed"
                assert client.call("GET", "/api/v2/auth/me")[1]["user"]["id"] == user_id, "Wrong identity"
                assert client.call("GET", "/test/student")[0] == 200, "Student permission failed"
                assert client.call("GET", "/test/admin")[0] == 403, "Student elevated privileges"
                users.append(user_id)
            assert users[0] != users[1], "User isolation failed"
            assert first.call("POST", "/api/v2/auth/logout", csrf=False)[0] == 403, "CSRF missing accepted"
            raw = next(c.value for c in first.jar if c.name == "ds_v2_session")
            assert first.call("POST", "/api/v2/auth/logout")[0] == 204, "Logout failed"
            assert first.call("GET", "/api/v2/auth/me")[0] == 401, "Session still active"
            assert first.call("GET", "/api/v2/auth/me", headers={"Cookie": "ds_v2_session="+raw})[0] == 401, "Revoked credential accepted"
            assert second.call("GET", "/api/v2/auth/me")[1]["user"]["id"] == users[1], "Other user affected"
            assert first.call("POST", "/api/v2/auth/logout")[0] == 204, "Idempotent logout failed"
            assert second.call("POST", "/api/v2/auth/logout")[0] == 204, "Second logout failed"
            admin = Client()
            admin_credentials = {"email": f"{uuid4().hex}@example.com", "password": new_token()}
            create_admin(**admin_credentials, settings=settings)
            assert admin.call("POST", "/api/v2/auth/login", admin_credentials)[0] == 200, "Local admin login failed"
            assert admin.call("GET", "/test/admin")[0] == 200, "Admin permission failed"
            assert admin.call("POST", "/api/v2/auth/logout")[0] == 204, "Admin logout failed"
            print("Real HTTP: two independent student register/login/me/permissions/logout flows PASS")
            print("Real HTTP: local admin, CSRF rejection, revoked credential, session isolation PASS")
        # A bound-but-not-listening port reliably refuses DB connections without
        # stopping PostgreSQL or changing any existing database/container.
        with socket.socket() as unavailable:
            unavailable.bind(("127.0.0.1", 0))
            failing_env = {**env, "DS_V2_DB_PORT": str(unavailable.getsockname()[1])}
            with running_server(failing_env, logs):
                client = Client()
                assert client.call("GET", "/api/v2/health")[0] == 200
                assert client.call("GET", "/api/v2/health/db")[0] == 503
                code, data = client.call("GET", "/api/v2/auth/me", headers={"Cookie": "ds_v2_session="+new_token()})
                assert code == 503 and data == {"error": {"code": "service_unavailable", "message": "Service temporarily unavailable"}}
                code, data = client.call("POST", "/api/v2/auth/login", {"email": f"{uuid4().hex}@example.com", "password": new_token()})
                assert code == 503 and data["error"]["code"] == "service_unavailable"
                print("Real HTTP: refused database connection yields sanitized 503; liveness stays 200 PASS")
    print("Temporary two-worker API stopped; isolated test database removed; development data untouched")


if __name__ == "__main__":
    main()
