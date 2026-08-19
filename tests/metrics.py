"""公共检索评测指标模块。

本模块只包含纯函数，不依赖任何检索器实现，供 Dense / BM25 / Hybrid
等所有检索方法共用。所有函数输入均为 chunk_id 列表，输出为单个数值。
"""
from __future__ import annotations

import math
from typing import Iterable, List, Sequence


def as_list(value) -> List:
    """把标量或列表统一为列表；None 返回空列表。"""
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def recall_at_k(retrieved_ids: Sequence[str], expected_ids, k: int) -> float:
    """Recall@K = |retrieved[:k] ∩ expected| / |expected|。

    参数:
        retrieved_ids: 按相关度降序排列的检索结果 chunk_id 列表。
        expected_ids: 期望命中的 chunk_id（单个或列表）。
        k: 截断位置（>=1）。
    返回:
        [0, 1] 之间的召回率；期望为空时返回 0.0。
    """
    expected = set(as_list(expected_ids))
    if not expected or k <= 0:
        return 0.0
    hits = sum(1 for cid in retrieved_ids[:k] if cid in expected)
    return hits / len(expected)


def mrr_at_k(retrieved_ids: Sequence[str], expected_ids, k: int) -> float:
    """单条查询的 Reciprocal Rank@K。

    首个命中出现在 rank <= k 时返回 1/rank，否则返回 0。
    对全部查询取均值即得到 MRR@K。
    """
    expected = set(as_list(expected_ids))
    if not expected or k <= 0:
        return 0.0
    for rank, cid in enumerate(retrieved_ids[:k], start=1):
        if cid in expected:
            return 1.0 / rank
    return 0.0


def ndcg_at_k(retrieved_ids: Sequence[str], expected_ids, k: int) -> float:
    """nDCG@K（binary relevance）。

    DCG@K = Σ rel_i / log2(i + 1)，rel_i 表示第 i 位结果是否命中期望 chunk；
    IDCG@K 为期望 chunk 排在理想位置（最前）时的最大 DCG。
    """
    expected = set(as_list(expected_ids))
    if not expected or k <= 0:
        return 0.0

    def dcg(items: Sequence[str]) -> float:
        return sum(
            1.0 / math.log2(i + 1)
            for i, cid in enumerate(items, start=1)
            if cid in expected
        )

    dcg_value = dcg(retrieved_ids[:k])
    idcg_value = sum(
        1.0 / math.log2(i + 1)
        for i in range(1, min(k, len(expected)) + 1)
    )
    return dcg_value / idcg_value if idcg_value > 0 else 0.0


def avg_latency(latencies: Iterable[float]) -> float:
    """平均检索耗时（毫秒）。"""
    values = list(latencies)
    return sum(values) / len(values) if values else 0.0


def p95_latency(latencies: Iterable[float]) -> float:
    """检索耗时 95 分位（毫秒）。"""
    values = sorted(latencies)
    if not values:
        return 0.0
    index = max(0, math.ceil(len(values) * 0.95) - 1)
    return values[index]