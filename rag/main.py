"""Canonical RAG entry point shared by backend and experiments."""
from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Dict, List, Sequence

import dashscope
from dotenv import load_dotenv

from rag.config import (
    DEFAULT_TOP_K,
    KNOWLEDGE_BASE_PATH,
    MIN_RETRIEVAL_SCORE,
    PROJECT_ROOT,
    RERANK_CANDIDATE_K,
    QUERY_EXPANSION_POOL_K,
    QUERY_EXPANSION_RRF_K,
    QUERY_EXPANSION_SUBQUERY_WEIGHT,
)
from rag.generators.qwen_generator import QwenGenerator
from rag.query_router import resolve_mode
from rag.query_processor import QueryProcessor
from rag.rerankers import QwenReranker
from rag.retrievers import (
    BM25Retriever,
    DenseRetriever,
    DenseRerankRetriever,
    HybridRetriever,
    load_chunks_from_jsonl,
)


logger = logging.getLogger(__name__)

# Load project-level environment variables.
load_dotenv(PROJECT_ROOT / ".env", override=True)
if os.getenv("DASHSCOPE_API_KEY"):
    dashscope.api_key = os.getenv("DASHSCOPE_API_KEY")

_workspace_id = os.getenv("DASHSCOPE_WORKSPACE_ID")
_region = os.getenv("DASHSCOPE_REGION")

if _workspace_id and _region:
    dashscope.base_http_api_url = (
        f"https://{_workspace_id}.{_region}.maas.aliyuncs.com/api/v1"
    )

_DENSE = DenseRetriever()
_DENSE_RERANK = DenseRerankRetriever(dense=_DENSE)
_BM25 = BM25Retriever()
_HYBRID = HybridRetriever(
    dense=_DENSE,
    bm25=_BM25,
    candidate_k=RERANK_CANDIDATE_K,
)
_RERANKER = QwenReranker()
_QUERY_PROCESSOR = QueryProcessor()
_GENERATOR: QwenGenerator | None = None


def get_retriever(name: str):
    normalized = (name or "dense").strip().lower()
    if normalized == "dense":
        return _DENSE
    if normalized == "dense_rerank":
        return _DENSE_RERANK
    if normalized == "bm25":
        return _BM25
    if normalized == "hybrid":
        return _HYBRID
    raise ValueError(f"未知 retriever：{name}")


def prepare_knowledge_base(
    file_path: Path = KNOWLEDGE_BASE_PATH,
    use_cache: bool = True,
) -> List[Dict]:
    """Load chunks and prepare the indexes required by production RAG."""
    chunks = load_chunks_from_jsonl(Path(file_path))
    _HYBRID.prepare(chunks, use_cache=use_cache)
    return chunks


def prepare_retriever(
    retriever_name: str,
    chunks: Sequence[Dict],
    *,
    use_cache: bool = True,
) -> None:
    retriever = get_retriever(retriever_name)
    if retriever_name.lower() in {"dense", "dense_rerank", "hybrid"}:
        retriever.prepare(chunks, use_cache=use_cache)
    else:
        retriever.prepare(chunks)


def retrieve(
    query: str,
    chunks: Sequence[Dict],
    top_k: int = DEFAULT_TOP_K,
    retriever_name: str = "dense",
) -> List[Dict]:
    retriever = get_retriever(retriever_name)
    return retriever.retrieve(query=query, chunks=chunks, top_k=top_k)


