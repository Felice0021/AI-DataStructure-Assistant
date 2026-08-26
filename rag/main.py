"""Canonical RAG entry point shared by backend and experiments."""
from __future__ import annotations

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
)
from rag.generators.qwen_generator import QwenGenerator
from rag.retrievers import BM25Retriever, DenseRetriever, load_chunks_from_jsonl


# Load project-level environment variables.
load_dotenv(PROJECT_ROOT / ".env", override=False)
if os.getenv("DASHSCOPE_API_KEY"):
    dashscope.api_key = os.getenv("DASHSCOPE_API_KEY")

_DENSE = DenseRetriever()
_BM25 = BM25Retriever()
_GENERATOR: QwenGenerator | None = None


def get_retriever(name: str):
    normalized = (name or "dense").strip().lower()
    if normalized == "dense":
        return _DENSE
    if normalized == "bm25":
        return _BM25
    raise ValueError(f"未知 retriever：{name}")


def prepare_knowledge_base(
    file_path: Path = KNOWLEDGE_BASE_PATH,
    use_cache: bool = True,
) -> List[Dict]:
    """Load chunks and prepare dense document embeddings once.

    The dense cache is corpus-fingerprint aware; if the corpus or embedding
    configuration changes, a new cache file is generated automatically.
    """
    chunks = load_chunks_from_jsonl(Path(file_path))
    _DENSE.prepare(chunks, use_cache=use_cache)
    return chunks


def prepare_retriever(
    retriever_name: str,
    chunks: Sequence[Dict],
    *,
    use_cache: bool = True,
) -> None:
    retriever = get_retriever(retriever_name)
    if retriever_name.lower() == "dense":
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


def _get_generator() -> QwenGenerator:
    global _GENERATOR
    if _GENERATOR is None:
        _GENERATOR = QwenGenerator()
    return _GENERATOR


def answer_question(
    query: str,
    chunks: Sequence[Dict],
    top_k: int = DEFAULT_TOP_K,
    retriever_name: str = "dense",
    min_retrieval_score: float | None = None,
) -> Dict:
    """Run retrieval + generation using the canonical RAG implementation.

    For backward-compatible production behavior, the historical threshold is
    applied only to Dense retrieval. BM25 scores use a different scale and are
    never compared against the Dense cosine threshold.
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

        threshold = min_retrieval_score
        if threshold is None and retriever_name.lower() == "dense":
            threshold = MIN_RETRIEVAL_SCORE

        if threshold is not None and top1_score < threshold:
            return {
                "answer": "根据当前资料无法确定",
                "sources": [],
                "retrieved_chunks": retrieved,
                "retrieval_scores": scores,
                "top1_score": top1_score,
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
