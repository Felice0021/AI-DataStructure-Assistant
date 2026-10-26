"""Explicit paid synthetic-only smoke. Never imported/executed by pytest."""
import argparse,json,os,time
from pathlib import Path
from uuid import UUID,uuid4
from sqlalchemy import select
from backend.v2.core.config import Settings
from backend.v2.models import Document,EmbeddingJob,CloudAudit
from backend.v2.db.session import build_session_factory
from backend.v2.services.rag_service import ask
from backend.v2.schemas.rag import AskRequest
from backend.v2.tests.support import isolated_database
from backend.v2.tests.test_auth import local_settings,client_for,register,post,csrf_headers
from backend.v2.tests.test_context import verify
from backend.v2.tests.test_ingestion import upload
from backend.v2.worker import run_once as parse_once
from backend.v2.embedding_worker import run_once as embed_once
from types import SimpleNamespace
import tempfile

LEDGER=Path('/tmp/ds-v2-synthetic-cloud-budget.json')


class Budget:
    def __init__(self):
        if LEDGER.exists():self.state=json.loads(LEDGER.read_text())
        else:
            self.state={'calls':0,'upper_cny':0.0,'events':[]}
            fd=os.open(LEDGER,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
            with os.fdopen(fd,'w') as h:json.dump(self.state,h)
    def reserve(self,purpose):
        if self.state['calls']>=12 or self.state['upper_cny']+.4>5:raise RuntimeError('synthetic_budget_exhausted')
        self.state['calls']+=1;self.state['upper_cny']=round(self.state['calls']*.4,2)
        self.state['events'].append({'purpose':purpose,'time':int(time.time())})
        # Durable reservation precedes even a possibly billable failed request.
        with LEDGER.open('w') as h:json.dump(self.state,h);h.flush();os.fsync(h.fileno())


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--allow-paid-synthetic',action='store_true');a=p.parse_args()
    if not a.allow_paid_synthetic:p.error('Explicit --allow-paid-synthetic required')
    base=Settings()
    if not all(getattr(base,k+'_api_key') for k in ('embedding','rerank','generation')):
        print(json.dumps({'status':'BLOCKED','reason':'missing_v2_credentials'}));return
    if not all('.cn-beijing.maas.aliyuncs.com' in getattr(base,k+'_endpoint') for k in ('embedding','rerank','generation')):
        print(json.dumps({'status':'BLOCKED','reason':'pricing_only_verified_for_beijing'}));return
    budget=Budget()
    if 12-budget.state['calls']<9:
        print(json.dumps({'status':'BLOCKED','reason':'insufficient_remaining_smoke_budget','reserved_calls':budget.state['calls']}));return
    result={'embedding':'NOT VERIFIED','reranker':'NOT VERIFIED','generator':'NOT VERIFIED','rag':'NOT VERIFIED','refusal':'NOT VERIFIED'}
    with isolated_database() as (engine,s),tempfile.TemporaryDirectory(prefix='ds-paid-synthetic-') as directory:
        from pathlib import Path
        config=local_settings(s,file_storage_root=Path(directory).resolve()/'objects',embedding_provider='dashscope',embedding_cloud_enabled=True,
            embedding_model_revision='synthetic-smoke-20261026',embedding_request_retries=0,embedding_batch_size=10,embedding_max_api_calls=6,
            rerank_provider='qwen',rerank_cloud_enabled=True,rerank_model_verified=True,rerank_retries=0,rerank_max_total_bytes=16000,
            generation_provider='qwen',generation_cloud_enabled=True,generation_model_verified=True,generation_model='qwen3.8-flash',
            generation_retries=0,generation_validation_retries=0,generation_max_output_tokens=512,generation_max_input_bytes=16000)
        with client_for(config) as client:
            credentials,user=register(client);assert post(client,'login',credentials).status_code==200
            response=client.post('/api/v2/knowledge-bases',json={'name':'synthetic-cloud-'+uuid4().hex,'description':'SYNTHETIC ONLY; no user or V1 material'},headers=csrf_headers(client));assert response.status_code==201
            kb=response.json()['knowledge_base'];kb_id=UUID(kb['id'])
            for purpose in ('embedding','reranking','generation'):
                assert client.post('/api/v2/knowledge-bases/'+kb['id']+'/cloud-consents/'+purpose,headers=csrf_headers(client)).status_code==200
            factory=build_session_factory(engine);env={'engine':engine,'factory':factory,'settings':config,'client':client,'user':user,'kb':kb,'base':'/api/v2/knowledge-bases/'+kb['id']+'/documents'}
            # Author-created, short, non-sensitive fixture. No file/text input accepted by this CLI.
            record=upload(env,name='synthetic-cloud.txt',data='# Synthetic course\nAVL树是平衡二叉搜索树。每个结点左右子树的高度差绝对值不超过1。\n该合成片段没有具体结点或插入序列，也没有定义空树高度约定。'.encode())
            parse_once(factory,config)
            assert client.post(env['base']+'/'+record['id']+'/embedding',json={'allow_cloud':True},headers=csrf_headers(client)).status_code==202
            try:
                embed_once(factory,config,before_cloud_call=budget.reserve)
                with factory() as db:
                    doc=db.get(Document,UUID(record['id']));job=db.scalar(select(EmbeddingJob).where(EmbeddingJob.document_id==doc.id))
                    if doc.status!='ready':
                        result['embedding']='BLOCKED';result['embedding_error']=job.error_code;raise RuntimeError('embedding_not_ready')
                result['embedding']='PASS'
                for name,question in [('normal','AVL树是什么，它的平衡条件是什么？'),('refusal','资料没有给出具体树和插入序列，请计算这棵AVL树的精确高度。')]:
                    request=AskRequest(query=question,knowledge_base_ids=[kb_id],rerank='required',allow_cloud=True,allow_cloud_rerank=True,allow_cloud_generation=True)
                    output=ask(factory,SimpleNamespace(id=UUID(user['id'])),request,config,verify_session=lambda db:verify(env,db),before_cloud_call=budget.reserve)
                    result['reranker']='PASS'
                    if output['generation_model']=='qwen3.8-flash' and output['status'] in {'answered','insufficient_evidence'}:result['generator']='PASS'
                    if name=='normal':
                        result['rag']='PASS' if output['status']=='answered' and output['sources'] else 'FAIL'
                        result['normal_status']=output['status'];result['normal_reason']=output['reason']
                    else:result['refusal']='PASS' if output['status']=='insufficient_evidence' and output['generation_model']=='qwen3.8-flash' else 'FAIL';result['refusal_status']=output['status']
            except Exception as error:
                result['stopped_reason']=getattr(error,'code',type(error).__name__)
            with factory() as db:
                events=db.scalars(select(CloudAudit).where(CloudAudit.event.in_(['succeeded','failed']))).all()
                result['calls']=[{'purpose':r.purpose,'event':r.event,'elapsed_ms':r.details.get('elapsed_ms'),'usage':r.details.get('usage',{})} for r in events]
                # Beijing list prices, no free-tier assumptions. Usage is estimated billing, not invoice.
                cost=0
                for r in events:
                    u=r.details.get('usage',{});inp=u.get('prompt_tokens',u.get('input_tokens',u.get('total_tokens',0)));out=u.get('completion_tokens',u.get('output_tokens',0))
                    cost+=(inp*({'embedding':.125,'reranking':.5,'generation':.8}[r.purpose])+out*(2.7 if r.purpose=='generation' else 0))/1e6
                result['estimated_usage_cost_cny']=round(cost,6)
    result.update(reserved_calls=budget.state['calls'],reserved_upper_cny=budget.state['upper_cny'],data='synthetic_only',cloud_defaults_unchanged=True,
        models={'embedding':'qwen3.7-text-embedding-flash/1024','reranker':'qwen3.7-text-rerank','generator':'qwen3.8-flash'})
    path=Path('/tmp/ds-v2-cloud-smoke-result.json');path.write_text(json.dumps(result,ensure_ascii=False,indent=2));print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':
    try:main()
    except Exception as error:print(json.dumps({'status':'BLOCKED','reason':type(error).__name__}))
