"""
RAG 自动评测

同时评测：
1. API 端到端问答
2. RAG 检索质量

输入：
tests/test_questions.jsonl

输出：
tests/test_results.jsonl
tests/evaluation_summary.json
"""

import json
import math
import statistics
import time
from pathlib import Path

import requests

from rag.config import (
    DEFAULT_TOP_K,
    MIN_RETRIEVAL_SCORE,
)
from rag.rag_demo.main import (
    prepare_knowledge_base,
    retrieve,
)


API_URL = "http://127.0.0.1:8000/api/v1/ask"

BASE_DIR = Path(__file__).parent
QUESTION_FILE = BASE_DIR / "test_questions.jsonl"
RESULT_FILE = BASE_DIR / "test_results.jsonl"
SUMMARY_FILE = BASE_DIR / "evaluation_summary.json"

TOP_K = DEFAULT_TOP_K


def load_questions():
    questions = []

    with QUESTION_FILE.open(
        "r",
        encoding="utf-8",
    ) as f:
        for line in f:
            line = line.strip()

            if line:
                questions.append(
                    json.loads(line)
                )

    return questions


def call_api(question):
    payload = {
        "question": question,
        "top_k": TOP_K,
    }

    start = time.perf_counter()

    try:
        response = requests.post(
            API_URL,
            json=payload,
            timeout=60,
        )

        latency_ms = (
            time.perf_counter() - start
        ) * 1000

        response.raise_for_status()

        result = response.json()

        if not result.get("success"):
            return {
                "answer": "",
                "sources": [],
                "error": result.get("error"),
            }, latency_ms

        data = result.get("data") or {}

        return {
            "answer": data.get("answer", ""),
            "sources": data.get("sources", []),
            "error": None,
        }, latency_ms

    except Exception as exc:
        latency_ms = (
            time.perf_counter() - start
        ) * 1000

        return {
            "answer": "",
            "sources": [],
            "error": {
                "type": "interface_error",
                "message": str(exc),
            },
        }, latency_ms


def to_list(value):
    if value is None:
        return []

    if isinstance(value, list):
        return value

    return [value]


def check_hit(
    retrieved_chunks,
    field,
    expected,
):
    expected_values = to_list(expected)

    if not expected_values:
        return False

    return any(
        chunk.get(field) in expected_values
        for chunk in retrieved_chunks[:TOP_K]
    )


def check_chunk_hit(
    retrieved_chunks,
    expected_chunk_ids,
):
    expected = set(
        to_list(expected_chunk_ids)
    )

    if not expected:
        return False

    retrieved = {
        chunk.get("chunk_id")
        for chunk in retrieved_chunks[:TOP_K]
    }

    return bool(
        expected & retrieved
    )


def is_refusal(answer):
    answer = (answer or "").strip()

    refuse_keywords = [
        "根据当前资料无法确定",
        "无法回答",
        "无法确定",
        "不在知识库",
        "超出范围",
        "没有相关信息",
        "不知道",
    ]

    return any(
        keyword in answer
        for keyword in refuse_keywords
    )


def classify_error(
    item,
    api_result,
    chapter_hit,
    source_hit,
):
    if api_result.get("error"):
        return "接口错误"

    answer = api_result.get(
        "answer",
        "",
    )

    sources = api_result.get(
        "sources",
        [],
    )

    refused = is_refusal(answer)

    if item.get(
        "is_out_of_scope",
        False,
    ):
        if not refused:
            return "范围外判断错误"

        if sources:
            return "范围外来源未清空"

        return None

    if refused:
        return "范围内误拒答"

    if not sources:
        return "来源缺失"

    if not chapter_hit:
        return "检索错误"

    if not source_hit:
        return "来源错误"

    if not answer.strip():
        return "生成错误"

    return None


def percentile_95(values):
    if not values:
        return 0

    values = sorted(values)

    index = (
        math.ceil(
            len(values) * 0.95
        )
        - 1
    )

    return values[index]


