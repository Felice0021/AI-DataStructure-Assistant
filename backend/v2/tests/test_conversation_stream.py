"""Random PostgreSQL + real HTTP auth/Guard/persistence; synthetic streaming upstream."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from threading import Event
import json
import os
from uuid import uuid4
import pytest
from sqlalchemy import text
from backend.v2.tests.test_ingestion import setup
from backend.v2.tests.test_retrieval import env
from backend.v2.tests.test_conversation_rag import turn_env
from backend.v2.tests.test_auth import csrf_headers,client_for,register,post
from backend.v2.services.generation_provider import GenerationError
from backend.v2.tests.test_generation_stream import event

pytestmark=[pytest.mark.integration,pytest.mark.skipif(os.getenv('DS_V2_RUN_DB_TESTS')!='1',reason='Isolated PostgreSQL')]


def frames(response):
    assert response.status_code==200,response.text
    assert response.headers['content-type'].startswith('text/event-stream')
    assert response.headers['cache-control']=='no-store, no-transform'
    result=[]
    for frame in response.text.split('\n\n'):
        if not frame or frame.startswith(':'):continue
        lines=frame.splitlines();payload=json.loads(next(x[6:] for x in lines if x.startswith('data: ')))
        assert lines[0]=='event: '+payload['type'] and lines[1]=='id: '+str(payload['seq'])
        result.append(payload)
    assert [x['seq'] for x in result]==list(range(1,len(result)+1))
    return result


@pytest.fixture
def streaming(env,monkeypatch):
    c,url,data=turn_env(env);s=env['settings']
    s.generation_provider='qwen';s.generation_cloud_enabled=True;s.generation_model_verified=True
    from pydantic import SecretStr
    s.generation_api_key=SecretStr('synthetic-stream-test-not-a-key');s.generation_retries=0
    data.update(query='Dijkstra是什么？',allow_cloud_generation=True)
    grant='/api/v2/knowledge-bases/'+env['kb']['id']+'/cloud-consents/generation'
    assert c.post(grant,headers=csrf_headers(c)).status_code==200
    env.update(url=url,data=data,calls=0,after_first=None,answer='Dijkstra 可用于非负边权图的最短路径分析。 [S1]',
        completion_tokens=30,closed=Event(),entered=Event(),release=None)
    async def source(provider,messages,check_cancel):
        env['calls']+=1
        try:
            raw=json.dumps({'status':'answered','answer':env['answer'],'used_source_ids':['[S1]']},ensure_ascii=True)
            start=raw.index('answer')+len('answer')+7
            yield event(raw[:start])
            env['entered'].set()
            if env['after_first']:env['after_first']()
            if env['release']:
                while not env['release'].is_set():await asyncio.sleep(0.01)
            yield event(raw[start:])
            yield event('', 'stop')
            yield json.dumps({'choices':[],'usage':{'prompt_tokens':40,'completion_tokens':env['completion_tokens'],
                'total_tokens':40+env['completion_tokens']}})
            yield '[DONE]'
        finally:env['closed'].set()
    monkeypatch.setattr('backend.v2.services.generation_stream.http_events',source)
    return env


def call(e,data=None):
    return e['client'].post(e['url']+'/ask-stream',json=data or e['data'],headers=csrf_headers(e['client']))


def test_real_stream_order_guard_audit_persistence_and_cross_transport_idempotency(streaming):
    e=streaming;out=frames(call(e))
    assert out[0]['payload']['stage']=='accepted' and out[-1]['type']=='result'
    types=[x['type'] for x in out]
    assert 'draft' in types
    draft=''.join(x['payload']['text'] for x in out if x['type']=='draft')
    assert draft==e['answer'] and '{"status"' not in draft
    stages=[x['payload']['stage'] for x in out if x['type']=='status']
    assert stages.index('retrieving')<stages.index('generating')<stages.index('validating')<stages.index('saving')
    body=out[-1]['payload']['result'];assert body['sources'][0]['knowledge_base_id']==e['kb']['id']
    assert body['answer']==draft and body['sources'][0]['citation_id']=='[S1]'
    rows=e['client'].get(e['url']+'/messages').json()['items']
    assert [x['role'] for x in rows]==['user','assistant'] and rows[-1]['metadata_json']['result']==body
    replay=frames(call(e));assert replay[-1]['payload']['result']==body and not any(x['type']=='draft' for x in replay)
    assert e['client'].post(e['url']+'/ask',json=e['data'],headers=csrf_headers(e['client'])).json()==body
    assert e['calls']==1 and e['closed'].is_set()
    with e['engine'].connect() as db:
        audit=db.execute(text("SELECT event,details FROM cloud_audits WHERE purpose='generation' ORDER BY created_at")).all()
        assert [r.event for r in audit]==['granted','attempt','succeeded']
        assert audit[-1].details['usage']['completion_tokens']==30
        assert e['answer'] not in json.dumps([r.details for r in audit],ensure_ascii=False)


def test_long_streaming_answer_within_new_budgets_is_validated_and_saved(streaming):
    e=streaming
    e['answer']='Dijkstra 通过边松弛不断更新最短路径估计值。[S1]\n'*140
    e['completion_tokens']=1800
    raw=json.dumps({'status':'answered','answer':e['answer'],'used_source_ids':['[S1]']},ensure_ascii=True)
    assert 12000<len(raw.encode())<e['settings'].generation_max_output_bytes
    assert 1024<e['completion_tokens']<=e['settings'].generation_max_output_tokens
    out=frames(call(e))
    assert out[-1]['type']=='result' and out[-1]['payload']['result']['answer']==e['answer']
    assert ''.join(frame['payload']['text'] for frame in out if frame['type']=='draft')==e['answer']
    assert e['client'].get(e['url']+'/messages').json()['total']==2
    with e['engine'].connect() as db:
        usage=db.execute(text("SELECT details FROM cloud_audits WHERE event='succeeded' AND purpose='generation'")).scalar_one()['usage']
        assert usage['completion_tokens']==1800


@pytest.mark.parametrize('kind,sql,code',[
    ('source',"UPDATE documents SET index_revision=index_revision+1",'context_stale'),
    ('document',"UPDATE documents SET deleted_at=clock_timestamp()",'context_stale'),
    ('kb',"UPDATE knowledge_bases SET deleted_at=clock_timestamp()",'knowledge_base_not_found'),
    ('user',"UPDATE users SET is_active=false",'unauthorized'),
    ('session',"UPDATE auth_sessions SET revoked_at=clock_timestamp()",'unauthorized'),
    ('consent',"UPDATE cloud_consents SET revoked_at=clock_timestamp()",'cloud_consent_required'),
    ('conversation',"UPDATE conversations SET deleted_at=clock_timestamp()",'conversation_not_found'),
])
def test_midstream_revocation_stops_publication_and_pair_writes(streaming,kind,sql,code):
    e=streaming
    def revoke():
        with e['engine'].begin() as db:db.execute(text(sql))
    e['after_first']=revoke
    out=frames(call(e))
    assert out[-1]['type']=='error' and out[-1]['payload']['code']==code
    assert not any(x['type']=='result' for x in out)
    with e['engine'].connect() as db:assert db.scalar(text('SELECT count(*) FROM messages'))==0
    assert e['closed'].is_set()


def test_invalid_citation_withdraws_draft_and_no_half_turn_is_saved(streaming):
    e=streaming;e['answer']='生成时出现尚未核实的内容 [S99]'
    out=frames(call(e));assert any(x['type']=='draft' for x in out)
    assert out[-1]['type']=='error' and out[-1]['payload']['status']==502
    assert e['client'].get(e['url']+'/messages').json()['total']==0
    e['answer']='Dijkstra 是最短路径算法。 [S1]'
    assert frames(call(e))[-1]['type']=='result'
    assert e['client'].get(e['url']+'/messages').json()['total']==2


def test_missing_guards_csrf_origin_and_scope_fail_closed(streaming):
    e=streaming;c=e['client'];path=e['url']+'/ask-stream'
    assert c.post(path,json=e['data']).status_code==403
    bad={**csrf_headers(c),'Origin':'https://untrusted.example'}
    assert c.post(path,json=e['data'],headers=bad).json()['error']['code']=='origin_rejected'
    payload={**e['data'],'allow_cloud_generation':False}
    out=frames(call(e,payload));assert out[-1]['payload']['code']=='generation_cloud_consent_required' and e['calls']==0
    with e['engine'].begin() as db:db.execute(text('UPDATE cloud_consents SET revoked_at=clock_timestamp()'))
    out=frames(call(e));assert out[-1]['payload']['code']=='cloud_consent_required' and e['calls']==0
    with client_for(e['settings']) as other:
        credentials,_=register(other);assert post(other,'login',credentials).status_code==200
        assert other.post(path,json=e['data'],headers=csrf_headers(other)).status_code==404
        r=other.post('/api/v2/conversations',json={'title':'independent'},headers=csrf_headers(other))
        assert other.post('/api/v2/conversations/'+r.json()['conversation']['id']+'/ask-stream',json=e['data'],headers=csrf_headers(other)).status_code==404


def test_timeouts_release_locks_and_same_request_can_be_retried(streaming):
    e=streaming;e['release']=Event();e['settings'].conversation_stream_timeout_seconds=1
    first=frames(call(e))
    assert first[-1]['type']=='error' and first[-1]['payload']['code']=='stream_timeout'
    assert e['closed'].wait(2)
    assert e['client'].get(e['url']+'/messages').json()['total']==0
    e['release'].set();e['settings'].conversation_stream_timeout_seconds=120
    assert frames(call(e))[-1]['type']=='result'
    assert e['client'].get(e['url']+'/messages').json()['total']==2


def test_same_conversation_lock_covers_stream_and_legacy_ask(streaming):
    e=streaming;e['release']=Event();headers=csrf_headers(e['client'])
    with ThreadPoolExecutor(2) as pool:
        pending=pool.submit(call,e)
        assert e['entered'].wait(5)
        try:
            r=e['client'].post(e['url']+'/ask',json=e['data'],headers=headers)
            assert r.status_code==409 and r.json()['error']['code']=='conversation_busy'
        finally:e['release'].set()
        assert frames(pending.result(timeout=10))[-1]['type']=='result'
    assert e['client'].get(e['url']+'/messages').json()['total']==2


def test_legacy_test_provider_emits_honest_stages_without_simulated_tokens(env):
    c,url,data=turn_env(env)
    out=frames(c.post(url+'/ask-stream',json=data,headers=csrf_headers(c)))
    assert out[-1]['type']=='result' and not any(x['type']=='draft' for x in out)
    assert all(not x['payload']['preview'] for x in out if x['type']=='status')
    empty=frames(c.post(url+'/ask-stream',json={**data,'query':'unmatchedzzzzz','request_id':str(uuid4()),'retrieval_mode':'bm25'},headers=csrf_headers(c)))
    assert empty[-1]['payload']['result']['status']=='insufficient_evidence' and not empty[-1]['payload']['result']['sources']


def test_database_failure_after_generation_rolls_back_the_complete_pair(streaming,monkeypatch):
    from backend.v2.services import conversation_rag
    from sqlalchemy.exc import OperationalError
    e=streaming;original=conversation_rag.checked_result
    def failed(*a,**kw):raise OperationalError('synthetic test only',None,Exception('unavailable'))
    monkeypatch.setattr(conversation_rag,'checked_result',failed)
    out=frames(call(e));assert out[-1]['type']=='error' and out[-1]['payload']['code']=='service_unavailable'
    with e['engine'].connect() as db:assert db.scalar(text('SELECT count(*) FROM messages'))==0
    monkeypatch.setattr(conversation_rag,'checked_result',original)
    assert frames(call(e))[-1]['type']=='result'
    assert e['client'].get(e['url']+'/messages').json()['total']==2


def test_stream_capacity_is_bounded_before_starting_a_producer(streaming):
    e=streaming;slots=e['client'].app.state.rag_stream_slots
    acquired=[]
    try:
        while slots.acquire(blocking=False):acquired.append(True)
        r=call(e)
        assert r.status_code==503 and r.json()['error']['code']=='service_busy' and e['calls']==0
    finally:
        for _ in acquired:slots.release()
    assert frames(call(e))[-1]['type']=='result'


def test_verified_tree_path_never_exposes_unvalidated_model_diagrams(setup,monkeypatch):
    from backend.v2.tests.test_verified_tree_http import RULES
    from backend.v2.tests.test_ingestion import upload
    from backend.v2.worker import run_once as parse_once
    from backend.v2.embedding_worker import run_once as index_once
    e=setup;s=e['settings'];s.embedding_provider='deterministic';s.embedding_allow_test_provider=True
    upload(e,data=RULES.encode());assert parse_once(e['factory'],s) and index_once(e['factory'],s)
    c,url,data=turn_env(e);data['query']='空AVL树，依次插入30,10,20，画出最终树。'
    from backend.v2.services.generation_provider import Completion
    class Source:
        model='controlled-tree-stream-not-qwen'
        def generate_stream(self,messages,*,before_attempt,on_delta,check_cancel):
            before_attempt();on_delta('根 2，左孩子 1，结点1的右孩子3。')
            return Completion(json.dumps({'status':'answered','answer':'课程说明[S1]','used_source_ids':['[S1]']}))
    monkeypatch.setattr('backend.v2.services.rag_service.build_provider',lambda *a,**kw:Source())
    out=frames(c.post(url+'/ask-stream',json=data,headers=csrf_headers(c)))
    assert not any(x['type']=='draft' for x in out)
    result=out[-1]['payload']['result']
    assert result['status']=='answered' and result['tree_visualization']['rotations'][0]['kind']=='LR'
    assert [f['stage'] for f in result['tree_visualization']['rotations'][0]['frames']]==['before','intermediate','after']
    assert '根 2，' not in result['answer']


@pytest.mark.parametrize('sql,code',[
    ('UPDATE documents SET index_revision=index_revision+1','context_stale'),
    ('UPDATE auth_sessions SET revoked_at=clock_timestamp()','unauthorized'),
])
def test_terminal_delivery_rechecks_after_a_previously_valid_commit(streaming,monkeypatch,sql,code):
    from backend.v2.services import conversation_rag
    e=streaming;original=conversation_rag.run
    def changed(*a,**kw):
        result=original(*a,**kw)
        with e['engine'].begin() as db:db.execute(text(sql))
        return result
    monkeypatch.setattr(conversation_rag,'run',changed)
    out=frames(call(e))
    assert out[-1]['type']=='error' and out[-1]['payload']['code']==code
    assert not any(x['type']=='result' for x in out)
    # This pair was fully valid at its commit point, not a partial/unverified draft.
    # Subsequent source revocation is handled by the existing historical redaction fence.
    with e['engine'].connect() as db:assert db.scalar(text('SELECT count(*) FROM messages'))==2
    if code=='context_stale':
        history=e['client'].get(e['url']+'/messages').json()['items']
        assert history[-1]['metadata_json']=={}
