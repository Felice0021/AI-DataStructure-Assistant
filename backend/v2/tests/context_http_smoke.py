"""Real context HTTP/Worker/PG verification; synthetic data, never cloud."""
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
    with isolated_database() as (engine,settings), tempfile.TemporaryDirectory(prefix='ds-context-http-') as directory, tempfile.TemporaryFile() as logs:
        root=Path(directory).resolve();(root/'temp').mkdir(mode=0o700)
        env=os.environ.copy();env.update({
            'DS_V2_DB_NAME':settings.db_name,'DS_V2_DB_HOST':settings.db_host,'DS_V2_DB_PORT':str(settings.db_port),
            'DS_V2_DB_USER':settings.db_user,'DS_V2_DB_PASSWORD':settings.db_password.get_secret_value(),
            'DS_V2_ENVIRONMENT':'development','DS_V2_ALLOW_INSECURE_LOOPBACK':'true','DS_V2_ALLOWED_ORIGINS':json.dumps([ORIGIN]),
            'DS_V2_FILE_STORAGE_ROOT':str(root/'objects'),'TMPDIR':str(root/'temp'),
            'DS_V2_EMBEDDING_PROVIDER':'deterministic','DS_V2_EMBEDDING_ALLOW_TEST_PROVIDER':'true',
            'DS_V2_EMBEDDING_CLOUD_ENABLED':'false','DS_V2_RERANK_PROVIDER':'deterministic','DS_V2_RERANK_ALLOW_TEST_PROVIDER':'true','DS_V2_RERANK_CLOUD_ENABLED':'false','DS_V2_WORKER_POLL_SECONDS':'.1'})
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
            def context(client,scope,**kw):
                return client.call('POST','/api/v2/retrieval/prepare-context',{
                    'query':'AVL 红黑树','knowledge_base_ids':scope,'top_k':10,'rerank':'required',**kw})
            evidence=[]
            for client,kb in [(a,kbs[0]),(b,kbs[1]),(admin,public)]:
                scope=[kb,public] if kb!=public else [public]
                code,result=context(client,scope);assert code==200
                assert result['rerank_applied'] and result['rerank_model']=='deterministic-overlap-v1'
                assert result['evidence'] and result['estimated_tokens']==len(result['context_text'].encode())
                blocks=json.loads(result['context_text'])
                assert [v['citation_id'] for v in blocks]==[v['citation_id'] for v in result['evidence']]
                assert all(v['knowledge_base_id'] in scope for v in result['evidence'])
                again=context(client,scope)[1];assert again['context_text']==result['context_text']
                if client is a:
                    evidence=[{k:v[k] for k in ('original_rank','rerank_rank','rerank_score','fused_score','dense_score','bm25_score')} for v in result['evidence']]
                    code,off=context(client,scope,rerank='off');assert code==200 and not off['rerank_applied']
                    assert all(v['rerank_score'] is None for v in off['evidence'])
            for intruder in (b,admin):assert context(intruder,[kbs[0],public])[0]==404
            assert context(a,[kbs[1]])[0]==404
            assert a.call('POST','/api/v2/retrieval/prepare-context',{'query':'AVL','knowledge_base_ids':[kbs[0]]},csrf=False)[0]==403
            assert context(a,[kbs[0]],user_id=uids[1])[0]==422
            # Final evidence must match current actual PostgreSQL content and source hash.
            code,result=context(a,[kbs[0],public]);assert code==200
            with engine.connect() as c:
                for v in result['evidence']:
                    row=c.execute(text('SELECT content,content_hash,generation FROM document_chunks WHERE id=:id'),{'id':UUID(v['chunk_id'])}).one()
                    assert row.content==v['content'] and row.content_hash==v['content_hash'] and row.generation==v['generation']
            public_path='/api/v2/knowledge-bases/'+public+'/documents/'+docs[2][2]
            assert admin.call('DELETE',public_path)[0]==204
            assert context(a,[public])[1]['evidence']==[]
            path='/api/v2/knowledge-bases/'+kbs[0]+'/documents/'+docs[0][2]
            assert a.call('POST',path+'/ingestion',{'reprocess':True})[0]==202
            assert context(a,[kbs[0]])[1]['evidence']==[]
            assert b.call('POST','/api/v2/auth/logout')[0]==204
            assert context(b,[kbs[1]])[0]==401
            print('Real HTTP context/citation mapping, original scores and rerank flags: PASS')
            print('Two students + admin, mixed/public/private scopes, CSRF, delete/reparse/logout: PASS')
            # Score-only diagnostics; no UUIDs, text, account data or credentials.
            Path('/tmp/ds-context-http-scores.json').write_text(json.dumps(evidence))
    print('Temporary DB/storage/API/workers cleaned; Qwen Rerank NOT VERIFIED')


if __name__=='__main__':main()
