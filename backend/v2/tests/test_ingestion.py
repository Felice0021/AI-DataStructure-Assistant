from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
import os
from threading import Barrier, Event
from uuid import UUID, uuid4

from alembic import command
import pytest
from sqlalchemy import delete, func, inspect, select, text
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session, sessionmaker

from backend.v2.core.security import new_token
from backend.v2.manage import create_admin
from backend.v2.models import Document, DocumentChunk, IngestionJob, User
from backend.v2.services import ingestion_service as jobs
from backend.v2.services.chunking import TextBlock, chunk_blocks
from backend.v2.services.parser_runner import parse_source
from backend.v2.tests.document_samples import TXT, PDF, DOCX_MIME
from backend.v2.tests.ingestion_samples import text_pdf, course_docx
from backend.v2.tests.support import isolated_database
from backend.v2.tests.test_auth import client_for, csrf_headers, local_settings, post, register
from backend.v2.tests.test_database import migration_config
from backend.v2.worker import run_once

pytestmark=[pytest.mark.integration,pytest.mark.skipif(os.environ.get("DS_V2_RUN_DB_TESTS")!="1",reason="Isolated PostgreSQL tests")]


@pytest.fixture
def setup(tmp_path):
    with isolated_database() as (engine, settings):
        config=local_settings(settings,file_storage_root=tmp_path.resolve()/"objects")
        with client_for(config) as client:
            credentials,user=register(client)
            assert post(client,"login",credentials).status_code==200
            result=client.post("/api/v2/knowledge-bases",json={"name":uuid4().hex},headers=csrf_headers(client))
            assert result.status_code==201
            kb=result.json()["knowledge_base"]
            yield {"engine":engine,"factory":sessionmaker(engine,expire_on_commit=False),"settings":config,"client":client,"user":user,
                   "kb":kb,"base":"/api/v2/knowledge-bases/"+kb["id"]+"/documents"}


def upload(setup,name="source.txt",data=TXT,mime="text/plain"):
    response=setup["client"].post(setup["base"],files={"file":(name,data,mime)},headers=csrf_headers(setup["client"]))
    assert response.status_code==201
    return response.json()["document"]


def claim(setup):
    with setup["factory"]() as session:return jobs.claim_next(session,setup["settings"])


def expire(setup):
    with setup["engine"].begin() as connection:
        connection.execute(text("UPDATE ingestion_jobs SET lease_expires_at=clock_timestamp()-interval '1 second' WHERE status='running'"))


def state(setup):
    with setup["factory"]() as session:
        return session.scalar(select(Document)),session.scalar(select(IngestionJob)),session.scalars(select(DocumentChunk).order_by(DocumentChunk.chunk_index)).all()


def test_upload_job_atomic_and_safe_api(setup):
    record=upload(setup)
    path=setup["base"]+"/"+record["id"]
    response=setup["client"].get(path+"/ingestion")
    assert response.status_code==200
    job=response.json()["job"]
    assert job["status"]=="queued" and job["attempts"]==0
    assert not {"lease_token","lease_expires_at","requested_by"}&job.keys()
    assert setup["client"].get(path+"/chunks").json()["items"]==[]
    for _ in range(2):
        assert setup["client"].post(path+"/ingestion",json={},headers=csrf_headers(setup["client"])).json()["job"]["id"]==job["id"]
    with setup["factory"]() as session:assert session.scalar(select(func.count()).select_from(IngestionJob))==1


@pytest.mark.parametrize("name,data,mime,expected",[("x.txt",b"\xef\xbb\xbf"+TXT,"text/plain","数据结构"),("x.pdf",text_pdf(),"application/pdf","Course Alpha"),("x.docx",course_docx(),DOCX_MIME,"课程标题")])
def test_worker_actual_parse_and_chunks(setup,name,data,mime,expected):
    record=upload(setup,name,data,mime)
    assert run_once(setup["factory"],setup["settings"])
    document,job,chunks=state(setup)
    assert document.status=="parsed" and document.parsed_version==document.ingestion_version==1
    assert job.status=="succeeded" and job.attempts==1
    assert expected in "\n".join(c.content for c in chunks)
    assert [c.chunk_index for c in chunks]==list(range(len(chunks)))
    assert {c.generation for c in chunks}=={1}
    if mime=="application/pdf":assert {c.page_number for c in chunks}=={1,2}
    assert setup["client"].get(setup["base"]+"/"+record["id"]+"/chunks").json()["total"]==len(chunks)
    assert not run_once(setup["factory"],setup["settings"])


