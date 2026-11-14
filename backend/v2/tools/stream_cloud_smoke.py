"""Explicit ONE generation request, original synthetic text, random DB; never run by pytest.

No paid embedding/rerank, no V1 documents, no production database or configuration writes.
The existing durable synthetic budget is reserved before the HTTP request and never reset.
"""
import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
import secrets
import socket
import tempfile
import threading
import time
from uuid import uuid4
import httpx2
import uvicorn
from sqlalchemy import text
from backend.v2.core.config import Settings
from backend.v2.main import create_app
from backend.v2.tests.support import isolated_database
from backend.v2.tests.test_auth import local_settings
from backend.v2.db.session import build_session_factory
from backend.v2.worker import run_once as parse_once
from backend.v2.embedding_worker import run_once as embed_once
from backend.v2.tools.cloud_smoke import Budget

TEXT='# 原创流式测试资料\n栈遵循后进先出，最后入栈的元素最先出栈，主要操作为入栈和出栈。队列遵循先进先出，先入队的元素先出队，通常在队尾入队、队头出队。顺序执行三个元素A、B、C的入栈和出栈操作，依次出栈得到C、B、A；同样依次入队后出队得到A、B、C。本资料由测试工具原创，仅用于工程测试，不包含V1教材或用户个人资料。'


