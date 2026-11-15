"""Actual isolated PostgreSQL/API tests; controlled draft is never a Qwen quality score."""
import json
import os
from uuid import UUID
import pytest
from sqlalchemy import select,text

from backend.v2.models import DocumentChunk
from backend.v2.services.generation_provider import Completion
from backend.v2.tests.test_auth import client_for,csrf_headers,register,post
from backend.v2.tests.test_context_turns import conversation,send
from backend.v2.tests.test_ingestion import setup,upload
from backend.v2.tests.test_verified_partition import QUERY,RULE,HOARE,COMPLEXITY
from backend.v2.worker import run_once as parse_once
from backend.v2.embedding_worker import run_once as index_once

pytestmark=[pytest.mark.integration,pytest.mark.skipif(os.getenv('DS_V2_RUN_DB_TESTS')!='1',reason='Isolated PostgreSQL')]


@pytest.fixture
def partition_env(setup,monkeypatch):
    e=setup;s=e['settings'];s.embedding_provider='deterministic';s.embedding_allow_test_provider=True
    s.generation_validation_retries=1
    e['document']=upload(e,name='original-partition-rules.txt',data=(RULE+COMPLEXITY+HOARE).encode())
    assert parse_once(e['factory'],s) and index_once(e['factory'],s)
    e.update(calls=[],draft='课程中的Lomuto分区规则。',citation='[S1]',during=None)
    class Controlled:
        model='partition-oracle-not-qwen'
        def generate(self,messages,*,before_attempt):
            before_attempt();e['calls'].append(messages)
            if e['during']:e['during']()
            return Completion(json.dumps({'status':'answered','answer':e['draft']+' '+e['citation'],'used_source_ids':[e['citation']]},ensure_ascii=False))
    monkeypatch.setattr('backend.v2.services.rag_service.build_provider',lambda *a,**kw:Controlled())
    return e


def test_exact_partition_is_saved_as_one_verified_pair_and_replay_is_idempotent(partition_env):
    e=partition_env;url=conversation(e);r,payload=send(e,url,QUERY)
    assert r.status_code==200,r.text
    body=r.json();assert body['status']=='answered'
    assert '最终数组：[1, 2, 3]；基准最终下标：1。' in body['answer']
    assert '| 2 | 1 | (0, 1) | [1, 3, 2] | 2 |' in body['answer']
    assert body['execution_performed'] is False
    source=body['sources'][0]
    with e['factory']() as db:
        chunk=db.get(DocumentChunk,UUID(source['chunk_id']))
        assert RULE in chunk.content and chunk.content_hash==source['content_hash']
    assert source['document_id']==e['document']['id'] and source['knowledge_base_id']==e['kb']['id']
    count=len(e['calls'])
    assert e['client'].post(url+'/ask',json=payload,headers=csrf_headers(e['client'])).json()==body
    assert len(e['calls'])==count
    messages=e['client'].get(url+'/messages').json()['items']
    assert [m['role'] for m in messages]==['user','assistant'] and messages[-1]['content']==body['answer']
    legacy=e['client'].post('/api/v2/rag/ask',json={k:v for k,v in payload.items() if k!='request_id'},headers=csrf_headers(e['client']))
    assert legacy.status_code==200 and legacy.json()['answer']==body['answer']


def test_variant_substitution_and_bad_citation_cannot_persist_and_retry_can_recover(partition_env):
    e=partition_env;url=conversation(e);e['draft']='用Hoare完成这道题。'
    r,payload=send(e,url,QUERY)
    assert r.status_code==502 and r.json()['reason']=='partition_variant_substitution'
    assert len(e['calls'])==2 and e['client'].get(url+'/messages').json()['total']==0
    e['draft']='Lomuto课程规则。';e['citation']='[S99]'
    r=e['client'].post(url+'/ask',json=payload,headers=csrf_headers(e['client']))
    assert r.status_code==502 and r.json()['reason']=='invalid_citations'
    assert e['client'].get(url+'/messages').json()['total']==0
    e['citation']='[S1]'
    assert e['client'].post(url+'/ask',json=payload,headers=csrf_headers(e['client'])).json()['status']=='answered'
    assert e['client'].get(url+'/messages').json()['total']==2


def test_hoare_or_missing_conditions_are_not_silently_answered_with_lomuto(partition_env):
    e=partition_env
    for query,reason in [(QUERY.replace('Lomuto','Hoare'),'partition_variant_not_supported'),
                         (QUERY.replace('数组下标从0开始',''),'partition_conditions_required')]:
        r,_=send(e,conversation(e),query)
        assert r.status_code==200 and r.json()['reason']==reason and not r.json()['sources']
    assert e['calls']==[]


def test_course_with_only_other_variant_is_not_an_algorithm_source(setup,monkeypatch):
    e=setup;s=e['settings'];s.embedding_provider='deterministic';s.embedding_allow_test_provider=True
    upload(e,name='hoare-only.txt',data=HOARE.encode());assert parse_once(e['factory'],s) and index_once(e['factory'],s)
    def forbidden(*a,**kw):raise AssertionError('No generation without compatible course rule')
    monkeypatch.setattr('backend.v2.services.rag_service.build_provider',forbidden)
    r,_=send(e,conversation(e),QUERY)
    assert r.status_code==200 and r.json()['reason']=='partition_rule_evidence_required' and not r.json()['sources']


def test_foreign_account_scope_and_stale_replay_are_denied(partition_env):
    e=partition_env;url=conversation(e);r,payload=send(e,url,QUERY);assert r.json()['status']=='answered'
    with client_for(e['settings']) as other:
        credentials,_=register(other);assert post(other,'login',credentials).status_code==200
        assert other.post(url+'/ask',json=payload,headers=csrf_headers(other)).status_code==404
    kb=e['client'].post('/api/v2/knowledge-bases',json={'name':'partition-other'},headers=csrf_headers(e['client'])).json()['knowledge_base']['id']
    assert send(e,url,QUERY,knowledge_base_ids=[kb])[0].json()['status']=='insufficient_evidence'
    with e['engine'].begin() as db:db.execute(text('UPDATE documents SET index_revision=index_revision+1 WHERE id=:id'),{'id':e['document']['id']})
    assert e['client'].post(url+'/ask',json=payload,headers=csrf_headers(e['client'])).status_code==409


def test_source_change_during_generation_rolls_back_both_messages(partition_env):
    e=partition_env;url=conversation(e)
    def invalidate():
        with e['engine'].begin() as db:db.execute(text('UPDATE documents SET index_revision=index_revision+1 WHERE id=:id'),{'id':e['document']['id']})
    e['during']=invalidate
    r,_=send(e,url,QUERY)
    assert r.status_code==409 and e['client'].get(url+'/messages').json()['total']==0


@pytest.mark.parametrize('case',['最好','平均','最坏'])
def test_complexity_answer_is_not_replaced_by_another_partition_variant(partition_env,case):
    e=partition_env;e['draft']='一次Lomuto分区时间O(n)、辅助空间O(1)。完整快速排序最坏O(n²)，两者不同。'
    r,_=send(e,conversation(e),'Lomuto分区的'+case+'情况复杂度如何？')
    assert r.status_code==200 and r.json()['answer']==e['draft']+' '+r.json()['sources'][0]['citation_id']
