"""Bounded last-pivot, zero-based Lomuto only. Never executes submitted code.

Course support is a finite positive rule grammar, not arbitrary semantic entailment.
Numeric outputs come from checked transitions, not unchecked generator prose.
"""
from collections import Counter
from dataclasses import dataclass
import json
import re
import unicodedata

from backend.v2.services.answer_validation import AnswerValidationError
from backend.v2.core.errors import AuthError

VARIANT = re.compile(r'(?<![A-Za-z0-9_])(Lomuto|Hoare)(?![A-Za-z0-9_])', re.I)
LIMIT = 32


def names(text):
    return tuple(dict.fromkeys(x.casefold() for x in VARIANT.findall(text)))


class PartitionError(ValueError):
    pass


@dataclass(frozen=True)
class Calculation:
    original: tuple[int, ...]
    steps: tuple[dict, ...]
    final: tuple[int, ...]
    pivot_index: int

    def validate(self):
        a=list(self.original);i=0
        if not 1<=len(a)<=LIMIT or any(type(k) is not int or abs(k)>999999999 for k in a):
            raise PartitionError('partition_input_limit')
        pivot=a[-1]
        if len(self.steps)!=len(a):raise PartitionError('partition_step_count')
        for j,step in enumerate(self.steps[:-1]):
            if step.get('j')!=j or step.get('pivot_index')!=len(a)-1:
                raise PartitionError('partition_scan_order')
            before=a.copy();accepted=a[j]<=pivot
            swap=(i,j) if accepted else None
            if accepted:a[i],a[j]=a[j],a[i];i+=1
            if (step.get('swap')!=swap or step.get('boundary')!=i or step.get('array')!=tuple(a)
                    or Counter(a)!=Counter(self.original) or a[-1]!=pivot
                    or any(k>pivot for k in a[:i]) or any(k<=pivot for k in a[i:j+1])):
                raise PartitionError('partition_transition_invalid')
            if not accepted and before!=a:raise PartitionError('partition_spurious_swap')
        a[i],a[-1]=a[-1],a[i]
        last=self.steps[-1]
        if (last.get('swap')!=(i,len(a)-1) or last.get('array')!=tuple(a)
                or last.get('pivot_index')!=i or self.final!=tuple(a) or self.pivot_index!=i
                or Counter(a)!=Counter(self.original) or a[i]!=pivot
                or any(k>pivot for k in a[:i]) or any(k<=pivot for k in a[i+1:])):
            raise PartitionError('partition_final_invalid')


def calculate(values):
    if not 1<=len(values)<=LIMIT or any(type(k) is not int or abs(k)>999999999 for k in values):
        raise PartitionError('partition_input_limit')
    a=list(values);pivot=a[-1];i=0;steps=[]
    for j in range(len(a)-1):
        pair=None
        if a[j]<=pivot:
            pair=(i,j);a[i],a[j]=a[j],a[i];i+=1
        steps.append({'j':j,'swap':pair,'array':tuple(a),'boundary':i,'pivot_index':len(a)-1})
    a[i],a[-1]=a[-1],a[i]
    steps.append({'swap':(i,len(a)-1),'array':tuple(a),'pivot_index':i})
    result=Calculation(tuple(values),tuple(steps),tuple(a),i);result.validate();return result


