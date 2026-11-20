"""Run the two QA matrices through isolated HTTP/PG with controlled generation."""
import json
import os

import pytest

from backend.v2.services.generation_provider import Completion
from backend.v2.services.verified_trees import unverified_tree_prose
from backend.v2.tests.test_context_turns import conversation, send
from backend.v2.tests.test_ingestion import setup, upload
from backend.v2.tests.test_midterm_regressions import FOLLOWUPS, QUESTIONS
from backend.v2.worker import run_once as parse_once
from backend.v2.embedding_worker import run_once as index_once

pytestmark = [pytest.mark.integration, pytest.mark.skipif(
    os.getenv('DS_V2_RUN_DB_TESTS') != '1', reason='Isolated PostgreSQL')]

# Self-authored small evidence set. These are retrieval inputs, not response fixtures.
LESSONS = [
    '栈遵循后进先出 LIFO，A、B、C 依次入栈后先出 C 再出 B。队列遵循先进先出 FIFO。',
    '逻辑结构是元素关系；存储结构是计算机表示方法。线性表顺序存储查找第 i 个元素用地址计算 O(1)，链式存储顺链查找 O(n)。',
    '顺序表中间插入元素时，需要把插入位置及其后的元素后移。已有5个元素且在第3个位置插入，第3、4、5个元素都要移动。',
    '单链表删除数据结点需重连其前驱 next。有头结点时更新头结点的 next，保留头结点；无头结点时更新首元指针。空表直接返回，单元素删除后无数据结点。',
    '二叉搜索树 BST 左子树键小于根，右子树键大于根。二叉搜索树的中序遍历递增，但不同结构可有相同的中序。',
    '二叉树前序或先序遍历按根、左、右，中序按左、根、右，后序按左、右、根。先序与后序通常不能区分单孩子左右位置。',
    '图邻接矩阵适合稠密图，空间复杂度 O(n²)。邻接表适合稀疏图，n 个顶点表头与 O(e) 条边结点合计 O(n+e)。',
    'DFS 深度优先使用栈，BFS 广度优先使用队列；图遍历标记已访问顶点。BFS 分层扩展保证无权图最短路径，DFS 不按距离扩展。',
    '最小生成树的 Prim 从已选集合向未选顶点选最小边，邻接矩阵实现时间 O(n²)，适合稠密图。Kruskal 按全图边权顺序选择不同连通分量之间的边。',
    '哈夫曼树每步合并最小的两个权值，2 和 3 得到 5。WPL 带权路径长度为各叶权重乘以深度之和。',
    '散列表用散列函数定位；冲突时可用链地址法或开放定址法。线性探测检查下一个槽位并对容量取模，直到空槽或穷尽表。',
    'B树是多路平衡查找树。B+树内部结点作为索引，记录在叶子结点，叶子按键顺序链接可支持范围查询。',
    '二叉树的顺序存储空间复杂度可能受树形影响；这里讨论二叉树顺序存储。',
]
TERMS = ('LIFO', '存储结构', '后移', '数据结点需重连', '中序遍历递增',
         '按左、右、根', 'O(n+e)', 'BFS 分层', 'Kruskal', 'WPL', '线性探测', '按键顺序链接')


def seed(env):
    settings = env['settings']
    settings.embedding_provider = 'deterministic'
    settings.embedding_allow_test_provider = True
    for i, lesson in enumerate(LESSONS):
        upload(env, name=f'midterm-original-{i}.txt', data=lesson.encode())
        assert parse_once(env['factory'], settings)
        assert index_once(env['factory'], settings)


