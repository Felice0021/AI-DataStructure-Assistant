"""Actual HTTP + random PostgreSQL + parsing/indexing. Generator is a reference oracle, not Qwen."""
import json
import os
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, text
from backend.v2.models import Message, DocumentChunk, User
from backend.v2.services import conversation_rag, generation_provider
from backend.v2.services.conversation_context import load_recent, revalidate
from backend.v2.services.generation_provider import Completion
from backend.v2.tests.test_ingestion import setup, upload
from backend.v2.tests.test_auth import csrf_headers, client_for, register, post
from backend.v2.worker import run_once as parse_once
from backend.v2.embedding_worker import run_once as index_once

CASES = json.loads((Path(__file__).parent/'fixtures/context_reference_cases.json').read_text())['cases']
pytestmark = [pytest.mark.integration, pytest.mark.skipif(os.getenv('DS_V2_RUN_DB_TESTS') != '1', reason='Isolated PostgreSQL')]


@pytest.fixture
def context_env(setup, monkeypatch):
    s = setup['settings']
    s.embedding_provider = 'deterministic'; s.embedding_allow_test_provider = True
    s.generation_provider = 'deterministic'; s.generation_allow_test_provider = True
    for case in CASES:
        upload(setup, name=case['id']+'.txt', data=case['lesson'].encode())
        assert parse_once(setup['factory'], s)
        assert index_once(setup['factory'], s)
    calls = []
    class Reference:
        model = 'reference-oracle-not-a-quality-evaluation'
        def generate(self, messages, *, before_attempt):
            before_attempt(); calls.append(messages)
            q = json.loads(messages[1]['content'])
            query = q.get('resolved_question', q['text'])
            blocks = json.loads(messages[2]['content'])['blocks']
            for case in CASES:
                if query in case['resolved']:
                    answer = case['answers'][case['resolved'].index(query)]
                    block = next(b for b in blocks if answer in b['content'])
                    return Completion(json.dumps({'status':'answered','answer':answer+' '+block['citation_id'],
                                                  'used_source_ids':[block['citation_id']]},ensure_ascii=False))
            return Completion(json.dumps({'status':'insufficient_evidence','answer':'','used_source_ids':[]}))
    monkeypatch.setattr('backend.v2.services.rag_service.build_provider', lambda *a, **kw: Reference())
    setup['calls'] = calls
    return setup


def conversation(env):
    c = env['client']
    r = c.post('/api/v2/conversations', json={'title':'上下文测试'}, headers=csrf_headers(c))
    assert r.status_code == 201
    return '/api/v2/conversations/'+r.json()['conversation']['id']


def send(env, url, query, **kw):
    data = {'query':query, 'knowledge_base_ids':[env['kb']['id']], 'request_id':str(uuid4()),
            'retrieval_mode':'bm25', 'rerank':'off', **kw}
    r = env['client'].post(url+'/ask', json=data, headers=csrf_headers(env['client']))
    return r, data


@pytest.mark.parametrize('case', CASES, ids=[c['id'] for c in CASES])
def test_second_turn_uses_history_and_current_reference_evidence(context_env, case):
    e = context_env; url = conversation(e)
    for i, question in enumerate(case['questions']):
        r, data = send(e, url, question)
        assert r.status_code == 200, r.text
        result = r.json(); assert result['status'] == 'answered'
        source = result['sources'][0]
        assert result['answer'] == case['answers'][i]+' '+source['citation_id']
        assert source['knowledge_base_id'] == e['kb']['id']
        with e['factory']() as s:
            chunk = s.get(DocumentChunk, UUID(source['chunk_id']))
            assert case['answers'][i] in chunk.content
            assert chunk.content_hash == source['content_hash']
        prompt = e['calls'][-1]
        q = json.loads(prompt[1]['content'])
        assert q.get('resolved_question', q['text']) == case['resolved'][i]
        if i:
            history = json.loads(prompt[3]['content'])
            assert history['type'] == 'untrusted_conversation'
            assert history['turns'][0]['user'] == case['questions'][0]
            assert case['answers'][0] in history['turns'][0]['assistant']
            assert '[S' not in history['turns'][0]['assistant']
            count = len(e['calls'])
            # Transport replay never regenerates or incorporates the newly saved pair again.
            replay = e['client'].post(url+'/ask', json=data, headers=csrf_headers(e['client']))
            assert replay.json() == result and len(e['calls']) == count
    messages = e['client'].get(url+'/messages').json()['items']
    assert [m['role'] for m in messages] == ['user','assistant','user','assistant']
    assert messages[-1]['metadata_json']['context']['resolved_query'] == case['resolved'][1]
    # A separate conversation has no referent and must not call generation.
    count = len(e['calls'])
    r, _ = send(e, conversation(e), case['questions'][1])
    assert r.json()['reason'] == 'conversation_context_required' and r.json()['sources'] == []
    assert len(e['calls']) == count


def test_scope_change_foreign_account_and_stale_sources(context_env):
    e = context_env; c = e['client']; url = conversation(e)
    assert send(e, url, 'AVL树是什么？')[0].status_code == 200
    kb = c.post('/api/v2/knowledge-bases',json={'name':uuid4().hex},headers=csrf_headers(c)).json()['knowledge_base']['id']
    r, _ = send(e, url, '它为什么需要旋转？', knowledge_base_ids=[kb])
    assert r.json()['reason'] == 'conversation_context_required'
    with client_for(e['settings']) as other:
        creds, _ = register(other); assert post(other, 'login', creds).status_code == 200
        assert other.post(url+'/ask',json={'query':'它为什么旋转？','knowledge_base_ids':[e['kb']['id']],
                                         'request_id':str(uuid4())},headers=csrf_headers(other)).status_code == 404
    # Fresh conversation, then mark the referenced document as a new generation.
    url = conversation(e); first, _ = send(e,url,'AVL树是什么？')
    source = first.json()['sources'][0]
    with e['engine'].begin() as con:
        con.execute(text("UPDATE documents SET index_revision=index_revision+1 WHERE id=:id"), {'id':source['document_id']})
    count = len(e['calls']); r, _ = send(e,url,'它为什么需要旋转？')
    assert r.json()['reason'] == 'conversation_context_required'
    assert len(e['calls']) == count


def test_history_limit_and_revalidation_after_loading(context_env):
    e = context_env; url = conversation(e)
    for _ in range(4):
        assert send(e, url, 'AVL树是什么？')[0].json()['status'] == 'answered'
    assert len(json.loads(e['calls'][-1][3]['content'])['turns']) == 3
    with e['factory']() as s:
        user = s.get(User, UUID(e['user']['id']))
        verify = lambda session: session.get(User, user.id)
        recent = load_recent(s,user,UUID(url.rsplit('/',1)[-1]),[UUID(e['kb']['id'])],e['settings'],verify,conversation_rag.checked_result)
    assert len(recent) == 3
    with e['engine'].begin() as con:
        con.execute(text('UPDATE documents SET deleted_at=clock_timestamp()'))
    from backend.v2.core.errors import AuthError
    with e['factory']() as s, pytest.raises(AuthError):
        user = s.get(User, UUID(e['user']['id']))
        revalidate(s,user,UUID(url.rsplit('/',1)[-1]),recent,e['settings'],verify,conversation_rag.checked_result)
