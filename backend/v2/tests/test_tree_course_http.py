"""Two reported online questions against real HTTP/DB with original-style course rules.

The generator is controlled; successful results do not claim Qwen validation.
"""
import json
import os

import pytest

from backend.v2.services.generation_provider import Completion
from backend.v2.tests.test_auth import csrf_headers
from backend.v2.tests.test_ingestion import setup,upload
from backend.v2.worker import run_once as parse_once
from backend.v2.embedding_worker import run_once as index_once

pytestmark=[pytest.mark.integration,pytest.mark.skipif(os.getenv('DS_V2_RUN_DB_TESTS')!='1',reason='Isolated PostgreSQL')]


@pytest.mark.parametrize('query,lesson',[
    ('空AVL树，依次插入30,10,20，画出最终树。',
     '平衡二叉树AVL：左右子树高度差绝对值不超过1，且左右子树都是AVL树。'),
    ('从一棵空 AVL 树开始，依次插入 30、10、20。请根据课程知识库中的 AVL 树规则，'
     '画出最终树形图，并说明是否发生旋转、旋转类型及过程。',
     '平衡二叉树AVL：左右子树高度差绝对值不超过1，且左右子树都是AVL树。'),
    ('构造空BST树，依次插入40,20,30,70,60，画出最终树。',
     '二叉排序树BST定义：左子树所有节点关键字<根关键字；右子树所有节点关键字>根关键字；左右子树仍是BST。'),
])
def test_course_wording_produces_verified_tree_over_http(setup,monkeypatch,query,lesson):
    env=setup;settings=env['settings']
    settings.embedding_provider='deterministic';settings.embedding_allow_test_provider=True
    upload(env,name='course-tree-rule.txt',data=lesson.encode())
    assert parse_once(env['factory'],settings) and index_once(env['factory'],settings)
    calls=[]

    class Reference:
        model='controlled-course-rule-not-qwen'
        def generate(self,messages,*,before_attempt):
            before_attempt();calls.append(messages)
            blocks=json.loads(messages[2]['content'])['blocks']
            assert len(blocks)==1 and lesson in blocks[0]['content']
            citation=blocks[0]['citation_id']
            return Completion(json.dumps({'status':'answered','answer':'课程规则说明。'+citation,
                                          'used_source_ids':[citation]},ensure_ascii=False))

    monkeypatch.setattr('backend.v2.services.rag_service.build_provider',lambda *a,**kw:Reference())
    response=env['client'].post('/api/v2/rag/ask',json={'query':query,
        'knowledge_base_ids':[env['kb']['id']], 'retrieval_mode':'bm25','rerank':'off'},
        headers=csrf_headers(env['client']))
    assert response.status_code==200,response.text
    body=response.json()
    assert body['status']=='answered' and body['reason'] is None
    assert len(calls)==1 and len(body['sources'])==1
    assert body['tree_visualization'] is not None
    assert body['tree_visualization']['source_citations']==[body['sources'][0]['citation_id']]
