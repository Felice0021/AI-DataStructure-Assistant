"""Real two-process HTTP/Worker/PostgreSQL checks; synthetic data, no cloud calls."""
import json
import os
from pathlib import Path
import socket
import tempfile
import time
from uuid import UUID, uuid4
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from backend.v2.core.security import new_token
from backend.v2.manage import create_admin
from backend.v2.models import Document
from backend.v2.tests.documents_http_smoke import multipart
from backend.v2.tests.embedding_http_smoke import launch
from backend.v2.tests.ingestion_http_smoke import stop_worker
from backend.v2.tests.http_smoke import Client, ORIGIN, running_server
from backend.v2.tests.support import isolated_database


def main():
    with socket.socket() as probe:probe.bind(('127.0.0.1',8001))
    with isolated_database() as (engine,settings), tempfile.TemporaryDirectory(prefix='ds-retrieval-http-') as directory, tempfile.TemporaryFile() as logs:
        root=Path(directory).resolve();(root/'temp').mkdir(mode=0o700)
        env=os.environ.copy();env.update({
            'DS_V2_DB_NAME':settings.db_name,'DS_V2_DB_HOST':settings.db_host,'DS_V2_DB_PORT':str(settings.db_port),
            'DS_V2_DB_USER':settings.db_user,'DS_V2_DB_PASSWORD':settings.db_password.get_secret_value(),
            'DS_V2_ENVIRONMENT':'development','DS_V2_ALLOW_INSECURE_LOOPBACK':'true','DS_V2_ALLOWED_ORIGINS':json.dumps([ORIGIN]),
            'DS_V2_FILE_STORAGE_ROOT':str(root/'objects'),'TMPDIR':str(root/'temp'),
            'DS_V2_EMBEDDING_PROVIDER':'deterministic','DS_V2_EMBEDDING_ALLOW_TEST_PROVIDER':'true',
            'DS_V2_EMBEDDING_CLOUD_ENABLED':'false','DS_V2_WORKER_POLL_SECONDS':'.1'})
        with running_server(env,logs):
            a,b,admin=Client(),Client(),Client();uids=[];kbs=[]
            for client in (a,b):
                credentials={'email':uuid4().hex+'@example.com','password':new_token()}
                code,result=client.call('POST','/api/v2/auth/register',credentials);assert code==201;uids.append(result['user']['id'])
                assert client.call('POST','/api/v2/auth/login',credentials)[0]==200
                code,result=client.call('POST','/api/v2/knowledge-bases',{'name':uuid4().hex});assert code==201;kbs.append(result['knowledge_base']['id'])
            credentials={'email':uuid4().hex+'@example.com','password':new_token()};create_admin(**credentials,settings=settings)
            assert admin.call('POST','/api/v2/auth/login',credentials)[0]==200
            code,result=admin.call('POST','/api/v2/admin/knowledge-bases',{'name':uuid4().hex});assert code==201;public=result['knowledge_base']['id']
            docs=[]
            for client,kb,content in [(a,kbs[0],'# AVL\nAVL 红黑树 insert_node 二叉树。\n\n# 图\nDijkstra 最短路径算法。'),
                                      (b,kbs[1],'# 私人合成\nAVL 独立课程 private_b_marker。'),
                                      (admin,public,'# 公共合成\nAVL 红黑树 公共数据结构。')]:
                base='/api/v2/knowledge-bases/'+kb+'/documents'
                code,result=multipart(client,base,'synthetic.txt',content.encode(),'text/plain');assert code==201
                docs.append((client,kb,result['document']['id']))
            workers=[launch('backend.v2.worker',env,logs),launch('backend.v2.embedding_worker',env,logs)]
            try:
                deadline=time.monotonic()+20
                while True:
                    with Session(engine) as session:states=session.scalars(select(Document.status)).all()
                    if all(s=='ready' for s in states):break
                    assert time.monotonic()<deadline and all(p.poll() is None for p in workers),'Worker readiness failed'
                    time.sleep(.1)
            finally:
                for process in workers:stop_worker(process)
            def query(client,scope,mode='hybrid',**kw):
                return client.call('POST','/api/v2/retrieval/search',{'query':'AVL 红黑树','knowledge_base_ids':scope,'mode':mode,'top_k':10,**kw})
            evidence={}
            for mode in ('bm25','dense','hybrid'):
                code,result=query(a,[kbs[0],public],mode);assert code==200 and result['actual_mode']==mode
                assert result['results'] and all(r['knowledge_base_id'] in [kbs[0],public] for r in result['results'])
                assert len({r['chunk_id'] for r in result['results']})==len(result['results'])
                if mode=='hybrid':
                    for r in result['results']:
                        expected=sum(1/(60+r[key]) for key in ('dense_rank','bm25_rank') if r[key] is not None)
                        assert abs(r['fused_score']-expected)<1e-12
                evidence[mode]=[{k:r[k] for k in ('fused_score','dense_score','bm25_score','dense_rank','bm25_rank')} for r in result['results']]
                again=query(a,[kbs[0],public],mode)[1];assert again['results']==result['results']
                assert query(b,[kbs[1],public],mode)[0]==200
                assert query(admin,[public],mode)[0]==200
                for intruder in (b,admin):assert query(intruder,[public,kbs[0]],mode)[0]==404
                assert query(a,[kbs[1]],mode)[0]==404
            assert query(a,[kbs[0]],query='private_b_marker',mode='bm25')[1]['results']==[]
            assert a.call('POST','/api/v2/retrieval/search',{'query':'AVL','knowledge_base_ids':[kbs[0]]},csrf=False)[0]==403
            # Compare real PG cosine ranking to the HTTP Dense diagnostics.
            from backend.v2.services.embedding_provider import DeterministicProvider
            local=settings.model_copy(update={'environment':'development','embedding_provider':'deterministic','embedding_allow_test_provider':True})
            vector=DeterministicProvider(local).embed(['AVL 红黑树'],text_type='query',before_attempt=lambda:None)[0]
            with engine.connect() as c:
                values=c.execute(text('SELECT 1-(e.embedding <=> CAST(:v AS vector)) AS score FROM chunk_embeddings e JOIN documents d ON d.id=e.document_id WHERE d.knowledge_base_id IN (:a,:p) ORDER BY e.embedding <=> CAST(:v AS vector),e.chunk_id'),{'v':str(vector),'a':UUID(kbs[0]),'p':UUID(public)}).scalars().all()
                assert all(abs(x['dense_score']-y)<1e-7 for x,y in zip(evidence['dense'],values))
            # Public file deletion and reparse instantly remove old-generation hits.
            public_path='/api/v2/knowledge-bases/'+public+'/documents/'+docs[2][2]
            assert admin.call('DELETE',public_path)[0]==204
            for mode in ('bm25','dense','hybrid'):assert query(a,[public],mode)[1]['results']==[]
            path='/api/v2/knowledge-bases/'+kbs[0]+'/documents/'+docs[0][2]
            assert a.call('POST',path+'/ingestion',{'reprocess':True})[0]==202
            for mode in ('bm25','dense','hybrid'):assert query(a,[kbs[0]],mode)[1]['results']==[]
            # Permission change/deactivation are committed in the isolated database only.
            with engine.begin() as c:c.execute(text('UPDATE knowledge_bases SET owner_id=:b WHERE id=:a'),{'a':UUID(kbs[0]),'b':UUID(uids[1])})
            assert query(a,[kbs[0]])[0]==404
            with engine.begin() as c:c.execute(text('UPDATE users SET is_active=false WHERE id=:u'),{'u':UUID(uids[1])})
            assert query(b,[kbs[1]])[0]==401
            assert admin.call('DELETE','/api/v2/knowledge-bases/'+public)[0]==204
            assert query(a,[public])[0]==404
            Path('/tmp/ds-retrieval-http-results.json').write_text(json.dumps(evidence))
            print('Real HTTP BM25/Dense/Hybrid + pgvector cosine/RRF numeric checks: PASS')
            print('Two students + admin, public/private scopes, CSRF, deletion/reparse/permission changes: PASS')
    print('Temporary DB/storage/API/workers cleaned; deterministic Provider only; cloud NOT VERIFIED')


if __name__=='__main__':main()
