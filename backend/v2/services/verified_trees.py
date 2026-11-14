"""Bounded trusted tree calculations, independent of model-generated prose or user code."""
from bisect import bisect_right
from dataclasses import dataclass, field
import json
import re

from backend.v2.services.tree_inputs import normalized, operation_sequence, first_insert_count


class TreeError(ValueError):
    pass


@dataclass
class Node:
    key: int
    left: 'Node | None' = None
    right: 'Node | None' = None


def snapshot(node):
    return None if node is None else {'key':node.key,'left':snapshot(node.left),'right':snapshot(node.right)}


def inspect_binary(root, *, balanced=False):
    seen=set();keys=[];factors={}
    def visit(node,lo,hi):
        if node is None:return 0
        if id(node) in seen or type(node.key) is not int or not lo<node.key<hi:
            raise TreeError('invalid_bst')
        seen.add(id(node))
        if len(seen)>32:raise TreeError('tree_limit')
        left=visit(node.left,lo,node.key);keys.append(node.key);right=visit(node.right,node.key,hi)
        factors[node.key]=left-right
        if balanced and abs(left-right)>1:raise TreeError('invalid_avl_balance')
        return 1+max(left,right)
    height=visit(root,float('-inf'),float('inf'))
    return {'inorder':keys,'height':height,'balance_factors':factors}


def rotate(root,kind):
    if root is None:raise TreeError('invalid_rotation_case')
    before=inspect_binary(root);f=before['balance_factors']
    if (kind not in {'LL','RR','LR','RL'} or abs(f[root.key])!=2
            or kind[0]=='L' and not (f[root.key]==2 and root.left is not None)
            or kind[0]=='R' and not (f[root.key]==-2 and root.right is not None)):
        raise TreeError('invalid_rotation_case')
    child=root.left if kind[0]=='L' else root.right
    if (kind=='LL' and f[child.key]<0 or kind=='RR' and f[child.key]>0
            or kind=='LR' and f[child.key]>=0 or kind=='RL' and f[child.key]<=0
            or any(abs(value)>1 for key,value in f.items() if key!=root.key)):
        raise TreeError('invalid_rotation_case')
    def left(n):
        pivot=n.right;n.right=pivot.left;pivot.left=n;return pivot
    def right(n):
        pivot=n.left;n.left=pivot.right;pivot.right=n;return pivot
    if kind=='LR':root.left=left(root.left)
    if kind=='RL':root.right=right(root.right)
    root=right(root) if kind[0]=='L' else left(root)
    after=inspect_binary(root,balanced=True)
    if before['inorder']!=after['inorder']:raise TreeError('rotation_changed_keys')
    return root


def binary_insert(root,key,avl,events):
    if root is None:return Node(key)
    if key==root.key:raise TreeError('duplicate_key')
    if key<root.key:root.left=binary_insert(root.left,key,avl,events)
    else:root.right=binary_insert(root.right,key,avl,events)
    if avl:
        info=inspect_binary(root);bf=info['balance_factors']
        if abs(bf[root.key])>1:
            kind=('LL' if bf[root.left.key]>=0 else 'LR') if bf[root.key]>0 else ('RR' if bf[root.right.key]<=0 else 'RL')
            before=snapshot(root);root=rotate(root,kind)
            events.append({'rotation':kind,'before':before,'after':snapshot(root)})
    return root


@dataclass
class MultiNode:
    keys: list[int] = field(default_factory=list)
    children: list['MultiNode'] = field(default_factory=list)


def multi_snapshot(node):
    return {'keys':list(node.keys),'children':[multi_snapshot(c) for c in node.children]}


