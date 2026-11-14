"""Transport/trace properties and deterministic provenance; no external model calls."""
import copy
import json
from pathlib import Path
import pytest
from pydantic import ValidationError
from backend.v2.schemas.tree import VerifiedTreeVisualization,TreeGraph
from backend.v2.schemas.rag import AskResponse,AnswerDraft
from backend.v2.tests.tree_display_cases import cases,CASES
from backend.v2.services.verified_trees import calculate


@pytest.mark.parametrize('kind',['LL','RR','LR','RL'])
def test_trace_captures_actual_rotation_stages_and_keys(kind):
    dto=cases()[kind];rotation=dto['rotations'][0]
    assert [f['stage'] for f in rotation['frames']]==(['before','intermediate','after'] if len(kind)==2 and kind[0]!=kind[1] else ['before','after'])
    for f in rotation['frames']: assert sorted(n['keys'][0] for n in f['graph']['nodes'])==[10,20,30]
    if kind in {'LR','RL'}:
        nodes={n['id']:n for n in rotation['frames'][1]['graph']['nodes']}
        root=nodes['n0']
        if kind=='LR':
            assert root['keys']==[30] and nodes[root['children'][0]]['keys']==[20]
            assert nodes[nodes[root['children'][0]]['children'][0]]['keys']==[10]
        else:
            assert root['keys']==[10] and nodes[root['children'][1]]['keys']==[20]
            assert nodes[nodes[root['children'][1]]['children'][1]]['keys']==[30]
    assert '```' not in dto['explanation'] and '[S1]' in dto['explanation']
    calculation,_=calculate(CASES[kind])
    assert '```text' in calculation.render('[S1]') # legacy/copy representation preserved
    assert ('第一次旋转后' in calculation.render('[S1]'))==(kind in {'LR','RL'})


def test_browser_fixtures_are_actual_server_calculator_output():
    path=Path(__file__).resolve().parents[3]/'frontend-v2/src/__tests__/fixtures/verified-trees.json'
    assert json.loads(path.read_text())==cases()
    for name,raw in cases().items():
        tree=VerifiedTreeVisualization.model_validate(raw)
        assert tree.family==name if name in {'BST','B','B+'} else tree.family=='AVL'
    sparse=cases()['BST']['final']['nodes']
    assert any(n['children'][0] is None and n['children'][1] is not None for n in sparse)
    assert len(cases()['B']['final']['nodes'])>7 and len(cases()['B+']['final']['nodes'])>7


@pytest.mark.parametrize('mutation',[
    lambda d:d.update(version=True),
    lambda d:d.update(version=1.0),
    lambda d:d.update(svg='<svg onload="alert(1)"/>'),
    lambda d:d['final']['nodes'][0].update(onclick='alert(1)'),
    lambda d:d['final']['nodes'][0].update(keys=['<script>']),
    lambda d:d['final']['nodes'][0].update(keys=[True]),
    lambda d:d['final']['nodes'][0].update(keys=[float('inf')]),
    lambda d:d['final']['nodes'][0].update(keys=[1000000000]),
    lambda d:d['final']['nodes'][0].update(children=['n0',None]),
    lambda d:d['final']['nodes'][0].update(children=['n1','n1']),
    lambda d:d['final']['nodes'][0].update(children=['n63',None]),
    lambda d:d['final']['nodes'].append(copy.deepcopy(d['final']['nodes'][0])),
    lambda d:d['final']['nodes'].append({'id':'n63','keys':[99],'children':[None,None]}),
    lambda d:d['final']['nodes'][1].update(keys=[99]),
    lambda d:d['rotations'][0]['frames'].pop(1),
    lambda d:d['rotations'][0]['frames'][1].update(stage='after'),
    lambda d:d['rotations'][0]['frames'][0]['graph']['nodes'][0].update(keys=[31]),
    lambda d:d.update(source_citations=['[S1]','[S1]']),
    lambda d:d.update(rotations=d['rotations']*17),
    lambda d:d.update(family='B'),
])
def test_invalid_or_injected_structures_fail_closed(mutation):
    raw=copy.deepcopy(cases()['LR']);mutation(raw)
    with pytest.raises(ValidationError):VerifiedTreeVisualization.model_validate(raw)


def test_graph_depth_and_node_bounds():
    nodes=[{'id':f'n{i}','keys':[i],'children':[None,f'n{i+1}' if i<17 else None]} for i in range(18)]
    with pytest.raises(ValidationError):TreeGraph.model_validate({'root':'n0','nodes':nodes})
    with pytest.raises(ValidationError):TreeGraph.model_validate({'root':'n0','nodes':[nodes[0]]*65})
    # A valid per-graph structure can still exceed the aggregate frame budget.
    from backend.v2.services.tree_visualization import graph
    calc,_=calculate('空AVL树，依次插入'+','.join(str(k) for k in range(15))+'，画出最终树。')
    full=graph(calc.final,True)
    raw=copy.deepcopy(cases()['LR']);raw['final']=full
    raw['rotations']=[{'kind':'LR','frames':[{'stage':stage,'graph':full} for stage in ('before','intermediate','after')]}]*16
    with pytest.raises(ValidationError,match='tree_display_limit'):VerifiedTreeVisualization.model_validate(raw)



def test_model_cannot_supply_verified_display_data_and_old_response_is_compatible():
    with pytest.raises(ValidationError):AnswerDraft.model_validate({'status':'answered','answer':'结论[S1]',
        'used_source_ids':['[S1]'],'tree_visualization':cases()['LR']})
    raw=json.loads((Path(__file__).resolve().parents[3]/'docs/v2/fixtures/rag-answered.response.json').read_text())
    raw.pop('tree_visualization')
    assert AskResponse.model_validate(raw).tree_visualization is None
    raw['tree_visualization']=cases()['LR'];assert AskResponse.model_validate(raw).tree_visualization is not None
    raw['status']='insufficient_evidence'
    with pytest.raises(ValidationError):AskResponse.model_validate(raw)
    raw['status']='answered';raw['sources'][0]['citation_id']='[S2]'
    with pytest.raises(ValidationError):AskResponse.model_validate(raw)


@pytest.mark.parametrize('family,mutation',[
    ('B',lambda d:d['final']['nodes'][0].update(children=['n1'])),
    ('B',lambda d:d['final']['nodes'][1].update(keys=[999])),
    ('B+',lambda d:d['final']['nodes'][0].update(keys=[6])),
    ('B+',lambda d:d['final']['nodes'][-1].update(keys=[1,2])),
])
def test_invalid_multiway_order_children_and_record_sets(family,mutation):
    data=copy.deepcopy(cases()[family]);mutation(data)
    with pytest.raises(ValidationError):VerifiedTreeVisualization.model_validate(data)


def test_local_rotation_is_not_mistaken_for_the_final_whole_tree():
    from backend.v2.services.tree_visualization import build
    from backend.v2.services.tree_rule_evidence import rule_supported
    from backend.v2.tests.tree_display_cases import RULES
    calc,reason=calculate('空AVL树，依次插入10,20,30,40,50，画出最终树。')
    assert reason is None
    tree=build(calc,['[S1]'],{'[S1]':rule_supported(calc,RULES)})
    assert len(tree.final.nodes)==5
    assert len(tree.rotations[-1].frames[-1].graph.nodes)==3
    assert tree.final!=tree.rotations[-1].frames[-1].graph
