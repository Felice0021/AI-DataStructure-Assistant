from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from threading import Barrier
import os
from uuid import UUID, uuid4

from alembic import command
import pytest
from sqlalchemy import func, inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.v2.core.errors import AuthError
from backend.v2.core.security import new_token
from backend.v2.manage import create_admin
from backend.v2.models import KnowledgeBase, User
from backend.v2.schemas.knowledge_base import KnowledgeBaseCreate
from backend.v2.services import knowledge_base_service as service
from backend.v2.tests.support import isolated_database
from backend.v2.tests.test_auth import client_for, csrf_headers, local_settings, post, register
from backend.v2.tests.test_database import database, migration_config

pytestmark = [pytest.mark.integration, pytest.mark.skipif(
    os.environ.get("DS_V2_RUN_DB_TESTS") != "1", reason="Opt in to isolated PostgreSQL tests",
)]
BASE = "/api/v2/knowledge-bases"
ADMIN = "/api/v2/admin/knowledge-bases"


@pytest.fixture(scope="module")
def actors(database):
    config = local_settings(database[1])
    with ExitStack() as stack:
        result = {"engine": database[0], "config": config}
        for role in ("a", "b", "admin"):
            client = stack.enter_context(client_for(config))
            if role == "admin":
                credentials = {"email": f"{uuid4().hex}@example.com", "password": new_token()}
                create_admin(**credentials, settings=config)
            else:
                credentials, _ = register(client)
            assert post(client, "login", credentials).status_code == 200
            result[role] = client
            result[role + "_user"] = client.get("/api/v2/auth/me").json()["user"]
        yield result


def write(client, method, path, data=None):
    return client.request(method, path, json=data, headers=csrf_headers(client))


def create(actors, role="a", *, name=None, public=False, description="private test description"):
    response = write(actors[role], "POST", ADMIN if public else BASE, {"name": name or uuid4().hex, "description": description})
    assert response.status_code == 201
    return response.json()["knowledge_base"]


def test_own_crud_and_response_fields(actors):
    kb = create(actors, name="  Ｄata\t Structures  ")
    assert kb["name"] == "Data Structures"
    assert kb["owner_id"] == actors["a_user"]["id"]
    assert kb["visibility"] == "private" and kb["index_version"] == 0
    assert set(kb) == {"id", "owner_id", "name", "description", "visibility", "index_version", "created_at", "updated_at"}
    path = BASE + "/" + kb["id"]
    response = actors["a"].get(path)
    assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
    updated = write(actors["a"], "PATCH", path, {"name": uuid4().hex, "description": ""})
    assert updated.status_code == 200 and updated.json()["knowledge_base"]["description"] == ""
    assert updated.json()["knowledge_base"]["updated_at"] >= kb["updated_at"]
    assert write(actors["a"], "DELETE", path).status_code == 204
    assert actors["a"].get(path).status_code == 404
    assert write(actors["a"], "DELETE", path).status_code == 404


@pytest.mark.parametrize("role", ["b", "admin"])
@pytest.mark.parametrize("method", ["GET", "PATCH", "DELETE"])
def test_other_private_resource_is_always_404(actors, role, method):
    kb = create(actors)
    path = BASE + "/" + kb["id"]
    response = actors[role].get(path) if method == "GET" else write(actors[role], method, path, {"name": "forbidden change"} if method == "PATCH" else None)
    assert response.status_code == 404
    assert response.json() == {"error": {"code": "knowledge_base_not_found", "message": "Knowledge base not found"}}
    assert kb["name"] not in response.text and kb["description"] not in response.text
    assert actors["a"].get(path).json()["knowledge_base"] == kb


def test_list_scope_pagination_and_untrusted_identity(actors):
    own, other = create(actors), create(actors, "b")
    public = create(actors, "admin", public=True)
    for role in ("a", "b", "admin"):
        response = actors[role].get(BASE, params={"limit": 100, "user_id": actors["a_user"]["id"]})
        assert response.status_code == 200
        result = response.json()
        assert public["id"] in {item["id"] for item in result["items"]}
        assert all(item["visibility"] == "public" or item["owner_id"] == actors[role + "_user"]["id"] for item in result["items"])
        if role != "a":
            assert own["id"] not in {item["id"] for item in result["items"]}
        if role != "b":
            assert other["id"] not in {item["id"] for item in result["items"]}
    first = actors["a"].get(BASE, params={"limit": 1, "offset": 0}).json()
    second = actors["a"].get(BASE, params={"limit": 1, "offset": 1}).json()
    assert first["total"] == second["total"] and first["items"][0]["id"] != second["items"][0]["id"]
    assert actors["a"].get(BASE, params={"limit": 101}).status_code == 422
    assert actors["a"].get(BASE, params={"offset": -1}).status_code == 422


