import os
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from backend.v2.core.security import new_token
from backend.v2.tests.support import create_probe_app
from backend.v2.tests.test_database import database, migration_config

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


def test_conversation_crud_and_isolation(config, database):
    with client_for(config) as client_a, client_for(config) as client_b:
        # 注册并登录 A 和 B
        cred_a = register(client_a)
        login(client_a, cred_a)
        
        cred_b = register(client_b)
        login(client_b, cred_b)

        # A 创建会话
        conv_id = create_conversation(client_a, "A 的会话")

        # A 可以访问
        assert client_a.get(f"/api/v2/conversations/{conv_id}").status_code == 200

        # B 访问 A 的会话 -> 应该统一返回 404 (不泄露存在性)
        assert client_b.get(f"/api/v2/conversations/{conv_id}").status_code == 404
        assert client_b.patch(f"/api/v2/conversations/{conv_id}", json={"title": "hacked"}, headers=csrf_headers(client_b)).status_code == 404
        assert client_b.post(f"/api/v2/conversations/{conv_id}/messages", json={"content": "test"}, headers=csrf_headers(client_b)).status_code == 404

        # A 改名
        resp = client_a.patch(f"/api/v2/conversations/{conv_id}", json={"title": "A 改名了"}, headers=csrf_headers(client_a))
        assert resp.status_code == 200
        assert resp.json()["conversation"]["title"] == "A 改名了"


def test_soft_delete(config, database):
    with client_for(config) as client:
        cred = register(client)
        login(client, cred)
        
        conv_id = create_conversation(client)

        # 删除
        assert client.delete(f"/api/v2/conversations/{conv_id}", headers=csrf_headers(client)).status_code == 204

        # 列表里没它了
        resp = client.get("/api/v2/conversations")
        assert len(resp.json()["items"]) == 0

        # 详情、追加消息全 404
        assert client.get(f"/api/v2/conversations/{conv_id}").status_code == 404
        assert client.post(f"/api/v2/conversations/{conv_id}/messages", json={"content": "test"}, headers=csrf_headers(client)).status_code == 404


def test_message_append_and_seq(config, database):
    with client_for(config) as client:
        cred = register(client)
        login(client, cred)
        
        conv_id = create_conversation(client)

        # 追加两条
        r1 = client.post(f"/api/v2/conversations/{conv_id}/messages", json={"content": "第一条"}, headers=csrf_headers(client))
        assert r1.status_code == 201
        assert r1.json()["seq"] == 1

        r2 = client.post(f"/api/v2/conversations/{conv_id}/messages", json={"content": "第二条"}, headers=csrf_headers(client))
        assert r2.status_code == 201
        assert r2.json()["seq"] == 2

        # 客户端伪造 assistant 角色 -> 422
        r3 = client.post(f"/api/v2/conversations/{conv_id}/messages", json={"role": "assistant", "content": "fake"}, headers=csrf_headers(client))
        assert r3.status_code == 422

        # 列表按 seq 升序
        resp = client.get(f"/api/v2/conversations/{conv_id}/messages")
        items = resp.json()["items"]
        assert [m["seq"] for m in items] == [1, 2]
        assert items[0]["content"] == "第一条"


def test_concurrent_message_append(config, database):
    with client_for(config) as client:
        cred = register(client)
        login(client, cred)
        
        conv_id = create_conversation(client)

        # 多线程并发追加（注意：TestClient 在同一个 client 实例下并发可能会由于 Cookie 导致问题，所以这里每个线程单独创建 client）
        def append_msg(i):
            with client_for(config) as thread_client:
                login(thread_client, cred)
                res = thread_client.post(f"/api/v2/conversations/{conv_id}/messages", json={"content": f"msg {i}"}, headers=csrf_headers(thread_client))
                return res.status_code

        with ThreadPoolExecutor(max_workers=5) as executor:
            results = list(executor.map(append_msg, range(10)))

        # 应该全部 201
        assert all(code == 201 for code in results)

        # 检查 seq 无重复且连续
        resp = client.get(f"/api/v2/conversations/{conv_id}/messages?limit=20")
        items = resp.json()["items"]
        seqs = [m["seq"] for m in items]
        assert seqs == list(range(1, 11))
