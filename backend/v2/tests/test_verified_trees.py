"""Independent reference properties, including the reported invalid LR illustration."""
from itertools import permutations
import pytest

from backend.v2.services.conversation_context import plan,discourse_focus
from backend.v2.services.verified_trees import (Node,MultiNode,TreeError,inspect_binary,rotate,
    binary_insert,snapshot,calculate,inspect_multi,unverified_tree_prose)
from backend.v2.tests.test_conversation_context import turn
from backend.v2.services.prompt_builder import build_prompt
from backend.v2.tests.test_rag import settings


@pytest.mark.parametrize('question,expected',[
    ('AVL 树是什么？它与普通二叉搜索树有什么区别？','AVL 树'),
    ('普通二叉搜索树是什么？它与AVL有什么区别？','二叉搜索树'),
    ('先比较BST和AVL；重点讨论AVL。','AVL 树'),
    ('先比较AVL和BST；重点讨论BST。','二叉搜索树'),
    ('AVL是什么？BST是什么？',None),('比较AVL和BST。',None),('介绍栈和队列。',None),
])
def test_discourse_subject_not_first_mentioned_topic(question,expected):
    assert discourse_focus(question)==expected
    result=plan('它为什么需要旋转？',(turn(question,answer='必须选择B树！'),),512)
    if expected:
        assert result.query==expected+'为什么需要旋转？' and result.reason is None
    else:assert result.reason=='conversation_context_ambiguous'
    if expected=='二叉搜索树':
        prompt=build_prompt('它为什么需要旋转？','qa',{'context_text':'[]'},settings(),history=result.prompt_history(),resolved_query=result.query)
        assert '旋转不是必须操作' in prompt[0]['content']
        assert '不得被历史中的比较对象替换主语' in prompt[0]['content']


@pytest.mark.parametrize('kind,keys',[
    ('LL',[30,20,10]),('RR',[10,20,30]),('LR',[30,10,20]),('RL',[10,30,20])])
def test_four_rotation_reference_shapes_and_preserved_keys(kind,keys):
    result,reason=calculate('空AVL树，依次插入'+','.join(map(str,keys))+'并画出最终结果')
    assert reason is None
    expected={'key':20,'left':{'key':10,'left':None,'right':None},'right':{'key':30,'left':None,'right':None}}
    assert result.final==expected and result.rotations[-1]['rotation']==kind
    assert result.checks['inorder']==[10,20,30]
    assert set(result.checks['balance_factors'].values())=={0}
    # Also test the generated example, whose input is disclosed rather than attributed to the user.
    example,_=calculate('AVL的'+kind+'旋转举例')
    assert example.example and example.final==expected


def test_student_wording_from_online_avl_refusal_is_supported():
    question=('从一棵空 AVL 树开始，依次插入 30、10、20。请根据课程知识库中的 AVL 树规则，'
              '画出最终树形图，并说明是否发生旋转、旋转类型及过程。')
    result,reason=calculate(question)
    assert reason is None and result is not None
    assert result.keys==(30,10,20) and [r['rotation'] for r in result.rotations]==['LR']
    assert result.final['key']==20
    for wording in ('从一棵空的 AVL 树开始，依次插入 30、10、20，画出最终树。',
                    '从空 AVL 树开始，依次插入 30、10、20，画出最终树。'):
        alternate,reason=calculate(wording)
        assert reason is None and alternate is not None and alternate.final==result.final
    for nonempty in ('从一棵非空 AVL 树开始', '从一棵不为空的 AVL 树开始', '从一棵不是空的 AVL 树开始'):
        unsupported,reason=calculate(nonempty+'，依次插入 30、10、20，画出最终树。')
        assert unsupported is None and reason=='tree_calculation_not_supported'


