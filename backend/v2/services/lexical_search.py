"""Bounded request-local Okapi BM25. Never imports V1 or caches private text."""
from collections import Counter
from functools import lru_cache
import logging
import math
import re
import unicodedata

import jieba

PARTS = re.compile(r'[a-zA-Z_][a-zA-Z0-9_]*|\d+(?:\.\d+)?|[\u3400-\u9fff]+')
STOPWORDS = frozenset('的 了 和 与 是 在 及 或 一个 这个 那个 the a an and or of to is in'.split())


@lru_cache(maxsize=1)
def tokenizer():
    # Only the public dictionary is shared. No user input is added to it.
    jieba.setLogLevel(logging.WARNING)
    result = jieba.Tokenizer()
    result.initialize()
    for term in ('红黑树', '二叉树', '数据结构', '最短路径'):
        result.add_word(term, freq=1000000)
    return result


def tokenize(value):
    value = unicodedata.normalize('NFKC', value).casefold()
    # Protect mixed technical terms before Chinese segmentation (B 树 / B-tree).
    value = re.sub(r'(?<![a-z0-9_])b\s*(?:-\s*)?(?:树|tree)(?![a-z0-9_])', ' btree ', value)
    output = []
    for part in PARTS.findall(value):
        pieces = tokenizer().lcut(part, HMM=False) if '\u3400' <= part[0] <= '\u9fff' else [part]
        output.extend(p for p in pieces if p.strip() and p not in STOPWORDS)
    return output


def bm25(query_tokens, rows, settings):
    if not query_tokens or not rows:
        return []
    frequencies, lengths, df = [], [], Counter()
    total = 0
    for row in rows:
        terms = tokenize(row['content'])
        total += len(terms)
        if total > settings.retrieval_max_corpus_tokens:
            from backend.v2.core.errors import AuthError
            raise AuthError(413, 'retrieval_corpus_limit', 'Select a smaller knowledge base scope')
        tf = Counter(terms)
        frequencies.append(tf); lengths.append(len(terms)); df.update(tf.keys())
    average = sum(lengths) / len(rows)
    if not average:
        return []
    scores = []
    for row, tf, length in zip(rows, frequencies, lengths):
        score = 0.0
        norm = settings.retrieval_bm25_k1 * (1-settings.retrieval_bm25_b+settings.retrieval_bm25_b*length/average)
        for term in sorted(set(query_tokens)):
            count = tf.get(term, 0)
            if count:
                idf = math.log(1+(len(rows)-df[term]+0.5)/(df[term]+0.5))
                score += idf*count*(settings.retrieval_bm25_k1+1)/(count+norm)
        if score > 0:
            scores.append((row['chunk_id'], score))
    return sorted(scores, key=lambda x: (-x[1], str(x[0])))
