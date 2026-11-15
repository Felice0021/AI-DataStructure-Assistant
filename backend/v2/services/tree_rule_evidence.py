"""Finite source grammar and typed convention comparison, not semantic entailment.

Only positive declarative clauses in the current tree-family scope are accepted.
Unknown/conditional convention wording cannot be promoted to textbook support.
"""
from dataclasses import dataclass
import re
from backend.v2.services.tree_inputs import normalized

LABELS={
    'max_children':'内部结点最大孩子数', 'max_keys':'内部结点最大键数',
    'leaf_capacity':'叶最大键数', 'leaf_left':'分裂左叶键数', 'leaf_right':'分裂右叶键数',
    'separator':'父分隔键', 'split_timing':'分裂时机', 'median':'提升中位键',
}
VALUES={'right_min':'复制右叶最小键','left_max':'复制左叶最大键',
    'after':'插入溢出后分裂','before':'插入前分裂满结点',
    'middle':'唯一中间键','lower':'较小中间键','upper':'较大中间键'}
FAMILY=r'AVL(?:树)?|平衡二叉树|红黑树|red-?blacktree|RBtree|普通二叉搜索树|二叉搜索树|二叉排序树|BST|B\+(?:树)?|B树'


def _family(name):
    name=name.upper()
    if name in {'红黑树','RED-BLACKTREE','REDBLACKTREE','RBTREE'}:return 'RB'  # Scope boundary only; no RB construction calculator.
    if name.startswith(('AVL','平衡')):return 'AVL'
    if name in {'B树','B+树','B+'}:return name.removesuffix('树')
    return 'BST'


def _clauses(content,family):
    scope=set()
    for clause in re.split(r'[。；;\n，,]',normalized(content)):
        clause=re.sub(r'[\s`*_#]','',clause)
        # A family as the grammatical subject; a BST mentioned as AVL's definition
        # does not change the subject. Coordinated family subjects stay separate.
        head=re.match(r'(?:本课程|本测试)?(?:的)?('+FAMILY+r')(?:(?:和|与)('+FAMILY+r'))?',clause,re.I)
        if head:
            scope={_family(n) for n in head.groups() if n};clause=clause[head.end():]
        if family in scope and clause:yield clause,len(scope)>1


def _facts(clause,family):
    """Read complete atomic clauses, never infer conventions from keyword presence."""
    clause=re.sub(r'^(?:本课程|本测试)?(?:约定|规定|要求|采用)(?:为|是|:)?','',clause)
    patterns=[
        (r'(?:每个)?(?:内部|非叶)?(?:节点|结点)?(?:最多|至多)(\d+)个?孩子',lambda m:{'max_children':int(m[1])}),
        (r'(?:每个)?(?:内部|非叶)?(?:节点|结点)?(?:最多|至多)(\d+)个?键',lambda m:{'max_keys':int(m[1])}),
        (r'叶(?:节点|结点)?(?:最多|至多)(\d+)个?键',lambda m:{'leaf_capacity':int(m[1])}),
        (r'(溢出)?左叶(?:保留|前|取)(\d+)个?键',lambda m:{'leaf_left':int(m[2]),**({'split_timing':'after'} if m[1] else {})}),
        (r'右叶(?:保留|后|取)(\d+)个?键',lambda m:{'leaf_right':int(m[1])}),
        (r'(叶溢出)?(?:按)?左(\d+)右(\d+)(?:分裂)?',lambda m:{'leaf_left':int(m[2]),'leaf_right':int(m[3]),**({'split_timing':'after'} if m[1] else {})}),
        (r'(?:父(?:节点|结点|键)?|分隔键)(?:取|复制|拷贝)(右叶|右子树|左叶|左子树)(?:的)?(最小|最大)键',
         lambda m:{'separator':('right' if m[1].startswith('右') else 'left')+('_min' if m[2]=='最小' else '_max')}),
        (r'复制右叶最小键到父|叶分裂父键按约定复制右叶最小键',lambda m:{'separator':'right_min'}),
        (r'(?:内部(?:节点|结点))?(?:溢出后|插入后)(?:分裂并)?(?:提升|上移)(较小|较大)?(?:中间键|中位键)',
         lambda m:{'split_timing':'after','median':{'较小':'lower','较大':'upper',None:'middle'}[m[1]]}),
        (r'插入前分裂满(?:节点|结点)',lambda m:{'split_timing':'before'}),
    ]
    for pattern,read in patterns:
        match=re.fullmatch(pattern,clause)
        if match:return read(match)
    return {}


