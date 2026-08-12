"""Retrieval-only evaluation for the BM25 baseline.

Run from the project root:
    PYTHONPATH=. python3 tests/run_bm25_evaluation.py

Outputs:
    tests/bm25_test_results.jsonl
    tests/bm25_evaluation_summary.json
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import time
from pathlib import Path
from typing import Dict, Iterable, List

from rag.config import DEFAULT_TOP_K, KNOWLEDGE_BASE_PATH
from rag.retrievers.bm25 import BM25Retriever


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_QUESTION_FILE = PROJECT_ROOT / "tests" / "test_questions.jsonl"
DEFAULT_RESULT_FILE = PROJECT_ROOT / "tests" / "bm25_test_results.jsonl"
DEFAULT_SUMMARY_FILE = PROJECT_ROOT / "tests" / "bm25_evaluation_summary.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate BM25 retrieval baseline")
    parser.add_argument("--top-k", type=int, default=DEFAULT_TOP_K)
    parser.add_argument("--k1", type=float, default=1.5)
    parser.add_argument("--b", type=float, default=0.75)
    parser.add_argument("--knowledge-file", type=Path, default=KNOWLEDGE_BASE_PATH)
    parser.add_argument("--question-file", type=Path, default=DEFAULT_QUESTION_FILE)
    parser.add_argument("--result-file", type=Path, default=DEFAULT_RESULT_FILE)
    parser.add_argument("--summary-file", type=Path, default=DEFAULT_SUMMARY_FILE)
    return parser.parse_args()


def load_jsonl(path: Path) -> List[Dict]:
    records: List[Dict] = []
    with path.open("r", encoding="utf-8") as file:
        for line_number, raw_line in enumerate(file, start=1):
            line = raw_line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise RuntimeError(
                    f"{path} 第 {line_number} 行 JSON 格式错误：{exc}"
                ) from exc
    return records


def as_list(value) -> List:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def field_hit(retrieved: List[Dict], field: str, expected) -> bool:
    expected_values = set(as_list(expected))
    if not expected_values:
        return False
    return any(item.get(field) in expected_values for item in retrieved)


def chunk_recall(retrieved: List[Dict], expected_chunk_ids) -> float:
    expected = set(as_list(expected_chunk_ids))
    if not expected:
        return 0.0
    retrieved_ids = {item.get("chunk_id") for item in retrieved}
    return len(expected & retrieved_ids) / len(expected)


def reciprocal_rank(retrieved: List[Dict], expected_chunk_ids) -> float:
    expected = set(as_list(expected_chunk_ids))
    if not expected:
        return 0.0
    for rank, item in enumerate(retrieved, start=1):
        if item.get("chunk_id") in expected:
            return 1.0 / rank
    return 0.0


def percentile_95(values: Iterable[float]) -> float:
    values = sorted(values)
    if not values:
        return 0.0
    index = max(0, math.ceil(len(values) * 0.95) - 1)
    return values[index]


def main() -> None:
    args = parse_args()
    if args.top_k <= 0:
        raise ValueError("--top-k 必须大于 0")

    questions = load_jsonl(args.question_file)

    build_start = time.perf_counter()
    retriever = BM25Retriever.from_jsonl(
        args.knowledge_file,
        k1=args.k1,
        b=args.b,
    )
    build_latency_ms = (time.perf_counter() - build_start) * 1000

    results: List[Dict] = []
    retrieval_latencies: List[float] = []

    for item in questions:
        start = time.perf_counter()
        retrieved = retriever.retrieve(item["question"], top_k=args.top_k)
        latency_ms = (time.perf_counter() - start) * 1000
        retrieval_latencies.append(latency_ms)

        is_out = bool(item.get("is_out_of_scope", False))
        expected_chunk_ids = item.get("expected_chunk_id")

        result = {
            "id": item["id"],
            "question": item["question"],
            "type": item.get("type"),
            "is_out_of_scope": is_out,
            "retrieved_chunk_ids": [chunk.get("chunk_id") for chunk in retrieved],
            "retrieval_scores": [round(float(chunk["score"]), 6) for chunk in retrieved],
            "top1_score": round(float(retrieved[0]["score"]), 6) if retrieved else None,
            "chapter_hit": None if is_out else field_hit(
                retrieved, "chapter", item.get("expected_chapter")
            ),
            "source_hit": None if is_out else field_hit(
                retrieved, "source_file", item.get("expected_source")
            ),
            "chunk_hit": None if is_out else (
                chunk_recall(retrieved, expected_chunk_ids) > 0
            ),
            "chunk_recall": None if is_out else chunk_recall(
                retrieved, expected_chunk_ids
            ),
            "reciprocal_rank": None if is_out else reciprocal_rank(
                retrieved, expected_chunk_ids
            ),
            "latency_ms": round(latency_ms, 3),
        }
        results.append(result)

    args.result_file.parent.mkdir(parents=True, exist_ok=True)
    with args.result_file.open("w", encoding="utf-8") as file:
        for result in results:
            file.write(json.dumps(result, ensure_ascii=False) + "\n")

    in_scope = [r for r in results if not r["is_out_of_scope"]]
    out_scope = [r for r in results if r["is_out_of_scope"]]

    def rate(field: str) -> float:
        if not in_scope:
            return 0.0
        return sum(1 for r in in_scope if r[field]) / len(in_scope)

    in_top1 = [r["top1_score"] for r in in_scope if r["top1_score"] is not None]
    out_top1 = [r["top1_score"] for r in out_scope if r["top1_score"] is not None]

    summary = {
        "retrieval_only": True,
        "total": len(results),
        "in_scope_total": len(in_scope),
        "out_of_scope_total": len(out_scope),
        "knowledge_chunk_count": retriever.document_count,
        "retriever": "bm25",
        "tokenizer": "jieba",
        "top_k": args.top_k,
        "k1": args.k1,
        "b": args.b,
        "chapter_hit@k": rate("chapter_hit"),
        "source_hit@k": rate("source_hit"),
        "chunk_hit@k": rate("chunk_hit"),
        "chunk_recall@k": (
            statistics.mean(r["chunk_recall"] for r in in_scope)
            if in_scope else 0.0
        ),
        "mrr@k": (
            statistics.mean(r["reciprocal_rank"] for r in in_scope)
            if in_scope else 0.0
        ),
        "index_build_latency_ms": round(build_latency_ms, 3),
        "avg_retrieval_latency_ms": round(
            statistics.mean(retrieval_latencies), 3
        ) if retrieval_latencies else 0.0,
        "p95_retrieval_latency_ms": round(
            percentile_95(retrieval_latencies), 3
        ),
        "in_scope_top1_score_mean": (
            round(statistics.mean(in_top1), 6) if in_top1 else None
        ),
        "out_of_scope_top1_score_mean": (
            round(statistics.mean(out_top1), 6) if out_top1 else None
        ),
        "note": (
            "BM25 score is not calibrated against the dense retriever's cosine "
            "threshold; out-of-scope abstention must be calibrated separately."
        ),
    }

    with args.summary_file.open("w", encoding="utf-8") as file:
        json.dump(summary, file, ensure_ascii=False, indent=2)

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"详细结果：{args.result_file}")
    print(f"汇总结果：{args.summary_file}")


if __name__ == "__main__":
    main()