def test_two_workers_claim_only_one(setup):
    upload(setup)
    barrier=Barrier(2)
    def attempt():
        barrier.wait(timeout=10)
        return claim(setup)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda _:attempt(),range(2)))
    assert sum(result is not None for result in results)==1
    assert state(setup)[1].attempts==1


def test_expired_claim_is_fenced_and_reclaimed(setup):
    upload(setup)
    old=claim(setup);expire(setup);current=claim(setup)
    assert old.token!=current.token
    chunks=chunk_blocks([TextBlock("course text")])
    with setup["factory"]() as session:assert not jobs.complete(session,old,chunks,setup["settings"])
    with setup["factory"]() as session:assert jobs.complete(session,current,chunks,setup["settings"])
    with setup["factory"]() as session:assert not jobs.complete(session,current,chunks,setup["settings"])
    assert state(setup)[1].attempts==2 and len(state(setup)[2])==1


def test_expired_max_attempts_is_terminal(setup):
    setup["settings"].ingestion_max_attempts=1
    upload(setup);claim(setup);expire(setup)
    assert claim(setup) is None
    document,job,chunks=state(setup)
    assert document.status=="failed" and job.error_code=="attempts_exhausted" and not chunks
    assert claim(setup) is None


@pytest.mark.parametrize("target",["document","knowledge_base"])
def test_delete_during_parse_prohibits_publish(setup,target):
    record=upload(setup);current=claim(setup)
    with setup["factory"]() as session:source=jobs.open_claim_source(session,current,setup["settings"])
    path=setup["base"]+"/"+record["id"] if target=="document" else "/api/v2/knowledge-bases/"+setup["kb"]["id"]
    assert setup["client"].delete(path,headers=csrf_headers(setup["client"])).status_code==204
    with source:chunks=parse_source(source,current,setup["settings"])
    with setup["factory"]() as session:assert not jobs.complete(session,current,chunks,setup["settings"])
    assert state(setup)[1].status=="cancelled" and not state(setup)[2]


def test_retry_backoff_and_bounded_attempts(setup):
    upload(setup);current=claim(setup)
    with setup["factory"]() as session:assert jobs.fail(session,current,"storage_unavailable",True,setup["settings"])
    assert claim(setup) is None
    with setup["engine"].begin() as connection:connection.execute(text("UPDATE ingestion_jobs SET next_retry_at=clock_timestamp()-interval '1 second'"))
    assert claim(setup).token!=current.token
    assert state(setup)[1].attempts==2


@pytest.mark.parametrize("data,expected",[(PDF,"no_text"),(b"%PDF-1.7\nnot-a-pdf\n%%EOF\n","invalid_format")])
def test_permanent_parse_failures_do_not_auto_retry(setup,data,expected):
    record=upload(setup,"x.pdf",data,"application/pdf")
    run_once(setup["factory"],setup["settings"])
    document,job,chunks=state(setup)
    assert document.status=="failed" and job.status=="failed" and job.error_code==expected
    assert not chunks and not run_once(setup["factory"],setup["settings"])
    response=setup["client"].post(setup["base"]+"/"+record["id"]+"/ingestion",json={},headers=csrf_headers(setup["client"]))
    assert response.status_code==202 and response.json()["job"]["generation"]==2


def test_reprocess_never_mixes_chunk_generations(setup):
    record=upload(setup);run_once(setup["factory"],setup["settings"])
    old_ids={c.id for c in state(setup)[2]}
    path=setup["base"]+"/"+record["id"]
    assert setup["client"].post(path+"/ingestion",json={},headers=csrf_headers(setup["client"])).status_code==409
    assert setup["client"].post(path+"/ingestion",json={"reprocess":True},headers=csrf_headers(setup["client"])).status_code==202
    assert setup["client"].get(path+"/chunks").json()["items"]==[]
    run_once(setup["factory"],setup["settings"])
    document,job,chunks=state(setup)
    assert document.parsed_version==job.generation==2
    assert {c.generation for c in chunks}=={2} and not old_ids&{c.id for c in chunks}
    with setup["factory"]() as session:
        sample=chunks[0]
        with pytest.raises(IntegrityError):
            session.add(DocumentChunk(document_id=document.id,generation=2,chunk_index=sample.chunk_index,content="duplicate",content_hash="a"*64));session.flush()


def test_missing_job_reconciliation(setup):
    upload(setup)
    with setup["engine"].begin() as connection:connection.execute(delete(IngestionJob))
    assert run_once(setup["factory"],setup["settings"])
    assert state(setup)[0].status=="parsed"


