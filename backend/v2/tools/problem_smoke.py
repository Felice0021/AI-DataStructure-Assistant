"""Real Qwen static problem-solving evaluation; no user code is ever executed."""
import argparse
import json
import os
from pathlib import Path
import tempfile
import time
from uuid import uuid4

from backend.v2.core.config import Settings, REPOSITORY_ROOT
from backend.v2.db.session import build_session_factory
from backend.v2.models import DocumentChunk
from uuid import UUID
from backend.v2.tests.support import isolated_database
from backend.v2.tests.test_auth import local_settings, client_for, register, post, csrf_headers
from backend.v2.tests.test_ingestion import upload
from backend.v2.worker import run_once as parse_once
from backend.v2.embedding_worker import run_once as index_once


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--v2-env-file',required=True)
    parser.add_argument('--output-dir',required=True)
    parser.add_argument('--case',action='append',help='Optional fixture IDs for a targeted regression')
    args=parser.parse_args()
    out=Path(args.output_dir).resolve()
    if out==REPOSITORY_ROOT or REPOSITORY_ROOT in out.parents:raise ValueError('Output must be outside checkout')
    out.mkdir(mode=0o700,parents=True,exist_ok=True);os.chmod(out,0o700)
    target=out/('problems-'+uuid4().hex+'.json')
    source=Settings(_env_file=Path(args.v2_env_file))
    cases=json.loads((REPOSITORY_ROOT/'backend/v2/tests/fixtures/problem_reference_cases.json').read_text())['cases']
    if args.case:
        if set(args.case)-{c['id'] for c in cases}:raise ValueError('Unknown case')
        cases=[c for c in cases if c['id'] in args.case]
    report={'model':source.generation_model,'content':'team-authored reference rules; expected answers not sent as evidence',
            'quality_review':'pending_human','cases':[]}
    def save():
        with target.open('w',encoding='utf8') as f:
            os.chmod(target,0o600);json.dump(report,f,ensure_ascii=False,indent=2)
    if not source.generation_api_key:print('BLOCKED missing_v2_key');return 2
    try:
        with isolated_database() as (engine,base),tempfile.TemporaryDirectory(prefix='v2-problems-') as tmp:
            s=local_settings(base,file_storage_root=Path(tmp).resolve()/'files',
                embedding_provider='deterministic',embedding_allow_test_provider=True,embedding_cloud_enabled=False,
                rerank_provider='disabled',rerank_cloud_enabled=False,generation_provider='qwen',
                generation_cloud_enabled=True,generation_model_verified=True,generation_api_key=source.generation_api_key,
                generation_model=source.generation_model,generation_endpoint=source.generation_endpoint,
                generation_timeout_seconds=source.generation_timeout_seconds,generation_retries=0,
                generation_validation_retries=0,generation_max_calls=1)
            factory=build_session_factory(engine)
            with client_for(s) as c:
                credentials,user=register(c);assert post(c,'login',credentials).status_code==200
                kb=c.post('/api/v2/knowledge-bases',json={'name':'original-problem-rules-'+uuid4().hex},headers=csrf_headers(c)).json()['knowledge_base']
                assert c.post('/api/v2/knowledge-bases/'+kb['id']+'/cloud-consents/generation',headers=csrf_headers(c)).status_code==200
                env={'client':c,'base':'/api/v2/knowledge-bases/'+kb['id']+'/documents'}
                for case in cases:
                    upload(env,name=case['id']+'.txt',data=case['rules'].encode())
                    assert parse_once(factory,s) and index_once(factory,s)
                for case in cases:
                    started=time.monotonic()
                    r=c.post('/api/v2/rag/ask',json={'query':case['query'],'knowledge_base_ids':[kb['id']],
                        'retrieval_mode':'bm25','answer_mode':'auto','rerank':'off','allow_cloud_generation':True},headers=csrf_headers(c))
                    body=r.json()
                    sources=body.get('sources',[])
                    structurally_valid=(r.status_code==200 and ((not case['expected_reason'] and body.get('status')=='answered' and bool(sources)
                        and all(x['knowledge_base_id']==kb['id'] and x['citation_id'] in body['answer'] for x in sources))
                        or (case['expected_reason'] and body.get('status')=='insufficient_evidence'
                            and body.get('reason')==case['expected_reason'] and not sources)))
                    with factory() as db:
                        evidence=[{'chunk_id':x['chunk_id'],'content':db.get(DocumentChunk,UUID(x['chunk_id'])).content,'content_hash':x['content_hash']} for x in sources]
                    report['cases'].append({'id':case['id'],'question':case['query'],'reference_answer':case['reference_answer'],
                        'expected_reason':case['expected_reason'],'http_status':r.status_code,'response':body,
                        'evidence':evidence,'fact_correctness':None,'steps_complete':None,'citation_faithfulness':None,
                        'latency_ms':round((time.monotonic()-started)*1000),'structure_valid':structurally_valid})
                    save();print('CASE',case['id'],'HTTP',r.status_code,'STATUS',body.get('status'),'STRUCTURE',structurally_valid,flush=True)
                    if r.status_code in {401,403,429,503}:
                        report['stopped']='authentication_or_provider_error';save();return 1
                valid=all(c['structure_valid'] for c in report['cases'])
                report['result']='ENGINEERING_PASS_QUALITY_PENDING_HUMAN' if valid else 'RECORDED_WITH_FAILURES'
                save();print('TRANSCRIPT',target)
                return 0 if valid else 1
    except Exception as error:
        report['result']='BLOCKED';report['error_code']=getattr(error,'code',type(error).__name__);save()
        print('BLOCKED',report['error_code']);print('TRANSCRIPT',target);return 2


if __name__=='__main__':raise SystemExit(main())
