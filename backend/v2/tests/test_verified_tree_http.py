"""Real database/HTTP authorization and publication gates; no cloud model in pytest."""
import json
import os
from uuid import UUID
import pytest
from sqlalchemy import select,text

from backend.v2.models import Message
from backend.v2.services.generation_provider import Completion
from backend.v2.services.verified_trees import calculate
from backend.v2.tests.test_auth import csrf_headers,client_for,register,post
from backend.v2.tests.test_context_turns import conversation,send
from backend.v2.tests.test_ingestion import setup,upload
from backend.v2.worker import run_once as parse_once
from backend.v2.embedding_worker import run_once as index_once

pytestmark=[pytest.mark.integration,pytest.mark.skipif(os.getenv('DS_V2_RUN_DB_TESTS')!='1',reason='Isolated PostgreSQL')]
RULES='AVL是二叉搜索树，每个结点左右高度差至多一。普通二叉搜索树只要求左小右大，不必平衡；有序输入可能使其退化为链，查找最坏为O(n)。AVL高度为O(log n)，标准存储高度实现的查找、插入、删除最坏为O(log n)。AVL可用LL右旋、RR左旋、LR先左后右、RL先右后左恢复平衡，旋转保持中序有序及键集合。B树非叶孩子数比键数多一，子树键范围被父键严格分隔；溢出后按题定中位键提升，剩余键和孩子分别组成左右结点。B+树的记录键全部在叶，内部键用于导航；本测试约定分隔键取右子树最小键。叶溢出按题定左右键数分裂，复制右叶最小键到父，右叶保留此键；内部溢出按题定中位提升。所有叶子必须同层，分裂容量与时机须遵循题目约定。'


@pytest.fixture
def tree_env(setup,monkeypatch):
    e=setup;s=e['settings'];s.embedding_provider='deterministic';s.embedding_allow_test_provider=True
    e['document']=upload(e,name='original-verified-tree-rules.txt',data=RULES.encode())
    assert parse_once(e['factory'],s) and index_once(e['factory'],s)
    e['draft']='课程规则说明。';e['citation']='[S1]';e['calls']=[];e['during_generation']=None
    class Reference:
        model='controlled-tree-draft-not-qwen'
        def generate(self,messages,*,before_attempt):
            before_attempt();e['calls'].append(messages)
            if e['during_generation']:e['during_generation']()
            return Completion(json.dumps({'status':'answered','answer':e['draft']+' '+e['citation'],
                'used_source_ids':[e['citation']]},ensure_ascii=False))
    monkeypatch.setattr('backend.v2.services.rag_service.build_provider',lambda *a,**kw:Reference())
    return e


def test_primary_subject_multi_turn_and_boundaries(tree_env):
    e=tree_env;url=conversation(e)
    first='AVL 树是什么？它与普通二叉搜索树有什么区别？'
    assert send(e,url,first)[0].json()['status']=='answered'
    r,_=send(e,url,'它为什么需要旋转？');assert r.json()['status']=='answered'
    assert json.loads(e['calls'][-1][1]['content'])['resolved_question']=='AVL 树为什么需要旋转？'
    count=len(e['calls'])
    assert send(e,conversation(e),'它为什么需要旋转？')[0].json()['reason']=='conversation_context_required'
    kb=e['client'].post('/api/v2/knowledge-bases',json={'name':'other-tree-scope'},headers=csrf_headers(e['client'])).json()['knowledge_base']['id']
    assert send(e,url,'它为什么需要旋转？',knowledge_base_ids=[kb])[0].json()['reason']=='conversation_context_required'
    assert len(e['calls'])==count


def test_unchecked_model_tree_is_not_published_or_saved_and_retry_is_idempotent(tree_env):
    e=tree_env;url=conversation(e)
    e['draft']='根 2，左孩子 1，结点 1 的右孩子 3。'
    r,data=send(e,url,'AVL旋转的原理是什么？')
    assert r.status_code==502 and r.json()['reason']=='unverified_tree_prose'
    assert r.json()['answer'] is None and r.json()['sources']==[]
    assert e['client'].get(url+'/messages').json()['total']==0
    e['draft']='AVL旋转要保持二叉搜索树全局有序，并恢复高度平衡。'
    c=e['client'];r=c.post(url+'/ask',json=data,headers=csrf_headers(c));assert r.status_code==200
    count=len(e['calls']);assert c.post(url+'/ask',json=data,headers=csrf_headers(c)).json()==r.json()
    assert len(e['calls'])==count and c.get(url+'/messages').json()['total']==2


def test_concrete_result_comes_from_verified_algorithm_not_bad_draft(tree_env):
    e=tree_env;e['draft']='根 2，左孩子 1，结点 1 的右孩子 3。'
    url=conversation(e);query='空AVL树，依次插入30,10,20，画出最终树。'
    r,_=send(e,url,query);assert r.status_code==200,r.text
    body=r.json();result,_=calculate(query)
    assert result.final=={'key':20,'left':{'key':10,'left':None,'right':None},'right':{'key':30,'left':None,'right':None}}
    assert body['answer']==result.render(body['sources'][0]['citation_id'])
    assert '根 2，' not in body['answer'] and '服务端算法' in body['answer']
    assert body['sources'][0]['document_id']==e['document']['id']
    assert e['client'].get(url+'/messages').json()['items'][-1]['content']==body['answer']


def test_verified_math_does_not_launder_bad_citations_or_lost_permissions(tree_env):
    e=tree_env;url=conversation(e);query='空AVL树，依次插入30,10,20，画出最终树。'
    e['citation']='[S99]';r,data=send(e,url,query)
    assert r.status_code==502 and r.json()['reason']=='invalid_citations'
    assert e['client'].get(url+'/messages').json()['total']==0
    e['citation']='[S1]'
    def invalidate():
        with e['engine'].begin() as conn:
            conn.execute(text('UPDATE documents SET index_revision=index_revision+1 WHERE id=:id'),{'id':e['document']['id']})
    e['during_generation']=invalidate
    r=e['client'].post(url+'/ask',json=data,headers=csrf_headers(e['client']))
    assert r.status_code==409
    with e['factory']() as db:assert list(db.scalars(select(Message).where(Message.conversation_id==UUID(url.rsplit('/',1)[1]))))==[]
    with client_for(e['settings']) as other:
        credentials,_=register(other);assert post(other,'login',credentials).status_code==200
        assert other.post(url+'/ask',json=data,headers=csrf_headers(other)).status_code==404


def test_missing_course_rules_cannot_be_replaced_by_the_calculator(setup,monkeypatch):
    e=setup;s=e['settings'];s.embedding_provider='deterministic';s.embedding_allow_test_provider=True
    upload(e,name='original-title-only.txt',data='AVL课程只有标题，没有具体理论说明。'.encode())
    assert parse_once(e['factory'],s) and index_once(e['factory'],s)
    def forbidden(*a,**kw):raise AssertionError('Must not generate without course rules')
    monkeypatch.setattr('backend.v2.services.rag_service.build_provider',forbidden)
    r,_=send(e,conversation(e),'空AVL树，依次插入30,10,20，画出最终树。')
    assert r.status_code==200 and r.json()['reason']=='tree_rule_evidence_required' and not r.json()['sources']