@pytest.mark.parametrize("method,path", [("GET", BASE), ("POST", BASE), ("GET", BASE+"/"+str(uuid4())), ("PATCH", BASE+"/"+str(uuid4())), ("DELETE", BASE+"/"+str(uuid4())), ("POST", ADMIN)])
def test_anonymous_is_rejected(actors, method, path):
    with client_for(actors["config"]) as anonymous:
        response = anonymous.get(path) if method == "GET" else write(anonymous, method, path, {"name": "anonymous"})
        assert response.status_code == 401


def test_public_management_is_admin_only(actors):
    for role in ("a", "b"):
        response = write(actors[role], "POST", ADMIN, {"name": uuid4().hex})
        assert response.status_code == 403
    kb = create(actors, "admin", public=True)
    assert kb["owner_id"] is None and kb["visibility"] == "public"
    path = BASE + "/" + kb["id"]
    assert actors["b"].get(path).status_code == 200
    assert write(actors["b"], "PATCH", path, {"name": uuid4().hex}).status_code == 403
    assert write(actors["b"], "DELETE", path).status_code == 403
    assert write(actors["admin"], "PATCH", path, {"description": "system managed"}).status_code == 200
    assert write(actors["admin"], "DELETE", path).status_code == 204
    assert actors["admin"].get(path).status_code == 404
    assert kb["id"] not in {r["id"] for r in actors["b"].get(BASE, params={"limit": 100}).json()["items"]}


@pytest.mark.parametrize("extra", [{"owner_id": str(uuid4())}, {"visibility": "public"}, {"index_version": 10}, {"user_id": str(uuid4())}, {"name_key": "forged"}, {"deleted_at": None}, {"id": str(uuid4())}])
def test_create_rejects_immutable_or_internal_fields(actors, extra):
    assert write(actors["a"], "POST", BASE, {"name": uuid4().hex, **extra}).status_code == 422


@pytest.mark.parametrize("extra", [{"owner_id": str(uuid4())}, {"visibility": "public"}, {"index_version": 10}, {"name_key": "forged"}, {"deleted_at": None}])
def test_patch_rejects_immutable_fields(actors, extra):
    kb = create(actors)
    path = BASE+"/"+kb["id"]
    assert write(actors["a"], "PATCH", path, {"name": "not written", **extra}).status_code == 422
    assert actors["a"].get(path).json()["knowledge_base"] == kb


@pytest.mark.parametrize("data", [{"name": ""}, {"name": " \n\t "}, {"name": "x"*121}, {"name": "bad\x00name"}, {"name": None}, {"name": "valid", "description": "x"*4001}, {"name": "valid", "description": None}])
def test_invalid_create_input(actors, data):
    assert write(actors["a"], "POST", BASE, data).status_code == 422


@pytest.mark.parametrize("data", [{}, {"name": None}, {"description": None}, {"name": " "}, {"description": "bad\x00text"}])
def test_invalid_patch_input(actors, data):
    kb = create(actors)
    assert write(actors["a"], "PATCH", BASE+"/"+kb["id"], data).status_code == 422


def test_missing_and_malformed_ids(actors):
    for method in ("GET", "PATCH", "DELETE"):
        for value, expected in [("not-a-uuid", 422), (str(uuid4()), 404)]:
            path = BASE+"/"+value
            response = actors["a"].get(path) if method == "GET" else write(actors["a"], method, path, {"name": "valid"} if method == "PATCH" else None)
            assert response.status_code == expected


