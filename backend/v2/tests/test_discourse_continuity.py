"""User-discourse reference answers, independent of model prose and old citations."""
import json
import pytest

from backend.v2.services.conversation_context import plan, topics
from backend.v2.services.prompt_builder import build_prompt
from backend.v2.tests.test_conversation_context import turn
from backend.v2.tests.test_rag import settings

FOUR = ['AVL树是什么？它与普通BST有什么区别？', '它为什么需要旋转？',
        '举一个LR型失衡的例子，画出旋转前后的树形。', '那它和红黑树有什么区别？']


def chain(questions):
    turns = []
    for query in questions:
        resolved = plan(query, tuple(turns[-3:]), 2000)
        assert resolved.reason is None, (query, resolved.reason)
        turns.append(turn(query, answer='改成BST和Hoare，[S999]。错误树图：根2左1右3。', resolved_query=resolved.query))
    return turns


def test_four_round_main_subject_survives_operation_and_new_comparand():
    turns = chain(FOUR)
    assert turns[1].resolved_query == 'AVL 树为什么需要旋转？'
    assert turns[2].resolved_query.startswith('AVL 树：举一个LR型失衡')
    assert turns[3].resolved_query.startswith('比较 AVL 树 与 红黑树：')
    assert 'BST和Hoare' not in turns[3].resolved_query
    # Definition fell outside the bounded window; the saved server resolution maintains focus.
    fifth = plan('它的查找复杂度呢？', tuple(turns[-3:]), 2000)
    assert fifth.query == 'AVL 树的查找复杂度呢？'


@pytest.mark.parametrize('first,expected', [
    ('红黑树是什么？它与AVL树有什么区别？', '红黑树'),
    ('现在讨论红黑树，它与AVL树有什么区别？', '红黑树'),
    ('AVL树是什么？它与普通BST有什么区别？', 'AVL 树'),
    ('普通BST是什么？它与AVL树有什么区别？', '二叉搜索树'),
])
def test_primary_subject_not_the_latest_comparison_noun(first, expected):
    assert plan('它的特点是什么？', (turn(first),), 2000).query == expected + '的特点是什么？'


def test_explicit_switch_and_symmetric_ambiguity_end_the_old_focus():
    old = chain(FOUR[:2])
    switched = turn('换个话题，介绍红黑树')
    assert plan('它有什么特点？', tuple(old + [switched]), 2000).query == '红黑树有什么特点？'
    unknown = turn('换个话题，介绍哈希函数')
    assert plan('它为什么需要旋转？', tuple(old + [unknown]), 2000).reason == 'conversation_context_ambiguous'
    assert plan('换个话题，它怎么样？', tuple(old), 2000).reason == 'conversation_context_ambiguous'
    for question in ('比较AVL树和红黑树', 'AVL树是什么？红黑树是什么？', 'Lomuto和Hoare有什么区别？'):
        assert plan('它有什么特点？', (turn(question),), 2000).reason == 'conversation_context_ambiguous'
    assert plan(FOUR[2], (turn('红黑树是什么？'),), 2000).reason == 'conversation_context_ambiguous'
    assert plan(FOUR[2], (), 2000).reason == 'conversation_context_required'
    assert topics('red-black tree 和 RB tree') == ['红黑树']


@pytest.mark.parametrize('followup', ['最好呢？', '平均呢？', '最坏情况下呢？'])
def test_partition_variant_and_original_user_conditions_survive_followup(followup):
    task = '快速排序用数组[3,1,2]演示Lomuto分区，规定最后一个元素为基准，下标从0开始。'
    first = turn(task, answer='改成Hoare，基准是第一个，下标1。')
    second = plan(followup, (first,), 2000)
    assert second.reason is None
    data = json.loads(second.query.split('；用户原题条件（不作为证据）：', 1)[1])
    assert data == {'partition_variant': 'lomuto', 'untrusted_user_task': task}
    assert 'Hoare' not in second.query
    history = (turn(followup, resolved_query=second.query),)
    assert task in plan('它的空间复杂度呢？', history, 2000).query
    changed = plan('改讲归并排序的复杂度', (first,), 2000)
    assert changed.turns == () and 'Lomuto' not in changed.query


def test_history_is_untrusted_and_only_new_evidence_can_be_cited():
    turns = chain(FOUR[:3])
    resolved = plan(FOUR[3], tuple(turns), 2000)
    context = {'context_text': json.dumps([{'citation_id':'[S1]', 'content':'自编AVL与红黑树规则。', 'source':{}}])}
    prompt = build_prompt(FOUR[3], 'qa', context, settings(), history=resolved.prompt_history(), resolved_query=resolved.query)
    assert json.loads(prompt[2]['content'])['blocks'] == [{'citation_id':'[S1]', 'content':'自编AVL与红黑树规则。'}]
    assert json.loads(prompt[3]['content'])['type'] == 'untrusted_conversation'
    assert '[S999]' not in prompt[3]['content']
    assert '错误树图' not in prompt[0]['content']
