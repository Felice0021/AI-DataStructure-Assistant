from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from io import BytesIO
import hashlib
import os
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, inspect, select, text
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session
from starlette.datastructures import UploadFile, Headers

from backend.v2.models import Document, User
from backend.v2.services import document_service as service
from backend.v2.services.file_storage import LocalFileStorage
from backend.v2.tests.document_samples import PDF, TXT, DOCX_MIME, docx
from backend.v2.tests.test_auth import client_for, csrf_headers, local_settings, post, register
from backend.v2.tests.test_database import database, migration_config
from backend.v2.tests.test_knowledge_bases import actors, create, write

pytestmark = [pytest.mark.integration, pytest.mark.skipif(os.environ.get("DS_V2_RUN_DB_TESTS") != "1", reason="Opt in to isolated DB tests")]


@pytest.fixture
def files(actors, tmp_path):
    config=actors["config"].model_copy(update={"file_storage_root":tmp_path.resolve()/"objects"})
    with ExitStack() as stack:
        result={"config":config,"engine":actors["engine"],"actors":actors}
        for role in ("a","b","admin"):
            client=stack.enter_context(client_for(config))
            client.cookies.set(config.session_cookie, actors[role].cookies.get(config.session_cookie))
            result[role]=client
        result["kb"]=create(actors)
        result["base"]="/api/v2/knowledge-bases/"+result["kb"]["id"]+"/documents"
        yield result


def upload(files, *, role="a", name="notes.txt", data=TXT, mime="text/plain", base=None, csrf=True):
    return files[role].post(base or files["base"], files={"file":(name,data,mime)},headers=csrf_headers(files[role]) if csrf else {})


def objects(files):
    root=files["config"].file_storage_root
    return list(root.iterdir()) if root.exists() else []


@pytest.mark.parametrize("name,data,mime",[("a.pdf",PDF,"application/pdf"),("a.docx",docx(),DOCX_MIME),("笔记.txt",TXT,"text/plain")])
def test_upload_list_detail_download_delete(files,name,data,mime):
    response=upload(files,name=name,data=data,mime=mime)
    assert response.status_code==201,response.text
    record=response.json()["document"]
    assert record["status"]=="uploaded" and record["sha256"]==hashlib.sha256(data).hexdigest()
    assert record["size_bytes"]==len(data) and record["mime_type"]==mime
    assert not {"storage_key","deleted_at","storage_deleted_at"}&record.keys()
    path=files["base"]+"/"+record["id"]
    assert files["a"].get(path).json()["document"]==record
    listing=files["a"].get(files["base"],params={"limit":1}).json()
    assert listing["items"]==[record] and listing["total"]==1
    download=files["a"].get(path+"/download")
    assert download.status_code==200 and download.content==data
    assert download.headers["content-disposition"].startswith("attachment;")
    assert download.headers["content-type"]=="application/octet-stream"
    assert download.headers["x-content-type-options"]=="nosniff"
    assert download.headers["cache-control"]=="no-store"
    assert write(files["a"],"DELETE",path).status_code==204
    assert write(files["a"],"DELETE",path).status_code==204
    assert files["a"].get(path).status_code==404
    assert files["a"].get(path+"/download").status_code==404
    assert files["a"].get(files["base"]).json()["items"]==[]
    assert not objects(files)


@pytest.mark.parametrize("role",["b","admin"])
@pytest.mark.parametrize("operation",["list","detail","download","delete","upload"])
def test_other_private_files_are_inaccessible(files,role,operation):
    record=upload(files).json()["document"]
    path=files["base"]+"/"+record["id"]
    if operation=="upload": response=upload(files,role=role)
    elif operation=="delete": response=write(files[role],"DELETE",path)
    else: response=files[role].get(files["base"] if operation=="list" else path+("/download" if operation=="download" else ""))
    assert response.status_code==404
    assert files["a"].get(path+"/download").content==TXT