def source_support(content,variant='lomuto'):
    """Require an affirmative, complete last-pivot + <= + final-swap proposition.

    Hoare paragraphs, titles, example arrays, and unknown rule phrasing cannot supply it.
    A recognized contradictory Lomuto pivot/comparison clause fails closed.
    """
    text=re.sub(r'\s','',unicodedata.normalize('NFKC',content))
    clauses=re.split(r'[。；;\n]',text);scope=None;complete=False;conflict=False;unknown=False;facts=set()
    for clause in clauses:
        if clause.startswith('快速排序'):scope=None
        head=re.match(r'(Lomuto|Hoare)(?:分区|partition)?',clause,re.I)
        if head:scope=head[1].casefold()
        if scope!=variant:continue
        if variant=='hoare':
            if re.fullmatch(r'Hoare分区使用左右双向扫描交换错位元素,返回分界下标,不保证基准归位',clause,re.I):complete=True
            continue
        example=re.fullmatch(r'数组([+\d,\-]+)一次分区后为([+\d,\-]+),pivot下标(\d+)',clause,re.I)
        if example:
            try:
                checked=calculate(tuple(map(int,example[1].split(','))))
                if checked.final!=tuple(map(int,example[2].split(','))) or checked.pivot_index!=int(example[3]):conflict=True
            except (ValueError,PartitionError):unknown=True
            continue  # A checked example still does not establish the general rule.
        if head and re.search(r'(?:以|用|选择)(?:第一个|首|中间)元素(?:为|作)(?:pivot|基准)',clause,re.I):conflict=True
        pattern=(r'Lomuto分区以(?:末元素|最后(?:一个)?元素)(?:为|作)(?:pivot|基准),?'
                 r'从左到右把小于等于(?:pivot|基准)的元素交换到前部,?'
                 r'再把(?:pivot|基准)交换到分界位置')
        recognized=bool(re.fullmatch(pattern,clause,re.I))
        if recognized:complete=True
        if re.fullmatch(r'Lomuto分区以最后元素作pivot,i初始为区间左端',clause,re.I):
            facts.add('initial');recognized=True
        if re.fullmatch(r'j从左端扫描到pivot前一位置,若a\[j\]<=pivot则交换a\[i\],a\[j\]并i加1,最后交换a\[i\]和pivot',clause,re.I):
            facts.add('scan_swap');recognized=True
        if re.fullmatch(r'i是pivot的最终下标',clause,re.I):
            facts.add('return');recognized=True
        if head and re.search(r'(?:仅|只)把小于(?:pivot|基准)的元素交换到前部',clause,re.I):conflict=True
        if not recognized and re.search(r'基准|pivot|交换|边界|扫描',clause,re.I):unknown=True
    complete=complete or facts=={'initial','scan_swap','return'}
    return 'conflict' if conflict else 'unrecognized' if unknown else 'complete' if complete else 'insufficient'


def original_task(query):
    marker='；用户原题条件（不作为证据）：'
    if marker not in query:return query
    try:
        condition=json.loads(query.split(marker,1)[1]);task=condition.get('untrusted_user_task')
    except (ValueError,AttributeError):return query
    return task if isinstance(task,str) and len(task)<=2000 and names(task)==(condition.get('partition_variant'),) else query


@dataclass(frozen=True)
class Plan:
    calculation: Calculation | None
    evidence: dict
    variant: str = 'lomuto'
    quick_core: tuple = ()

    @property
    def instruction(self):
        return (f'\n本题指定{self.variant}分区，不能替换算法变体，也不要讨论另一种变体。仅引用本轮支持该变体的规则，不把用户输入当作教材。'
                + ('你只简短解释规则并实际引用，不生成数值步骤；Lomuto末元素基准、下标0、<=的具体数组状态由服务端有界算法计算。' if self.calculation
                   else '本次只解释原理或复杂度，不自行添加未经计算校验的具体数组示例。区别单次分区与完整快速排序；缺少相应复杂度证据时拒答。'))

    def instruct(self,messages,max_bytes):
        messages[0]['content']+=self.instruction
        if len(json.dumps(messages,ensure_ascii=False,separators=(',',':')).encode())>max_bytes:
            raise AuthError(422,'generation_input_limit','Prompt budget exceeded')

    def finish(self, draft, citations):
        if any(v!=self.variant for v in names(draft)):raise AnswerValidationError('partition_variant_substitution')
        if not citations or any(self.evidence.get(c)!='complete' for c in citations):
            raise AnswerValidationError('partition_rule_citation_required')
        if self.calculation is None:
            if re.search(r'\[\s*[+-]?\d+(?:\s*,\s*[+-]?\d+)*\s*\]',draft):
                raise AnswerValidationError('unverified_partition_example')
            return draft
        try:self.calculation.validate()
        except PartitionError:raise AnswerValidationError('partition_invariant_failed') from None
        r=self.calculation;pivot=r.original[-1];refs=' '.join(citations)
        lines=['### 单次 Lomuto 分区',
            '课程资料支持的规则：末元素为基准，从左到右把小于等于基准的元素交换到前区，扫描后把基准放到分界位置 '+refs+'。',
            '输入数组、基准选择和下标0来自用户题设；下面的数组状态由服务端参考算法计算并逐步校验，不是教材逐项解答，也没有编译或运行用户代码。',
            '初始数组：'+str(list(r.original))+'；基准值：'+str(pivot)+'；基准初始下标：'+str(len(r.original)-1)+'。',
            '| 步骤 | 扫描下标j | 交换下标 | 当前数组 | 基准下标 |','|---|---|---|---|---|']
        core=[c for c in citations if c in self.quick_core]
        if core:
            lines.insert(1,'快速排序的基本思想：先按基准分区，再递归处理两侧子数组 '+' '.join(core)+'。本题按指定变体演示一次分区。')
        for number,step in enumerate(r.steps,1):
            last=number==len(r.steps)
            lines.append(f"| {'基准归位' if last else number} | {'—' if last else step['j']} | {step['swap'] if step['swap'] is not None else '不交换'} | {list(step['array'])} | {step['pivot_index']} |")
        lines+=['最终数组：'+str(list(r.final))+'；基准最终下标：'+str(r.pivot_index)+'。',
            '校验通过：每步元素多重集合不变；扫描时基准保持末位；最终左侧全部≤基准、右侧全部>基准。一次分区不等于完成整次快速排序。']
        header=next(i for i,line in enumerate(lines) if line.startswith('| 步骤'))
        return '\n\n'.join(lines[:header])+'\n\n'+'\n'.join(lines[header:])


