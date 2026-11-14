"""Real isolated PostgreSQL/API convention provenance, without paid models."""
import json
import os
import pytest
from backend.v2.services.generation_provider import Completion
from backend.v2.services.verified_trees import calculate
from backend.v2.tests.test_auth import csrf_headers
from backend.v2.tests.test_context_turns import conversation,send
from backend.v2.tests.test_ingestion import setup,upload
from backend.v2.tests.test_tree_rule_evidence import QUERY,GENERAL,EXPLICIT
from backend.v2.worker import run_once as parse_once
from backend.v2.embedding_worker import run_once as index_once

pytestmark=[pytest.mark.integration,pytest.mark.skipif(os.getenv('DS_V2_RUN_DB_TESTS')!='1',reason='Isolated PostgreSQL')]


def seed(e,monkeypatch,sources):
    s=e['settings'];s.embedding_provider='deterministic';s.embedding_allow_test_provider=True
    for i,source in enumerate(sources):
        upload(e,name=f'original-convention-{i}.txt',data=source.encode())
        assert parse_once(e['factory'],s) and index_once(e['factory'],s)
    e['calls']=[];e['cite_all']=True
    class Reference:
        model='controlled-provenance-not-qwen'
        def generate(self,messages,*,before_attempt):
            before_attempt();e['calls'].append(messages)
            blocks=json.loads(messages[2]['content'])['blocks']
            if not e['cite_all']:blocks=[b for b in blocks if '只有标题' not in b['content']]
            citations=[b['citation_id'] for b in blocks]
            return Completion(json.dumps({'status':'answered','answer':'课程规则说明。'+' '.join(citations),
                'used_source_ids':citations},ensure_ascii=False))
    monkeypatch.setattr('backend.v2.services.rag_service.build_provider',lambda *a,**kw:Reference())


@pytest.mark.parametrize('source,reason',[
    (EXPLICIT,None),
    (GENERAL,None),
    (EXPLICIT.replace('左叶保留2键，右叶保留1键','左叶保留1键，右叶保留2键'),'tree_rule_conflict'),
    ('B+树只有标题，没有理论说明。','tree_rule_evidence_required'),
    (GENERAL+'叶溢出按左边两键右边一键的约定分裂。','tree_rule_unverified'),
])
def test_http_convention_basis_and_pre_generation_refusals(setup,monkeypatch,source,reason):
    e=setup;seed(e,monkeypatch,[source]);url=conversation(e)
    r,_=send(e,url,QUERY);assert r.status_code==200,r.text
    b=r.json()
    if reason:
        assert b['status']=='insufficient_evidence' and b['reason']==reason
        assert b['sources']==[] and e['calls']==[]
        assert '最终结构' not in b['answer']
    else:
        assert b['status']=='answered' and len(e['calls'])==1
        assert len(b['sources'])==1 and b['sources'][0]['citation_id'] in b['answer']
        assert '规则依据 [S1]' not in b['answer']
        assert '构造假设来自用户题设' in b['answer'] if source==GENERAL else '课程资料明确给出的约定：' in b['answer']
        result,_=calculate(QUERY)
        assert result.final=={'keys':[30],'children':[{'keys':[10,20],'children':[]},{'keys':[30],'children':[]}]}
        assert '根: [30]' in b['answer'] and '孩子1: [10, 20]' in b['answer'] and '孩子2: [30]' in b['answer']
        items=e['client'].get(url+'/messages').json()['items']
        assert len(items)==2 and items[-1]['content']==b['answer']


def test_unsupported_citation_is_not_laundered_by_another_valid_source_and_retry_is_atomic(setup,monkeypatch):
    e=setup;seed(e,monkeypatch,[EXPLICIT,'B+树只有标题。']);url=conversation(e)
    r,data=send(e,url,QUERY)
    assert len(json.loads(e['calls'][-1][2]['content'])['blocks'])==2
    assert r.status_code==502 and r.json()['reason']=='tree_rule_citation_required'
    assert r.json()['answer'] is None and r.json()['sources']==[]
    assert e['client'].get(url+'/messages').json()['total']==0
    # Same request_id may retry after a validation failure; exactly one pair is committed.
    e['cite_all']=False;c=e['client']
    r=c.post(url+'/ask',json=data,headers=csrf_headers(c));assert r.status_code==200,r.text
    assert len(r.json()['sources'])==1
    calls=len(e['calls']);assert c.post(url+'/ask',json=data,headers=csrf_headers(c)).json()==r.json()
    assert len(e['calls'])==calls and c.get(url+'/messages').json()['total']==2


def test_conflicting_uncited_source_is_not_silently_ignored(setup,monkeypatch):
    e=setup;seed(e,monkeypatch,[EXPLICIT,GENERAL+'左1右2。']);url=conversation(e)
    r,_=send(e,url,QUERY)
    assert r.status_code==200 and r.json()['reason']=='tree_rule_conflict'
    assert r.json()['sources']==[] and not e['calls']
