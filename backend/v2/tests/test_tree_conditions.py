"""Positive/negative input contracts; no default B/B+ convention is invented."""
import pytest
from backend.v2.services.evidence_policy import missing_conditions
from backend.v2.services.prompt_builder import build_prompt
from backend.v2.tests.test_rag import settings


@pytest.mark.parametrize('query',[
    '画出空AVL树插入10后的结果。',
    '构造AVL树，依次插入10、20、30。',
    '构造AVL树，依次插入10，20，30。',
    '构造AVL树，依次插入10 20 30。',
    '画出空AVL树插入-10后的结果。',
    '构造AVL树，插入Ａ。',
    '解释AVL树插入原理。',
    '如何构造AVL树？',
    '解释三阶B+树插入的一般规则。',
    '描述B树插入算法步骤。',
    '分析B+树插入代码的逻辑错误。',
    '请给一个B+树构造例子。',
    '请自拟三阶B+树插入10、20、30的示例，并标明假设。',
    '画出AVL树示意图。',
    '画出空B树插入10后的结果。',
    '画出空B+树插入10后的结果。',
    '构造3阶B树，插入10、20。',
    '构造3阶B树，结点最多3个孩子，依次插入10、20、30；溢出后提升中间键。',
    '构造4阶B树，结点最多4个孩子，依次插入10、20、30、40；溢出后提升右中位键。',
    '构造B树，最小度数t=2，插入10、20、30、40；插入前分裂满节点并提升中间键。',
    '构造3阶B+树，依次插入10,20,30。约定最多3孩子、2键；溢出左叶保留前2键，右叶后1键，父节点复制右叶最小键。画出结果。',
    '构造3阶B+树，依次插入10 20 30。最多3个孩子，叶最多2键；溢出左叶前1键，右叶后2键，父节点复制右叶最小键。',
    '构造3阶B树，依次插入10,10,20。重复键忽略。',
])
def test_sufficient_inputs_or_explicit_example(query):
    assert missing_conditions(query) is None


@pytest.mark.parametrize('query,reason',[
    ('画出AVL树。','missing_operation_sequence'),
    ('模拟AVL树插入过程并画出结果。','missing_operation_sequence'),
    ('构造AVL树，插入10个元素。','missing_operation_sequence'),
    ('画出B+树依次插入10、20、30后的树。','missing_tree_order'),
    ('示例题：画出B+树依次插入10、20、30后的最终结果。','missing_tree_order'),
    ('构造3阶B树，插入10,20,30。','ambiguous_tree_rules'),
    ('构造3阶B+树，最多3个孩子，插入10,20,30。','ambiguous_tree_rules'),
    ('构造3阶B+树，最多3个孩子，叶最多2键，插入10,20,30。','ambiguous_tree_split'),
    ('构造3阶B+树，最多3孩子、2键，插入10,20,30。溢出左叶前2键，右叶后1键。','ambiguous_tree_split'),
    ('构造3阶B+树，最多3孩子、2键，插入10,20,30。溢出左叶前2键，右叶后2键，父节点复制右叶最小键。','ambiguous_tree_split'),
    ('构造3阶B+树，最多3孩子、2键，插入10,20,30,40,50。溢出左叶前2键，右叶后1键，父节点复制右叶最小键。','ambiguous_tree_split'),
    ('构造4阶B树，最多4个孩子，插入10,20,30,40。溢出后提升中间键。','ambiguous_tree_split'),
    ('构造3阶B树，最多3个孩子，插入10,10。','ambiguous_tree_rules'),
    ('构造3阶B树，最多3个孩子，允许重复键，插入10,10。','ambiguous_tree_rules'),
    ('画出空1阶B树插入10后的结果。','ambiguous_tree_rules'),
    ('已有非空B树插入10，画出结果。','ambiguous_tree_rules'),
    ('构造3阶B树，最多4个孩子，插入10。','ambiguous_tree_rules'),
])
def test_relevant_ambiguities_require_clarification(query,reason):
    assert missing_conditions(query)==reason


def test_tree_prompt_distinguishes_principles_examples_and_concrete_givens():
    prompt=build_prompt('如何构造AVL树？','exercise',{'context_text':'[]'},settings())
    rules=prompt[0]['content']
    assert '一般原理题只说明规则' in rules
    assert '不要求无关分裂条件' in rules
    assert '标注示例、初始状态、规则和假设' in rules
    assert '不替换分裂策略' in rules
