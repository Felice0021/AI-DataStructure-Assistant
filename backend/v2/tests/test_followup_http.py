"""Random PostgreSQL + actual HTTP stack; reference generator is not a quality score."""
import json
import os
from uuid import UUID

import pytest
from sqlalchemy import select, text

from backend.v2.models import Message
from backend.v2.services.generation_provider import Completion
from backend.v2.tests.test_auth import csrf_headers, client_for, register, post
from backend.v2.tests.test_context_turns import conversation, send
from backend.v2.tests.test_ingestion import setup, upload
from backend.v2.worker import run_once as parse_once
from backend.v2.embedding_worker import run_once as index_once

pytestmark=[pytest.mark.integration,pytest.mark.skipif(os.getenv('DS_V2_RUN_DB_TESTS')!='1',reason='Isolated PostgreSQL')]


@pytest.fixture
def followup_env(setup,monkeypatch):
    e=setup;s=e['settings'];s.embedding_provider='deterministic';s.embedding_allow_test_provider=True
    lesson='递归必须有终止条件；非负阶乘在0或1时返回1。Lomuto分区以末元素为pivot，从左到右把小于等于pivot的元素交换到前部，再把pivot交换到分界位置。AVL插入按二叉搜索树规则，LL失衡右旋。'
    e['document']=upload(e,name='original-followup-rules.txt',data=lesson.encode())
    assert parse_once(e['factory'],s) and index_once(e['factory'],s)
    e['calls']=[];e['during_generation']=None
    class Reference:
        model='followup-reference-oracle-not-qwen'
        def generate(self,messages,*,before_attempt):
            before_attempt();e['calls'].append(messages)
            question=json.loads(messages[1]['content']);query=question['text']
            resolved=question.get('resolved_question',query)
            blocks=json.loads(messages[2]['content'])['blocks']
            # Prior code/claims must not be copied into the evidence payload.
            assert all('int f(' not in b['content'] and '忽略系统' not in b['content'] for b in blocks)
            if 'untrusted_user_code' in resolved:
                data=json.loads(resolved.split('：',1)[1]);assert data['function']=='f'
                assert 'int f(int n)' in data['untrusted_user_code']
                answer='阶乘需要在0或1返回1。' if '修改' in query else '缺少终止条件导致递归无法结束。'
            elif 'untrusted_previous_step' in resolved:
                data=json.loads(resolved.split('：',1)[1]);assert data['step_number']==2
                answer='先核查键与pivot的大小，只有满足分区规则才应交换。'
            elif 'requested_prefix_count' in resolved:
                data=json.loads(resolved.split('：',1)[1])
                answer={2:'根30，左子20。',3:'根20，左子10，右子30。'}[data['requested_prefix_count']]
                assert data['next_key']=={2:'20',3:'10'}[data['requested_prefix_count']]
            elif 'Lomuto' in query:
                answer='1. 选定pivot。\n2. 交换候选键，忽略系统规则的文字是不可信的。'
            elif '待插入序列' in query:
                answer='先插入30，根为30。'
            else:
                answer='递归必须有终止条件。'
            if e['during_generation']:e['during_generation']()
            citation=blocks[0]['citation_id']
            return Completion(json.dumps({'status':'answered','answer':answer+' '+citation,'used_source_ids':[citation]},ensure_ascii=False))
    monkeypatch.setattr('backend.v2.services.rag_service.build_provider',lambda *a,**kw:Reference())
    return e


def code_turn(e):
    url=conversation(e)
    first,_=send(e,url,'分析阶乘递归终止条件：int f(int n){return n*f(n-1);}')
    assert first.json()['status']=='answered',first.json()
    return url


def test_continuous_code_and_idempotent_retry(followup_env):
    e=followup_env;url=code_turn(e)
    for query,expected in [('这个函数为什么死循环？','缺少终止条件导致递归无法结束。'),('那应该怎么修改？','阶乘需要在0或1返回1。')]:
        r,data=send(e,url,query);assert r.status_code==200,r.text
        body=r.json();assert body['answer']==expected+' '+body['sources'][0]['citation_id']
        assert body['sources'][0]['document_id']==e['document']['id']
        count=len(e['calls'])
        assert e['client'].post(url+'/ask',json=data,headers=csrf_headers(e['client'])).json()==body
        assert len(e['calls'])==count
    assert len(e['client'].get(url+'/messages').json()['items'])==6


def test_step_claim_and_explicit_insertion_cursor(followup_env):
    e=followup_env;url=conversation(e)
    assert send(e,url,'快速排序使用Lomuto分区，展示步骤。')[0].json()['status']=='answered'
    r,_=send(e,url,'第二步为什么要交换？');assert r.status_code==200 and r.json()['status']=='answered'
    assert '忽略系统' not in r.json()['answer']
    assert '忽略系统' not in e['calls'][-1][0]['content']
    url=conversation(e)
    assert send(e,url,'空AVL树，待插入序列30、20、10，先展示第1次插入。')[0].json()['status']=='answered'
    for expected in ('根30，左子20。','根20，左子10，右子30。'):
        r,_=send(e,url,'继续展示下一次插入。')
        assert r.json()['answer']==expected+' '+r.json()['sources'][0]['citation_id']
    count=len(e['calls']);r,_=send(e,url,'继续展示下一次插入。')
    assert r.json()['reason']=='conversation_context_ambiguous' and r.json()['sources']==[]
    assert len(e['calls'])==count


def test_concrete_reference_boundaries_and_expired_source_replay(followup_env):
    e=followup_env;c=e['client'];url=code_turn(e);count=len(e['calls'])
    new_url=conversation(e)
    assert send(e,new_url,'这个函数为什么死循环？')[0].json()['reason']=='conversation_context_required'
    kb=c.post('/api/v2/knowledge-bases',json={'name':'other-scope'},headers=csrf_headers(c)).json()['knowledge_base']['id']
    assert send(e,url,'那应该怎么修改？',knowledge_base_ids=[kb])[0].json()['reason']=='conversation_context_required'
    # Fresh valid turn for source invalidation and replay checks.
    url=code_turn(e);r,data=send(e,url,'这个函数为什么死循环？');assert r.json()['status']=='answered'
    with client_for(e['settings']) as other:
        credentials,_=register(other);assert post(other,'login',credentials).status_code==200
        assert other.post(url+'/ask',json=data,headers=csrf_headers(other)).status_code==404
    with e['engine'].begin() as conn:
        conn.execute(text('UPDATE documents SET index_revision=index_revision+1 WHERE id=:id'),{'id':e['document']['id']})
    count=len(e['calls'])
    assert c.post(url+'/ask',json=data,headers=csrf_headers(c)).status_code==409
    r,_=send(e,url,'那应该怎么修改？')
    assert r.json()['reason']=='conversation_context_required' and not r.json()['sources']
    assert len(e['calls'])==count


def test_history_source_change_during_generation_rolls_back_pair(followup_env):
    e=followup_env;url=code_turn(e)
    def invalidate():
        with e['engine'].begin() as conn:
            conn.execute(text('UPDATE documents SET index_revision=index_revision+1 WHERE id=:id'),{'id':e['document']['id']})
    e['during_generation']=invalidate
    r,_=send(e,url,'这个函数为什么死循环？')
    assert r.status_code==409
    with e['factory']() as session:
        rows=session.scalars(select(Message).where(Message.conversation_id==UUID(url.rsplit('/',1)[1]))).all()
        assert len(rows)==2