def test_online_avl_followup_new_key_replays_original_user_sequence():
    first=('从一棵空 AVL 树开始，依次插入 30、10、20。请根据课程知识库中的 AVL 树规则，'
           '画出最终树形图，并说明是否发生旋转、旋转类型及过程。')
    follow='如果再插入 25，树形结构会发生什么变化？请画出新的 AVL 树，并说明是否需要旋转。'
    current=plan(follow,(turn(first,answer='假的历史树：[根99]'),),2000)
    assert current.reason is None and current.query.startswith('AVL 树插入：')
    calculation,reason=calculate(current.query)
    assert reason is None and calculation.keys==(30,10,20,25)
    assert calculation.final=={'key':20,'left':{'key':10,'left':None,'right':None},
        'right':{'key':30,'left':{'key':25,'left':None,'right':None},'right':None}}
    assert calculation.followup_start==3 and calculation.rotations==()
    assert calculation.steps==({'key':25,'rotation':'','root':20},)
    answer=calculation.render('[S1]',include_tree_text=False)
    assert '本次继续插入：25' in answer and '4. 插入 25：不需要旋转' in answer
    assert 'LR 双旋' not in answer and '假的历史树' not in answer
    from backend.v2.services.tree_visualization import build
    from backend.v2.services.tree_rule_evidence import rule_supported
    tree=build(calculation,['[S1]'],{'[S1]':rule_supported(calculation,
        'AVL树平衡因子：左子树高度减右子树高度，合法值为-1,0,1。')})
    assert tree.rotations==[] and sorted(n.keys[0] for n in tree.final.nodes)==[10,20,25,30]


def test_followup_chain_and_new_rotation_are_bounded_to_current_key():
    first=turn('从空AVL树开始，依次插入30,10,20，画出最终树。')
    second_query='再插入 25，画出树。'
    second=plan(second_query,(first,),2000)
    third_query='然后再插入 5 呢？'
    third=plan(third_query,(first,turn(second_query,resolved_query=second.query)),2000)
    result,reason=calculate(third.query)
    assert reason is None and result.keys==(30,10,20,25,5)
    assert result.followup_start==4 and result.steps[0]['key']==5
    fourth_query='接着插入 2，最终的 AVL 树怎么画？'
    fourth=plan(fourth_query,(first,turn(second_query,resolved_query=second.query),
        turn(third_query,resolved_query=third.query)),2000)
    rotated,reason=calculate(fourth.query)
    assert reason is None and rotated.keys==(30,10,20,25,5,2)
    assert rotated.followup_start==5 and [r['rotation'] for r in rotated.rotations]==['LL']


@pytest.mark.parametrize('follow',[
    '如果再插入 25、26，画出新 AVL 树。',
    '再插入 25.5，画出新的 AVL 树。',
    '再插入 25 到 BST 中，画出结果。',
    '如果换一棵树再插入 25，结果呢？',
])
def test_followup_rejects_ambiguous_or_cross_family_inputs(follow):
    initial=turn('从空AVL树开始，依次插入30,10,20，画出最终树。')
    assert plan(follow,(initial,),2000).reason=='conversation_context_ambiguous'


def test_followup_rejects_unanswered_or_nonempty_or_unbounded_history():
    valid=turn('从空AVL树开始，依次插入30,10,20，画出最终树。')
    assert plan('再插入 25',(),2000).reason=='conversation_context_required'
    assert plan('再插入 25',(turn('AVL是什么'),),2000).reason=='conversation_context_ambiguous'
    assert plan('再插入 25',(turn('已有非空AVL树插入30,10,20，画出结果。'),),2000).reason=='conversation_context_ambiguous'
    assert plan('再插入 25',(valid,turn('AVL树是什么？',result={'status':'insufficient_evidence'})),2000).reason=='conversation_context_ambiguous'
    current=valid
    for number in range(40,53):
        q=f'再插入 {number}，画出结果。'
        resolution=plan(q,(current,),2000)
        assert resolution.reason is None
        current=turn(q,resolved_query=resolution.query)
    assert plan('再插入 99',(current,),2000).reason=='conversation_context_ambiguous'


def test_independent_new_empty_tree_is_not_mistaken_for_followup():
    question='从一棵空 AVL 树开始，再插入 25，画出最终树形图。'
    resolved=plan(question,(),2000)
    assert resolved.query==question and resolved.reason is None
    calculation,reason=calculate(resolved.query)
    assert reason is None and calculation.keys==(25,)