def _retrieve_production_candidates(
    query: str,
    mode: str,
    chunks: Sequence[Dict],
    *,
    top_k: int,
) -> tuple[List[Dict], List[str], float | None]:
    """Production retrieval with batched multi-query Hybrid search."""

    retrieval_queries = _QUERY_PROCESSOR.process(
        query,
        mode=mode,
    )

    if not retrieval_queries:
        retrieval_queries = [query]

    per_query_k = min(
        len(chunks),
        max(RERANK_CANDIDATE_K, top_k),
    )

    # All Dense query embeddings are generated in one API request.
    per_query_results = _HYBRID.retrieve_many(
        retrieval_queries,
        chunks,
        top_k=per_query_k,
    )

    original_results = (
        per_query_results[0]
        if per_query_results
        else []
    )

    original_dense_top1 = (
        original_results[0].get(
            "dense_top1_score"
        )
        if original_results
        else None
    )

    if len(retrieval_queries) == 1:
        candidates = original_results

        for item in candidates:
            item["multi_query_score"] = (
                item.get("score")
            )
            item["matched_queries"] = [query]

        return (
            candidates,
            retrieval_queries,
            original_dense_top1,
        )

    fused: Dict[str, Dict] = {}

    for query_index, (
        retrieval_query,
        results,
    ) in enumerate(
        zip(
            retrieval_queries,
            per_query_results,
        )
    ):
        query_weight = (
            1.0
            if query_index == 0
            else QUERY_EXPANSION_SUBQUERY_WEIGHT
        )

        for rank, item in enumerate(
            results,
            start=1,
        ):
            chunk_id = str(
                item.get("chunk_id", "")
            )

            if not chunk_id:
                continue

            if chunk_id not in fused:
                fused[chunk_id] = {
                    "chunk": dict(item),
                    "score": 0.0,
                    "matches": [],
                }

            record = fused[chunk_id]

            record["score"] += (
                query_weight
                / (
                    QUERY_EXPANSION_RRF_K
                    + rank
                )
            )

            record["matches"].append(
                {
                    "query_index": query_index,
                    "query": retrieval_query,
                    "rank": rank,
                    "hybrid_score": float(
                        item.get(
                            "score",
                            0.0,
                        )
                    ),
                    "dense_rank": item.get(
                        "dense_rank"
                    ),
                    "bm25_rank": item.get(
                        "bm25_rank"
                    ),
                    "dense_score": item.get(
                        "dense_score"
                    ),
                    "bm25_score": item.get(
                        "bm25_score"
                    ),
                }
            )

    ranked = sorted(
        fused.values(),
        key=lambda record: (
            -float(record["score"]),
            str(
                record["chunk"].get(
                    "chunk_id",
                    "",
                )
            ),
        ),
    )

    pool_k = min(
        len(ranked),
        max(
            QUERY_EXPANSION_POOL_K,
            top_k,
        ),
    )

    candidates: List[Dict] = []

    for record in ranked[:pool_k]:
        item = dict(record["chunk"])

        item["multi_query_score"] = float(
            record["score"]
        )
        item["score"] = float(
            record["score"]
        )

        item["matched_queries"] = [
            match["query"]
            for match in record["matches"]
        ]

        item["query_matches"] = (
            record["matches"]
        )

        item["dense_top1_score"] = (
            original_dense_top1
        )

        candidates.append(item)

    return (
        candidates,
        retrieval_queries,
        original_dense_top1,
    )

def _get_generator() -> QwenGenerator:
    global _GENERATOR
    if _GENERATOR is None:
        _GENERATOR = QwenGenerator()
    return _GENERATOR


def _empty_result(
    *,
    mode: str,
    started_at: float,
    code: str,
    message: str,
) -> Dict:
    total_ms = int((time.perf_counter() - started_at) * 1000)
    return {
        "answer": "",
        "sources": [],
        "retrieved_chunks": [],
        "mode": mode,
        "out_of_scope": False,
        "threshold_score": None,
        "rerank_fallback": False,
        "latency_ms": {
            "retrieval": 0,
            "rerank": 0,
            "generation": 0,
            "total": total_ms,
        },
        "error": {"code": code, "message": message},
    }


