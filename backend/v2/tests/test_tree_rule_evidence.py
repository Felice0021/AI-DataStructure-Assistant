"""Finite textbook convention recognition; numerical calculation golds stay unchanged."""
import pytest
from backend.v2.services.verified_trees import calculate
from backend.v2.services.tree_rule_evidence import rule_supported

QUERY='构造3阶B+树，最多3孩子、2键，插入10,20,30；溢出左叶前2键，右叶后1键，父节点复制右叶最小键。'
GENERAL='B+树的记录键全部在叶，内部键用于导航。所有叶子必须同层。'
EXPLICIT=GENERAL+'B+树内部结点最多3个孩子，内部结点最多2个键，叶结点最多2个键。溢出左叶保留2键，右叶保留1键，父结点复制右叶最小键。'


@pytest.mark.parametrize('source,kind',[
    (EXPLICIT,'explicit'),
    (EXPLICIT.replace('B+','b+'),'explicit'),
    (EXPLICIT.replace('左叶保留2键，右叶保留1键','左叶保留1键，右叶保留2键'),'conflict'),
    (GENERAL,'principle_only'),
    ('B+树。分裂。叶。','unrecognized'),
    ('B+树课程只有标题。','insufficient'),
    (GENERAL+'叶结点最多3个键。','conflict'),
    (GENERAL+'父结点复制左叶最大键。','conflict'),
    (GENERAL+'插入前分裂满结点。','conflict'),
    (GENERAL+'如果分裂则左叶保留2键。','unrecognized'),
    (GENERAL+'左叶保留两键，右叶保留一键。','unrecognized'),
    (GENERAL+'不要求左叶保留2键。','unrecognized'),
    (GENERAL+'溢出时左右叶各自保留若干键。','unrecognized'),
    (GENERAL+'B树溢出后提升中间键，取较小中间键。','principle_only'),
])
def test_convention_comparison_uses_values_and_family_scope(source,kind):
    result,_=calculate(QUERY)
    assert rule_supported(result,source).kind==kind
    assert result.final=={'keys':[30],'children':[{'keys':[10,20],'children':[]},{'keys':[30],'children':[]}]}


def test_partial_course_rule_is_not_claimed_as_full_textbook_convention():
    result,_=calculate(QUERY)
    support=rule_supported(result,GENERAL+'父结点复制右叶最小键。')
    assert support.kind=='principle_only' and support.matched==('separator',)
    answer=result.render('[S1]',supports={'[S1]':support})
    assert '课程资料支持的原理：' in answer
    assert '课程资料明确给出的约定：父分隔键=复制右叶最小键 [S1]' in answer
    assert '构造假设来自用户题设' in answer and '分裂左叶键数=2' in answer
    assert '规则依据 [S1]' not in answer


def test_red_black_comparand_rules_do_not_become_avl_conventions():
    result,_=calculate('空AVL树，依次插入30,10,20，画出最终树。')
    source='AVL每个结点左右高度差至多一。旋转保持中序有序及键集合。红黑树不要求左右高度差至多一。'
    support=rule_supported(result,source)
    assert support.kind=='principle_only'
    assert set(support.principles)=={'AVL高度平衡','旋转与有序性规则'}
    assert rule_supported(result,'红黑树不要求左右高度差至多一。').kind=='insufficient'


def test_explicit_agreement_has_precise_attribution_and_conflicts_cannot_render():
    result,_=calculate(QUERY)
    support=rule_supported(result,EXPLICIT)
    assert set(support.matched)==set(result.conventions)
    answer=result.render('[S1]',supports={'[S1]':support})
    assert '课程资料明确给出的约定：' in answer and '分裂左叶键数=2' in answer
    assert '构造假设来自用户题设' not in answer
    assert '引用不代表教材逐项给出了本题结果' in answer
    conflict=rule_supported(result,EXPLICIT.replace('左叶保留2键','左叶保留1键'))
    with pytest.raises(ValueError,match='unsupported_tree_rule_citation'):
        result.render('[S1]',supports={'[S1]':conflict})


def test_each_source_is_assessed_independently_and_contradictions_are_not_overwritten():
    result,_=calculate(QUERY)
    assert rule_supported(result,EXPLICIT+'左叶保留1键。').kind=='conflict'
    bad=rule_supported(result,'B+树课程只有标题。')
    with pytest.raises(ValueError):result.render('[S1] [S2]',supports={'[S1]':rule_supported(result,EXPLICIT),'[S2]':bad})


@pytest.mark.parametrize('query,source,kind',[
    ('构造4阶B树，最多4孩子，插入1,2,3,4；溢出后提升中间键，取较小中间键。','B树内部结点最多4个孩子。溢出后提升较大中间键。','conflict'),
    ('构造4阶B树，最多4孩子，插入1,2,3,4；溢出后提升中间键，取较小中间键。','B树内部结点最多4个孩子。溢出后提升中间键。','unrecognized'),
    ('构造3阶B树，最多3孩子，插入1,2,3；溢出后提升中间键。','B树内部结点最多3个孩子，内部结点最多2个键。溢出后提升中间键。','explicit'),
    ('空AVL树，依次插入30,10,20，画出最终树。','AVL每个结点左右高度差至多一。旋转保持中序有序及键集合。','principle_only'),
    ('从空二叉搜索树构造，依次插入30,10,20，画出结果。','二叉搜索树只要求左小右大。','principle_only'),
])
def test_btree_median_and_original_binary_rules(query,source,kind):
    result,reason=calculate(query)
    assert reason is None and result is not None
    assert rule_supported(result,source).kind==kind


def test_existing_reference_example_is_bound_to_input_and_checked_shape():
    from backend.v2.tests.test_problem_solving import CASES
    case=next(c for c in CASES if c['id']=='bplus')
    result,_=calculate(case['query']);source=case['lesson']
    support=rule_supported(result,source)
    assert support.kind=='explicit' and support.scope=='same_input_example'
    assert '相同输入示例中给出的约定' in result.render('[S1]',supports={'[S1]':support})
    assert rule_supported(result,source.replace('根分隔键30','根分隔键20')).kind=='unrecognized'
    assert rule_supported(result,source.replace('左2右1','左1右2')).kind=='conflict'
    assert rule_supported(result,source.replace('插入10,20,30','插入10,20,40')).kind=='unrecognized'


def test_bplus_leaf_conventions_cannot_be_misattributed_to_btree():
    result,_=calculate('构造3阶B树，最多3孩子，插入1,2,3；溢出后提升中间键。')
    assert rule_supported(result,'B树非叶孩子数比键数多一。左叶保留2键，右叶保留1键。').kind=='unrecognized'
