"""Conservative lexical/conflicting-key preflight, not semantic evidence scoring."""
import re
import unicodedata
from backend.v2.services.lexical_search import tokenize
from backend.v2.services.tree_inputs import normalized, operation_sequence

GENERIC=frozenset('什么 为什么 如何 请 解释 分析 计算 给定 资料 问题 课程 explain what why how code'.split())


def task_kind(query):
    """Internal pedagogy categories; public answer_mode remains qa/exercise/code."""
    if re.search(r'#include|```|std::|->|\b(?:int|void|char|bool|Node|TreeNode)\s*\*?\s+\w+\s*\(|\b(?:if|while|for)\s*\(|(?:^|\n)\s*(?:async\s+)?def\s+\w+\s*\(|代码纠错|修正代码|递归(?:终止条件|边界)|逻辑错误',query,re.I):
        return 'code'
    if re.search(r'给定|依次|构造|求出|画出|模拟插入|遍历序列|最终结果|排序过程|计算.*(?:序列|结果)',query):
        return 'exercise'
    if re.search(r'是什么|什么是|定义|概念|特点|区别',query) and not re.search(r'复杂度|原理|过程|步骤',query):
        return 'qa'
    if re.search(r'代码|程序|报错|指针|越界|纠错',query):
        return 'code'
    if re.search(r'算法|复杂度|排序|遍历|BFS|DFS|Dijkstra|最坏情况|最好情况|平均情况',query,re.I):
        return 'algorithm'
    return 'qa'


def resolve_mode(query,requested):
    if requested!='auto':return requested
    kind=task_kind(query)
    return 'exercise' if kind=='algorithm' else kind


