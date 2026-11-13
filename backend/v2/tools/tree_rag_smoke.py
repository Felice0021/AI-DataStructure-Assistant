"""Explicit real-Qwen checks on original tree rules in a disposable PostgreSQL database."""
import argparse
import json
import os
from pathlib import Path
import tempfile
import time
from uuid import uuid4
from unittest.mock import patch
from sqlalchemy import select,func

from backend.v2.core.config import Settings,REPOSITORY_ROOT
from backend.v2.db.session import build_session_factory
from backend.v2.models.cloud import CloudAudit
from backend.v2.services.verified_trees import calculate
from backend.v2.services.generation_provider import QwenProvider
from backend.v2.tests.support import isolated_database
from backend.v2.tests.test_auth import local_settings,client_for,register,post,csrf_headers
from backend.v2.tests.test_ingestion import upload
from backend.v2.tests.test_verified_tree_http import RULES
from backend.v2.worker import run_once as parse_once
from backend.v2.embedding_worker import run_once as index_once

CASES=[
    ('focus',['AVL 树是什么？它与普通二叉搜索树有什么区别？','它为什么需要旋转？']),
    ('focus-reversed',['普通二叉搜索树是什么？它与AVL树有什么区别？','它为什么需要旋转？']),
    *[(kind,['AVL 的'+kind+'旋转请举例。']) for kind in ('LL','RR','LR','RL')],
    ('BST',['从空二叉搜索树构造，依次插入30,10,20,40，画出结果。']),
    ('B',['构造3阶B树，最多3个孩子，依次插入10,20,30；溢出后提升中间键。']),
    ('B+-left2',['构造3阶B+树，最多3孩子、2键，插入10,20,30；溢出左叶前2键，右叶后1键，父节点复制右叶最小键。']),
    ('B+-left1',['构造3阶B+树，最多3孩子、2键，插入10,20,30；溢出左叶前1键，右叶后2键，父节点复制右叶最小键。']),
    ('ambiguous',['比较AVL与二叉搜索树的区别。','它的特点呢？']),
    ('no-evidence',['unmatchedzzzzz']),
]


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--v2-env-file',required=True)
    parser.add_argument('--output-dir',required=True)
    parser.add_argument('--real-qwen',action='store_true',help='Explicitly authorize these original-text cloud calls')
    parser.add_argument('--case',action='append',choices=[c[0] for c in CASES])
    parser.add_argument('--capture-drafts',action='store_true',help='Store only unvalidated original-test response bodies privately')
    args=parser.parse_args()
    if not args.real_qwen:parser.error('--real-qwen is required; no implicit paid calls')
    root=Path(args.output_dir).resolve()
    if root==REPOSITORY_ROOT or REPOSITORY_ROOT in root.parents:parser.error('Output must be outside checkout')
    root.mkdir(mode=0o700,parents=True,exist_ok=True);root.chmod(0o700)
    target=root/('trees-'+uuid4().hex+'.json')
    source=Settings(_env_file=Path(args.v2_env_file))
    if not source.generation_api_key:print('BLOCKED missing_v2_key');return 2
    report={'model':source.generation_model,'source':'project-authored test rules, not V1 corpus','validation_retry_limit':1,
        'retrieval':'bm25 with isolated deterministic indexing','human_quality':'NOT_SCORED',
        'structure_owner':'server verified algorithms; Qwen supplies conceptual text/citation selection','cases':[]}
    def save():
        fd=os.open(target,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
        with os.fdopen(fd,'w',encoding='utf8') as file:json.dump(report,file,ensure_ascii=False,indent=2)
    try:
        with isolated_database() as (engine,base),tempfile.TemporaryDirectory(prefix='v2-tree-smoke-') as tmp:
            config=local_settings(base,file_storage_root=Path(tmp).resolve()/'files',embedding_provider='deterministic',
                embedding_allow_test_provider=True,embedding_cloud_enabled=False,rerank_provider='disabled',
                rerank_cloud_enabled=False,generation_provider='qwen',generation_cloud_enabled=True,
                generation_model_verified=True,generation_api_key=source.generation_api_key,
                generation_model=source.generation_model,generation_endpoint=source.generation_endpoint,
                generation_timeout_seconds=source.generation_timeout_seconds,generation_retries=0,
                generation_validation_retries=1,generation_max_calls=2)
            factory=build_session_factory(engine)
            def audit_count():
                with factory() as db:return db.scalar(select(func.count()).select_from(CloudAudit).where(CloudAudit.purpose=='generation',CloudAudit.event=='succeeded'))
            original_http=QwenProvider._http;drafts=[]
            def observed_http(provider,messages):
                payload=original_http(provider,messages)  # Real transport and Guard remain in effect.
                if args.capture_drafts:drafts.append(payload['choices'][0]['message']['content'])
                return payload
            with patch.object(QwenProvider,'_http',observed_http),client_for(config) as c:
                report['stage']='register_and_login'
                credentials,_=register(c);assert post(c,'login',credentials).status_code==200
                kb=c.post('/api/v2/knowledge-bases',json={'name':'original-verified-tree-'+uuid4().hex},headers=csrf_headers(c)).json()['knowledge_base']
                assert c.post('/api/v2/knowledge-bases/'+kb['id']+'/cloud-consents/generation',headers=csrf_headers(c)).status_code==200
                report['stage']='upload_and_isolated_processing'
                upload({'client':c,'base':'/api/v2/knowledge-bases/'+kb['id']+'/documents'},name='original-tree-rules.txt',data=RULES.encode())
                assert parse_once(factory,config) and index_once(factory,config)
                for name,questions in CASES:
                    if args.case and name not in args.case:continue
                    conv=c.post('/api/v2/conversations',json={'title':'original-'+name},headers=csrf_headers(c)).json()['conversation']['id']
                    for index,query in enumerate(questions):
                        drafts.clear()
                        before=audit_count();start=time.monotonic()
                        r=c.post('/api/v2/conversations/'+conv+'/ask',json={'query':query,'knowledge_base_ids':[kb['id']],
                            'request_id':str(uuid4()),'retrieval_mode':'bm25','rerank':'off','allow_cloud_generation':True},headers=csrf_headers(c))
                        body=r.json();calls=audit_count()-before;result,_=calculate(query)
                        refusal=name=='no-evidence' or name=='ambiguous' and index==1
                        valid=(r.status_code==200 and (body.get('status')=='insufficient_evidence' and not body.get('sources') and calls==0 if refusal else
                            body.get('status')=='answered' and bool(body.get('sources')) and 1<=calls<=2
                            and all(s['knowledge_base_id']==kb['id'] and s['citation_id'] in body['answer'] for s in body['sources'])))
                        if result and valid:valid=body['answer']==result.render(' '.join(s['citation_id'] for s in body['sources']))
                        items=c.get('/api/v2/conversations/'+conv+'/messages').json()['items']
                        resolved=items[-1]['metadata_json']['context']['resolved_query'] if items else None
                        if name=='focus' and index==1:valid=valid and resolved=='AVL 树为什么需要旋转？'
                        if name=='focus-reversed' and index==1:valid=valid and resolved=='二叉搜索树为什么需要旋转？'
                        if refusal:valid=valid and body.get('reason')==('no_evidence' if name=='no-evidence' else 'conversation_context_ambiguous')
                        report['cases'].append({'id':name,'round':index+1,'question':query,'http_status':r.status_code,
                            'response':body,'elapsed_ms':round((time.monotonic()-start)*1000),'successful_cloud_calls':calls,
                            'resolved_query':resolved,'verified_structure':result.final if result else None,
                            'unvalidated_original_test_drafts':list(drafts),'engineering_pass':valid})
                        save();print('CASE',name,'ROUND',index+1,'HTTP',r.status_code,'PASS',valid,flush=True)
                        if r.status_code in {401,403,429,503}:report['result']='BLOCKED';save();return 1
                with factory() as db:
                    report['cloud_usage']=[row.details for row in db.scalars(select(CloudAudit).where(CloudAudit.purpose=='generation',CloudAudit.event=='succeeded')).all()]
                report['result']='PASS' if all(x['engineering_pass'] for x in report['cases']) else 'FAIL'
                save();print('TRANSCRIPT',target);return 0 if report['result']=='PASS' else 1
    except Exception as error:
        report['result']='BLOCKED';report['error_code']=getattr(error,'code',type(error).__name__);save()
        print('BLOCKED',report['error_code']);print('TRANSCRIPT',target);return 2


if __name__=='__main__':raise SystemExit(main())