def inspect_multi(root,children_limit,leaf_limit,*,plus):
    seen=set();leaves=[];data=[]
    def visit(node,depth,is_root=False):
        if id(node) in seen or len(seen)>=64:raise TreeError('invalid_multi_graph')
        seen.add(id(node))
        if not node.keys or any(type(k) is not int for k in node.keys) or sorted(set(node.keys))!=node.keys:raise TreeError('invalid_multi_keys')
        cap=children_limit-1 if node.children or not plus else leaf_limit
        minimum=(children_limit+1)//2-1 if node.children or not plus else (leaf_limit+1)//2
        if cap is not None and len(node.keys)>cap:raise TreeError('multi_capacity')
        if not is_root and len(node.keys)<minimum:raise TreeError('multi_underfull')
        if not node.children:
            leaves.append(depth);data.extend(node.keys)
            return node.keys[0],node.keys[-1]
        if len(node.children)!=len(node.keys)+1:raise TreeError('multi_child_count')
        ranges=[visit(c,depth+1) for c in node.children]
        for i,key in enumerate(node.keys):
            if plus:
                if not ranges[i][1]<key==ranges[i+1][0]:raise TreeError('bplus_separator')
            elif not ranges[i][1]<key<ranges[i+1][0]:raise TreeError('btree_order')
        if not plus:data.extend(node.keys)
        return ranges[0][0],ranges[-1][1]
    visit(root,0,True)
    if len(set(leaves))!=1 or len(data)!=len(set(data)):raise TreeError('multi_leaf_depth_or_duplicates')
    return sorted(data)


def multi_insert(root,key,m,leaf_cap,left_count,plus,lower_median):
    def insert(node):
        if not node.children:node.keys.insert(bisect_right(node.keys,key),key)
        else:
            index=bisect_right(node.keys,key);split=insert(node.children[index])
            if split:
                separator,right=split;node.keys.insert(index,separator);node.children.insert(index+1,right)
        capacity=m-1 if node.children or not plus else leaf_cap
        if len(node.keys)<=capacity:return None
        if plus and not node.children:
            right=MultiNode(node.keys[left_count:]);node.keys=node.keys[:left_count]
            return right.keys[0],right
        index=(len(node.keys)-1)//2 if lower_median else len(node.keys)//2
        separator=node.keys[index]
        right=MultiNode(node.keys[index+1:],node.children[index+1:] if node.children else [])
        node.keys=node.keys[:index]
        if node.children:node.children=node.children[:index+1]
        return separator,right
    split=insert(root)
    if split:separator,right=split;root=MultiNode([separator],[root,right])
    return root


@dataclass(frozen=True)
class Calculation:
    family: str
    keys: tuple[int,...]
    final: dict
    checks: dict
    steps: tuple[dict,...] = ()
    rotations: tuple[dict,...] = ()
    example: bool = False
    conventions: dict = field(default_factory=dict)

    def render(self,citation,*,supports=None):
        lines=['### 已校验的'+('示例' if self.example else '构造结果'),
            '以下结构由服务端算法计算并校验；不是运行用户代码。',
            '从空树依次插入：'+', '.join(map(str,self.keys))+'。']
        if supports is not None:
            from backend.v2.services.tree_rule_evidence import attribution
            lines+=attribution(self,supports)
        else:
            lines+=['课程资料仅作为相关原理的来源 '+citation+'；具体输入与约定来自题设或明示的自拟示例，不宣称由教材规定。']
        if self.example:lines.append('这是明确自拟的演示输入，不是替换题目条件。')
        if self.checks.get('rotation_mismatch'):lines.append(self.checks['rotation_mismatch'])
        if self.family in {'B','B+'}:
            lines.append(self.checks.get('rules','单键结果不依赖阶数或分裂策略。'))
        if self.steps:
            lines+=['','| 插入键 | 调整 | 当前根 |','|---|---|---|']
            lines += [f"| {s['key']} | {s['rotation'] or '无需旋转'} | {s['root']} |" for s in self.steps]
        for event in self.rotations:
            if event['rotation'] in {'LR','RL'}:
                side,first,second=('left','左','右') if event['rotation']=='LR' else ('right','右','左')
                lines.append(f"参考算法操作：先对结点{event['before'][side]['key']}{first}旋，再对结点{event['before']['key']}{second}旋。")
            lines += ['',event['rotation']+'：旋转前','```text',*binary_lines(event['before']),'```','旋转后','```text',*binary_lines(event['after']),'```']
        lines+=['','最终结构','```text',*(binary_lines(self.final) if self.family in {'AVL','BST'} else multi_lines(self.final)),'```',
            '校验：键集合不变；'+('中序严格有序；所有结点平衡因子绝对值不超过一。' if self.family=='AVL' else '中序严格有序。' if self.family=='BST' else '结点有序、容量和分隔范围正确，所有叶子同层。')]
        if self.checks.get('root_only'):lines[-1]='校验：根叶键有序、键集合一致；本次没有分裂。'
        if self.family=='AVL':lines.append('平衡因子（左高减右高）：'+', '.join(f'{k}: {v}' for k,v in self.checks['balance_factors'].items())+'。')
        return '\n'.join(lines)