def missing_conditions(query):
    query=normalized(query)
    if task_kind(query)=='code':return None
    if not re.search(r'AVL|二叉(?:搜索|排序)?树|B\s*\+?\s*树',query,re.I):
        return None
    if not re.search(r'画出|构造|模拟|插入|删除',query):
        return None
    # A self-authored example may choose and disclose conventions. A concrete exercise may not.
    if re.search(r'自拟|自定|自行(?:假设|设定|拟定)|举(?:一)?个.*例|给(?:出)?(?:一个|个)?.*(?:例子|示例)|示意图',query):
        return None
    keys=operation_sequence(query)
    explanatory=bool(re.search(r'原理|一般|规则|方法|如何|为什么|示例|算法|步骤|过程',query))
    draw_task=bool(re.search(r'画出|模拟',query) and not re.search(r'如何|解释|说明|介绍|原理',query))
    if not keys and explanatory and not draw_task and not re.search(r'最终|结果|本题|该题|给定',query):
        return None
    if not keys:
        return 'missing_operation_sequence'
    family=re.search(r'B\s*(\+)?\s*树',query,re.I)
    if family is None:
        return None
    if re.search(r'已有|非空|当前树|原树',query) and not re.search(r'初始为空|从空树',query):
        return 'ambiguous_tree_rules'
    if len(set(keys))!=len(keys):
        # Placement/multiplicity changes splits; mere mention of "重复键" is not a policy.
        if re.search(r'重复键(?:全部)?忽略|忽略重复键',query):
            keys=tuple(dict.fromkeys(keys))
        else:
            return 'ambiguous_tree_rules'
    order_match=re.search(r'(\d+|[二三四五六七八九十])\s*阶|阶数\s*(?:为|是|[:=])?\s*(\d+)',query)
    order=None
    if order_match:
        value=next(x for x in order_match.groups() if x is not None)
        order=int(value) if value.isdigit() else '一二三四五六七八九十'.index(value)+1
        if order<2:return 'ambiguous_tree_rules'
    child=re.search(r'(?:最多|至多|最大)(?:有)?\s*(\d+)\s*个?(?:孩子|子节点|子女|子树)',query)
    degree=re.search(r'(?:最小度数|最小度)\s*t?\s*(?:为|是|[:=])?\s*(\d+)',query,re.I)
    leaf=re.search(r'叶(?:结点|节点)?[^。;；]{0,16}?(?:最多|至多)\s*(\d+)\s*个?(?:键|关键字)',query)
    if degree and (int(degree[1])<2 or family[1]):return 'ambiguous_tree_rules'
    if child and (int(child[1])<2 or order is not None and int(child[1])!=order):return 'ambiguous_tree_rules'
    if re.search(r'叶(?:结点|节点)?[^。;；]{0,16}?(?:最多|至多)\s*0\s*个?(?:键|关键字)',query):return 'ambiguous_tree_rules'
    # One key cannot overflow an empty construction; still reject explicitly contradictory rules.
    if len(keys)==1:return None
    if order is None and child is None and degree is None:return 'missing_tree_order'
    defined=bool(child or degree or re.search(r'阶数(?:表示|指|定义为|为)(?:结点|节点)?(?:的)?(?:最大|最多)孩子数',query))
    if not defined:
        # Both common order/degree conventions allow this unsplit root leaf.
        if order and len(keys)<=order-1 and (not leaf or len(keys)<=int(leaf[1])):return None
        return 'ambiguous_tree_rules'
    children=int(child[1]) if child else 2*int(degree[1]) if degree else order
    capacity=children-1
    if family[1]:
        shorthand=re.search(r'(?:最多|至多)\s*\d+\s*个?孩子\s*[,、]\s*(\d+)\s*个?(?:键|关键字)',query)
        if leaf or shorthand:
            capacity=int((leaf or shorthand)[1])
        elif re.search(r'内部|非叶',query) or not re.search(r'(?:最多|至多)\s*'+str(capacity)+r'\s*个?(?:键|关键字)',query):
            return 'ambiguous_tree_rules'
        if capacity<1:return 'ambiguous_tree_rules'
    if len(keys)<=capacity:return None
    if family[1]:
        left=re.search(r'左(?:叶|节点|结点)?(?:保留)?(?:前|取)?\s*(\d+)\s*(?:个?键)?',query)
        right=re.search(r'右(?:叶|节点|结点)?(?:保留)?(?:后|取)?\s*(\d+)\s*(?:个?键)?',query)
        copy_min=re.search(r'(?:复制|拷贝)右叶(?:结点|节点)?(?:的)?最小键|右叶(?:的)?最小键(?:复制|拷贝)',query)
        if (not left or not right or not copy_min or int(left[1])+int(right[1])!=capacity+1
                or not 1<=int(left[1])<=capacity or not 1<=int(right[1])<=capacity):
            return 'ambiguous_tree_split'
        if len(keys)>capacity+children-1:
            internal=re.search(r'内部(?:节点|结点)(.+)',query)
            if not internal or not median_split_defined(internal[1],children):return 'ambiguous_tree_split'
    elif not median_split_defined(query,capacity+1):
        # Min-degree top-down splitting has an odd full-node size, before insertion.
        if not (degree and re.search(r'插入前.*分裂满(?:节点|结点)',query) and re.search(r'(?:提升|上移)中间键|中间键(?:提升|上移)',query)):
            return 'ambiguous_tree_split'
    return None


def median_split_defined(query,overflow_keys):
    timing=bool(re.search(r'溢出|插入后|自底向上',query))
    promotion=bool(re.search(r'(?:提升|上移|上提)(?:左|右|上|下)?中(?:间|位)键|中间键(?:提升|上移|上提)',query))
    choice=overflow_keys%2==1 or bool(re.search(r'左中位|右中位|上中位|下中位|较[大小]的?中间键',query))
    return timing and promotion and choice


def preflight(query,evidence):
    if not evidence:return 'no_evidence'
    missing=missing_conditions(query)
    if missing:return missing
    terms={t for t in tokenize(query) if (len(t)>1 or t in {"树","图","栈","堆"}) and t not in GENERIC}
    if not terms or not any(terms&set(tokenize(e['content'])) for e in evidence):return 'no_lexical_support'
    facts={}
    for item in evidence:
        in_code=False
        for line in item['content'].splitlines():
            if line.strip().startswith('```'):in_code=not in_code;continue
            if in_code:continue
            match=re.fullmatch(r'\s*([^=：:\n]{2,60})\s*[=：:]\s*([^=：:\n]{1,200})\s*',line)
            if match:
                key=unicodedata.normalize('NFKC',match[1]).strip().casefold()
                value=unicodedata.normalize('NFKC',match[2]).strip().casefold()
                if terms&set(tokenize(key)):facts.setdefault(key,set()).add(value)
    return 'conflicting_assertions' if any(len(values)>1 for values in facts.values()) else None
