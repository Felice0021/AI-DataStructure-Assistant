"""Self-authored finite rule grammar examples, not copied course records."""
import pytest
from backend.v2.services.tree_rule_evidence import rule_supported
from backend.v2.services.verified_trees import calculate

LR='LR型失衡：左孩子的右子树插入，先对左孩子左旋转为LL，再整体右旋；属于双旋。'
RL='RL型失衡：右孩子的左子树插入，先对右孩子右旋转为RR，再整体左旋；属于双旋。'


@pytest.mark.parametrize('kind,rule',[('LR',LR),('RL',RL)])
def test_standalone_complete_rule_has_typed_support_without_an_avl_sentence_subject(kind,rule):
    calc,reason=calculate('AVL 的'+kind+'旋转请举例。')
    assert reason is None
    support=rule_supported(calc,rule)
    assert support.kind=='principle_only' and support.usable
    assert support.matched==() and support.scope=='general'
    rendered=calc.render('[S1]',supports={'[S1]':support})
    assert '课程资料支持的原理' in rendered and '[S1]' in rendered
    assert '服务端算法' in rendered and '不是运行用户代码' in rendered


@pytest.mark.parametrize('bad',[
    LR.replace('右子树','左子树'),LR.replace('先对左孩子','先对右孩子'),
    LR.replace('左旋转为LL','右旋转为LL'),LR.replace('转为LL','转为RR'),
    LR.replace('整体右旋','整体左旋'),
])
def test_wrong_case_path_target_order_or_intermediate_is_not_a_reference(bad):
    calc,_=calculate('AVL 的LR旋转请举例。')
    assert rule_supported(calc,bad).kind=='conflict'


@pytest.mark.parametrize('bad',[
    LR.replace('先对','不能先对'),LR.replace('先对','如果先对'),
    LR.replace('再整体右旋','再采用未知操作'),
    'LR型失衡：左旋右旋。',
])
def test_unknown_or_conditional_declarations_are_not_promoted_to_support(bad):
    calc,_=calculate('AVL 的LR旋转请举例。')
    assert rule_supported(calc,bad).kind=='unrecognized'


def test_headings_import_json_and_other_rotation_alone_do_not_support_lr():
    calc,_=calculate('AVL 的LR旋转请举例。')
    assert not rule_supported(calc,'LR旋转课程标题。').usable
    assert not rule_supported(calc,'{"section":"AVL LR旋转规则"}').usable
    assert not rule_supported(calc,RL).usable
    assert rule_supported(calc,'# V1:synthetic-rule\n{"section":"import metadata"}\n'+LR).usable


def test_lr_exact_shape_global_order_balance_and_set_are_verified():
    calc,_=calculate('AVL 的LR旋转请举例。')
    assert calc.keys==(30,10,20)
    assert calc.rotations[0]['before']=={'key':30,'left':{'key':10,'left':None,'right':{'key':20,'left':None,'right':None}},'right':None}
    assert calc.final=={'key':20,'left':{'key':10,'left':None,'right':None},'right':{'key':30,'left':None,'right':None}}
    assert calc.checks['inorder']==[10,20,30]
    assert all(abs(v)<=1 for v in calc.checks['balance_factors'].values())
    rendered=calc.render('[S1]',supports={'[S1]':rule_supported(calc,LR)})
    assert '先对结点10左旋，再对结点30右旋' in rendered


def test_rule_citation_guidance_filters_model_input_only_and_respects_budget():
    import json
    from backend.v2.core.errors import AuthError
    from backend.v2.services.prompt_builder import build_prompt
    from backend.v2.tests.test_rag import settings
    context={'context_text':json.dumps([{'citation_id':'[S1]','content':LR,'source':{}},
                                       {'citation_id':'[S2]','content':'另一篇课程标题','source':{}}])}
    messages=build_prompt('AVL的LR旋转请举例','qa',context,settings(),rule_citations=('[S1]',))
    assert '已核验的规则来源：[S1]。' in messages[0]['content']
    assert [b['citation_id'] for b in json.loads(messages[2]['content'])['blocks']]==['[S1]']
    assert len(json.loads(context['context_text']))==2  # Original publication snapshots are intact.
    limit=len(json.dumps(messages,ensure_ascii=False,separators=(',',':')).encode())-1
    with pytest.raises(AuthError):build_prompt('AVL的LR旋转请举例','qa',context,settings(generation_max_input_bytes=limit),rule_citations=('[S1]',))
