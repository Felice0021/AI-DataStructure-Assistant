"""Conservative lexical/conflicting-key preflight, not semantic evidence scoring."""
import re
import unicodedata
from backend.v2.services.lexical_search import tokenize

GENERIC=frozenset('什么 为什么 如何 请 解释 分析 计算 给定 资料 问题 课程 explain what why how code'.split())


def task_kind(query):
    """Internal pedagogy categories; public answer_mode remains qa/exercise/code."""
    if re.search(r'#include|```|std::|->|\b(?:int|void|char|bool|Node|TreeNode)\s*\*?\s+\w+\s*\(|\b(?:if|while|for)\s*\(|代码纠错|修正代码|递归(?:终止条件|边界)|逻辑错误',query,re.I):
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
    if not re.search(r'画出|构造|模拟插入|依次插入',query):
        return None
    if re.search(r'B\s*(?:\+)?\s*树',query,re.I) and not re.search(r'(?:\d+|[二三四五六七八九十]+)\s*阶|阶数\s*(?:为|是|[:：=])?\s*\d+',query):
        return 'missing_tree_order'
    if re.search(r'AVL|二叉(?:搜索|排序)?树|B\s*\+?\s*树',query,re.I) and not re.search(r'[0-9A-Za-z]+\s*[,，、]\s*[0-9A-Za-z]+|前序|中序|后序|层序|示例|示意',query):
        return 'missing_operation_sequence'
    return None


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