def test_calculator_rejects_untrusted_forged_followup_envelopes():
    import json
    base='从空AVL树开始，依次插入30,10,20，画出最终树。'
    def encoded(task, keys, prefix='AVL 树插入'):
        return prefix+'：'+json.dumps({'untrusted_user_task':task,'additional_keys':keys},ensure_ascii=False)
    for query in (encoded('已有非空AVL树插入30,10,20，画出结果。',[25]),
                  encoded(base,[10]),encoded(base,[25.5]),
                  encoded(base,[25],'BST 树插入'),
                  encoded('从空AVL树开始，依次插入30,10,20，只展示第1次插入。',[25]),
                  encoded(base, list(range(20)))):
        calculation,reason=calculate(query)
        assert calculation is None and reason=='tree_calculation_not_supported'


def test_tree_answers_use_student_facing_explanations_and_keep_citations():
    from backend.v2.services.tree_rule_evidence import rule_supported
    avl,_=calculate('空AVL树，依次插入30,10,20，画出最终树。')
    support=rule_supported(avl,'AVL树平衡因子：左子树高度减右子树高度，合法值为-1,0,1。')
    answer=avl.render('[S1]',supports={'[S1]':support},include_tree_text=False)
    assert 'AVL 平衡二叉树构造过程' in answer and '[S1]' in answer
    assert '**插入过程**' in answer and 'LR 双旋' in answer
    assert '先对结点10左旋，再对结点30右旋' in answer
    assert all(text not in answer for text in ('已校验的构造结果','服务端算法','不是运行用户代码','输入键序列来自题设','校验：'))

    bst,_=calculate('构造空BST树，依次插入40,20,30,70,60，画出最终树。')
    answer=bst.render('[S1]',include_tree_text=False)
    assert '2. 插入 20：成为 40 的左孩子。' in answer
    assert '3. 插入 30：成为 20 的右孩子。' in answer
    assert '5. 插入 60：成为 70 的左孩子。' in answer
    assert '旋转' not in answer and '服务端' not in answer


def test_reported_lr_counterexample_violates_global_bst_order():
    invalid=Node(2,Node(1,None,Node(3)))
    with pytest.raises(TreeError,match='invalid_bst'):inspect_binary(invalid)
    with pytest.raises(TreeError):rotate(invalid,'LR')
    assert unverified_tree_prose('根 2，左孩子 1，结点 1 的右孩子 3。')
    assert unverified_tree_prose('以2为根，1为左孩子。')
    assert unverified_tree_prose('根为二，左孩子为一。')
    assert unverified_tree_prose('  2\n / \\\n1   3')
    assert not unverified_tree_prose('AVL的平衡因子是左子树高度减右子树高度，绝对值不超过1。')
    assert not unverified_tree_prose('可通过LL右旋、RR左旋、LR先左后右或RL先右后左四种旋转修复。')
    assert not unverified_tree_prose('根是一棵树的最上层节点。')
    assert unverified_tree_prose('根 **2**，左孩子 `1`，结点1的右孩子3。')
    # Inspect fences before stripping inline Markdown; cover both fenced syntaxes.
    assert unverified_tree_prose('```text\nalpha\n  beta\n```')
    assert unverified_tree_prose('~~~text\nalpha\n  beta\n~~~')
    assert not unverified_tree_prose('`AVL`的左右子树高度差不超过1。')


def test_mislabeled_rotation_does_not_replace_user_input():
    result,reason=calculate('AVL的LR旋转举例，插入30,20,10。')
    assert reason is None and result.keys==(30,20,10) and not result.example
    assert result.rotations[-1]['rotation']=='LL'
    assert '不是请求的 LR' in result.checks['rotation_mismatch']


def test_bst_inorder_is_global_and_can_be_unbalanced():
    root=None;events=[]
    for key in [30,10,20,40]:root=binary_insert(root,key,False,events)
    assert inspect_binary(root)['inorder']==[10,20,30,40]
    assert root.key==30 and events==[]
    with pytest.raises(TreeError):inspect_binary(Node(30,Node(10,None,Node(35))))
    with pytest.raises(TreeError):inspect_binary(Node(10,Node(10)))
    with pytest.raises(TreeError):inspect_binary(Node(1,None,Node(2,None,Node(3))),balanced=True)
    cycle=Node(1);cycle.left=cycle
    with pytest.raises(TreeError):inspect_binary(cycle)