def test_normalized_uniqueness_and_different_owner_names(actors):
    name = "Topic " + uuid4().hex
    kb = create(actors, name=name)
    for variant in [name.upper(), "  "+name.replace(" ", "\t\t")+"  ", name.replace("Topic", "Ｔｏｐｉｃ")]:
        assert write(actors["a"], "POST", BASE, {"name": variant}).status_code == 409
    assert create(actors, "b", name=name)["owner_id"] != kb["owner_id"]
    public = create(actors, "admin", name=name, public=True)
    assert write(actors["admin"], "POST", ADMIN, {"name": name.upper()}).status_code == 409
    assert write(actors["a"], "DELETE", BASE+"/"+kb["id"]).status_code == 204
    assert create(actors, name=name)["id"] != kb["id"]
    assert write(actors["admin"], "DELETE", BASE+"/"+public["id"]).status_code == 204
    assert create(actors, "admin", name=name, public=True)["id"] != public["id"]


def test_conflicting_rename_rolls_back_all_fields(actors):
    first, second = create(actors), create(actors)
    path = BASE+"/"+second["id"]
    response = write(actors["a"], "PATCH", path, {"name": first["name"], "description": "must roll back"})
    assert response.status_code == 409
    assert actors["a"].get(path).json()["knowledge_base"] == second


@pytest.mark.parametrize("method", ["POST", "PATCH", "DELETE"])
@pytest.mark.parametrize("mode", ["missing", "wrong", "cross_origin"])
def test_csrf_required_for_every_write(actors, method, mode):
    kb = create(actors)
    path = BASE if method == "POST" else BASE+"/"+kb["id"]
    headers = csrf_headers(actors["a"])
    if mode == "missing": headers.pop("X-CSRF-Token")
    elif mode == "wrong": headers["X-CSRF-Token"] = "0"*64
    else: headers["Origin"] = "http://evil.example.com"
    response = actors["a"].request(method, path, json={"name": "not written"}, headers=headers)
    assert response.status_code == 403
    assert actors["a"].get(BASE+"/"+kb["id"]).json()["knowledge_base"] == kb


def test_concurrent_same_name_creation(actors):
    name, barrier = uuid4().hex, Barrier(2)
    raw = actors["a"].cookies.get(actors["config"].session_cookie)

    def attempt(_):
        with client_for(actors["config"]) as client:
            client.cookies.set(actors["config"].session_cookie, raw)
            headers = csrf_headers(client)
            barrier.wait(timeout=10)
            return client.post(BASE, json={"name": name}, headers=headers).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = list(pool.map(attempt, range(2)))
    assert sorted(statuses) == [201, 409]
    with Session(actors["engine"]) as session:
        assert session.scalar(select(func.count()).select_from(KnowledgeBase).where(KnowledgeBase.owner_id == UUID(actors["a_user"]["id"]), KnowledgeBase.name == name, KnowledgeBase.deleted_at.is_(None))) == 1


def test_service_permissions_and_tombstone(actors):
    kb = create(actors)
    with Session(actors["engine"]) as session:
        owner = session.get(User, UUID(actors["a_user"]["id"]))
        student = session.get(User, UUID(actors["b_user"]["id"]))
        admin = session.get(User, UUID(actors["admin_user"]["id"]))
        for actor in (student, admin):
            with pytest.raises(AuthError) as error:
                service.get_readable(session, actor, UUID(kb["id"]))
            assert error.value.status == 404
        with pytest.raises(AuthError) as error:
            service.create_public(session, student, KnowledgeBaseCreate(name=uuid4().hex))
        assert error.value.status == 403
        service.delete(session, owner, UUID(kb["id"]))
        assert session.get(KnowledgeBase, UUID(kb["id"])).deleted_at is not None
        with pytest.raises(AuthError) as error:
            service.get_writable(session, owner, UUID(kb["id"]))
        assert error.value.status == 404


@pytest.mark.parametrize("values", [
    {"visibility": "private", "owner_id": None},
    {"visibility": "public", "owner_id": "owner"},
    {"visibility": "invalid", "owner_id": "owner"},
    {"visibility": "private", "owner_id": str(uuid4())},
    {"visibility": "private", "owner_id": "owner", "index_version": -1},
    {"visibility": "private", "owner_id": "owner", "name": "  \t "},
    {"visibility": "private", "owner_id": "owner", "description": "x"*4001},
])
def test_database_constraints(actors, values):
    values = {**values}
    if values.get("owner_id") == "owner": values["owner_id"] = UUID(actors["a_user"]["id"])
    with Session(actors["engine"]) as session:
        with pytest.raises(IntegrityError):
            session.add(KnowledgeBase(**{"name": uuid4().hex, **values}))
            session.flush()
        session.rollback()