def test_public_admin_management(files):
    kb=create(files["actors"],"admin",public=True)
    base="/api/v2/knowledge-bases/"+kb["id"]+"/documents"
    assert upload(files,base=base).status_code==403
    record=upload(files,role="admin",base=base).json()["document"]
    path=base+"/"+record["id"]
    assert files["b"].get(path+"/download").content==TXT
    assert write(files["b"],"DELETE",path).status_code==403
    assert write(files["admin"],"DELETE",path).status_code==204


def test_deleted_parent_and_cross_kb(files):
    record=upload(files).json()["document"]
    other=create(files["actors"])
    wrong="/api/v2/knowledge-bases/"+other["id"]+"/documents/"+record["id"]
    assert files["a"].get(wrong).status_code==404
    assert files["a"].get(wrong+"/download").status_code==404
    assert write(files["a"],"DELETE",wrong).status_code==404
    assert write(files["a"],"DELETE","/api/v2/knowledge-bases/"+files["kb"]["id"]).status_code==204
    path=files["base"]+"/"+record["id"]
    for route in (files["base"],path,path+"/download"): assert files["a"].get(route).status_code==404
    assert write(files["a"],"DELETE",path).status_code==404
    assert upload(files).status_code==404


@pytest.mark.parametrize("value,status",[("invalid",422),(str(uuid4()),404)])
def test_bad_ids(files,value,status):
    assert upload(files,base="/api/v2/knowledge-bases/"+value+"/documents").status_code==status
    assert files["a"].get(files["base"]+"/"+value).status_code==status
    assert files["a"].get(files["base"]+"/"+value+"/download").status_code==status


@pytest.mark.parametrize("name,data,mime",[("x.exe",TXT,"text/plain"),("../x.txt",TXT,"text/plain"),("x.pdf",TXT,"application/pdf"),("x.txt",b"","text/plain"),("x.txt",b"\xff","text/plain"),("x.docx",b"broken",DOCX_MIME)])
def test_invalid_upload_does_not_persist(files,name,data,mime):
    assert upload(files,name=name,data=data,mime=mime).status_code==422
    assert not objects(files)
    assert files["a"].get(files["base"]).json()["total"]==0


@pytest.mark.parametrize("mode",["missing","wrong","origin"])
def test_csrf_upload_and_delete(files,mode):
    record=upload(files).json()["document"]
    headers=csrf_headers(files["a"])
    if mode=="missing": headers.pop("X-CSRF-Token")
    elif mode=="wrong": headers["X-CSRF-Token"]="0"*64
    else: headers["Origin"]="https://evil.example.com"
    assert files["a"].post(files["base"],files={"file":("x.txt",TXT,"text/plain")},headers=headers).status_code==403
    assert files["a"].delete(files["base"]+"/"+record["id"],headers=headers).status_code==403


def test_anonymous_and_extra_fields(files):
    with client_for(files["config"]) as client:
        assert client.get(files["base"]).status_code==401
        assert client.post(files["base"],files={"file":("x.txt",TXT,"text/plain")},headers=csrf_headers(client)).status_code==401
    client=files["a"]
    assert client.post(files["base"],files={"file":("x.txt",TXT,"text/plain")},data={"status":"ready"},headers=csrf_headers(client)).status_code==422
    assert client.post(files["base"],files=[("file",("x.txt",TXT)),("file",("y.txt",TXT))],headers=csrf_headers(client)).status_code==422
    assert not objects(files)
    assert client.get(files["base"],params={"limit":101}).status_code==422


def test_size_and_count_quotas(files):
    files["config"].upload_max_bytes=len(TXT)-1
    assert upload(files).status_code==413
    assert not objects(files)
    files["config"].upload_max_bytes=1000
    files["config"].documents_per_kb=1
    assert upload(files).status_code==201
    assert upload(files).status_code==409