def main():
    questions = load_questions()

    print("正在初始化正式知识库用于检索评测...")
    chunks = prepare_knowledge_base()

    print(
        f"知识片段数量：{len(chunks)}"
    )

    results = []
    latencies = []

    for item in questions:
        print()
        print(
            "测试：",
            item["id"],
            item["question"],
        )

        # -------------------------
        # 1. 直接评测检索
        # -------------------------

        retrieved = retrieve(
            query=item["question"],
            chunks=chunks,
            top_k=TOP_K,
        )

        retrieval_scores = [
            round(
                chunk["score"],
                6,
            )
            for chunk in retrieved
        ]

        retrieved_chunk_ids = [
            chunk["chunk_id"]
            for chunk in retrieved
        ]

        is_out = item.get(
            "is_out_of_scope",
            False,
        )

        if is_out:
            chapter_hit = None
            source_hit = None
            chunk_hit = None

        else:
            chapter_hit = check_hit(
                retrieved,
                "chapter",
                item.get(
                    "expected_chapter"
                ),
            )

            source_hit = check_hit(
                retrieved,
                "source_file",
                item.get(
                    "expected_source"
                ),
            )

            chunk_hit = check_chunk_hit(
                retrieved,
                item.get(
                    "expected_chunk_id"
                ),
            )

        # -------------------------
        # 2. API 端到端评测
        # -------------------------

        api_result, latency_ms = call_api(
            item["question"]
        )

        answer = api_result.get(
            "answer",
            "",
        )

        sources = api_result.get(
            "sources",
            [],
        )

        refused = is_refusal(
            answer
        )

        error_type = classify_error(
            item,
            api_result,
            chapter_hit,
            source_hit,
        )

        result = {
            "id": item["id"],
            "question": item["question"],
            "type": item.get("type"),
            "is_out_of_scope": is_out,

            "answer": answer,
            "sources": sources,

            "retrieved_chunk_ids":
                retrieved_chunk_ids,

            "retrieval_scores":
                retrieval_scores,

            "top1_score": (
                retrieval_scores[0]
                if retrieval_scores
                else None
            ),

            "chapter_hit": chapter_hit,
            "source_hit": source_hit,
            "chunk_hit": chunk_hit,

            "refused": refused,

            "latency_ms": round(
                latency_ms,
                2,
            ),

            "error":
                api_result.get("error"),

            "error_type":
                error_type,
        }

        results.append(result)
        latencies.append(latency_ms)

        print(
            "scores:",
            retrieval_scores,
        )

        print(
            "sources:",
            len(sources),
        )

        print(
            "refused:",
            refused,
        )

        print(
            "error_type:",
            error_type,
        )

    # -------------------------
    # 保存详细结果
    # -------------------------

    with RESULT_FILE.open(
        "w",
        encoding="utf-8",
    ) as f:
        for result in results:
            f.write(
                json.dumps(
                    result,
                    ensure_ascii=False,
                )
                + "\n"
            )

    # -------------------------
    # 汇总
    # -------------------------

    in_scope = [
        r
        for r in results
        if not r["is_out_of_scope"]
    ]

    out_scope = [
        r
        for r in results
        if r["is_out_of_scope"]
    ]

    successful = [
        r
        for r in results
        if r["error"] is None
    ]

    failed_questions = [
        {
            "id": r["id"],
            "question": r["question"],
            "error_type":
                r["error_type"],
        }
        for r in results
        if r["error_type"]
    ]

    summary = {
        "total":
            len(results),

        "in_scope_total":
            len(in_scope),

        "out_of_scope_total":
            len(out_scope),

        "knowledge_chunk_count":
            len(chunks),

        "top_k":
            TOP_K,

        "min_retrieval_score":
            MIN_RETRIEVAL_SCORE,

        "request_success_rate": (
            len(successful) /
            len(results)
            if results
            else 0
        ),

        # 只对范围内问题计算
        "chapter_hit@3": (
            sum(
                1
                for r in in_scope
                if r["chapter_hit"]
            )
            / len(in_scope)
            if in_scope
            else 0
        ),

        "source_hit@3": (
            sum(
                1
                for r in in_scope
                if r["source_hit"]
            )
            / len(in_scope)
            if in_scope
            else 0
        ),

        "chunk_hit@3": (
            sum(
                1
                for r in in_scope
                if r["chunk_hit"]
            )
            / len(in_scope)
            if in_scope
            else 0
        ),

        "out_of_scope_refuse_accuracy": (
            sum(
                1
                for r in out_scope
                if r["refused"]
            )
            / len(out_scope)
            if out_scope
            else 0
        ),

        "out_of_scope_sources_empty_rate": (
            sum(
                1
                for r in out_scope
                if not r["sources"]
            )
            / len(out_scope)
            if out_scope
            else 0
        ),

        "avg_latency_ms": (
            round(
                statistics.mean(
                    latencies
                ),
                2,
            )
            if latencies
            else 0
        ),

        "p95_latency_ms": (
            round(
                percentile_95(
                    latencies
                ),
                2,
            )
            if latencies
            else 0
        ),

        "failed_questions":
            failed_questions,
    }

    with SUMMARY_FILE.open(
        "w",
        encoding="utf-8",
    ) as f:
        json.dump(
            summary,
            f,
            ensure_ascii=False,
            indent=2,
        )

    print()
    print("=" * 70)
    print("评测完成")
    print("=" * 70)

    print(
        json.dumps(
            summary,
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