def binary_lines(tree,prefix='',label='根'):
    if tree is None:return []
    result=[prefix+label+': '+str(tree['key'])]
    result+=binary_lines(tree['left'],prefix+'  ','左')
    result+=binary_lines(tree['right'],prefix+'  ','右')
    return result


def multi_lines(tree,prefix='',label='根'):
    result=[prefix+label+': ['+', '.join(map(str,tree['keys']))+']']
    for i,child in enumerate(tree['children']):result+=multi_lines(child,prefix+'  ',f'孩子{i+1}')
    return result


def tree_family(query):
    if re.search(r'(?<![A-Za-z])AVL|平衡二叉树',query,re.I):return 'AVL'
    if re.search(r'二叉搜索树|二叉排序树|(?<![A-Za-z0-9_])BST(?![A-Za-z0-9_])',query,re.I):return 'BST'
    if re.search(r'B\s*\+\s*树',query,re.I):return 'B+'
    if re.search(r'B\s*树',query,re.I):return 'B'
    return None


def stated_order(query):
    match=re.search(r'(\d+|[三四五六七八])\s*阶',query)
    if not match:return None
    return int(match[1]) if match[1].isdigit() else '一二三四五六七八'.index(match[1])+1


def calculate(query):
    """Return (result, refusal). Unknown conventions never become implicit algorithm defaults."""
    query=normalized(query);prefix_count=None
    # These fields describe a requested calculation, never an authoritative historical state.
    if '：' in query or ':' in query:
        try:reference=json.loads(re.split(r'[:：]',query,maxsplit=1)[1])
        except (ValueError,IndexError):reference=None
        if isinstance(reference,dict) and 'untrusted_previous_step' in reference:return None,None
        if isinstance(reference,dict) and 'requested_prefix_count' in reference:
            task=reference.get('untrusted_user_task');count=reference['requested_prefix_count']
            if (not isinstance(task,str) or type(count) is not int
                    or not 1<=count<=len(operation_sequence(task))
                    or reference.get('next_key')!=operation_sequence(task)[count-1]):
                return None,'tree_calculation_not_supported'
            query=task;prefix_count=count
    family=tree_family(query)
    if not family:return None,None
    rotation_names=re.findall(r'(?<![A-Za-z0-9_])(LL|RR|LR|RL)(?![A-Za-z0-9_])',query,re.I)
    illustration=family=='AVL' and re.search(r'示例|例子|举例',query) and (rotation_names or '旋转' in query)
    concrete=bool(re.search(r'构造|画出|模拟插入|依次插入|空.*插入',query))
    if not (illustration or concrete):return None,None
    from backend.v2.services.evidence_policy import missing_conditions
    reason=missing_conditions(query)
    if reason:return None,reason
    kinds=sum(bool(re.search(pattern,query,re.I)) for pattern in (r'AVL|平衡二叉树',r'BST|二叉搜索树|二叉排序树',r'B\s*\+\s*树',r'B\s*树'))
    if kinds>1:return None,'tree_calculation_not_supported'
    if re.search(r'删除|已有|非空|原树|当前树',query):return None,'tree_calculation_not_supported'
    values=operation_sequence(query)
    if not values and unverified_tree_prose(query):return None,'tree_calculation_not_supported'
    own_example=bool(illustration and not values)
    self_example=bool(family in {'B','B+'} and not values and re.search(r'自拟|自定|给(?:出)?(?:一个|个).*例|举(?:一)?个.*例',query))
    if self_example:
        child=re.search(r'(?:最多|至多)\s*(\d+)\s*个?孩子',query)
        m=stated_order(query) or (int(child[1]) if child else 3)
        if child and int(child[1])!=m:return None,'tree_calculation_not_supported'
        if not 3<=m<=8:return None,'tree_calculation_not_supported'
        values=tuple(str(10*i) for i in range(1,m+1))
        query+=f'；从空树构造，最多{m}孩子、{m-1}键；溢出后提升中间键。'
        if family=='B+':query+=f'溢出左叶前{(m+1)//2}键，右叶后{m-(m+1)//2}键，父节点复制右叶最小键。'
    if illustration and not values:
        if len(set(n.upper() for n in rotation_names))>1:return None,'tree_calculation_not_supported'
        kind=rotation_names[0].upper() if rotation_names else 'LR'
        values={'LL':('30','20','10'),'RR':('10','20','30'),'LR':('30','10','20'),'RL':('10','30','20')}[kind]
    if not values:return None,None  # Existing condition preflight explains missing inputs.
    requested=prefix_count or first_insert_count(query)
    if requested is not None:
        if not 1<=requested<=len(values):return None,'tree_calculation_not_supported'
        values=values[:requested]
    if len(values)>16 or any(not re.fullmatch(r'[+-]?\d{1,9}',k) for k in values):return None,'tree_calculation_not_supported'
    keys=tuple(map(int,values))
    if len(set(keys))!=len(keys):
        if re.search(r'重复键(?:全部)?忽略|忽略重复键',query):keys=tuple(dict.fromkeys(keys))
        else:return None,'tree_calculation_not_supported'
    if not illustration and not re.search(r'构造|从空|初始为空|空(?:AVL|BST|B\s*\+?|二叉(?:搜索|排序)?)?树',query,re.I):
        return None,'tree_calculation_not_supported'
    if family in {'AVL','BST'}:
        root=None;events=[];steps=[]
        for i,key in enumerate(keys):
            start=len(events);root=binary_insert(root,key,family=='AVL',events)
            checks=inspect_binary(root,balanced=family=='AVL')
            if checks['inorder']!=sorted(keys[:i+1]):raise TreeError('insertion_changed_keys')
            steps.append({'key':key,'rotation':'/'.join(e['rotation'] for e in events[start:]),'root':root.key})
        if illustration and len(set(n.upper() for n in rotation_names))==1:
            requested_case=rotation_names[0].upper();actual_cases=[e['rotation'] for e in events]
            if requested_case not in actual_cases:
                checks['rotation_mismatch']='所给输入实际触发 '+('/'.join(actual_cases) or '无需旋转')+'，不是请求的 '+requested_case+'；未更换输入。'
        return Calculation(family,keys,snapshot(root),checks,tuple(steps),tuple(events),own_example),None
    child=re.search(r'(?:最多|至多)\s*(\d+)\s*个?孩子',query)
    if len(keys)==1:return Calculation(family,keys,{'keys':list(keys),'children':[]},{'keys':list(keys),'root_only':True}),None
    if not child:
        m=stated_order(query)
        if m is not None:
            if 3<=m<=8 and len(keys)<=m-1:
                return Calculation(family,keys,{'keys':sorted(keys),'children':[]},{'keys':sorted(keys),'root_only':True,'rules':'本次根叶未分裂，不选择额外分裂约定。'}),None
        return None,'tree_calculation_not_supported'
    if not 3<=int(child[1])<=8:return None,'tree_calculation_not_supported'
    m=int(child[1]);cap=m-1;left=None
    if stated_order(query) is not None and stated_order(query)!=m:return None,'tree_calculation_not_supported'
    if len(keys)>cap and family=='B' and (not re.search(r'溢出|插入后|自底向上',query) or re.search(r'插入前',query)):
        return None,'tree_calculation_not_supported'
    if family=='B+':
        leaf=re.search(r'叶(?:节点|结点)?[^。;；]{0,16}?(?:最多|至多)\s*(\d+)\s*个?键',query)
        shorthand=re.search(r'(?:最多|至多)\s*\d+\s*个?孩子\s*[,、]\s*(\d+)\s*个?键',query)
        if not (leaf or shorthand):return None,'tree_calculation_not_supported'
        cap=int((leaf or shorthand)[1])
        split=re.search(r'左(?:叶)?(?:保留)?(?:前|取)?\s*(\d+)',query)
        left=int(split[1]) if split else None
        if not 1<=cap<=8 or len(keys)>cap and left is None:return None,'tree_calculation_not_supported'
    lower=bool(re.search(r'左中位|下中位|较小的?中间键',query))
    if lower and re.search(r'右中位|上中位|较大的?中间键',query):return None,'tree_calculation_not_supported'
    root=MultiNode()
    for i,key in enumerate(keys):
        root=multi_insert(root,key,m,cap,left,family=='B+',lower)
        actual=inspect_multi(root,m,cap,plus=family=='B+')
        if actual!=sorted(keys[:i+1]):raise TreeError('insertion_changed_keys')
    rules=f'结点最多 {m} 个孩子；'+('本次没有分裂，不补充分裂约定。' if len(keys)<=cap else f'叶最多 {cap} 键，溢出左叶保留 {left} 键、右叶保留 {cap+1-left} 键，复制右叶最小键到父。' if family=='B+' else '按题中约定，溢出后提升'+('较小中间键。' if lower else '中间键（偶数键取较大中间键）。'))
    # Provenance metadata only: the insertion/rotation/split computations above are unchanged.
    conventions={'max_children':m,'max_keys':m-1}
    if family=='B+':conventions['leaf_capacity']=cap
    if len(keys)>cap:
        conventions['split_timing']='after'
        if family=='B+':
            conventions.update(leaf_left=left,leaf_right=cap+1-left,separator='right_min')
        if family=='B' or any(c.children for c in root.children):
            conventions['median']='middle' if m%2 else 'lower' if lower else 'upper'
    return Calculation(family,keys,multi_snapshot(root),{'keys':actual,'rules':rules},example=self_example,conventions=conventions),None