def _principle(clause,family):
    # Small positive proposition grammar. These labels describe exactly the scope
    # credited to a citation, not a claim that it specifies a numerical construction.
    common=[(r'插入结果依赖初始树、阶数和分裂约定','构造结果依赖初始状态和分裂约定'),
            (r'分裂容量与时机须遵循题目约定','分裂容量与时机需明确')]
    specific={
        'AVL':[(r'.*(?:左右高度差至多一|左右高度差不超过1|平衡因子.*绝对值不超过一).*','AVL高度平衡'),
               (r'平衡因子为左高减右高|绝对值至多1','AVL平衡因子定义及界限'),
               (r'.*(?:旋转保持中序有序及键集合|LL失衡右旋).*','旋转与有序性规则'),
               (r'从空树插入单键时该键为根','空树插入单键成为根')],
        'BST':[(r'.*(?:只要求左小右大|中序严格有序|中序遍历递增).*','二叉搜索树有序性')],
        'B':[(r'非叶孩子数比键数多一','孩子数与键数关系'),
             (r'子树键范围被父键严格分隔','父键分隔子树范围'),
             (r'溢出后按题定中位键提升','按给定中位规则分裂')],
        'B+':[(r'的?记录键全部在叶','记录键存于叶'),(r'内部键用于导航','内部键用于导航'),
              (r'叶溢出按题定左右键数分裂','按给定左右键数分裂'),
              (r'内部溢出按题定中位提升','按给定内部中位规则分裂'),
              (r'叶分裂父键按约定复制右叶最小键','父键复制右叶最小键'),
              (r'复制右叶最小键到父','父键复制右叶最小键'),
              (r'右叶保留此键','叶中保留分隔记录键'),
              (r'所有叶子必须同层','叶子同层')],
    }
    return next((label for pattern,label in common+specific[family] if re.fullmatch(pattern,clause)),None)


@dataclass(frozen=True)
class RuleSupport:
    kind: str  # explicit / principle_only / conflict / unrecognized / insufficient
    principles: tuple[str,...]=()
    matched: tuple[str,...]=()
    conflicts: tuple[str,...]=()
    scope: str='general'

    @property
    def usable(self):return self.kind in {'explicit','principle_only'}


def _double_rotation_support(calculation, content):
    """A complete case/path/target/order proposition, not a bag of AVL keywords.

    Some course chunks are standalone LR/RL declarations, without an AVL subject
    in the same sentence. Recognize only this bounded positive syntax and compare
    every slot against the independently checked rotation. Import JSON is never
    used to supply missing rule facts.
    """
    required={event['rotation'] for event in calculation.rotations}
    expected={'LR':('左','右','左','左','LL','右'),
              'RL':('右','左','右','右','RR','左')}
    principles=[]
    for line in normalized(content).splitlines():
        line=re.sub(r'[\s`*_]','',line)
        head=re.match(r'(LR|RL)型失衡:',line)
        if not head or head[1] not in required:continue
        match=re.fullmatch(r'(LR|RL)型失衡:(左|右)孩子(?:的)?(左|右)子树插入,'
            r'先(?:对)?(左|右)孩子(左|右)旋转为(LL|RR),再整体(左|右)旋;属于双旋[。.]?',line)
        if not match:return RuleSupport('unrecognized')
        if match.groups()[1:]!=expected[match[1]]:
            return RuleSupport('conflict',conflicts=('rotation_'+match[1],))
        principles.append(match[1]+'失衡的插入位置、子结点调整和双旋顺序')
    return RuleSupport('principle_only',tuple(principles)) if principles else None


def _bound_example(calculation,content):
    """The existing one-split B+ reference format, bound to identical keys and shape.

    This is not a general rule mined from arbitrary examples. A changed sequence or
    an unverifiable diagram is unknown; it is never generalized to other exercises.
    """
    text=re.sub(r'\s','',normalized(content))
    if not text.startswith('本例') or calculation.family!='B+':return None
    pattern=(r'本例(\d+)阶B\+树内部(?:节点|结点)最多(\d+)孩子(\d+)键,叶最多(\d+)键;'
        r'(\d+)键溢出按左(\d+)右(\d+)分裂,复制右叶最小键到父(?:节点|结点)。'
        r'插入([+\d,\-]+)后,根分隔键([+\-]?\d+);左叶([+\d,\-]+);右叶([+\d,\-]+);叶链左到右。')
    match=re.fullmatch(pattern,text)
    if not match:return RuleSupport('unrecognized')
    order,children,max_keys,cap,overflow,left,right=map(int,match.groups()[:7])
    read=lambda s:tuple(map(int,s.split(',')))
    if read(match[8])!=calculation.keys or order!=children or overflow!=cap+1:
        return RuleSupport('unrecognized')
    facts=dict(max_children=children,max_keys=max_keys,leaf_capacity=cap,
        split_timing='after',leaf_left=left,leaf_right=right,separator='right_min')
    conflicts=tuple(k for k,v in calculation.conventions.items() if k in facts and facts[k]!=v)
    if conflicts:return RuleSupport('conflict',conflicts=conflicts,scope='same_input_example')
    leaf=lambda keys:{'keys':list(keys),'children':[]}
    shape={'keys':[int(match[9])],'children':[leaf(read(match[10])),leaf(read(match[11]))]}
    if shape!=calculation.final:return RuleSupport('unrecognized')
    return RuleSupport('explicit',matched=tuple(calculation.conventions),scope='same_input_example')


