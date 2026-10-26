"""Real HTTP + standalone workers + SIGKILL/real lease expiry, all disposable."""
import hashlib
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import tempfile
import time
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.v2.core.config import REPOSITORY_ROOT
from backend.v2.core.security import new_token
from backend.v2.models import Document, DocumentChunk, IngestionJob
from backend.v2.tests.document_samples import DOCX_MIME
from backend.v2.tests.documents_http_smoke import multipart
from backend.v2.tests.http_smoke import ORIGIN, Client, running_server
from backend.v2.tests.ingestion_samples import text_pdf, course_docx
from backend.v2.tests.support import isolated_database


def worker(env, logs):
    return subprocess.Popen([sys.executable,"-m","backend.v2.worker"],cwd=REPOSITORY_ROOT,env=env,stdout=logs,stderr=logs)


def stop_worker(process):
    if process.poll() is None:
        process.send_signal(signal.SIGTERM)
        try: process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill();process.wait(timeout=5)
            raise RuntimeError("Worker graceful shutdown failed")


def main():
    with socket.socket() as probe:
        probe.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
        probe.bind(("127.0.0.1",8001))
    with isolated_database() as (engine,settings), tempfile.TemporaryDirectory(prefix="ds-v2-ingestion-http-") as directory, tempfile.TemporaryFile() as logs:
        parser_temp = Path(directory).resolve() / "parser-temp"
        parser_temp.mkdir(mode=0o700)
        env=os.environ.copy()
        env["TMPDIR"] = str(parser_temp)
        env.update({"DS_V2_DB_NAME":settings.db_name,"DS_V2_DB_HOST":settings.db_host,"DS_V2_DB_PORT":str(settings.db_port),
                    "DS_V2_DB_USER":settings.db_user,"DS_V2_DB_PASSWORD":settings.db_password.get_secret_value(),
                    "DS_V2_ENVIRONMENT":"development","DS_V2_ALLOW_INSECURE_LOOPBACK":"true","DS_V2_ALLOWED_ORIGINS":json.dumps([ORIGIN]),
                    "DS_V2_FILE_STORAGE_ROOT":str(Path(directory).resolve()/"objects"),"DS_V2_PARSE_TIMEOUT_SECONDS":"1",
                    "DS_V2_INGESTION_LEASE_SECONDS":"20","DS_V2_WORKER_POLL_SECONDS":"0.1"})
        with running_server(env,logs):
            first,second=Client(),Client()
            for client in (first,second):
                credentials={"email":uuid4().hex+"@example.com","password":new_token()}
                assert client.call("POST","/api/v2/auth/register",credentials)[0]==201
                assert client.call("POST","/api/v2/auth/login",credentials)[0]==200
            status,kb=first.call("POST","/api/v2/knowledge-bases",{"name":uuid4().hex})
            assert status==201
            base="/api/v2/knowledge-bases/"+kb["knowledge_base"]["id"]+"/documents"
            txt=("# 课程章节\n\n链表与算法复杂度 O(n)\n\n```python\nprint(1)\n```\n"*10).encode()
            status,data=multipart(first,base,"course.txt",txt,"text/plain")
            assert status==201
            first_id=data["document"]["id"]
            crashed=worker(env,logs)
            try:
                deadline=time.monotonic()+10
                while True:
                    with Session(engine) as session:
                        job=session.scalar(select(IngestionJob).where(IngestionJob.document_id==UUID(first_id)))
                        status=job.status
                    if status=="running":break
                    assert time.monotonic()<deadline,"Worker never acquired test job"
                    assert crashed.poll() is None,"Worker exited before claim"
                    time.sleep(0.01)
                crashed.kill();crashed.wait(timeout=5)
            finally:
                stop_worker(crashed)
            # Do not alter lease timestamps: wait for the actual 20-second database lease.
            workers=[worker(env,logs),worker(env,logs)]
            try:
                records=[(first_id,"链表",None)]
                for name,raw,mime,expected in [("course.pdf",text_pdf(),"application/pdf","Course Alpha"),("course.docx",course_docx(),DOCX_MIME,"课程标题")]:
                    status,data=multipart(first,base,name,raw,mime)
                    assert status==201
                    records.append((data["document"]["id"],expected,2 if mime=="application/pdf" else None))
                deadline=time.monotonic()+40
                while True:
                    states=[first.call("GET",base+"/"+doc_id)[1]["document"]["status"] for doc_id,_,_ in records]
                    assert "failed" not in states,"A real document failed parsing"
                    if all(state=="parsed" for state in states):break
                    assert time.monotonic()<deadline,"Worker completion/lease recovery timed out"
                    assert all(p.poll() is None for p in workers),"Worker exited unexpectedly"
                    time.sleep(0.15)
                with Session(engine) as session:
                    for doc_id,expected,pages in records:
                        document=session.get(Document,UUID(doc_id))
                        job=session.scalar(select(IngestionJob).where(IngestionJob.document_id==document.id))
                        chunks=session.scalars(select(DocumentChunk).where(DocumentChunk.document_id==document.id).order_by(DocumentChunk.chunk_index)).all()
                        assert document.status=="parsed" and document.parsed_version==job.generation
                        assert job.status=="succeeded" and chunks
                        assert expected in "\n".join(c.content for c in chunks)
                        assert [c.chunk_index for c in chunks]==list(range(len(chunks)))
                        assert all(c.content_hash==hashlib.sha256(c.content.encode()).hexdigest() for c in chunks)
                        if pages:assert {c.page_number for c in chunks}==set(range(1,pages+1))
                        if doc_id==first_id:assert job.attempts==2
                for doc_id,_,_ in records:
                    path=base+"/"+doc_id
                    assert first.call("GET",path+"/chunks")[1]["total"]>0
                    for suffix in ("/ingestion","/chunks"):
                        assert second.call("GET",path+suffix)[0]==404
                    assert second.call("POST",path+"/ingestion",{})[0]==404
                    assert first.call("POST",path+"/ingestion",{},csrf=False)[0]==403
                print("Real HTTP + two standalone workers: PDF/DOCX/TXT parsed; DB content/order/hash/page checks PASS")
                print("Real SIGKILL + actual 20-second lease expiry recovery; fenced single result PASS")
                print("Real HTTP: independent users cannot read/retry private jobs or chunks; CSRF PASS")
            finally:
                for process in workers:stop_worker(process)
        print("Temporary workers/API/database/storage cleaned; development database unchanged")


if __name__=="__main__":main()
