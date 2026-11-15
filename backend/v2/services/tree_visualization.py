"""Serialize only validated reference-calculator output, never model prose/ASCII."""
from backend.v2.schemas.tree import VerifiedTreeVisualization
from backend.v2.services.verified_trees import Node, MultiNode, inspect_binary, inspect_multi, TreeError


def graph(tree, binary):
    nodes=[]
    def visit(item):
        if item is None: return None
        node_id='n'+str(len(nodes))
        row={'id':node_id,'keys':[item['key']] if binary else item['keys'],'children':[]}
        nodes.append(row)
        row['children']=[visit(item[side]) for side in ('left','right')] if binary else [visit(c) for c in item['children']]
        return node_id
    root=visit(tree)
    return {'root':root,'nodes':nodes}


def build(calculation, citations, supports):
    """Keep the calculator's original invariants in addition to the transport bounds."""
    binary=calculation.family in {'AVL','BST'}
    def binary_node(t):
        return None if t is None else Node(t['key'],binary_node(t['left']),binary_node(t['right']))
    def multi_node(t): return MultiNode(t['keys'],[multi_node(c) for c in t['children']])
    if binary:
        keys=inspect_binary(binary_node(calculation.final),balanced=calculation.family=='AVL')['inorder']
    else:
        rules=calculation.conventions
        keys=inspect_multi(multi_node(calculation.final),rules.get('max_children',8),rules.get('leaf_capacity',8),plus=calculation.family=='B+')
    if keys!=sorted(calculation.keys): raise TreeError('display_changed_keys')
    rotations=[]
    for event in calculation.rotations:
        frames=[]
        for stage in ('before','intermediate','after'):
            if stage in event:
                inspect_binary(binary_node(event[stage]),balanced=stage=='after')
                frames.append({'stage':stage,'graph':graph(event[stage],True)})
        rotations.append({'kind':event['rotation'],'frames':frames})
    return VerifiedTreeVisualization.model_validate({
        'family':calculation.family,'explanation':calculation.render(' '.join(citations),supports=supports,include_tree_text=False),
        'source_citations':list(citations),'final':graph(calculation.final,binary),'rotations':rotations,
    })
