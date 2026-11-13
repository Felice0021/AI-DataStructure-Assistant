"""Small lexical input reader, not a tree solver or a source of default conventions."""
import re
import unicodedata


def normalized(text):
    return unicodedata.normalize('NFKC', text)


def operation_sequence(text):
    """Read explicit single keys or key lists; never mistake an order/count for keys."""
    text = normalized(text)
    key = r'(?:[+-]?\d+|[A-Za-z])'
    run = re.compile(r'\s*[:=]?\s*[\[({]?\s*(' + key + r'(?:\s*[,、;\s]\s*' + key + r')*)(?![A-Za-z0-9])')
    for prefix in (r'(?:待插入序列|插入序列|键值?序列|序列)\s*(?:为|是)?', r'(?:依次|按顺序)?(?:插入|删除)\s*(?:键值?|元素)?\s*(?:为|是)?', r'(?:前序|先序|中序|后序|层序)\s*(?:为|是)?'):
        sequences = []
        for anchor in re.finditer(prefix, text):
            match = run.match(text, anchor.end())
            if match and re.match(r'\s*(?:个|次|步|阶)|[./-]\d', text[match.end():]):
                return ()  # Do not silently keep only the supported suffix of a malformed task.
            if match:
                sequences.extend(str(int(k)) if re.fullmatch(r'[+-]?\d+',k) else k for k in re.findall(key, match[1]))
        if sequences:
            return tuple(sequences)
    return ()


def first_insert_count(text):
    text = normalized(text)
    match = re.search(r'(?:先|只)(?:只)?展示(?:第|前)?([0-9]+|[一二三四五六七八九十])次插入', text)
    if not match:
        return None
    return int(match[1]) if match[1].isdigit() else '一二三四五六七八九十'.index(match[1]) + 1
