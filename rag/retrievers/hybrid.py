"""Hybrid Dense + BM25 retrieval using Reciprocal Rank Fusion (RRF)."""

from __future__ import annotations

from typing import Dict, List, Sequence

from rag.config import DEFAULT_TOP_K
from rag.retrievers.base import BaseRetriever
from rag.retrievers.bm25 import BM25Retriever
from rag.retrievers.dense import DenseRetriever


class HybridRetriever(BaseRetriever):
    """Fuse Dense and BM25 rankings with Reciprocal Rank Fusion.

    RRF uses rank positions instead of raw retrieval scores, avoiding direct
    comparison between cosine-similarity scores and BM25 scores.
    """

    def __init__(
        self,
        dense: DenseRetriever | None = None,
        bm25: BM25Retriever | None = None,
        *,
        candidate_k: int = 10,
        rrf_k: int = 60,
        dense_weight: float = 1.0,
        bm25_weight: float = 1.0,
    ) -> None:
        if candidate_k <= 0:
            raise ValueError("candidate_k 必须大于 0")
        if rrf_k < 0:
            raise ValueError("rrf_k 必须大于等于 0")
        if dense_weight < 0 or bm25_weight < 0:
            raise ValueError("fusion weight 不能为负数")
        if dense_weight == 0 and bm25_weight == 0:
            raise ValueError("Dense 与 BM25 权重不能同时为 0")

        self.dense = dense or DenseRetriever()
        self.bm25 = bm25 or BM25Retriever()

        self.candidate_k = int(candidate_k)
        self.rrf_k = int(rrf_k)
        self.dense_weight = float(dense_weight)
        self.bm25_weight = float(bm25_weight)

    def get_name(self) -> str:
        return "hybrid"

    def get_config(self) -> Dict:
        return {
            "retriever": self.get_name(),
            "candidate_k": self.candidate_k,
            "rrf_k": self.rrf_k,
            "dense_weight": self.dense_weight,
            "bm25_weight": self.bm25_weight,
            "dense": self.dense.get_config(),
            "bm25": self.bm25.get_config(),
        }

    def prepare(
        self,
        chunks: Sequence[Dict],
        *,
        use_cache: bool = True,
        **_: object,
    ) -> None:
        self.dense.prepare(chunks, use_cache=use_cache)
        self.bm25.prepare(chunks)

    def retrieve_many(
        self,
        queries: Sequence[str],
        chunks: Sequence[Dict],
        top_k: int = DEFAULT_TOP_K,
    ) -> List[List[Dict]]:
        """Batch Dense queries, then fuse each with BM25 via RRF."""
        queries = [
            (q or "").strip()
            for q in queries
        ]

        if not queries:
            return []

        if not chunks or top_k <= 0:
            return [[] for _ in queries]

        candidate_k = min(
            len(chunks),
            max(self.candidate_k, top_k),
        )

        dense_batches = self.dense.retrieve_many(
            queries,
            chunks,
            top_k=candidate_k,
        )

        all_results: List[List[Dict]] = []

        for query, dense_results in zip(
            queries,
            dense_batches,
        ):
            if not query:
                all_results.append([])
                continue

            bm25_results = self.bm25.retrieve(
                query=query,
                chunks=chunks,
                top_k=candidate_k,
            )

            dense_top1_score = (
                float(dense_results[0]["score"])
                if dense_results
                else None
            )

            fused: Dict[str, Dict] = {}

            def ensure_item(item: Dict) -> Dict:
                chunk_id = str(
                    item.get("chunk_id", "")
                )

                if not chunk_id:
                    raise RuntimeError(
                        "Hybrid retrieval 遇到缺少 "
                        "chunk_id 的结果"
                    )

                if chunk_id not in fused:
                    base = dict(item)
                    base.pop("embedding", None)

                    fused[chunk_id] = {
                        "chunk": base,
                        "score": 0.0,
                        "dense_rank": None,
                        "bm25_rank": None,
                        "dense_score": None,
                        "bm25_score": None,
                    }

                return fused[chunk_id]

            for rank, item in enumerate(
                dense_results,
                start=1,
            ):
                record = ensure_item(item)

                record["score"] += (
                    self.dense_weight
                    / (self.rrf_k + rank)
                )
                record["dense_rank"] = rank
                record["dense_score"] = float(
                    item["score"]
                )

            for rank, item in enumerate(
                bm25_results,
                start=1,
            ):
                record = ensure_item(item)

                record["score"] += (
                    self.bm25_weight
                    / (self.rrf_k + rank)
                )
                record["bm25_rank"] = rank
                record["bm25_score"] = float(
                    item["score"]
                )

            ranked = sorted(
                fused.values(),
                key=lambda x: (
                    -x["score"],
                    x["chunk"].get(
                        "chunk_id",
                        "",
                    ),
                ),
            )

            query_results: List[Dict] = []

            for record in ranked[:top_k]:
                item = dict(record["chunk"])

                item["score"] = float(
                    record["score"]
                )
                item["dense_rank"] = (
                    record["dense_rank"]
                )
                item["bm25_rank"] = (
                    record["bm25_rank"]
                )
                item["dense_score"] = (
                    record["dense_score"]
                )
                item["bm25_score"] = (
                    record["bm25_score"]
                )
                item["dense_top1_score"] = (
                    dense_top1_score
                )

                query_results.append(item)

            all_results.append(query_results)

        return all_results

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

        dense_results = self.dense.retrieve(
            query=query,
            chunks=chunks,
            top_k=candidate_k,
        )

        bm25_results = self.bm25.retrieve(
            query=query,
            chunks=chunks,
            top_k=candidate_k,
        )

        dense_top1_score = (
            float(dense_results[0]["score"])
            if dense_results
            else None
        )

        fused: Dict[str, Dict] = {}

        def ensure_item(item: Dict) -> Dict:
            chunk_id = str(item.get("chunk_id", ""))
            if not chunk_id:
                raise RuntimeError("Hybrid retrieval 遇到缺少 chunk_id 的结果")

            if chunk_id not in fused:
                base = dict(item)
                base.pop("embedding", None)

                fused[chunk_id] = {
                    "chunk": base,
                    "score": 0.0,
                    "dense_rank": None,
                    "bm25_rank": None,
                    "dense_score": None,
                    "bm25_score": None,
                }

            return fused[chunk_id]

        for rank, item in enumerate(dense_results, start=1):
            record = ensure_item(item)

            record["score"] += (
                self.dense_weight / (self.rrf_k + rank)
            )
            record["dense_rank"] = rank
            record["dense_score"] = float(item["score"])

        for rank, item in enumerate(bm25_results, start=1):
            record = ensure_item(item)

            record["score"] += (
                self.bm25_weight / (self.rrf_k + rank)
            )
            record["bm25_rank"] = rank
            record["bm25_score"] = float(item["score"])

        ranked = sorted(
            fused.values(),
            key=lambda x: (
                -x["score"],
                x["chunk"].get("chunk_id", ""),
            ),
        )

        results: List[Dict] = []

        for record in ranked[:top_k]:
            item = dict(record["chunk"])

            item["score"] = float(record["score"])
            item["dense_rank"] = record["dense_rank"]
            item["bm25_rank"] = record["bm25_rank"]
            item["dense_score"] = record["dense_score"]
            item["bm25_score"] = record["bm25_score"]
            item["dense_top1_score"] = dense_top1_score

            results.append(item)

        return results