def prepare(query,evidence,*,user_query=None):
    task=unicodedata.normalize('NFKC',original_task(query));specified=names(task)
    # Conceptual/complexity questions keep the original RAG path. They are not computations.
    current=user_query or query
    concrete=bool(re.search(r'数组|\[.*\]|演示.*分区|模拟.*分区',current))
    if not specified:return None,None
    if not concrete and len(specified)>1:return None,None  # An explicit conceptual comparison is not a calculation.
    if len(specified)!=1:return None,'partition_variant_ambiguous'
    if not concrete:
        support={e['citation_id']:source_support(e['content'],specified[0]) for e in evidence}
        if 'conflict' in support.values():return None,'partition_rule_conflict'
        if 'unrecognized' in support.values():return None,'partition_rule_unverified'
        if 'complete' not in support.values():return None,'partition_rule_evidence_required'
        return Plan(None,support,specified[0]),None
    if specified!=('lomuto',):return None,'partition_variant_not_supported'
    arrays=re.findall(r'\[([^\]]*)\]',task)
    if not arrays:
        bare=re.search(r'数组\s*([+-]?\d{1,9}(?:\s*[,、]\s*[+-]?\d{1,9})*)(?=[,，](?:以|按|规|下)|[。;；]|$)',task)
        if bare:arrays=[bare[1]]
    if len(arrays)!=1 or not re.fullmatch(r'\s*[+-]?\d{1,9}(?:\s*(?:[,、]\s*|\s+)[+-]?\d{1,9})*\s*',arrays[0]):
        return None,'partition_input_required'
    values=tuple(map(int,re.findall(r'[+-]?\d+',arrays[0])))
    if not 1<=len(values)<=LIMIT:return None,'partition_input_limit'
    pivot=re.search(r'(?:最后(?:一个)?|末(?:尾)?)元素\s*([+-]?\d{1,9})?\s*(?:为|作)(?:基准|pivot)',task,re.I)
    if (not pivot or not re.search(r'(?:下标|索引)\s*\(?从0开始',task)):
        return None,'partition_conditions_required'
    if pivot[1] is not None and int(pivot[1])!=values[-1]:return None,'partition_pivot_mismatch'
    boundary=re.search(r'(?:边界i|i)\s*(?:初始|初值)(?:为|是|=)?\s*([+-]?\d+)',task,re.I)
    if ((boundary and int(boundary[1])!=0)
            or re.search(r'首元素|第一个元素|随机|中间元素|降序|子区间|Hoare|(?:仅|只|严格)小于|下标从[1-9]',task,re.I)):
        return None,'partition_convention_not_supported'
    support={e['citation_id']:source_support(e['content']) for e in evidence}
    if 'conflict' in support.values():return None,'partition_rule_conflict'
    if 'unrecognized' in support.values():return None,'partition_rule_unverified'
    if 'complete' not in support.values():return None,'partition_rule_evidence_required'
    core=tuple(e['citation_id'] for e in evidence if re.search(r'快速排序先按基准分区[,，]再递归处理两侧子数组',e['content']))
    return Plan(calculate(values),support,quick_core=core),None