def run(
    query: str,
    chunks: Sequence[Dict],
    *,
    top_k: int = DEFAULT_TOP_K,
    mode: str = "auto",
    min_retrieval_score: float | None = None,
) -> Dict:
    """Run the production RAG pipeline.

    Production path:
    query -> mode routing -> Dense+BM25 RRF -> rerank -> scope check ->
    generation -> answer + sources.

    ``out_of_scope`` is intentionally decided from the Dense top-1 score,
    not from BM25/RRF/rerank scores because those scores are on different
    scales.
    """
    started_at = time.perf_counter()
    query = (query or "").strip()

    try:
        resolved_mode = resolve_mode(query, mode)
    except ValueError as exc:
        return _empty_result(
            mode="qa",
            started_at=started_at,
            code="INVALID_MODE",
            message=str(exc),
        )

    if not query:
        return _empty_result(
            mode=resolved_mode,
            started_at=started_at,
            code="INVALID_QUERY",
            message="问题不能为空。",
        )

    if top_k <= 0:
        return _empty_result(
            mode=resolved_mode,
            started_at=started_at,
            code="INVALID_TOP_K",
            message="top_k 必须大于 0。",
        )

    try:
        retrieval_started = time.perf_counter()

        (
            candidates,
            retrieval_queries,
            dense_top1_score,
        ) = _retrieve_production_candidates(
            query=query,
            mode=resolved_mode,
            chunks=chunks,
            top_k=top_k,
        )

        retrieval_ms = int(
            (time.perf_counter() - retrieval_started) * 1000
        )

        if not candidates:
            result = _empty_result(
                mode=resolved_mode,
                started_at=started_at,
                code="EMPTY_RETRIEVAL",
                message="没有检索到相关课程资料。",
            )
            result["latency_ms"]["retrieval"] = retrieval_ms
            result["latency_ms"]["total"] = int(
                (time.perf_counter() - started_at) * 1000
            )
            return result

        threshold = (
            MIN_RETRIEVAL_SCORE
            if min_retrieval_score is None
            else min_retrieval_score
        )

        if (
            dense_top1_score is not None
            and threshold is not None
            and float(dense_top1_score) < float(threshold)
        ):
            total_ms = int(
                (time.perf_counter() - started_at) * 1000
            )
            return {
                "answer": "根据当前资料无法确定",
                "sources": [],
                "retrieved_chunks": candidates,
                "retrieval_queries": retrieval_queries,
                "mode": resolved_mode,
                "out_of_scope": True,
                "threshold_score": float(dense_top1_score),
                "rerank_fallback": False,
                "latency_ms": {
                    "retrieval": retrieval_ms,
                    "rerank": 0,
                    "generation": 0,
                    "total": total_ms,
                },
                "error": None,
            }

        rerank_started = time.perf_counter()
        try:
            candidate_by_id = {
                str(item["chunk_id"]): item
                for item in candidates
            }

            reranked = _RERANKER.rerank(
                query=query,
                candidates=candidates,
                top_n=min(top_k, len(candidates)),
            )

            # QwenReranker was originally written for Dense-only candidates.
            # Restore Hybrid provenance so Dense/BM25 metadata stays truthful.
            for item in reranked:
                source = candidate_by_id.get(
                    str(item.get("chunk_id", ""))
                )
                if source is None:
                    continue

                item["hybrid_score"] = float(
                    source.get("score", 0.0)
                )

                for key in (
                    "dense_rank",
                    "bm25_rank",
                    "dense_score",
                    "bm25_score",
                    "dense_top1_score",
                ):
                    item[key] = source.get(key)

            final_chunks = reranked
            rerank_fallback = False
        except Exception as exc:
            logger.warning(
                "Reranker failed; falling back to Hybrid Top-K: %s",
                exc,
            )
            final_chunks = candidates[:top_k]
            rerank_fallback = True

        rerank_ms = int(
            (time.perf_counter() - rerank_started) * 1000
        )

        generation_started = time.perf_counter()
        answer = _get_generator().generate(
            query,
            final_chunks,
            mode=resolved_mode,
        )
        generation_ms = int(
            (time.perf_counter() - generation_started) * 1000
        )

        sources = [
            {
                "chunk_id": item.get("chunk_id", "unknown"),
                "chapter": item.get("chapter", ""),
                "section": item.get("section", ""),
                "source_file": item.get("source_file", ""),
                "page": item.get("page"),
                "content_type": item.get("content_type", ""),
            }
            for item in final_chunks
        ]

        total_ms = int(
            (time.perf_counter() - started_at) * 1000
        )
        return {
            "answer": answer,
            "sources": sources,
            "retrieved_chunks": final_chunks,
            "retrieval_queries": retrieval_queries,
            "mode": resolved_mode,
            "out_of_scope": False,
            "threshold_score": (
                float(dense_top1_score)
                if dense_top1_score is not None
                else None
            ),
            "rerank_fallback": rerank_fallback,
            "latency_ms": {
                "retrieval": retrieval_ms,
                "rerank": rerank_ms,
                "generation": generation_ms,
                "total": total_ms,
            },
            "error": None,
        }
    except Exception as exc:
        total_ms = int(
            (time.perf_counter() - started_at) * 1000
        )
        return {
            "answer": "",
            "sources": [],
            "retrieved_chunks": [],
            "mode": resolved_mode,
            "out_of_scope": False,
            "threshold_score": None,
            "rerank_fallback": False,
            "latency_ms": {
                "retrieval": 0,
                "rerank": 0,
                "generation": 0,
                "total": total_ms,
            },
            "error": {
                "code": type(exc).__name__,
                "message": str(exc),
            },
        }