def rule_supported(calculation,content):
    """Assess only conventions used by this bounded calculation; fail closed on unknown rules."""
    example=_bound_example(calculation,content)
    if example is not None:return example
    rotation=_double_rotation_support(calculation,content) if calculation.family=='AVL' else None
    if rotation and not rotation.usable:return rotation
    expected=calculation.conventions;facts={};principles=list(rotation.principles) if rotation else [];unknown=False
    for clause,mixed in _clauses(content,calculation.family):
        # Negation, alternative cases and quoted examples are outside this grammar.
        uncertain=bool(re.search(r'不|非本|若|如果|假设|例如|示例|或者|也可|可能|[?？]',clause.replace('不超过1','至多一')))
        parsed={} if uncertain or mixed else _facts(clause,calculation.family)
        if calculation.family!='B+' and parsed.keys() & {'leaf_capacity','leaf_left','leaf_right','separator'}:
            unknown=True;parsed={}
        principle=None if uncertain else _principle(clause,calculation.family)
        if principle:principles.append(principle)
        for key,value in parsed.items():facts.setdefault(key,set()).add(value)
        convention_cue=bool(re.search(r'约定|规定|要求|分裂|提升|上移|中位|中间键|最多|至多|分隔键|父.*(?:取|复制)|左叶|右叶|左\d+右\d+',clause))
        if convention_cue and not parsed and not principle:unknown=True
    matched=[];conflicts=[]
    for key,actual in expected.items():
        values=facts.get(key,set())
        # At odd overflow sizes lower/upper designate the same unique middle key.
        if key=='median' and actual=='middle':values={'middle' if v in {'lower','upper'} else v for v in values}
        if key=='median' and actual in {'lower','upper'} and 'middle' in values:
            unknown=True;values=values-{'middle'}  # Even overflow has no unique middle key.
        if values and values!={actual}:conflicts.append(key)
        elif values:matched.append(key)
    if conflicts:return RuleSupport('conflict',tuple(dict.fromkeys(principles)),tuple(matched),tuple(conflicts))
    if unknown:return RuleSupport('unrecognized')
    if not principles and not matched:return RuleSupport('insufficient')
    explicit=bool(expected) and set(matched)==set(expected)
    return RuleSupport('explicit' if explicit else 'principle_only',tuple(dict.fromkeys(principles)),tuple(matched))


def attribution(calculation,supports):
    """Static labels + validated citation IDs only; never interpolate arbitrary source prose."""
    lines=[];matched=set()
    for citation,support in supports.items():
        if not support.usable:raise ValueError('unsupported_tree_rule_citation')
        if support.principles:lines.append('课程资料支持的原理：'+'、'.join(support.principles)+' '+citation+'。')
        if support.matched:
            matched.update(support.matched)
            prefix='课程资料在相同输入示例中给出的约定：' if support.scope=='same_input_example' else '课程资料明确给出的约定：'
            lines.append(prefix+'；'.join(LABELS[k]+'='+str(VALUES.get(calculation.conventions[k],calculation.conventions[k])) for k in support.matched)+' '+citation+'。')
    assumptions=[k for k in calculation.conventions if k not in matched]
    if assumptions:
        lines.append('以下构造假设来自用户题设（自拟示例则为明示假设），不宣称是教材规定：'+'；'.join(LABELS[k]+'='+str(VALUES.get(calculation.conventions[k],calculation.conventions[k])) for k in assumptions)+'。')
    lines.append('输入键序列来自题设或明示的自拟示例；数值构造由服务端算法完成，引用不代表教材逐项给出了本题结果。')
    return lines