@contextmanager
def server(settings):
    sock=socket.socket();sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    base=f'http://127.0.0.1:{port}';settings.allowed_origins.append(base)
    app=create_app(settings);runner=uvicorn.Server(uvicorn.Config(app,log_level='critical',access_log=False))
    thread=threading.Thread(target=lambda:runner.run(sockets=[sock]),daemon=True);thread.start()
    until=time.monotonic()+5
    while not runner.started:
        if not thread.is_alive() or time.monotonic()>until:raise RuntimeError('local_server_unavailable')
        time.sleep(0.01)
    try:yield base
    finally:
        runner.should_exit=True;thread.join(timeout=5);sock.close()
        if thread.is_alive():raise RuntimeError('local_server_cleanup_failed')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--allow-one-cloud-request',action='store_true');p.add_argument('--report',type=Path,required=True)
    args=p.parse_args()
    if not args.allow_one_cloud_request:p.error('Explicit --allow-one-cloud-request required')
    if args.report.exists():p.error('Report already exists; preserve the previous evidence')
    report={'status':'BLOCKED','material':'original_synthetic_only','real_generation_attempt_limit':1,'paid_embedding_rerank_calls':0}
    base=Settings()
    if not base.generation_api_key:
        report['reason']='missing_v2_generation_key'
    else:
        try:
            budget=Budget()
            with isolated_database() as (engine,s),tempfile.TemporaryDirectory(prefix='v2-stream-cloud-') as tmp:
                config=local_settings(s,registration_enabled=True,file_storage_root=(Path(tmp)/'files').resolve(),embedding_provider='deterministic',embedding_allow_test_provider=True,
                    embedding_cloud_enabled=False,rerank_provider='disabled',rerank_cloud_enabled=False,
                    generation_provider='qwen',generation_cloud_enabled=True,generation_model_verified=True,
                    generation_retries=0,generation_validation_retries=0,generation_max_calls=1,
                    generation_max_output_tokens=512,generation_timeout_seconds=30)
                # local_settings retains the independent V2 generation endpoint/key, not V1 .env.
                config.generation_endpoint=base.generation_endpoint;config.generation_model=base.generation_model
                config.generation_api_key=base.generation_api_key
                with server(config) as url,httpx2.Client(base_url=url,headers={'Origin':url},trust_env=False,timeout=125) as client:
                    def write(path,body=None,**kwargs):
                        token=client.get('/api/v2/auth/csrf').json()['csrf_token']
                        return client.post(path,json=body,headers={'X-CSRF-Token':token},**kwargs)
                    credentials={'email':uuid4().hex+'@example.com','password':secrets.token_urlsafe(32)}
                    assert write('/api/v2/auth/register',credentials).status_code==201
                    assert write('/api/v2/auth/login',credentials).status_code==200
                    kb=write('/api/v2/knowledge-bases',{'name':'original-sse-smoke-'+uuid4().hex}).json()['knowledge_base']['id']
                    token=client.get('/api/v2/auth/csrf').json()['csrf_token']
                    doc=client.post('/api/v2/knowledge-bases/'+kb+'/documents',files={'file':('original-stream-smoke.txt',TEXT.encode(),'text/plain')},headers={'X-CSRF-Token':token})
                    if doc.status_code!=201:
                        report['initialization_error']={'stage':'synthetic_upload','status':doc.status_code,'code':doc.json().get('error',{}).get('code')}
                        raise RuntimeError('synthetic_upload_failed')
                    factory=build_session_factory(engine)
                    assert parse_once(factory,config) and embed_once(factory,config)
                    assert write('/api/v2/knowledge-bases/'+kb+'/cloud-consents/generation').status_code==200
                    conversation=write('/api/v2/conversations',{'title':'原创合成流式验证'}).json()['conversation']['id']
                    request_id=str(uuid4());payload={'request_id':request_id,'query':'栈和队列有什么区别？请简要说明，并用资料中的三个元素举例。',
                        'knowledge_base_ids':[kb],'retrieval_mode':'bm25','rerank':'off','allow_cloud_generation':True}
                    token=client.get('/api/v2/auth/csrf').json()['csrf_token']
                    budget.reserve('generation-stream') # one durable reservation even if a later request fails
                    started=time.monotonic();first=None;deltas=0;answer=None;error=None;count=0
                    with client.stream('POST','/api/v2/conversations/'+conversation+'/ask-stream',json=payload,headers={'X-CSRF-Token':token}) as response:
                        assert response.status_code==200
                        for line in response.iter_lines():
                            if not line.startswith('data: '):continue
                            event=json.loads(line[6:]);count+=1
                            if event['type']=='draft':
                                deltas+=1
                                if first is None:first=round((time.monotonic()-started)*1000,2)
                            elif event['type']=='result':answer=event['payload']['result']
                            elif event['type']=='error':error=event['payload']['code']
                    report.update(model=config.generation_model,provider='real_qwen_https_stream',first_draft_ms=first,
                        completion_ms=round((time.monotonic()-started)*1000,2),draft_events=deltas,sse_events=count,error=error)
                    with engine.connect() as db:
                        audits=db.execute(text("SELECT event,details FROM cloud_audits WHERE purpose='generation' ORDER BY created_at")).all()
                        report['actual_generation_attempts']=sum(r.event=='attempt' for r in audits)
                        report['usage']=[r.details.get('usage',{}) for r in audits if r.event=='succeeded']
                        report['persisted_messages']=db.scalar(text('SELECT count(*) FROM messages'))
                    if answer:
                        import re
                        cited=set(re.findall(r'\[S[1-9][0-9]*\]',answer['answer'] or ''))
                        actual={s['citation_id'] for s in answer['sources']}
                        report.update(status='PASS' if answer['status']=='answered' and deltas>1 and cited==actual and actual else 'FAIL',
                            answer_status=answer['status'],citation_ids=sorted(actual),answer=answer['answer'],model_used=answer['generation_model'])
                    else:report['status']='FAIL'
                    assert report['actual_generation_attempts']<=1
        except Exception as error:
            import traceback
            report['failure_location']=[{'module':Path(t.filename).name,'line':t.lineno} for t in traceback.extract_tb(error.__traceback__)][-3:]
            report['status']='BLOCKED' if str(error)=='synthetic_budget_exhausted' else 'FAIL'
            report['error_type']=type(error).__name__
    args.report.parent.mkdir(parents=True,exist_ok=True)
    fd=os.open(args.report,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    with os.fdopen(fd,'w') as h:json.dump(report,h,ensure_ascii=False,indent=2)
    print(json.dumps({k:v for k,v in report.items() if k!='answer'},ensure_ascii=False))
    return 0 if report['status']=='PASS' else 1


if __name__=='__main__':raise SystemExit(main())