def test_qa_matrices_through_retrieval_and_validated_persistence(setup, monkeypatch):
    env = setup
    env['settings'].generation_validation_retries = 1
    env['settings'].generation_max_calls = 2
    seed(env)
    expected = []
    invalid = set()
    attempts = []

    class Controlled:
        model = 'midterm-test-double'

        def generate(self, messages, *, before_attempt):
            before_attempt()
            case, question = expected[-1]
            blocks = json.loads(messages[2]['content'])['blocks']
            if case in {'Q07', 'M07'}:
                assert all('二叉树' not in block['content'] for block in blocks)
            term = TERMS[int(case[1:]) - 1]
            block = next((block for block in blocks if term in block['content']), None)
            assert block is not None, (case, [b['citation_id'] for b in blocks])
            cite = block['citation_id']
            answer = block['content'].strip()
            if case in {'Q06', 'M06'} and '求' in question and '求出' not in question:
                answer = '根 A 在中序下标为 3。后序序列：DEBCA。'
                if 'Q06' == case and case not in invalid:
                    invalid.add(case)
                    answer = answer.replace('标为 3', '标为 4')
            if case == 'M04' and question == QUESTIONS[case][1] and case not in invalid:
                invalid.add(case)
                answer = 'Node* q = *head; *head = q->next; free(q);'
            if case in {'Q05', 'M05'}:
                answer = '中序为 2、4、6、8、10。不同形态的 BST 可以具有相同中序序列。'
            if case == 'M05' and question == QUESTIONS['M05'][1]:
                invalid.add('M05')
                answer = 'BST 的根结点为4，左孩子为2，右孩子为6。'
            attempts.append((case, question))
            return Completion(json.dumps({'status': 'answered', 'answer': answer + cite,
                                          'used_source_ids': [cite]}, ensure_ascii=False))

    monkeypatch.setattr('backend.v2.services.rag_service.build_provider', lambda *a, **kw: Controlled())

    def check(case, questions):
        url = conversation(env)
        for question in questions:
            expected.append((case, question))
            response, _ = send(env, url, question)
            assert response.status_code == 200, (case, response.json().get('reason'))
            result = response.json()
            assert result['status'] == 'answered', (case, result.get('reason'))
            if case == 'M05' and question == QUESTIONS['M05'][1]:
                assert result['reason'] == 'bst_inorder_theory_fallback'
                assert '不能唯一确定' in result['answer']
                assert not unverified_tree_prose(result['answer'])
            assert all(src['citation_id'] in result['answer'] and src['knowledge_base_id'] == env['kb']['id']
                       for src in result['sources']) and result['sources']
        items = env['client'].get(url + '/messages').json()['items']
        assert len(items) == 2 * len(questions), case

    for case, questions in QUESTIONS.items():
        check(case, questions)
    for case, _, followup in FOLLOWUPS:
        check(case, [followup])
    assert len(attempts) == 43
    assert invalid == {'M04', 'Q06', 'M05'}


def test_bst_fallback_rejects_bad_citations_and_stale_evidence(setup, monkeypatch):
    from sqlalchemy import text

    env = setup
    env['settings'].embedding_provider = 'deterministic'
    env['settings'].embedding_allow_test_provider = True
    record = upload(env, name='bst-theory.txt', data='二叉搜索树的中序遍历结果严格递增。'.encode())
    assert parse_once(env['factory'], env['settings']) and index_once(env['factory'], env['settings'])
    url = conversation(env)
    question = QUESTIONS['M05'][1]

    class RejectedDraft:
        model = 'bst-fallback-test'
        stale = False

        def generate(self, messages, *, before_attempt):
            before_attempt()
            if self.stale:
                cite = json.loads(messages[2]['content'])['blocks'][0]['citation_id']
                with env['engine'].begin() as connection:
                    connection.execute(
                        text('UPDATE documents SET index_revision = index_revision + 1 WHERE id = :id'),
                        {'id': record['id']},
                    )
            else:
                cite = '[S99]'
            return Completion(json.dumps({
                'status': 'answered', 'answer': '根结点为4。' + cite, 'used_source_ids': [cite],
            }, ensure_ascii=False))

    provider = RejectedDraft()
    monkeypatch.setattr('backend.v2.services.rag_service.build_provider', lambda *a, **kw: provider)
    invalid, _ = send(env, url, question)
    assert invalid.status_code == 502 and invalid.json()['reason'] == 'invalid_citations'
    provider.stale = True
    stale, _ = send(env, url, question)
    assert stale.status_code == 409 and stale.json()['error']['code'] == 'context_stale'
    assert env['client'].get(url + '/messages').json()['items'] == []