def answer_question(
    query: str,
    chunks: Sequence[Dict],
    top_k: int = DEFAULT_TOP_K,
    retriever_name: str = "dense",
    min_retrieval_score: float | None = None,
) -> Dict:
    """Backward-compatible experiment/baseline entry point.

    New production code should call :func:`run`. This function is retained so
    existing retrieval experiments are not silently changed.
    """
    start = time.perf_counter()
    query = (query or "").strip()
    if not query:
        return {
            "answer": "",
            "sources": [],
            "retrieved_chunks": [],
            "latency_ms": 0,
            "error": {"code": "INVALID_QUERY", "message": "问题不能为空。"},
        }

    try:
        retrieved = retrieve(
            query=query,
            chunks=chunks,
            top_k=top_k,
            retriever_name=retriever_name,
        )
        if not retrieved:
            return {
                "answer": "",
                "sources": [],
                "retrieved_chunks": [],
                "latency_ms": int((time.perf_counter() - start) * 1000),
                "error": {"code": "EMPTY_RETRIEVAL", "message": "没有检索到相关课程资料。"},
            }

        scores = [float(item["score"]) for item in retrieved]
        top1_score = scores[0]

        normalized_retriever = retriever_name.lower()
        threshold_score = top1_score

        if normalized_retriever == "dense_rerank":
            threshold_score = float(
                retrieved[0].get(
                    "dense_top1_score",
                    retrieved[0].get(
                        "dense_score",
                        top1_score,
                    ),
                )
            )

        threshold = min_retrieval_score
        if (
            threshold is None
            and normalized_retriever
            in {"dense", "dense_rerank"}
        ):
            threshold = MIN_RETRIEVAL_SCORE

        if threshold is not None and threshold_score < threshold:
            return {
                "answer": "根据当前资料无法确定",
                "sources": [],
                "retrieved_chunks": retrieved,
                "retrieval_scores": scores,
                "top1_score": top1_score,
                "threshold_score": threshold_score,
                "out_of_scope": True,
                "latency_ms": int((time.perf_counter() - start) * 1000),
                "error": None,
            }

        answer = _get_generator().generate(query, retrieved)
        sources = [
            {
                "chunk_id": item.get("chunk_id", "unknown"),
                "chapter": item.get("chapter", ""),
                "section": item.get("section", ""),
                "source_file": item.get("source_file", ""),
                "page": item.get("page"),
            }
            for item in retrieved
        ]
        return {
            "answer": answer,
            "sources": sources,
            "retrieved_chunks": retrieved,
            "retrieval_scores": scores,
            "top1_score": top1_score,
            "threshold_score": threshold_score,
            "out_of_scope": False,
            "latency_ms": int((time.perf_counter() - start) * 1000),
            "error": None,
        }
    except Exception as exc:
        return {
            "answer": "",
            "sources": [],
            "retrieved_chunks": [],
            "latency_ms": int((time.perf_counter() - start) * 1000),
            "error": {"code": type(exc).__name__, "message": str(exc)},
        }
