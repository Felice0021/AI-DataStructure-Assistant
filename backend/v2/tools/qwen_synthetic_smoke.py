"""Explicit real-model smoke on synthetic content and an isolated PostgreSQL database."""
import argparse
import json
from pathlib import Path
import tempfile
from uuid import UUID, uuid4

from pydantic import SecretStr
from sqlalchemy import func, select
from backend.v2.core.config import Settings
from backend.v2.db.session import build_session_factory
from backend.v2.embedding_worker import run_once as embed_once
from backend.v2.models import CloudAudit, Document, ChunkEmbedding
from backend.v2.tests.support import isolated_database
from backend.v2.tests.test_auth import client_for, csrf_headers, local_settings, post, register
from backend.v2.tests.test_ingestion import upload
from backend.v2.worker import run_once as parse_once


def main():
    parser=argparse.ArgumentParser()
    keys=parser.add_mutually_exclusive_group(required=True)
    keys.add_argument('--v2-env-file', help='Existing private V2 dotenv; never printed or copied')
    keys.add_argument('--v2-key-file', help='Existing private single-line Key; read only in memory')
    args=parser.parse_args()
    if args.v2_env_file:
        source=Settings(_env_file=Path(args.v2_env_file))
    else:
        key=Path(args.v2_key_file).read_text().strip()
        if not key.startswith('sk-') or any(c.isspace() for c in key):
            print('BLOCKED invalid_key_format');return 2
        source=Settings(_env_file=None).model_copy(update={name+'_api_key':SecretStr(key) for name in ('embedding','rerank','generation')})
    if not all(getattr(source, name+'_api_key') for name in ('embedding','rerank','generation')):
        print('BLOCKED missing_v2_cloud_key');return 2
    with isolated_database() as (engine,base), tempfile.TemporaryDirectory(prefix='ds-qwen-synthetic-') as temp:
        config=local_settings(base,file_storage_root=Path(temp).resolve()/'objects',
            embedding_provider='deterministic',embedding_allow_test_provider=True,
            generation_provider='qwen',generation_cloud_enabled=True,generation_model_verified=True,
            generation_api_key=source.generation_api_key,generation_endpoint=source.generation_endpoint,
            generation_model=source.generation_model,generation_retries=0,generation_validation_retries=0,
            rerank_provider='disabled')
        factory=build_session_factory(engine)
        with client_for(config) as client:
            credentials,user=register(client)
            assert post(client,'login',credentials).status_code==200
            def create_kb():
                response=client.post('/api/v2/knowledge-bases',json={'name':'synthetic-'+uuid4().hex},headers=csrf_headers(client))
                assert response.status_code==201
                kb=response.json()['knowledge_base']
                return {'engine':engine,'factory':factory,'settings':config,'client':client,'user':user,'kb':kb,
                        'base':'/api/v2/knowledge-bases/'+kb['id']+'/documents'}
            def consent(env,purpose):
                url='/api/v2/knowledge-bases/'+env['kb']['id']+'/cloud-consents/'+purpose
                assert client.post(url,headers=csrf_headers(client)).status_code==200
            def ask(env,mode,*,query='AVL树的平衡条件是什么？',answer_mode='qa',cloud_embedding=False,rerank='off'):
                payload={'query':query,'knowledge_base_ids':[env['kb']['id']],
                         'retrieval_mode':mode,'answer_mode':answer_mode,'rerank':rerank,
                         'allow_cloud':cloud_embedding,'allow_cloud_rerank':rerank=='required','allow_cloud_generation':True}
                response=client.post('/api/v2/rag/ask',json=payload,headers=csrf_headers(client))
                body=response.json()
                print('ASK',mode,'HTTP',response.status_code,'status',body.get('status'),'reason',body.get('reason'),flush=True)
                if response.status_code!=200 or body.get('status')!='answered':return False
                sources=body.get('sources',[])
                valid='[S1]' in (body.get('answer') or '') and any(s.get('citation_id')=='[S1]' and s.get('knowledge_base_id')==env['kb']['id'] for s in sources)
                text=body.get('answer') or ''
                natural='chunk_id' not in text and 'source_file' not in text and len(text.strip())>8
                print('MODEL',body.get('generation_model'),'CITATION_VALID',valid,'NO_IMPORT_METADATA',natural,'RERANK',body.get('rerank_applied'),flush=True)
                return valid and natural
            data=('# 原创合成示例\nAVL树是一种二叉搜索树。每个节点的左右子树高度差绝对值不超过1。\n'
                  '栈采用后进先出，队列采用先进先出。\n'
                  '图的广度优先遍历按距离逐层访问，通常用队列保存待访问节点。\n'
                  '插入排序逐一将元素插入已排序的前缀，最坏时间复杂度是平方级。\n'
                  '例题：依次将甲、乙压栈后弹出两次，顺序为乙、甲。\n'
                  '示例代码：def is_empty(items): return len(items) == 0，作用是判断列表是否为空。\n').encode()
            first=create_kb();consent(first,'generation')
            record=upload(first,name='synthetic-avl.txt',data=data)
            assert parse_once(factory,config) and embed_once(factory,config)
            bm25_ok=ask(first,'bm25')
            if not bm25_ok:print('STOP generation_failed',flush=True);return 1
            config.embedding_provider='dashscope';config.embedding_cloud_enabled=True
            config.embedding_api_key=source.embedding_api_key;config.embedding_endpoint=source.embedding_endpoint
            config.embedding_model=source.embedding_model;config.embedding_model_revision='synthetic-e2e-v1'
            config.embedding_request_retries=0;config.embedding_backoff_seconds=.1
            config.rerank_provider='qwen';config.rerank_cloud_enabled=True;config.rerank_model_verified=True
            config.rerank_api_key=source.rerank_api_key;config.rerank_endpoint=source.rerank_endpoint
            config.rerank_model=source.rerank_model;config.rerank_retries=0
            second=create_kb()
            for purpose in ('embedding','reranking','generation'):consent(second,purpose)
            record=upload(second,name='synthetic-avl.txt',data=data)
            assert parse_once(factory,config)
            response=client.post(second['base']+'/'+record['id']+'/embedding',json={'allow_cloud':True},headers=csrf_headers(client))
            assert response.status_code==202
            assert embed_once(factory,config)
            with factory() as db:
                doc=db.get(Document,UUID(record['id']))
                count=db.scalar(select(func.count()).select_from(ChunkEmbedding).where(ChunkEmbedding.document_id==doc.id))
                print('REAL_EMBEDDING',config.embedding_model,'status',doc.status,'vectors',count,flush=True)
                if doc.status!='ready' or not count:return 1
            for mode in ('bm25','dense','hybrid'):
                payload={'query':'AVL树','knowledge_base_ids':[second['kb']['id']],'mode':mode,'top_k':3,'allow_cloud':mode!='bm25'}
                response=client.post('/api/v2/retrieval/search',json=payload,headers=csrf_headers(client))
                body=response.json();ok=response.status_code==200 and bool(body.get('results'))
                print('RETRIEVAL',mode,'HTTP',response.status_code,'has_results',bool(body.get('results')),flush=True)
                if not ok:return 1
            if not ask(second,'hybrid',cloud_embedding=True,rerank='required'):return 1
            for label,question,answer_mode in [
                ('stack','栈和队列的出入顺序有什么区别？','qa'),
                ('tree','AVL树的平衡条件是什么？','qa'),
                ('graph','图的广度优先遍历如何保存待访问节点？','qa'),
                ('sort','插入排序的最坏时间复杂度是什么？','qa'),
                ('exercise','例题中依次压入甲和乙，弹出顺序是什么？','exercise'),
                ('code','示例代码 is_empty 的作用是什么？','code')]:
                ok=ask(second,'bm25',query=question,answer_mode=answer_mode)
                print('SCENARIO',label,'PASS' if ok else 'FAIL',flush=True)
                if not ok:return 1
            missing={'query':'unmatchedzzzzz','knowledge_base_ids':[second['kb']['id']],
                     'retrieval_mode':'bm25','answer_mode':'qa','rerank':'off','allow_cloud_generation':True}
            response=client.post('/api/v2/rag/ask',json=missing,headers=csrf_headers(client));body=response.json()
            refused=response.status_code==200 and body.get('status')=='insufficient_evidence' and not body.get('sources')
            print('REFUSAL', 'PASS' if refused else 'FAIL',flush=True)
            if not refused:return 1
            with client_for(config) as other:
                other_credentials,_=register(other);assert post(other,'login',other_credentials).status_code==200
                response=other.post('/api/v2/rag/ask',json=missing,headers=csrf_headers(other))
                print('CROSS_USER_HTTP',response.status_code,flush=True)
                if response.status_code!=404:return 1
            with factory() as db:
                rows=db.scalars(select(CloudAudit).where(CloudAudit.event.in_(['attempt','succeeded','failed']))).all()
                summary={}
                for row in rows:summary[row.purpose+':'+row.event]=summary.get(row.purpose+':'+row.event,0)+1
                print('AUDIT_COUNTS',json.dumps(summary,sort_keys=True),flush=True)
            return 0


if __name__=='__main__':
    try:raise SystemExit(main())
    except Exception as exc:
        print('STOP',getattr(exc,'code',type(exc).__name__),flush=True)
        raise SystemExit(1) from None
