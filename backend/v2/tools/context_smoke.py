"""Opt-in real Qwen follow-up smoke on original fixture facts in a disposable DB.

Never prints credentials, prompts or answers. Transcripts are private files outside the checkout.
No production database, course documents, embedding space or model configuration is modified.
"""
import argparse
import json
import os
from pathlib import Path
import tempfile
import time
from uuid import uuid4

from backend.v2.core.config import Settings, REPOSITORY_ROOT
from backend.v2.db.session import build_session_factory
from backend.v2.tests.support import isolated_database
from backend.v2.tests.test_auth import local_settings, client_for, register, post, csrf_headers
from backend.v2.tests.test_ingestion import upload
from backend.v2.worker import run_once as parse_once
from backend.v2.embedding_worker import run_once as index_once


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--v2-env-file', required=True, help='Existing private V2 config, read normally, never copied')
    parser.add_argument('--output-dir', required=True)
    args = parser.parse_args()
    out = Path(args.output_dir).resolve()
    if out == REPOSITORY_ROOT or REPOSITORY_ROOT in out.parents:
        raise ValueError('Transcript directory must be outside repository')
    out.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(out, 0o700)
    target = out / ('context-' + uuid4().hex + '.json')
    source = Settings(_env_file=Path(args.v2_env_file))
    if not source.generation_api_key:
        print('BLOCKED missing_v2_generation_key'); return 2
    cases = json.loads((REPOSITORY_ROOT/'backend/v2/tests/fixtures/context_reference_cases.json').read_text())['cases']
    report = {'model': source.generation_model, 'retrieval': 'bm25',
              'content': 'team-authored small reference fixtures, not V1 course corpus',
              'model_quality_review': 'pending_human', 'turns': []}
    def save():
        with target.open('w', encoding='utf8') as f:
            os.chmod(target, 0o600)
            json.dump(report, f, ensure_ascii=False, indent=2)
    try:
        with isolated_database() as (engine, base), tempfile.TemporaryDirectory(prefix='v2-context-smoke-') as tmp:
            config = local_settings(base, file_storage_root=Path(tmp).resolve()/'objects',
                embedding_provider='deterministic', embedding_allow_test_provider=True, embedding_cloud_enabled=False,
                rerank_provider='disabled', rerank_cloud_enabled=False,
                generation_provider='qwen', generation_cloud_enabled=True, generation_model_verified=True,
                generation_api_key=source.generation_api_key, generation_model=source.generation_model,
                generation_endpoint=source.generation_endpoint, generation_timeout_seconds=10,
                generation_retries=0, generation_validation_retries=0, generation_max_calls=1)
            factory = build_session_factory(engine)
            with client_for(config) as c:
                credentials, user = register(c); assert post(c, 'login', credentials).status_code == 200
                kb = c.post('/api/v2/knowledge-bases',json={'name':'original-context-smoke-'+uuid4().hex},headers=csrf_headers(c)).json()['knowledge_base']
                assert c.post('/api/v2/knowledge-bases/'+kb['id']+'/cloud-consents/generation',headers=csrf_headers(c)).status_code == 200
                env = {'client':c, 'base':'/api/v2/knowledge-bases/'+kb['id']+'/documents'}
                for case in cases:
                    upload(env, name=case['id']+'.txt', data=case['lesson'].encode())
                    assert parse_once(factory, config) and index_once(factory, config)
                for case in cases:
                    conv = c.post('/api/v2/conversations',json={'title':'original-'+case['id']},headers=csrf_headers(c)).json()['conversation']['id']
                    for i, query in enumerate(case['questions']):
                        started = time.monotonic()
                        r = c.post('/api/v2/conversations/'+conv+'/ask',json={
                            'query':query,'request_id':str(uuid4()),'knowledge_base_ids':[kb['id']],
                            'retrieval_mode':'bm25','rerank':'off','allow_cloud_generation':True},headers=csrf_headers(c))
                        body = r.json()
                        valid = (r.status_code == 200 and body.get('status') == 'answered' and bool(body.get('sources'))
                                 and all(s['knowledge_base_id'] == kb['id'] and s['citation_id'] in body['answer'] for s in body['sources']))
                        report['turns'].append({'case':case['id'],'round':i+1,'question':query,
                            'reference_answer':case['answers'][i], 'http_status':r.status_code,'response':body,
                            'elapsed_ms':round((time.monotonic()-started)*1000), 'citation_structure_valid':valid})
                        save()
                        print('CASE',case['id'],'ROUND',i+1,'HTTP',r.status_code,'STATUS',body.get('status'),'CITATIONS',valid,flush=True)
                        if not valid:
                            report['result']='FAIL';save();return 1
                report['result']='ENGINEERING_PASS_QUALITY_PENDING_HUMAN';save()
                print('TRANSCRIPT',target);return 0
    except Exception as error:
        report['result']='BLOCKED';report['error_code']=getattr(error,'code',type(error).__name__);save()
        print('BLOCKED',report['error_code']);print('TRANSCRIPT',target);return 2


if __name__ == '__main__':
    raise SystemExit(main())
