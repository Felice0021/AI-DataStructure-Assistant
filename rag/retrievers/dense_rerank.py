"""Dense retrieval followed by Qwen reranking with optional score fusion."""

from __future__ import annotations

import logging

from typing import Dict, List, Sequence

from rag.config import (
    DEFAULT_TOP_K,
    RERANK_CANDIDATE_K,
    RERANK_FUSION_ALPHA,
)
from rag.rerankers import QwenReranker
from rag.retrievers.base import BaseRetriever
from rag.retrievers.dense import DenseRetriever


logger = logging.getLogger(__name__)


class DenseRerankRetriever(BaseRetriever):
    def __init__(
        self,
        *,
        dense: DenseRetriever | None = None,
        reranker: QwenReranker | None = None,
        candidate_k: int = RERANK_CANDIDATE_K,
        fusion_alpha: float = RERANK_FUSION_ALPHA,
    ) -> None:
        if candidate_k <= 0:
            raise ValueError("candidate_k 必须大于 0")

        if not 0.0 <= fusion_alpha <= 1.0:
            raise ValueError("fusion_alpha 必须位于 [0, 1]")

        self.dense = dense or DenseRetriever()
        self.reranker = reranker or QwenReranker()
        self.candidate_k = int(candidate_k)
        self.fusion_alpha = float(fusion_alpha)

    def get_name(self) -> str:
        return "dense_rerank"

    def get_config(self) -> Dict:
        return {
            "retriever": self.get_name(),
            "candidate_k": self.candidate_k,
            "fusion_alpha": self.fusion_alpha,
            "dense": self.dense.get_config(),
            "reranker": self.reranker.get_config(),
        }

    def prepare(
        self,
        chunks: Sequence[Dict],
        *,
        use_cache: bool = True,
        **_: object,
    ) -> None:
        self.dense.prepare(
            chunks,
            use_cache=use_cache,
        )

    @staticmethod
    def _minmax(values: List[float]) -> List[float]:
        if not values:
            return []

        lo = min(values)
        hi = max(values)

        if hi <= lo:
            return [1.0 for _ in values]

        return [
            (x - lo) / (hi - lo)
            for x in values
        ]

    def retrieve(
        self,
        query: str,
        chunks: Sequence[Dict],
        top_k: int = DEFAULT_TOP_K,
    ) -> List[Dict]:
        query = (query or "").strip()

        if not query or not chunks or top_k <= 0:
            return []

        candidate_k = min(
            len(chunks),
            max(self.candidate_k, top_k),
        )

        dense_candidates = self.dense.retrieve(
            query=query,
            chunks=chunks,
            top_k=candidate_k,
        )

        # 让 reranker 给所有 Dense Top-N 候选评分，
        # 而不是只返回最终 Top-K。
        dense_top1_score = float(
            dense_candidates[0]["score"]
        )

        try:
            reranked_all = self.reranker.rerank(
                query=query,
                candidates=dense_candidates,
                top_n=len(dense_candidates),
            )
        except Exception as exc:
            # Production fail-open:
            # reranker 不可用时，仍然返回 Dense Top-K。
            logger.warning(
                "Reranker failed; falling back to Dense Top-K: %s",
                exc,
            )

            fallback: List[Dict] = []

            for dense_rank, source in enumerate(
                dense_candidates[:top_k],
                start=1,
            ):
                item = dict(source)
                dense_score = float(
                    source.get("score", 0.0)
                )

                item["dense_rank"] = dense_rank
                item["dense_score"] = dense_score
                item["dense_top1_score"] = dense_top1_score
                item["rerank_score"] = None
                item["rerank_fallback"] = True

                fallback.append(item)

            return fallback

        # 恢复以 chunk_id 为键的 rerank 分数。
        rerank_score_by_id = {
            str(item["chunk_id"]): float(item["rerank_score"])
            for item in reranked_all
        }

        dense_scores = [
            float(item["score"])
            for item in dense_candidates
        ]

        rerank_scores = [
            rerank_score_by_id[str(item["chunk_id"])]
            for item in dense_candidates
        ]

        dense_norm = self._minmax(dense_scores)
        rerank_norm = self._minmax(rerank_scores)

        fused: List[Dict] = []

        for dense_rank, (
            source,
            dense_raw,
            dense_n,
            rerank_raw,
            rerank_n,
        ) in enumerate(
            zip(
                dense_candidates,
                dense_scores,
                dense_norm,
                rerank_scores,
                rerank_norm,
            ),
            start=1,
        ):
            final_score = (
                self.fusion_alpha * rerank_n
                + (1.0 - self.fusion_alpha) * dense_n
            )

            item = dict(source)

            item["dense_rank"] = dense_rank
            item["dense_score"] = dense_raw
            item["dense_score_norm"] = dense_n
            item["rerank_score"] = rerank_raw
            item["rerank_score_norm"] = rerank_n
            item["fusion_score"] = final_score
            item["dense_top1_score"] = dense_top1_score
            item["rerank_fallback"] = False

            # 统一评测接口仍然读取 score。
            item["score"] = final_score

            fused.append(item)

        fused.sort(
            key=lambda x: (
                -float(x["fusion_score"]),
                int(x["dense_rank"]),
            )
        )

        return fused[:top_k]