def test_database_failure_rolls_back_chunks_then_recovers(setup,monkeypatch):
    upload(setup);current=claim(setup)
    chunks=chunk_blocks([TextBlock("course content")])
    def broken(self):raise OperationalError("hidden",{},RuntimeError("private-detail"))
    with monkeypatch.context() as patch:
        patch.setattr(Session,"commit",broken)
        with setup["factory"]() as session:
            with pytest.raises(OperationalError):jobs.complete(session,current,chunks,setup["settings"])
    assert not state(setup)[2] and state(setup)[1].status=="running"
    expire(setup)
    run_once(setup["factory"],setup["settings"])
    assert state(setup)[0].status=="parsed"


def test_worker_shutdown_requeues_safely(setup):
    upload(setup)
    stop=Event();stop.set()
    run_once(setup["factory"],setup["settings"],stop)
    document,job,chunks=state(setup)
    assert job.status=="queued" and job.error_code=="worker_stopped" and not chunks
    assert document.status=="uploaded"


@pytest.mark.parametrize("role",["student","admin"])
def test_private_jobs_and_chunks_never_exposed(setup,role):
    record=upload(setup);run_once(setup["factory"],setup["settings"])
    with client_for(setup["settings"]) as outsider:
        if role=="student":credentials,_=register(outsider)
        else:
            credentials={"email":uuid4().hex+"@example.com","password":new_token()};create_admin(**credentials,settings=setup["settings"])
        assert post(outsider,"login",credentials).status_code==200
        path=setup["base"]+"/"+record["id"]
        for suffix in ("/ingestion","/chunks"):
            response=outsider.get(path+suffix)
            assert response.status_code==404 and "content" not in response.text
        assert outsider.post(path+"/ingestion",json={},headers=csrf_headers(outsider)).status_code==404


def test_processing_csrf_and_tampered_fields(setup):
    record=upload(setup);path=setup["base"]+"/"+record["id"]+"/ingestion"
    assert setup["client"].post(path,json={}).status_code==403
    assert setup["client"].post(path,json={"requested_by":str(uuid4())},headers=csrf_headers(setup["client"])).status_code==422


def test_worker_rechecks_requested_user_activation(setup):
    upload(setup)
    with setup["engine"].begin() as connection:connection.execute(text("UPDATE users SET is_active=false"))
    assert claim(setup) is None
    assert state(setup)[1].status=="cancelled"


@pytest.mark.parametrize("field,value,error",[("parse_max_text_chars",2,"text_limit"),("parse_max_chunks",1,"chunk_limit"),("parse_timeout_seconds",0.01,"parse_timeout")])
def test_real_file_processing_limits(setup,field,value,error):
    setattr(setup["settings"],field,value)
    setup["settings"].chunk_size=32;setup["settings"].chunk_overlap=4
    upload(setup,data=("课程资料"*30).encode())
    run_once(setup["factory"],setup["settings"])
    assert state(setup)[1].error_code==error and not state(setup)[2]


def test_migration_check_and_constraints(setup):
    with setup["engine"].begin() as connection:command.check(migration_config(connection))
    inspector=inspect(setup["engine"])
    assert {"document_chunks","ingestion_jobs"}<=set(inspector.get_table_names())
    assert inspector.get_foreign_keys("document_chunks")[0]["options"]["ondelete"]=="RESTRICT"


def test_storage_content_hash_is_rechecked(setup):
    upload(setup)
    root=setup["settings"].file_storage_root
    object_path=next(root.iterdir())
    original=object_path.read_bytes()
    object_path.write_bytes(b"x"*len(original))
    run_once(setup["factory"],setup["settings"])
    assert state(setup)[1].error_code=="content_changed" and not state(setup)[2]


def test_corrupt_docx_body_is_permanent_failure(setup):
    from backend.v2.tests.document_samples import docx
    from zipfile import ZipFile
    source=BytesIO(docx())
    with ZipFile(source) as archive:entries={name:archive.read(name) for name in archive.namelist()}
    entries["word/document.xml"]=b"<broken XML"
    upload(setup,"broken.docx",docx(entries),DOCX_MIME)
    run_once(setup["factory"],setup["settings"])
    assert state(setup)[1].error_code=="invalid_format" and not state(setup)[2]


def test_pdf_page_limit_worker(setup):
    setup["settings"].parse_max_pages=1
    upload(setup,"pages.pdf",text_pdf(),"application/pdf")
    run_once(setup["factory"],setup["settings"])
    assert state(setup)[1].error_code=="page_limit" and not state(setup)[2]


def test_lease_expiration_prohibits_commit_before_reclaim(setup):
    upload(setup);current=claim(setup);expire(setup)
    with setup["factory"]() as session:assert not jobs.complete(session,current,chunk_blocks([TextBlock("late result")]),setup["settings"])
    assert not state(setup)[2]


