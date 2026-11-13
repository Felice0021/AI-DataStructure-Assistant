"""Real isolated PostgreSQL + parser/index + HTTP turn persistence."""
import os
from uuid import uuid4
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
from sqlalchemy import text
from backend.v2.tests.test_ingestion import setup
from backend.v2.tests.test_retrieval import env
from backend.v2.tests.test_auth import client_for, csrf_headers, post, register
from backend.v2.services import conversation_rag

pytestmark = [pytest.mark.integration, pytest.mark.skipif(os.getenv('DS_V2_RUN_DB_TESTS') != '1', reason='Isolated PostgreSQL')]


def turn_env(env):
    env['settings'].generation_provider = 'deterministic'
    env['settings'].generation_allow_test_provider = True
    c = env['client']
    r = c.post('/api/v2/conversations', json={'title': '课程问答'}, headers=csrf_headers(c))
    assert r.status_code == 201
    url = '/api/v2/conversations/' + r.json()['conversation']['id']
    data = {'query': 'AVL', 'knowledge_base_ids': [env['kb']['id']], 'request_id': str(uuid4())}
    return c, url, data


def test_turn_persistence_replay_isolation_and_redaction(env):
    c, url, data = turn_env(env)
    for query in ['AVL', 'Dijkstra', 'unmatchedzzzzz']:
        payload = {**data, 'query': query, 'request_id': str(uuid4())}
        first = c.post(url+'/ask', json=payload, headers=csrf_headers(c))
        assert first.status_code == 200, first.text
        assert c.post(url+'/ask', json=payload, headers=csrf_headers(c)).json() == first.json()
        if query != 'unmatchedzzzzz':
            assert '[S1]' in first.json()['answer']
            assert first.json()['sources'][0]['knowledge_base_id'] == env['kb']['id']
        else:
            assert first.json()['status'] == 'insufficient_evidence'
        assert c.post(url+'/ask', json={**payload, 'query': 'changed'}, headers=csrf_headers(c)).status_code == 409
    messages = c.get(url+'/messages').json()['items']
    assert [m['role'] for m in messages] == ['user', 'assistant']*3
    assert [m['seq'] for m in messages] == list(range(1, 7))
    assert c.post(url+'/ask', json=data).status_code == 403
    assert c.post(url+'/messages', json={'role': 'assistant', 'content': 'fake'}, headers=csrf_headers(c)).status_code == 422
    with client_for(env['settings']) as other:
        creds, _ = register(other); assert post(other, 'login', creds).status_code == 200
        assert other.get(url+'/messages').status_code == 404
        assert other.post(url+'/ask', json=data, headers=csrf_headers(other)).status_code == 404
    with env['engine'].begin() as conn:
        conn.execute(text('UPDATE documents SET deleted_at=clock_timestamp()'))
    history = c.get(url+'/messages')
    assert history.status_code == 200
    assert history.json()['items'][1]['metadata_json'] == {}
    assert '[S1]' not in history.json()['items'][1]['content']


def test_failure_does_not_save_and_delete_during_generation(env, monkeypatch):
    c, url, data = turn_env(env)
    env['settings'].generation_provider = 'disabled'
    assert c.post(url+'/ask', json=data, headers=csrf_headers(c)).status_code == 503
    assert c.get(url+'/messages').json()['total'] == 0
    env['settings'].generation_provider = 'deterministic'
    original = conversation_rag.ask
    def deleted(*args, **kwargs):
        result = original(*args, **kwargs)
        with env['engine'].begin() as conn:
            conn.execute(text('UPDATE conversations SET deleted_at=clock_timestamp()'))
        return result
    monkeypatch.setattr(conversation_rag, 'ask', deleted)
    assert c.post(url+'/ask', json=data, headers=csrf_headers(c)).status_code == 404
    with env['engine'].connect() as conn:
        assert conn.scalar(text('SELECT count(*) FROM messages')) == 0


def test_parallel_turn_rejected_and_lock_released(env, monkeypatch):
    c, url, data = turn_env(env)
    entered, release = Event(), Event()
    original = conversation_rag.ask
    def slow(*args, **kwargs):
        entered.set(); assert release.wait(10)
        return original(*args, **kwargs)
    monkeypatch.setattr(conversation_rag, 'ask', slow)
    headers = csrf_headers(c)
    with ThreadPoolExecutor(2) as pool:
        future = pool.submit(c.post, url+'/ask', json=data, headers=headers)
        assert entered.wait(5)
        try:
            r = c.post(url+'/ask', json=data, headers=headers)
            assert r.status_code == 409 and r.json()['error']['code'] == 'conversation_busy'
        finally:
            release.set()
        assert future.result().status_code == 200
    assert c.post(url+'/ask', json=data, headers=headers).status_code == 200
    assert c.get(url+'/messages').json()['total'] == 2


def test_database_write_failure_rolls_back_pair(env):
    from sqlalchemy import event
    from sqlalchemy.exc import OperationalError
    from sqlalchemy.orm import Session
    from backend.v2.models import Message
    c, url, data = turn_env(env)
    def fail(session, *_):
        if any(isinstance(obj, Message) for obj in session.new):
            raise OperationalError('synthetic', {}, RuntimeError('synthetic-db-failure'))
    event.listen(Session, 'before_flush', fail)
    try:
        failed = c.post(url+'/ask', json=data, headers=csrf_headers(c))
        assert failed.status_code == 503
        assert failed.json()['error']['code'] == 'service_unavailable'
        assert 'synthetic-db-failure' not in failed.text
    finally:
        event.remove(Session, 'before_flush', fail)
    assert c.get(url+'/messages').json()['total'] == 0
    assert c.post(url+'/ask', json=data, headers=csrf_headers(c)).status_code == 200
    assert c.get(url+'/messages').json()['total'] == 2
