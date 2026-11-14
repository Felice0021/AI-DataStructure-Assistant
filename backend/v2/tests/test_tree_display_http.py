"""Real isolated PostgreSQL and HTTP publication/history boundaries; no paid provider."""
import os
import json
import pytest
from sqlalchemy import text
from backend.v2.tests.test_verified_tree_http import tree_env
from backend.v2.tests.test_ingestion import setup
from backend.v2.tests.test_context_turns import conversation,send
from backend.v2.tests.test_auth import client_for,register,post,csrf_headers
from backend.v2.tests.tree_display_cases import CASES,cases

pytestmark=[pytest.mark.integration,pytest.mark.skipif(os.getenv('DS_V2_RUN_DB_TESTS')!='1',reason='Isolated PostgreSQL')]


@pytest.mark.parametrize('name',['LL','RR','LR','RL','BST','B','B+'])
def test_http_verified_display_is_persisted_replayed_and_scoped(tree_env,name):
    e=tree_env;url=conversation(e)
    response,payload=send(e,url,CASES[name])
    assert response.status_code==200,response.text
    body=response.json();assert body['status']=='answered',body
    tree=body['tree_visualization']
    assert tree==cases()[name]
    assert tree['source_citations']==[s['citation_id'] for s in body['sources']]
    assert body['sources'][0]['document_id']==e['document']['id']
    assert '```text' in body['answer'] and '```' not in tree['explanation']
    count=len(e['calls'])
    assert e['client'].post(url+'/ask',json=payload,headers=csrf_headers(e['client'])).json()==body
    assert len(e['calls'])==count
    messages=e['client'].get(url+'/messages').json()['items']
    assert len(messages)==2 and messages[-1]['metadata_json']['result']['tree_visualization']==tree
    with client_for(e['settings']) as other:
        creds,_=register(other);assert post(other,'login',creds).status_code==200
        assert other.get(url+'/messages').status_code==404
        assert other.post(url+'/ask',json=payload,headers=csrf_headers(other)).status_code==404
    # Graphs cannot bypass the same source-generation fence used for replayed answers.
    with e['engine'].begin() as db:db.execute(text('UPDATE documents SET index_revision=index_revision+1 WHERE id=:id'),{'id':e['document']['id']})
    assert e['client'].post(url+'/ask',json=payload,headers=csrf_headers(e['client'])).status_code==409
    assert len(e['calls'])==count
    stale=e['client'].get(url+'/messages').json()['items'][-1]
    assert stale['metadata_json']=={} and '来源已变更或不可访问' in stale['content']


def test_plain_answer_refusal_and_invalid_draft_never_get_graphs(tree_env,monkeypatch):
    e=tree_env
    response,_=send(e,conversation(e),'AVL树是什么？')
    assert response.json()['status']=='answered' and response.json()['tree_visualization'] is None
    response,_=send(e,conversation(e),'unmatchedzzzzz')
    assert response.json()['status']=='insufficient_evidence' and response.json()['tree_visualization'] is None
    from backend.v2.services.generation_provider import Completion
    class Forgery:
        model='controlled-malformed-draft'
        def generate(self,messages,*,before_attempt):
            before_attempt()
            return Completion(json.dumps({'status':'answered','answer':'说明[S1]','used_source_ids':['[S1]'],'tree_visualization':cases()['LR']}))
    monkeypatch.setattr('backend.v2.services.rag_service.build_provider',lambda *a,**kw:Forgery())
    url=conversation(e);r,_=send(e,url,CASES['LR'])
    assert r.status_code==502 and r.json()['tree_visualization'] is None
    assert e['client'].get(url+'/messages').json()['total']==0