def test_database_generated_key_and_owner_delete_restriction(actors):
    kb = create(actors, name="Case " + uuid4().hex)
    with Session(actors["engine"]) as session:
        with pytest.raises(IntegrityError):
            session.add(KnowledgeBase(owner_id=UUID(kb["owner_id"]), visibility="private", name="  "+kb["name"].upper()+"  "))
            session.flush()
        session.rollback()
        with pytest.raises(IntegrityError):
            session.execute(text("DELETE FROM users WHERE id=:id"), {"id": UUID(kb["owner_id"])})
        session.rollback()
        record = session.get(KnowledgeBase, UUID(kb["id"]))
        assert record.name_key == kb["name"].lower()
    inspector = inspect(actors["engine"])
    assert {i["name"] for i in inspector.get_indexes("knowledge_bases")} == {
        "ix_knowledge_bases_owner_id", "ix_knowledge_bases_visibility",
        "uq_knowledge_bases_private_name", "uq_knowledge_bases_public_name",
    }
    assert inspector.get_foreign_keys("knowledge_bases")[0]["options"]["ondelete"] == "RESTRICT"


def test_upgrade_from_0002_preserves_data_and_repeats():
    with isolated_database("0002_login_limits") as (engine, _):
        with engine.begin() as connection:
            user_id = connection.scalar(text("INSERT INTO users(email,password_hash) VALUES (:email,'migration-placeholder') RETURNING id"), {"email": f"{uuid4().hex}@example.com"})
        with engine.begin() as connection: command.upgrade(migration_config(connection), "head")
        with engine.begin() as connection:
            kb_id = connection.scalar(text("INSERT INTO knowledge_bases(owner_id,name) VALUES (:owner,:name) RETURNING id"), {"owner": user_id, "name": uuid4().hex})
        with engine.begin() as connection: command.upgrade(migration_config(connection), "head")
        with Session(engine) as session:
            assert session.get(User, user_id) is not None
            assert session.get(KnowledgeBase, kb_id).owner_id == user_id
        with engine.begin() as connection: command.check(migration_config(connection))


@pytest.mark.parametrize("commit_delete", [True, False])
def test_delete_and_recreate_name_transaction_race(actors, commit_delete):
    """The unique index must wait for a pending tombstone, including rollback."""
    from queue import Queue
    from time import monotonic, sleep

    kb = create(actors)
    owner_id = UUID(kb["owner_id"])
    worker_pid = Queue()

    def recreate():
        with Session(actors["engine"]) as session:
            worker_pid.put(session.scalar(text("SELECT pg_backend_pid()")))
            owner = session.get(User, owner_id)
            try:
                return service.create_private(session, owner, KnowledgeBaseCreate(name=kb["name"])).id
            except AuthError as error:
                return error.status

    with Session(actors["engine"]) as deleting, ThreadPoolExecutor(max_workers=1) as pool:
        owner = deleting.get(User, owner_id)
        record = service.get_writable(deleting, owner, UUID(kb["id"]))
        record.deleted_at = deleting.scalar(select(func.clock_timestamp()))
        deleting.flush()
        future = pool.submit(recreate)
        try:
            pid = worker_pid.get(timeout=10)
            deadline = monotonic() + 10
            with actors["engine"].connect().execution_options(isolation_level="AUTOCOMMIT") as observer:
                while observer.scalar(text("SELECT wait_event_type FROM pg_stat_activity WHERE pid=:pid"), {"pid": pid}) != "Lock":
                    assert monotonic() < deadline, "Creation did not wait for the pending delete"
                    sleep(0.02)
            assert not future.done()
        finally:
            if commit_delete:
                deleting.commit()
            else:
                deleting.rollback()
        result = future.result(timeout=10)
    assert (isinstance(result, UUID) and result != UUID(kb["id"])) if commit_delete else result == 409
    with Session(actors["engine"]) as session:
        assert session.scalar(select(func.count()).select_from(KnowledgeBase).where(
            KnowledgeBase.owner_id == owner_id, KnowledgeBase.name == kb["name"], KnowledgeBase.deleted_at.is_(None),
        )) == 1
    path = BASE + "/" + kb["id"]
    if commit_delete:
        assert actors["a"].get(path).status_code == 404
        assert write(actors["a"], "PATCH", path, {"description": "must not resurrect"}).status_code == 404
        assert write(actors["a"], "DELETE", path).status_code == 404
