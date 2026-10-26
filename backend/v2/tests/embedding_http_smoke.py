"""Real indexing workers/pgvector; deterministic provider only, never cloud."""
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import tempfile
import time
from uuid import UUID,uuid4

from sqlalchemy import func,select,text
from sqlalchemy.orm import Session,sessionmaker
from backend.v2.core.config import REPOSITORY_ROOT
from backend.v2.core.security import new_token
from backend.v2.manage import create_admin
from backend.v2.models import ChunkEmbedding,Document,EmbeddingJob,User
from backend.v2.services.vector_search import embed_query,exact_search
from backend.v2.tests.documents_http_smoke import multipart
from backend.v2.tests.http_smoke import Client,ORIGIN,running_server
from backend.v2.tests.ingestion_http_smoke import stop_worker
from backend.v2.tests.ingestion_samples import text_pdf,course_docx
from backend.v2.tests.document_samples import DOCX_MIME
from backend.v2.tests.support import isolated_database


def launch(module,env,logs):return subprocess.Popen([sys.executable,'-m',module],cwd=REPOSITORY_ROOT,env=env,stdout=logs,stderr=logs)


def main():
    with socket.socket() as probe:
        probe.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1);probe.bind(('127.0.0.1',8001))
    with isolated_database() as (engine,settings),tempfile.TemporaryDirectory(prefix='ds-vector-http-') as directory,tempfile.TemporaryFile() as logs:
        root=Path(directory).resolve();(root/'temp').mkdir(mode=0o700)
        config=settings.model_copy(update={'environment':'development','embedding_provider':'deterministic','embedding_allow_test_provider':True,
            'embedding_batch_size':1,'embedding_timeout_seconds':0.2,'embedding_lease_seconds':20})
        env=os.environ.copy();env.update({'DS_V2_DB_NAME':settings.db_name,'DS_V2_DB_HOST':settings.db_host,'DS_V2_DB_PORT':str(settings.db_port),
            'DS_V2_DB_USER':settings.db_user,'DS_V2_DB_PASSWORD':settings.db_password.get_secret_value(),'DS_V2_ENVIRONMENT':'development',
            'DS_V2_ALLOW_INSECURE_LOOPBACK':'true','DS_V2_ALLOWED_ORIGINS':json.dumps([ORIGIN]),'DS_V2_FILE_STORAGE_ROOT':str(root/'objects'),
            'DS_V2_EMBEDDING_PROVIDER':'deterministic','DS_V2_EMBEDDING_ALLOW_TEST_PROVIDER':'true','DS_V2_EMBEDDING_CLOUD_ENABLED':'false',
            'DS_V2_EMBEDDING_BATCH_SIZE':'1','DS_V2_EMBEDDING_TIMEOUT_SECONDS':'0.2','DS_V2_EMBEDDING_LEASE_SECONDS':'20',
            'DS_V2_WORKER_POLL_SECONDS':'0.1','TMPDIR':str(root/'temp')})
        with running_server(env,logs):
            a,b,admin=Client(),Client(),Client();users=[];kbs=[]
            for client in (a,b):
                credentials={'email':uuid4().hex+'@example.com','password':new_token()}
                code,response=client.call('POST','/api/v2/auth/register',credentials);assert code==201;users.append(response['user']['id'])
                assert client.call('POST','/api/v2/auth/login',credentials)[0]==200
                code,response=client.call('POST','/api/v2/knowledge-bases',{'name':uuid4().hex});assert code==201;kbs.append(response['knowledge_base']['id'])
            ac={'email':uuid4().hex+'@example.com','password':new_token()};create_admin(**ac,settings=settings)
            assert admin.call('POST','/api/v2/auth/login',ac)[0]==200
            code,response=admin.call('POST','/api/v2/admin/knowledge-bases',{'name':uuid4().hex});assert code==201
            public=response['knowledge_base']['id']
            dataset=[(a,kbs[0],'many.txt','\n'.join(f'# 章节{i}\n合成课程算法复杂度 O(n)。' for i in range(30)).encode(),'text/plain'),
                     (a,kbs[0],'course.pdf',text_pdf(),'application/pdf'),(a,kbs[0],'course.docx',course_docx(),DOCX_MIME),
                     (b,kbs[1],'private.txt','另一学生合成课程'.encode(),'text/plain'),(admin,public,'public.txt','公共合成课程'.encode(),'text/plain')]
            docs=[]
            for client,kb,name,data,mime in dataset:
                base='/api/v2/knowledge-bases/'+kb+'/documents'
                code,response=multipart(client,base,name,data,mime);assert code==201
                docs.append((client,kb,response['document']['id']))
            parser=launch('backend.v2.worker',env,logs)
            try:
                deadline=time.monotonic()+15
                while True:
                    states=[client.call('GET','/api/v2/knowledge-bases/'+kb+'/documents/'+doc)[1]['document']['status'] for client,kb,doc in docs]
                    if all(x=='parsed' for x in states):break
                    assert time.monotonic()<deadline,'Parsing did not reach parsed'
                    time.sleep(0.1)
            finally:stop_worker(parser)
            # Crash only our own worker after a committed cached batch, then wait for real expiry.
            crashed=launch('backend.v2.embedding_worker',env,logs)
            try:
                deadline=time.monotonic()+15
                while True:
                    with Session(engine) as s:
                        job=s.scalar(select(EmbeddingJob).where(EmbeddingJob.document_id==UUID(docs[0][2])))
                        cached=s.scalar(select(func.count()).select_from(ChunkEmbedding).where(ChunkEmbedding.document_id==job.document_id))
                        running=job.status=='running'
                    if cached>0 and running:break
                    assert time.monotonic()<deadline and crashed.poll() is None,'Failed to observe cached in-flight batch'
                    time.sleep(0.005)
                crashed.kill();crashed.wait(timeout=5)
            finally:stop_worker(crashed)
            workers=[launch('backend.v2.embedding_worker',env,logs),launch('backend.v2.embedding_worker',env,logs)]
            try:
                deadline=time.monotonic()+45
                while True:
                    with Session(engine) as s:states=s.scalars(select(Document.status)).all()
                    assert 'index_failed' not in states,'Indexing failed'
                    if all(x=='ready' for x in states):break
                    assert time.monotonic()<deadline and all(w.poll() is None for w in workers),'Indexing recovery timed out'
                    time.sleep(0.1)
                factory=sessionmaker(engine,expire_on_commit=False)
                with factory() as s:
                    assert s.scalar(text('SELECT min(vector_dims(embedding)) FROM chunk_embeddings'))==1024
                    actors=[s.get(User,UUID(uid)) for uid in users]
                    actor_admin=s.scalar(select(User).where(User.email==ac['email']))
                for actor,kb in zip(actors,kbs):
                    q=embed_query(factory,actor,[UUID(kb),UUID(public)],'合成课程',config)
                    with factory() as s:hits=exact_search(s,actor,[UUID(kb),UUID(public)],q,config,top_k=100)
                    assert {h['knowledge_base_id'] for h in hits}=={UUID(kb),UUID(public)}
                    assert all(-1.001<=h['similarity']<=1.001 for h in hits)
                    if kb==kbs[0]:assert {h['page_number'] for h in hits if str(h['document_id'])==docs[1][2]}=={1,2}
                with factory() as s:
                    q=embed_query(factory,actor_admin,[UUID(public)],'合成课程',config)
                    assert {h['knowledge_base_id'] for h in exact_search(s,actor_admin,[UUID(public)],q,config)}=={UUID(public)}
                    recovered=s.scalar(select(EmbeddingJob).where(EmbeddingJob.document_id==UUID(docs[0][2])))
                    assert recovered.attempts==2 and recovered.api_calls<=recovered.expected_chunks+1
                path='/api/v2/knowledge-bases/'+kbs[0]+'/documents/'+docs[0][2]+'/embedding'
                assert b.call('GET',path)[0]==404 and admin.call('GET',path)[0]==404
                assert b.call('POST',path,{})[0]==404 and a.call('POST',path,{},csrf=False)[0]==403
                print('Real standalone workers: parsed/indexing/ready, 1024-dimensional pgvector exact search PASS')
                print('Real SIGKILL + lease expiry: partial cache reused, single ready publication PASS')
                print('Two authenticated students + admin: private/public vector scopes and HTTP permissions PASS')
            finally:
                for process in workers:stop_worker(process)
        print('Deterministic test provider only; no cloud calls; temporary DB/API/workers/storage cleaned')


if __name__=='__main__':main()