def unverified_tree_prose(answer):
    """Conservative presentation boundary, not general natural-language fact verification."""
    fenced=bool(re.search(r'(?m)^\s*(?:`{3,}|~{3,})',answer))
    key=r'(?:[-+]?\d+|[一二三四五六七八九十]+(?=$|[\s，,。；;、的]))'
    relation=r'(?:根(?:节点|结点)?|左(?:孩子|子节点|子结点)|右(?:孩子|子节点|子结点)|节点|结点)'
    answer=re.sub(r'[`*_]','',answer)  # Inspect formatting without changing the returned answer.
    return bool(fenced or re.search(r'[├└┌┐┤┘│]',answer)
        or re.search(r'(?m)^[ \t]*[/\\]+(?:[ \t]+[/\\]+)*[ \t]*$',answer)
        or re.search(r'\d+\s*(?:->|→)\s*\d+',answer)
        or re.search(r'(?:前序|中序|后序|层序|插入序列)\s*(?:为|是|[:：])\s*\[?\s*\d',answer)
        or re.search(relation+r'\s*(?:为|是|[:：=])?\s*'+key,answer)
        or re.search(r'(?:左|右)\s*(?:[-+]?\d+|(?:为|是|[:：=])\s*'+key+r')',answer)
        or re.search(key+r'\s*(?:作为|为|是)\s*'+relation,answer))
