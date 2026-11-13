"""Condition decisions on the real HTTP/DB path; generator is a controlled reference."""
import json
import os

import pytest
from backend.v2.services.generation_provider import Completion
from backend.v2.services.verified_trees import calculate
from backend.v2.tests.test_auth import csrf_headers
from backend.v2.tests.test_ingestion import setup, upload
from backend.v2.worker import run_once as parse_once
from backend.v2.embedding_worker import run_once as index_once

pytestmark=[pytest.mark.integration,pytest.mark.skipif(os.getenv('DS_V2_RUN_DB_TESTS')!='1',reason='Isolated PostgreSQL')]

@pytest.mark.parametrize('query,reason,answer',[
    ('画出空AVL树插入10的结果。',None,'空树插入10后根为10。'),
    ('画出空B树插入10的结果。',None,'空树插入10后根为10。'),
    ('画出空B+树插入10的结果。',None,'空树插入10后根叶包含10。'),
    ('构造3阶B+树，最多3孩子、2键，插入10 20 30；溢出左叶前2键，右叶后1键，父节点复制右叶最小键。',None,'根键30，左叶10、20，右叶30。'),
    ('构造3阶B+树，最多3孩子、2键，插入10、20、30；溢出左叶前1键，右叶后2键，父节点复制右叶最小键。',None,'根键20，左叶10，右叶20、30。'),
    ('构造3阶B树，插入10、20、30。','ambiguous_tree_rules',None),
    ('构造3阶B+树，最多3孩子、2键，插入10、20、30。','ambiguous_tree_split',None),
    ('解释B+树插入的原理和步骤。',None,'这里只说明B+树插入的一般规则，不给出缺少条件的具体构造结果。'),
    ('请自拟B+树构造示例。',None,'示例假设从空树开始，最多3孩子、叶最多2键，溢出左2右1且复制右叶最小键；输入10、20、30，根键30。'),
])
def test_real_http_condition_decisions(setup,monkeypatch,query,reason,answer):
    e=setup;s=e['settings'];s.embedding_provider='deterministic';s.embedding_allow_test_provider=True
    lesson='AVL从空树插入单键时该键为根。B树和B+树插入结果依赖初始树、阶数和分裂约定；B+叶分裂父键按约定复制右叶最小键。'
    document=upload(e,name='original-tree-rules.txt',data=lesson.encode())
    assert parse_once(e['factory'],s) and index_once(e['factory'],s)
    calls=[]
    class Reference:
        model='tree-reference-oracle-not-qwen'
        def generate(self,messages,*,before_attempt):
            before_attempt();calls.append(messages)
            block=json.loads(messages[2]['content'])['blocks'][0]
            return Completion(json.dumps({'status':'answered','answer':answer+' '+block['citation_id'],
                'used_source_ids':[block['citation_id']]},ensure_ascii=False))
    monkeypatch.setattr('backend.v2.services.rag_service.build_provider',lambda *a,**kw:Reference())
    c=e['client'];r=c.post('/api/v2/rag/ask',json={'query':query,'knowledge_base_ids':[e['kb']['id']],
        'retrieval_mode':'bm25','rerank':'off'},headers=csrf_headers(c))
    assert r.status_code==200,r.text
    body=r.json()
    if reason:
        assert body['status']=='insufficient_evidence' and body['reason']==reason
        assert body['sources']==[] and calls==[]
    else:
        assert body['status']=='answered' and len(calls)==1
        calculation,_=calculate(query)
        if calculation:
            if '空AVL' in query:assert calculation.final=={'key':10,'left':None,'right':None}
            elif '空B' in query:assert calculation.final=={'keys':[10],'children':[]}
            else:
                expected=({'keys':[20],'children':[{'keys':[10],'children':[]},{'keys':[20,30],'children':[]}]} if '左叶前1' in query else {'keys':[30],'children':[{'keys':[10,20],'children':[]},{'keys':[30],'children':[]}]})
                assert calculation.final==expected
            assert body['answer']==calculation.render(body['sources'][0]['citation_id'])
        else:assert body['answer']==answer+' '+body['sources'][0]['citation_id']
        assert body['sources'][0]['document_id']==document['id']