@pytest.mark.parametrize("field",["storage_bytes_per_kb","storage_total_bytes"])
def test_byte_quotas(files,field):
    budget = 1
    if field == "storage_total_bytes":
        with Session(files["engine"]) as session:
            budget += session.scalar(select(func.coalesce(func.sum(Document.size_bytes), 0)).where(Document.storage_deleted_at.is_(None)))
    setattr(files["config"],field,budget)
    assert upload(files).status_code==413
    assert not objects(files)


def test_db_failure_cleans_object(files,monkeypatch):
    saved = []
    original_save = LocalFileStorage.save
    def tracked_save(self, *args, **kwargs):
        result = original_save(self, *args, **kwargs)
        assert (self.root / result.key).is_file()
        saved.append(result.key)
        return result
    def broken(self): raise OperationalError("hidden",{},RuntimeError("private-db-detail"))
    with monkeypatch.context() as patch:
        patch.setattr(LocalFileStorage,"save",tracked_save)
        patch.setattr(Session,"commit",broken)
        response=upload(files)
    assert len(saved) == 1
    assert response.status_code==503 and "private-db-detail" not in response.text
    assert not objects(files)
    assert files["a"].get(files["base"]).json()["total"]==0


def test_write_failure_rolls_back(files,monkeypatch):
    def broken(*args,**kwargs): raise OSError("private-storage-path")
    with monkeypatch.context() as patch:
        patch.setattr(LocalFileStorage,"save",broken)
        response=upload(files)
    assert response.status_code==503 and "private-storage-path" not in response.text
    assert not objects(files)
    assert files["a"].get(files["base"]).json()["total"]==0


def test_failed_cleanup_keeps_tombstone_and_is_retryable(files,monkeypatch):
    record=upload(files).json()["document"]
    path=files["base"]+"/"+record["id"]
    def broken(*args): raise OSError("private-path")
    with monkeypatch.context() as patch:
        patch.setattr(LocalFileStorage,"remove",broken)
        assert write(files["a"],"DELETE",path).status_code==204
    assert files["a"].get(path+"/download").status_code==404
    assert len(objects(files))==1
    assert write(files["a"],"DELETE",path).status_code==204
    assert not objects(files)


def test_same_filename_is_allowed(files):
    first=upload(files).json()["document"]
    second=upload(files,data=TXT+b"different").json()["document"]
    assert first["id"]!=second["id"] and first["sha256"]!=second["sha256"]


def test_concurrent_read_and_delete(files):
    record=upload(files).json()["document"]
    path=files["base"]+"/"+record["id"]
    raw=files["a"].cookies.get(files["config"].session_cookie)
    def read():
        with client_for(files["config"]) as client:
            client.cookies.set(files["config"].session_cookie,raw)
            response=client.get(path+"/download")
            assert response.status_code in {200,404}
            if response.status_code==200: assert response.content==TXT
    with ThreadPoolExecutor(max_workers=2) as pool:
        future=pool.submit(read)
        assert write(files["a"],"DELETE",path).status_code==204
        future.result(timeout=10)
    assert files["b"].get(path+"/download").status_code==404
    assert files["a"].get(path+"/download").status_code==404


def test_document_schema_and_repeat_upgrade(files):
    from alembic import command
    engine=files["engine"]
    record=upload(files).json()["document"]
    with engine.begin() as connection: command.upgrade(migration_config(connection),"head")
    with engine.begin() as connection: command.check(migration_config(connection))
    inspector=inspect(engine)
    assert {f["options"]["ondelete"] for f in inspector.get_foreign_keys("documents")}=={"RESTRICT"}
    assert {i["name"] for i in inspector.get_indexes("documents")} >= {"ix_documents_kb_active","ix_documents_cleanup_pending"}
    assert files["a"].get(files["base"]+"/"+record["id"]).status_code==200


