"""Focused regressions derived from the midterm QA descriptions."""
import pytest

from backend.v2.services.conversation_context import plan
from backend.v2.services.verified_trees import calculate, unverified_tree_prose
from backend.v2.tests.test_conversation_context import turn

import json
from pathlib import Path

QUESTIONS = json.loads((Path(__file__).parent / 'fixtures/midterm_questions.json').read_text())
FOLLOWUPS = [(case, *QUESTIONS[case]) for case in ('M02', 'M07', 'M09', 'M10', 'M11')]

@pytest.mark.parametrize('case,first,question', FOLLOWUPS, ids=[row[0] for row in FOLLOWUPS])
def test_named_question_does_not_need_disambiguation(case, first, question):
    for history in [(), (turn(first),)]:
        resolved = plan(question, history, 2000)
        assert resolved.reason is None and resolved.query == question


def test_attribution_does_not_hide_a_real_reference():
    history = (turn('比较顺序存储和链式存储。'),)
    assert plan('你刚才提到的那个结构，它有什么缺点？', history, 2000).reason == 'conversation_context_ambiguous'
    assert plan('它为什么适合稠密图？', (turn('Prim 算法是什么？'),), 2000).query == 'Prim为什么适合稠密图？'


def test_bst_theory_allows_numeric_traversals_but_not_unverified_structure():
    query = '二叉搜索树的中序遍历可以得到递增序列。如果中序遍历结果为 2、4、6、8、10，能否确定具体结构？为什么？'
    assert calculate(query) == (None, None)
    assert not unverified_tree_prose('中序为 2、4、6、8、10。不同形态的 BST 可以得到相同的递增序列。')
    assert not unverified_tree_prose('前序：2、4、6。后序是 6、4、2。')
    assert unverified_tree_prose('中序为 2、4、6；根为 4，左孩子为 2，右孩子为 6。')
    assert unverified_tree_prose('插入序列为 2、4、6。')
    assert unverified_tree_prose('```text\n  4\n / \\\n2   6\n```')
    assert calculate('已知 BST 的中序遍历序列为 2、4、6，请构造这棵树。')[1] == 'missing_operation_sequence'


def test_traversal_calculates_postorder_and_checks_zero_based_index():
    from backend.v2.services.answer_validation import AnswerValidationError
    from backend.v2.services.traversal_check import calculate_traversal

    check = calculate_traversal(QUESTIONS['Q06'][0])
    assert (check.root, check.root_index, check.postorder) == ('A', 3, 'DEBCA')
    check.validate('根 A 在中序的下标为 3。[S1] 后序序列：D、E、B、C、A。')
    with pytest.raises(AnswerValidationError, match='traversal_index_mismatch'):
        check.validate('根 A 在中序的下标为 4。[S1] 后序序列：DEBCA。')
    with pytest.raises(AnswerValidationError, match='traversal_result_mismatch'):
        check.validate('后序序列：DBECA。[S1]')
    assert calculate_traversal('前序为ABC，中序为CAB，求后序。') is None
    other = calculate_traversal('前序为XYZ，中序为YXZ，求后序。')
    assert other.postorder == 'YZX' and other.root_index == 1


def test_focus_uses_retrieved_evidence_and_preserves_explicit_comparison():
    from backend.v2.services.evidence_policy import focused_evidence

    graph = {'content': '邻接矩阵需要 n² 个单元；邻接表需要 n 个表头和与边数成正比的边结点。'}
    tree = {'content': '完全二叉树可用顺序存储，普通二叉树可能浪费空间。'}
    leaf = {'content': 'B+树的叶子结点依关键字顺序相连，可区间遍历。'}
    index = {'content': 'B+树非叶结点保存索引。'}
    assert focused_evidence(QUESTIONS['Q07'][0], [tree, graph]) == [graph]
    assert focused_evidence(QUESTIONS['M12'][1], [index, leaf]) == [leaf]
    assert focused_evidence('比较邻接表和二叉树的存储方式', [tree, graph]) == [tree, graph]
    assert focused_evidence(QUESTIONS['Q07'][0], [tree]) == []


def test_pointer_question_requires_explanation_unless_implementation_requested():
    from backend.v2.services.evidence_policy import has_implementation, pointer_explanation_only

    assert pointer_explanation_only(QUESTIONS['M04'][1])
    assert pointer_explanation_only('删除单链表的第一个结点应该如何处理？')
    assert not pointer_explanation_only('给出有头结点单链表删除第一个结点的 C 代码。')
    assert has_implementation('Node* q = *head; *head = q->next; free(q);')
    assert not has_implementation('有哨兵时修改它的 next。无哨兵时更新首元指针。')


def test_fixed_c_list_fixture_compiles_and_runs(tmp_path):
    import shutil
    import subprocess

    compiler = shutil.which('cc')
    if compiler is None:
        pytest.skip('C compiler unavailable')
    fixture = Path(__file__).parent / 'fixtures/list_delete_first.c'
    executable = tmp_path / 'list_delete_first'
    subprocess.run([compiler, '-std=c11', '-Wall', '-Wextra', '-Werror',
                    str(fixture), '-o', str(executable)], check=True, timeout=15)
    subprocess.run([str(executable)], check=True, timeout=5)

@pytest.mark.parametrize('name,expected', [
    ('Prim算法', 'Prim'),
    ('Kruskal算法', 'Kruskal'),
    ('WPL计算', '带权路径长度'),
])
def test_latin_course_terms_adjacent_to_chinese_are_explicit(name, expected):
    from backend.v2.services.conversation_context import topics

    assert topics('请解释' + name + '的原理。') == [expected]
    query = '你刚才说' + name + '的基本原则是什么？'
    assert plan(query, (), 2000).reason is None
    assert plan(query, (turn('什么是栈？'),), 2000).reason is None


def test_latin_course_term_ascii_boundaries_remain_strict():
    from backend.v2.services.conversation_context import topics

    assert 'Prim' not in topics('XPrim算法')
    assert 'Kruskal' not in topics('Kruskal123算法')
    assert '带权路径长度' not in topics('WPL_EXTRA')
    assert topics('Prim算法和Kruskal算法有什么区别？') == ['Prim', 'Kruskal']
