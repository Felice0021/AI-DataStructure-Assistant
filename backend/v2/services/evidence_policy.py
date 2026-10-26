"""Conservative lexical/conflicting-key preflight, not semantic evidence scoring."""
import re
import unicodedata
from backend.v2.services.lexical_search import tokenize

GENERIC=frozenset('什么 为什么 如何 请 解释 分析 计算 给定 资料 问题 课程 explain what why how code'.split())


def resolve_mode(query,requested):
    if requested!='auto':return requested
    if re.search(r'#include|```|\b(?:int|void|char)\s+\w+\s*\(|代码|程序|报错|指针|越界',query,re.I):return 'code'
    if re.search(r'给定|计算|构造|求出|画出|遍历序列|排序过程|复杂度|最终结果',query):return 'exercise'
    return 'qa'


def preflight(query,evidence):
    if not evidence:return 'no_evidence'
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