def test_chunked_body_limit_without_content_length(files):
    files["config"].upload_max_bytes=8
    boundary="bounded-request"
    body=(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="x.txt"\r\nContent-Type: text/plain\r\n\r\n'.encode()+b"x"*70000+f'\r\n--{boundary}--\r\n'.encode())
    headers={**csrf_headers(files["a"]),"Content-Type":"multipart/form-data; boundary="+boundary}
    response=files["a"].post(files["base"],content=(body[i:i+1024] for i in range(0,len(body),1024)),headers=headers)
    assert response.status_code==413
    assert not objects(files)


def test_concurrent_upload_quota_cannot_be_bypassed(files):
    from threading import Barrier
    files["config"].documents_per_kb=1
    barrier=Barrier(2)
    raw=files["a"].cookies.get(files["config"].session_cookie)
    def attempt():
        with client_for(files["config"]) as client:
            client.cookies.set(files["config"].session_cookie,raw)
            headers=csrf_headers(client)
            barrier.wait(timeout=10)
            return client.post(files["base"],files={"file":("same.txt",TXT,"text/plain")},headers=headers).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda _:attempt(),range(2)))
    assert sorted(results)==[201,409]
    assert len(objects(files))==1


def test_global_upload_slot_is_cross_connection(files):
    with files["engine"].begin() as connection:
        connection.execute(text("SELECT pg_advisory_xact_lock(174923,3101)"))
        assert upload(files).status_code==429
    assert not objects(files)


def test_delete_database_failure_never_removes_live_file(files,monkeypatch):
    record=upload(files).json()["document"]
    path=files["base"]+"/"+record["id"]
    def broken(self): raise OperationalError("hidden",{},RuntimeError("private-db-detail"))
    with monkeypatch.context() as patch:
        patch.setattr(Session,"commit",broken)
        response=write(files["a"],"DELETE",path)
    assert response.status_code==503
    assert files["a"].get(path+"/download").content==TXT
    assert len(objects(files))==1


def test_missing_or_replaced_object_is_safe(files,tmp_path):
    record=upload(files).json()["document"]
    path=files["base"]+"/"+record["id"]
    obj=objects(files)[0]
    obj.unlink()
    outside=tmp_path.resolve()/"outside"
    outside.write_bytes(TXT)
    obj.symlink_to(outside)
    response=files["a"].get(path+"/download")
    assert response.status_code==503
    assert str(outside) not in response.text
    assert write(files["a"],"DELETE",path).status_code==204
    assert outside.read_bytes()==TXT


@pytest.mark.parametrize("override",[
    {"knowledge_base_id":uuid4()}, {"uploaded_by":uuid4()},
    {"size_bytes":0}, {"sha256":"invalid"}, {"storage_key":"../../path"},
    {"status":"untrusted"}, {"mime_type":"text/html"},
])
def test_document_database_constraints(files,override):
    values={"knowledge_base_id":UUID(files["kb"]["id"]),"uploaded_by":UUID(files["actors"]["a_user"]["id"]),
            "original_filename":"x.txt","storage_key":uuid4().hex*2,"sha256":"a"*64,"mime_type":"text/plain","size_bytes":1,**override}
    with Session(files["engine"]) as session:
        with pytest.raises(IntegrityError):
            session.add(Document(**values));session.flush()
        session.rollback()


def test_upgrade_from_0003_preserves_existing_knowledge_base():
    from alembic import command
    from backend.v2.tests.support import isolated_database
    with isolated_database("0003_knowledge_bases") as (engine,_):
        with engine.begin() as connection:
            owner=connection.scalar(text("INSERT INTO users(email,password_hash) VALUES (:email,'test-only-placeholder') RETURNING id"),{"email":uuid4().hex+"@example.com"})
            kb=connection.scalar(text("INSERT INTO knowledge_bases(owner_id,name) VALUES (:owner,:name) RETURNING id"),{"owner":owner,"name":uuid4().hex})
        with engine.begin() as connection: command.upgrade(migration_config(connection),"head")
        with engine.begin() as connection:
            assert connection.scalar(text("SELECT owner_id FROM knowledge_bases WHERE id=:id"),{"id":kb})==owner
            assert connection.scalar(text("SELECT count(*) FROM documents"))==0
            command.check(migration_config(connection))