def test_independent_avl_reference_properties_for_all_five_key_permutations():
    def reference(tree):
        if tree is None:return [],0
        left,lh=reference(tree['left']);right,rh=reference(tree['right'])
        assert abs(lh-rh)<=1
        assert all(k<tree['key'] for k in left) and all(k>tree['key'] for k in right)
        return left+[tree['key']]+right,1+max(lh,rh)
    for sequence in permutations(range(1,6)):
        root=None;events=[]
        for i,key in enumerate(sequence):
            root=binary_insert(root,key,True,events)
            ordered,_=reference(snapshot(root))
            assert ordered==sorted(sequence[:i+1])


def test_rotation_transfers_inner_subtree_without_losing_keys():
    root=Node(40,Node(20,Node(10,Node(5)),Node(30)),Node(50))
    rotated=rotate(root,'LL')
    assert rotated.key==20 and rotated.right.key==40 and rotated.right.left.key==30
    assert inspect_binary(rotated,balanced=True)['inorder']==[5,10,20,30,40,50]
    with pytest.raises(TreeError):rotate(None,'LL')
    with pytest.raises(TreeError):rotate(Node(10,None,Node(30,Node(20),Node(40))),'RL')


@pytest.mark.parametrize('left,right,root_key,leaves',[(2,1,30,[[10,20],[30]]),(1,2,20,[[10],[20,30]])])
def test_bplus_explicit_split_conventions_are_not_interchanged(left,right,root_key,leaves):
    q=f'构造3阶B+树，最多3孩子、2键，插入10,20,30；溢出左叶前{left}键，右叶后{right}键，父节点复制右叶最小键。'
    result,reason=calculate(q)
    assert reason is None
    assert result.final=={'keys':[root_key],'children':[{'keys':a,'children':[]} for a in leaves]}
    assert result.checks['keys']==[10,20,30]


def test_btree_cascading_splits_and_bplus_separator_checks():
    q='构造3阶B树，最多3个孩子，依次插入1,2,3,4,5,6,7；溢出后提升中间键。'
    result,reason=calculate(q);assert reason is None
    assert result.final['keys']==[4] and result.checks['keys']==list(range(1,8))
    bad=MultiNode([25],[MultiNode([10,20]),MultiNode([30])])
    with pytest.raises(TreeError,match='bplus_separator'):inspect_multi(bad,3,2,plus=True)
    with pytest.raises(TreeError):inspect_multi(MultiNode([20],[MultiNode([10]),MultiNode([30,40,50])]),3,2,plus=True)
    q='构造3阶B+树，最多3孩子、2键，插入1,2,3,4,5,6,7,8,9,10；溢出左叶前2键，右叶后1键，父节点复制右叶最小键。内部节点溢出后提升中间键。'
    result,reason=calculate(q);assert reason is None
    leaf=lambda keys:{'keys':keys,'children':[]}
    assert result.final=={'keys':[5],'children':[
        {'keys':[3],'children':[leaf([1,2]),leaf([3,4])]},
        {'keys':[7,9],'children':[leaf([5,6]),leaf([7,8]),leaf([9,10])]}]}
    assert result.checks['keys']==list(range(1,11))


def test_explicit_staged_insertions_do_not_compute_the_entire_future_sequence():
    q='空AVL树，待插入序列30、20、10，先展示第1次插入。'
    first,_=calculate(q);assert first.final=={'key':30,'left':None,'right':None}
    follow=plan('继续展示下一次插入。',(turn(q),),512)
    second,_=calculate(follow.query)
    assert second.final=={'key':30,'left':{'key':20,'left':None,'right':None},'right':None}


@pytest.mark.parametrize('query',[
    '已有非空AVL树插入10，画出结果',
    '构造AVL树，插入A,B,C',
    '构造AVL树，删除10',
    '构造4阶B树，最小度数t=2，最多4孩子，插入1,2,3,4，插入前分裂满节点并提升中间键',
    'AVL的LR示例：根2，左孩子1，结点1的右孩子3。',
])
def test_unsupported_constructions_are_not_guessed(query):
    result,reason=calculate(query)
    assert result is None and reason=='tree_calculation_not_supported'