def test_public_job_authority_and_role_change(setup):
    with client_for(setup["settings"]) as admin:
        credentials={"email":uuid4().hex+"@example.com","password":new_token()}
        create_admin(**credentials,settings=setup["settings"])
        assert post(admin,"login",credentials).status_code==200
        kb=admin.post("/api/v2/admin/knowledge-bases",json={"name":uuid4().hex},headers=csrf_headers(admin)).json()["knowledge_base"]
        base="/api/v2/knowledge-bases/"+kb["id"]+"/documents"
        record=admin.post(base,files={"file":("x.txt",TXT,"text/plain")},headers=csrf_headers(admin)).json()["document"]
        path=base+"/"+record["id"]
        assert setup["client"].get(path+"/ingestion").status_code==200
        assert setup["client"].post(path+"/ingestion",json={},headers=csrf_headers(setup["client"])).status_code==403
        current=claim(setup)
        with setup["engine"].begin() as connection:connection.execute(text("UPDATE users SET role='student' WHERE email=:email"),{"email":credentials["email"]})
        with setup["factory"]() as session:assert not jobs.complete(session,current,chunk_blocks([TextBlock("cancelled")]),setup["settings"])
        with setup["factory"]() as session:
            job=session.scalar(select(IngestionJob))
            assert job.status=="cancelled"
            assert session.get(Document,job.document_id).status=="failed"


def test_job_insert_failure_rolls_back_upload_and_cleans_object(setup,monkeypatch):
    from sqlalchemy import event
    def fail_insert(*_):raise OperationalError("hidden",{},RuntimeError("test-only-failure"))
    event.listen(IngestionJob,"before_insert",fail_insert)
    try:
        response=setup["client"].post(setup["base"],files={"file":("x.txt",TXT,"text/plain")},headers=csrf_headers(setup["client"]))
        assert response.status_code==503
    finally:event.remove(IngestionJob,"before_insert",fail_insert)
    with setup["factory"]() as session:
        assert session.scalar(select(func.count()).select_from(Document))==0
        assert session.scalar(select(func.count()).select_from(IngestionJob))==0
    assert not list(setup["settings"].file_storage_root.iterdir())


def test_upgrade_from_0004_reconciles_existing_file(tmp_path):
    from backend.v2.services.file_storage import LocalFileStorage
    settings=None
    with isolated_database("0004_documents") as (engine,settings):
        config=local_settings(settings,file_storage_root=tmp_path.resolve()/"legacy")
        storage=LocalFileStorage(config.file_storage_root)
        saved=storage.save(BytesIO(TXT),10000,"legacy.txt","text/plain")
        with engine.begin() as connection:
            owner=connection.scalar(text("INSERT INTO users(email,password_hash) VALUES (:email,'test-only-placeholder') RETURNING id"),{"email":uuid4().hex+"@example.com"})
            kb=connection.scalar(text("INSERT INTO knowledge_bases(owner_id,name) VALUES (:owner,'legacy') RETURNING id"),{"owner":owner})
            document=connection.scalar(text("INSERT INTO documents(knowledge_base_id,uploaded_by,original_filename,storage_key,mime_type,size_bytes,sha256) VALUES (:kb,:owner,'legacy.txt',:key,'text/plain',:size,:sha) RETURNING id"),{"kb":kb,"owner":owner,"key":saved.key,"size":saved.size,"sha":saved.sha256})
        with engine.begin() as connection:command.upgrade(migration_config(connection),"head")
        factory=sessionmaker(engine,expire_on_commit=False)
        assert run_once(factory,config)
        with factory() as session:
            assert session.get(Document,document).status=="parsed"
            assert session.scalar(select(func.count()).select_from(IngestionJob))==1
        with engine.begin() as connection:command.upgrade(migration_config(connection),"head");command.check(migration_config(connection))


def test_docx_external_entity_is_rejected_before_library_parse(setup):
    from backend.v2.tests.document_samples import docx
    from zipfile import ZipFile
    with ZipFile(BytesIO(docx())) as archive:entries={name:archive.read(name) for name in archive.namelist()}
    entries["word/document.xml"]=b'<!DOCTYPE document [<!ENTITY external SYSTEM "http://127.0.0.1:9/not-fetched">]><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>&external;</w:t></w:r></w:p></w:body></w:document>'
    upload(setup,"unsafe.docx",docx(entries),DOCX_MIME)
    run_once(setup["factory"],setup["settings"])
    assert state(setup)[1].error_code=="unsafe_xml" and not state(setup)[2]
