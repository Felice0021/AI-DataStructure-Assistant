from collections import Counter
from dataclasses import replace
from itertools import product
import json
import pytest

from backend.v2.services.verified_partition import calculate,prepare,source_support,PartitionError
from backend.v2.services.answer_validation import AnswerValidationError
from backend.v2.core.errors import AuthError

QUERY='请详细讲解快速排序的基本思想，并用数组[3,1,2]演示一次Lomuto分区。规定最后一个元素为基准，数组下标从0开始。'
RULE='快速排序先按基准分区，再递归处理两侧子数组。Lomuto分区以末元素为pivot，从左到右把小于等于pivot的元素交换到前部，再把pivot交换到分界位置。'
COMPLEXITY='一次Lomuto分区在最好、平均和最坏情况下时间均为O(n)，辅助空间为O(1)。完整快速排序最好时间O(n log n)，随机输入假设下平均O(n log n)，最坏O(n²)。常规递归实现栈空间平均O(log n)，最坏O(n)。'
HOARE='Hoare分区使用左右双向扫描交换错位元素，返回分界下标，不保证基准归位。'


def evidence(text=RULE):return [{'citation_id':'[S1]','content':text}]


def test_exact_lomuto_states_and_positions_not_hoare():
    r=calculate([3,1,2])
    assert [s['array'] for s in r.steps]==[(3,1,2),(1,3,2),(1,2,3)]
    assert [s['swap'] for s in r.steps]==[None,(0,1),(1,2)]
    assert [s['pivot_index'] for s in r.steps]==[2,2,1]
    assert r.final==(1,2,3) and r.pivot_index==1
    plan,reason=prepare(QUERY,evidence())
    assert reason is None and plan.calculation==r
    answer=plan.finish('课程中的Lomuto规则 [S1]',['[S1]'])
    assert '最终数组：[1, 2, 3]；基准最终下标：1' in answer
    assert '输入数组、基准选择和下标0来自用户题设' in answer
    assert '没有编译或运行用户代码' in answer and '服务端参考算法' in answer
    assert '快速排序的基本思想' in answer and '[S1]' in answer


def test_all_small_duplicate_negative_inputs_satisfy_independent_invariants():
    for size in range(1,6):
        for values in product((-1,0,1),repeat=size):
            r=calculate(values);r.validate();p=values[-1]
            assert Counter(r.final)==Counter(values) and r.final[r.pivot_index]==p
            assert all(x<=p for x in r.final[:r.pivot_index])
            assert all(x>p for x in r.final[r.pivot_index+1:])
            assert all(Counter(s['array'])==Counter(values) for s in r.steps)
    with pytest.raises(PartitionError):calculate([])
    with pytest.raises(PartitionError):calculate([0]*33)


@pytest.mark.parametrize('field,value',[('array',(1,3,2)),('pivot_index',0),('boundary',1),('swap',(0,1))])
def test_corrupt_intermediate_states_are_detected(field,value):
    r=calculate([3,1,2]);steps=list(r.steps);steps[0]=dict(steps[0],**{field:value})
    with pytest.raises(PartitionError):replace(r,steps=tuple(steps)).validate()


def test_corrupt_final_state_cannot_be_published():
    r=calculate([3,1,2])
    for invalid in (replace(r,final=(1,3,2)),replace(r,pivot_index=2),replace(r,original=())):
        with pytest.raises(PartitionError):invalid.validate()


@pytest.mark.parametrize('query,reason',[
    (QUERY.replace('Lomuto','Hoare'),'partition_variant_not_supported'),
    (QUERY.replace('Lomuto','Lomuto或Hoare'),'partition_variant_ambiguous'),
    (QUERY.replace('最后一个元素为基准','第一个元素为基准'),'partition_conditions_required'),
    (QUERY.replace('数组下标从0开始','数组下标从1开始'),'partition_conditions_required'),
    (QUERY.replace('数组下标从0开始',''),'partition_conditions_required'),
    (QUERY.replace('[3,1,2]','[3,1.5,2]'),'partition_input_required'),
    (QUERY.replace('[3,1,2]','[]'),'partition_input_required'),
    (QUERY+'严格小于基准才交换。','partition_convention_not_supported'),
])
def test_input_and_conventions_are_not_silently_replaced(query,reason):
    assert prepare(query,evidence())==(None,reason)


def test_source_variant_and_specific_rules_are_required():
    assert prepare(QUERY,evidence(HOARE))[1]=='partition_rule_evidence_required'
    assert prepare(QUERY,evidence('Lomuto分区课程标题。'))[1]=='partition_rule_evidence_required'
    assert prepare(QUERY,evidence(RULE.replace('末元素','首元素')))[1]=='partition_rule_conflict'
    assert prepare(QUERY,evidence(RULE+'Lomuto分区不以最后元素为基准。'))[1]=='partition_rule_unverified'
    assert source_support(HOARE)=='insufficient'
    assert source_support(HOARE,'hoare')=='complete'
    plan,_=prepare(QUERY,evidence()+[{'citation_id':'[S2]','content':HOARE}])
    with pytest.raises(AnswerValidationError,match='partition_rule_citation_required'):
        plan.finish('Lomuto规则[S1][S2]',['[S1]','[S2]'])
    with pytest.raises(AnswerValidationError,match='partition_variant_substitution'):
        plan.finish('改用Hoare完成[S1]',['[S1]'])


def test_existing_bare_array_reference_and_complete_atomic_source_rules():
    from backend.v2.tests.test_problem_solving import CASES
    case=next(c for c in CASES if c['id']=='quicksort')
    for source in (case['lesson'],case['rules']):
        p,reason=prepare(case['query'],evidence(source))
        assert reason is None and p.calculation.final==(1,2,3) and p.calculation.pivot_index==1
    assert prepare(case['query'].replace('最后元素2','最后元素3'),evidence())[1]=='partition_pivot_mismatch'


def test_complexity_keeps_variant_and_distinguishes_partition_from_whole_sort():
    query='Lomuto分区的最好、平均、最坏复杂度呢？'
    plan,reason=prepare(query,evidence(RULE+COMPLEXITY))
    assert reason is None and plan.calculation is None
    draft='一次Lomuto分区均O(n)，辅助O(1)；完整快排最坏O(n²)，不能混为一谈。[S1]'
    assert plan.finish(draft,['[S1]'])==draft
    with pytest.raises(AnswerValidationError):plan.finish('Hoare的复杂度。[S1]',['[S1]'])
    assert prepare('Lomuto与Hoare的原理有什么区别？',evidence())==(None,None)
    resolved='快速排序最坏呢；用户原题条件（不作为证据）：'+json.dumps({'partition_variant':'lomuto','untrusted_user_task':QUERY},ensure_ascii=False)
    carried,_=prepare(resolved,evidence(),user_query='最坏呢？')
    assert carried.calculation is None and carried.variant=='lomuto'


def test_added_control_instructions_respect_the_generation_input_budget():
    plan,_=prepare(QUERY,evidence())
    with pytest.raises(AuthError):plan.instruct([{'role':'system','content':'base'}],20)
