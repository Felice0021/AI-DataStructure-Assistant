"""Bounded display data. This is never an accepted model-output or request format."""
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator, field_validator

Key = Annotated[int, Field(strict=True, ge=-999999999, le=999999999)]
NodeId = Annotated[str, Field(pattern=r'^n(?:[0-9]|[1-5][0-9]|6[0-3])$')]
Citation = Annotated[str, Field(pattern=r'^\[S[1-9][0-9]?\]$')]


class DisplayModel(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)


class TreeNode(DisplayModel):
    id: NodeId
    keys: list[Key] = Field(min_length=1, max_length=8)
    children: list[NodeId | None] = Field(max_length=8)


class TreeGraph(DisplayModel):
    root: NodeId
    nodes: list[TreeNode] = Field(min_length=1, max_length=64)

    @model_validator(mode='after')
    def graph(self):
        nodes = {n.id: n for n in self.nodes}
        if len(nodes) != len(self.nodes) or self.root not in nodes:
            raise ValueError('invalid_tree_nodes')
        seen = set()
        def visit(node_id, depth):
            if node_id not in nodes or node_id in seen or depth > 16:
                raise ValueError('invalid_tree_graph')
            seen.add(node_id)
            for child in nodes[node_id].children:
                if child is not None: visit(child, depth + 1)
        visit(self.root, 0)
        if len(seen) != len(nodes): raise ValueError('unreachable_tree_node')
        return self


class TreeFrame(DisplayModel):
    stage: Literal['before', 'intermediate', 'after']
    graph: TreeGraph


class TreeRotation(DisplayModel):
    kind: Literal['LL', 'RR', 'LR', 'RL']
    frames: list[TreeFrame] = Field(min_length=2, max_length=3)

    @model_validator(mode='after')
    def stages(self):
        expected = ['before', 'intermediate', 'after'] if self.kind in {'LR', 'RL'} else ['before', 'after']
        if [f.stage for f in self.frames] != expected: raise ValueError('incomplete_rotation')
        return self


def inspect_graph(graph, family, balanced=False):
    """Validate display semantics; computations remain in verified_trees."""
    nodes = {n.id: n for n in graph.nodes}; leaves = []
    def visit(node_id, depth, lo, hi):
        n = nodes[node_id]
        if sorted(set(n.keys)) != n.keys: raise ValueError('unordered_tree_keys')
        if family in {'AVL', 'BST'}:
            if len(n.keys) != 1 or len(n.children) != 2 or not lo < n.keys[0] < hi:
                raise ValueError('invalid_binary_tree')
            left, right = n.children
            lk, lh = visit(left, depth+1, lo, n.keys[0]) if left else ([], 0)
            rk, rh = visit(right, depth+1, n.keys[0], hi) if right else ([], 0)
            if balanced and abs(lh-rh)>1: raise ValueError('unbalanced_final_avl')
            return lk+n.keys+rk, 1+max(lh,rh)
        if n.children:
            if len(n.children) != len(n.keys)+1 or None in n.children:
                raise ValueError('invalid_multi_children')
            ranges = [visit(c, depth+1, float('-inf'), float('inf'))[0] for c in n.children]
            for i, key in enumerate(n.keys):
                if not (max(ranges[i]) < key and (key == min(ranges[i+1]) if family=='B+' else key < min(ranges[i+1]))):
                    raise ValueError('invalid_multi_order')
            return sorted([k for r in ranges for k in r]+(n.keys if family=='B' else [])), 0
        leaves.append(depth)
        return n.keys, 0
    keys, _ = visit(graph.root, 0, float('-inf'), float('inf'))
    if len(keys)!=len(set(keys)) or len(set(leaves))>1: raise ValueError('invalid_tree_records')
    return keys


class VerifiedTreeVisualization(DisplayModel):
    version: Literal[1] = 1
    origin: Literal['server_verified_tree_v1'] = 'server_verified_tree_v1'
    family: Literal['AVL', 'BST', 'B', 'B+']
    explanation: str = Field(min_length=1, max_length=20000)
    source_citations: list[Citation] = Field(min_length=1, max_length=20)
    final: TreeGraph
    rotations: list[TreeRotation] = Field(max_length=16)

    @field_validator('version', mode='before')
    @classmethod
    def strict_version(cls, value):
        if type(value) is not int: raise ValueError('invalid_tree_version')
        return value

    @model_validator(mode='after')
    def semantics(self):
        if len(set(self.source_citations))!=len(self.source_citations): raise ValueError('duplicate_tree_citation')
        inspect_graph(self.final, self.family, balanced=self.family=='AVL')
        total=len(self.final.nodes)
        if self.rotations and self.family!='AVL': raise ValueError('invalid_rotation_family')
        for rotation in self.rotations:
            before=None
            for frame in rotation.frames:
                keys=inspect_graph(frame.graph,self.family,balanced=frame.stage=='after')
                if before is not None and keys!=before: raise ValueError('rotation_changed_keys')
                before=keys;total+=len(frame.graph.nodes)
        if total>512: raise ValueError('tree_display_limit')
        return self