@pytest.mark.parametrize("commit_delete",[True,False])
def test_parent_delete_race_rechecks_read_authorization(files,commit_delete):
    from queue import Queue
    from time import monotonic, sleep
    from backend.v2.core.errors import AuthError
    from backend.v2.models import KnowledgeBase
    record=upload(files).json()["document"]
    worker_pid=Queue()
    def read():
        with Session(files["engine"]) as session:
            worker_pid.put(session.scalar(text("SELECT pg_backend_pid()")))
            user=session.get(User,UUID(files["actors"]["a_user"]["id"]))
            try:
                return service.get_document(session,user,UUID(files["kb"]["id"]),UUID(record["id"])).id
            except AuthError as error:
                return error.status
    with Session(files["engine"]) as deleting, ThreadPoolExecutor(max_workers=1) as pool:
        parent=deleting.scalar(select(KnowledgeBase).where(KnowledgeBase.id==UUID(files["kb"]["id"])).with_for_update())
        parent.deleted_at=deleting.scalar(select(func.clock_timestamp()))
        deleting.flush()
        future=pool.submit(read)
        try:
            pid=worker_pid.get(timeout=10)
            deadline=monotonic()+10
            with files["engine"].connect().execution_options(isolation_level="AUTOCOMMIT") as observer:
                while observer.scalar(text("SELECT wait_event_type FROM pg_stat_activity WHERE pid=:pid"),{"pid":pid})!="Lock":
                    assert monotonic()<deadline
                    sleep(0.02)
            assert not future.done()
        finally:
            if commit_delete: deleting.commit()
            else: deleting.rollback()
        result=future.result(timeout=10)
    assert result==(404 if commit_delete else UUID(record["id"]))


def test_upload_timeout_rolls_back_and_closes_parser(files):
    import asyncio
    from starlette.requests import Request
    from backend.v2.routers.documents import upload_document
    class SlowReceive:
        async def __call__(self):
            await asyncio.sleep(2)
            return {"type":"http.request","body":b"","more_body":False}
    config=files["config"].model_copy(update={"upload_timeout_seconds":1})
    class App:
        class State: settings=config
        state=State()
    request=Request({"type":"http","method":"POST","path":"/", "headers":[(b"content-type",b"multipart/form-data; boundary=timeout")],"app":App()}, receive=SlowReceive())
    from backend.v2.core.errors import AuthError
    with Session(files["engine"]) as session:
        user=session.get(User,UUID(files["actors"]["a_user"]["id"]))
        with pytest.raises(AuthError) as error:
            asyncio.run(upload_document(UUID(files["kb"]["id"]),request,user,session))
        assert error.value.status==408
        assert not session.in_transaction()
    assert not objects(files)


@pytest.mark.parametrize("field",["owner_id","uploaded_by","storage_key","knowledge_base_id","visibility","index_version"])
def test_multipart_cannot_override_server_metadata(files,field):
    response=files["a"].post(files["base"],files={"file":("x.txt",TXT,"text/plain")},data={field:str(uuid4())},headers=csrf_headers(files["a"]))
    assert response.status_code==422
    assert not objects(files)


def test_cleanup_marker_failure_is_retryable(files,monkeypatch):
    record=upload(files).json()["document"]
    path=files["base"]+"/"+record["id"]
    original_commit=Session.commit
    calls=[]
    def second_commit_fails(self):
        calls.append(1)
        if len(calls)==2: raise OperationalError("hidden",{},RuntimeError("private-db-detail"))
        return original_commit(self)
    with monkeypatch.context() as patch:
        patch.setattr(Session,"commit",second_commit_fails)
        assert write(files["a"],"DELETE",path).status_code==204
    assert len(calls)==2
    assert not objects(files)
    assert files["a"].get(path+"/download").status_code==404
    assert write(files["a"],"DELETE",path).status_code==204
    with Session(files["engine"]) as session:
        assert session.get(Document,UUID(record["id"])).storage_deleted_at is not None
