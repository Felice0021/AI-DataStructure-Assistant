import json
from pathlib import Path
import re

import pytest
from backend.v2.services.evidence_policy import resolve_mode, task_kind, preflight
from backend.v2.services.prompt_builder import build_prompt
from backend.v2.services.answer_validation import validate_answer, AnswerValidationError
from backend.v2.tests.test_rag import settings, draft

CASES=json.loads((Path(__file__).parent/'fixtures/problem_reference_cases.json').read_text())['cases']

@pytest.mark.parametrize('case',CASES,ids=[c['id'] for c in CASES])
def test_reference_task_modes_and_missing_inputs(case):
    assert resolve_mode(case['query'],'auto') == case['mode']
    if case['expected_reason']:
        evidence=[] if case['expected_reason']=='no_evidence' else [{'content':case['lesson']}]
        assert preflight(case['query'],evidence) == case['expected_reason']


def test_task_prompts_and_code_not_executed():
    context={'context_text':'[]'}
    for query,kind,expected in [('解释BFS算法过程','algorithm','时间/空间复杂度'),('画出AVL树','exercise','等宽树形图'),('代码纠错','code','未编译、未运行')]:
        assert task_kind(query)==kind
        prompt=build_prompt(query,resolve_mode(query,'auto'),context,settings())
        assert expected in prompt[0]['content']
        assert str(settings().generation_max_output_tokens)+' token' in prompt[0]['content']
    assert resolve_mode('AVL树是什么','auto')=='qa'
    assert resolve_mode('指针是什么','auto')=='qa'
    assert resolve_mode('模拟插入3,2,1','auto')=='exercise'
    assert resolve_mode('递归终止条件是否正确','auto')=='code'


@pytest.mark.parametrize('answer',['我已编译并运行[S1]','程序已成功编译[S1]','该版本已通过编译[S1]','I have compiled the code[S1]','虚构依据[S9]'])
def test_compile_claims_and_wrong_citations_rejected(answer):
    with pytest.raises(AnswerValidationError):validate_answer(draft(answer),[{'citation_id':'[S1]'}])
    assert validate_answer(draft('以下仅静态分析，未编译、未运行[S1]'),[{'citation_id':'[S1]'}])==['[S1]']


def test_reference_processes_exactly():
    stack=[];popped=[]
    for op,value in [('push',1),('push',2),('pop',None),('push',3),('pop',None),('pop',None)]:
        if op=='push':stack.append(value)
        else:popped.append(stack.pop())
    assert popped==[2,3,1]
    graph={'A':['B','C'],'B':['D'],'C':['D'],'D':[]}
    queue=['A'];seen={'A'};bfs=[]
    while queue:
        node=queue.pop(0);bfs.append(node)
        for target in graph[node]:
            if target not in seen:seen.add(target);queue.append(target)
    dfs=[]
    def visit(node):
        if node in dfs:return
        dfs.append(node)
        for target in graph[node]:visit(target)
    visit('A')
    assert bfs==list('ABCD') and dfs==list('ABDC')
    values=[3,1,2];pivot=values[-1];i=0
    for j in range(len(values)-1):
        if values[j]<=pivot:values[i],values[j]=values[j],values[i];i+=1
    values[i],values[-1]=values[-1],values[i]
    assert values==[1,2,3] and i==1
