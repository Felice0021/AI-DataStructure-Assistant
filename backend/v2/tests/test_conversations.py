import os
import time
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.v2.core.security import new_token
from backend.v2.tests.support import create_probe_app
from backend.v2.tests.test_database import database

pytestmark = [pytest.mark.integration, pytest.mark.skipif(
    os.environ.get("DS_V2_RUN_DB_TESTS") != "1", reason="Opt in to isolated PostgreSQL tests",
)]
ORIGIN = "http://127.0.0.1:5173"


def local_settings(settings, **overrides):
    return settings.model_copy(update={
        "environment": "development", "allow_insecure_loopback": True,
        "allowed_origins": [ORIGIN], **overrides,
    })


def client_for(settings, ip="127.0.0.1"):
    return TestClient(create_probe_app(settings), base_url="http://127.0.0.1:8001", client=(ip, 45000))


def csrf_headers(client):
    result = client.get("/api/v2/auth/csrf", headers={"Origin": ORIGIN})
    assert result.status_code == 200
    return {"Origin": ORIGIN, "X-CSRF-Token": result.json()["csrf_token"]}


def register(client, email=None, password=None):
    credentials = {"email": email or f"{uuid4().hex}@example.com", "password": password or new_token()}
    response = client.post("/api/v2/auth/register", json=credentials, headers=csrf_headers(client))
    assert response.status_code == 201
    return credentials


def login(client, credentials):
    response = client.post("/api/v2/auth/login", json=credentials, headers=csrf_headers(client))
    assert response.status_code == 200
    return credentials


@pytest.fixture
def config(database):
    return local_settings(database[1])


def create_conversation(client, title="测试会话"):
    resp = client.post("/api/v2/conversations", json={"title": title}, headers=csrf_headers(client))
    assert resp.status_code == 201
    return resp.json()["conversation"]["id"]


def test_no_store_header(config, database):
    with client_for(config) as client:
        cred = register(client)
        login(client, cred)
        resp = client.get("/api/v2/conversations")
        assert resp.headers.get("Cache-Control") == "no-store"


def test_conversation_crud_isolation_and_admin(config, database):
    with client_for(config) as client_a, client_for(config) as client_b:
        cred_a = register(client_a)
        login(client_a, cred_a)
        cred_b = register(client_b)
        login(client_b, cred_b)

        # 分页边界
        resp = client_a.get("/api/v2/conversations?limit=0")
        assert resp.status_code == 422

        conv_id = create_conversation(client_a, "A 的会话")

        # 非法 UUID
        assert client_a.get("/api/v2/conversations/not-a-uuid").status_code == 422

        # 跨用户隔离
        assert client_b.get(f"/api/v2/conversations/{conv_id}").status_code == 404
        assert client_b.patch(f"/api/v2/conversations/{conv_id}", json={"title": "hacked"}, headers=csrf_headers(client_b)).status_code == 404
        assert client_b.post(f"/api/v2/conversations/{conv_id}/messages", json={"content": "test"}, headers=csrf_headers(client_b)).status_code == 404

        # 管理员也无法读取他人会话
        with Session(database[0]) as s:
            s.execute(text("UPDATE users SET role='admin' WHERE email=:e"), {"e": cred_b["email"]})
            s.commit()
        client_b.cookies.clear()
        login(client_b, cred_b)
        assert client_b.get(f"/api/v2/conversations/{conv_id}").status_code == 404


def test_soft_delete(config, database):
    with client_for(config) as client:
        cred = register(client)
        login(client, cred)
        conv_id = create_conversation(client)
        
        client.post(f"/api/v2/conversations/{conv_id}/messages", json={"content": "第一条"}, headers=csrf_headers(client))

        assert client.delete(f"/api/v2/conversations/{conv_id}", headers=csrf_headers(client)).status_code == 204

        assert len(client.get("/api/v2/conversations").json()["items"]) == 0
        assert client.get(f"/api/v2/conversations/{conv_id}").status_code == 404
        assert client.get(f"/api/v2/conversations/{conv_id}/messages").status_code == 404
        assert client.post(f"/api/v2/conversations/{conv_id}/messages", json={"content": "test"}, headers=csrf_headers(client)).status_code == 404


def test_updated_at_and_csrf(config, database):
    with client_for(config) as client:
        cred = register(client)
        login(client, cred)
        conv_id = create_conversation(client)

        # CSRF 拒绝：不传 Header
        assert client.post(f"/api/v2/conversations/{conv_id}/messages", json={"content": "test"}, headers={"Origin": ORIGIN}).status_code == 403

        # 追加消息更新 updated_at
        client.post(f"/api/v2/conversations/{conv_id}/messages", json={"content": "第一条"}, headers=csrf_headers(client))
        r2 = client.get(f"/api/v2/conversations/{conv_id}")
        updated_at_1 = r2.json()["conversation"]["updated_at"]

        time.sleep(0.1)

        client.post(f"/api/v2/conversations/{conv_id}/messages", json={"content": "第二条"}, headers=csrf_headers(client))
        r3 = client.get(f"/api/v2/conversations/{conv_id}")
        assert r3.json()["conversation"]["updated_at"] > updated_at_1


def test_message_validation_and_seq(config, database):
    with client_for(config) as client:
        cred = register(client)
        login(client, cred)
        conv_id = create_conversation(client)

        # 空白内容 422
        assert client.post(f"/api/v2/conversations/{conv_id}/messages", json={"content": "   \n  "}, headers=csrf_headers(client)).status_code == 422

        # NUL 字符 422
        assert client.post(f"/api/v2/conversations/{conv_id}/messages", json={"content": "test\x00"}, headers=csrf_headers(client)).status_code == 422

        # 标题含 NUL 字符 422
        assert client.post("/api/v2/conversations", json={"title": "test\x00"}, headers=csrf_headers(client)).status_code == 422
        
        # 伪造角色 422
        assert client.post(f"/api/v2/conversations/{conv_id}/messages", json={"role": "assistant", "content": "test"}, headers=csrf_headers(client)).status_code == 422

        r1 = client.post(f"/api/v2/conversations/{conv_id}/messages", json={"content": "第一条"}, headers=csrf_headers(client))
        r2 = client.post(f"/api/v2/conversations/{conv_id}/messages", json={"content": "第二条"}, headers=csrf_headers(client))
        assert r1.json()["seq"] == 1 and r2.json()["seq"] == 2


def test_concurrent_message_append(config, database):
    with client_for(config) as client:
        cred = register(client)
        login(client, cred)
        conv_id = create_conversation(client)

        def append_msg(i):
            with client_for(config) as thread_client:
                login(thread_client, cred)
                res = thread_client.post(f"/api/v2/conversations/{conv_id}/messages", json={"content": f"msg {i}"}, headers=csrf_headers(thread_client))
                return res.status_code

        with ThreadPoolExecutor(max_workers=5) as executor:
            results = list(executor.map(append_msg, range(10)))

        assert all(code == 201 for code in results)
        resp = client.get(f"/api/v2/conversations/{conv_id}/messages?limit=20")
        seqs = [m["seq"] for m in resp.json()["items"]]
        assert seqs == list(range(1, 11))
