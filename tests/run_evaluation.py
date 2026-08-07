"""
RAG自动评测脚本

输入:
tests/test_questions.jsonl

输出:
tests/test_results.jsonl
tests/evaluation_summary.json
"""

import json
import time
import requests
import statistics
import math
from pathlib import Path


# ==========================
# 配置
# ==========================

API_URL = "http://127.0.0.1:8000/api/v1/ask"

BASE_DIR = Path(__file__).parent

QUESTION_FILE = BASE_DIR / "test_questions.jsonl"

RESULT_FILE = BASE_DIR / "test_results.jsonl"

SUMMARY_FILE = BASE_DIR / "evaluation_summary.json"

TOP_K = 3


# ==========================
# 请求接口
# ==========================

def call_api(question):
    payload = {
        "question": question,
        "top_k": TOP_K
    }
    start = time.time()
    try:
        r = requests.post(
            API_URL,
            json=payload,
            timeout=60
        )

        latency = (
            time.time() - start
        ) * 1000

        r.raise_for_status()
        result = r.json()

        if not result.get("success"):
            return {
                "answer": "",
                "sources": [],
                "error":
                    result.get("error")
            }, latency


        data = result.get(
            "data",
            {}
        )

        return {
            "answer":
                data.get(
                    "answer",
                    ""
                ),

            "sources":
                data.get(
                    "sources",
                    []
                ),

            "latency_ms":
                data.get(
                    "latency_ms",
                    latency
                )
        }, latency


    except Exception as e:
        return {
            "answer": "",
            "sources": [],
            "error":
            {
                "type":
                    "interface_error",
                "message":
                    str(e)
            }

        }, latency

# ==========================
# 检索命中判断
# ==========================

def get_chunk_ids(sources):
    return [
        s.get(
            "chunk_id",
            ""
        )

        for s in sources

    ]


def check_chunk_hit(expected, sources):
    if not expected:
        return False

    retrieved = get_chunk_ids(
        sources
    )

    return any(
        x in retrieved
        for x in expected
    )


def check_chapter_hit(expected, sources):
    if not expected:
        return False

    for s in sources[:3]:
        if s.get("chapter") == expected:
            return True

    return False


def check_source_hit(expected, sources):
    if not expected:
        return False

    for s in sources[:3]:

        if s.get("source_file") == expected:

            return True

    return False

# ==========================
# 范围外判断
# ==========================

def check_refused(item, result):

    if not item.get(
        "is_out_of_scope",
        False
    ):

        return False

    answer = result.get(
        "answer",
        ""
    )

    sources = result.get(
        "sources",
        []
    )

    refuse_keywords = [
        "无法回答",
        "无法确定",
        "不在知识库",
        "超出范围",
        "没有相关信息",
        "不知道"
    ]

    # 明确拒答
    if any(
        k in answer
        for k in refuse_keywords
    ):

        return True

    # 没有来源也认为可能拒答
    if not sources:
        return True

    return False

# ==========================
# 生成质量简单判断
# ==========================

def check_generation(result):
    answer = result.get(
        "answer",
        ""
    ).strip()

    if not answer:
        return False

    return True

# ==========================
# 错误分类
# ==========================

def classify_error(item, result):
    # 接口错误

    if result.get("error"):
        return "接口错误"

    # 范围外问题

    if item.get(
        "is_out_of_scope",
        False
    ):

        if result.get(
            "refused",
            False
        ):
            return None

        return "范围外判断错误"

    # 没有检索结果

    if not result["sources"]:
        return "知识库缺失"

    # 章节错误

    if not result["chapter_hit"]:

        return "检索错误"

    # 来源错误

    if not result["source_hit"]:

        return "来源错误"

    # 生成失败

    if not check_generation(result):

        return "生成错误"

    return None

# ==========================
# 主流程
# ==========================

def main():

    questions = []

    with open(
        QUESTION_FILE,
        "r",
        encoding="utf-8"
    ) as f:

        for line in f:

            if line.strip():

                questions.append(
                    json.loads(line)
                )


    results = []

    latencies = []

    for item in questions:

        print(
            "测试:",
            item["id"],
            item["question"]
        )

        api_result, latency = call_api(

            item["question"]

        )

        sources = api_result.get(

            "sources",
            []

        )

        result = {


            "id":
                item["id"],


            "question":

                item["question"],


            "is_out_of_scope":

                item.get(
                    "is_out_of_scope",
                    False
                ),

            "answer":

                api_result.get(
                    "answer",
                    ""
                ),

            "sources":

                sources,


            "retrieved_chunk_ids":

                get_chunk_ids(
                    sources
                ),


            # 当前接口没有返回score

            "retrieval_scores":

                [],

            "chapter_hit":

                check_chapter_hit(

                    item.get(
                        "expected_chapter"
                    ),

                    sources

                ),

            "source_hit":

                check_source_hit(

                    item.get(
                        "expected_source"
                    ),

                    sources

                ),

            "refused":

                check_refused(

                    item,

                    api_result

                ),

            "latency_ms":

                round(
                    latency,
                    2
                ),

            "error":

                api_result.get(
                    "error"
                )

        }

        result["error_type"] = classify_error(

            item,

            result

        )

        results.append(result)


        latencies.append(
            latency
        )

    # ======================
    # 保存详细结果
    # ======================

    with open(

        RESULT_FILE,

        "w",

        encoding="utf-8"

    ) as f:


        for r in results:


            f.write(

                json.dumps(

                    r,

                    ensure_ascii=False

                )

                + "\n"

            )

    # ======================
    # 汇总
    # ======================
    total = len(results)

    success = sum(
        1

        for r in results

        if r["error"] is None

    )


    chapter_hit = sum(

        r["chapter_hit"]

        for r in results

    )


    source_hit = sum(

        r["source_hit"]

        for r in results

    )


    out_scope = [

        r

        for r in results

        if r["is_out_of_scope"]

    ]


    refused_correct = sum(

        1

        for r in out_scope

        if r["refused"]

    )


    failed = [

        {

            "id":
                r["id"],

            "question":
                r["question"],

            "error_type":
                r["error_type"]

        }

        for r in results

        if r["error_type"]

    ]


    sorted_latency = sorted(
        latencies
    )

    summary = {

        "total":

            total,

        "request_success_rate":

            success / total
            if total
            else 0,


        "chapter_hit@3":

            chapter_hit / total
            if total
            else 0,


        "source_hit@3":

            source_hit / total
            if total
            else 0,


        "out_of_scope_refuse_accuracy":

            refused_correct /
            len(out_scope)

            if out_scope

            else 0,


        "out_of_scope_sources_empty_rate":

            sum(

                1

                for r in out_scope

                if len(r["sources"]) == 0

            )

            /

            len(out_scope)

            if out_scope

            else 0,


        "avg_latency_ms":

            round(

                statistics.mean(
                    latencies
                ),

                2

            )

            if latencies

            else 0,


        "p95_latency_ms":

            round(

                sorted_latency[
                    math.ceil(
                        len(sorted_latency)
                        * 0.95
                    )
                    - 1
                ],

                2

            )

            if sorted_latency

            else 0,

        "failed_questions":

            failed

    }


    with open(

        SUMMARY_FILE,

        "w",

        encoding="utf-8"

    ) as f:

        json.dump(

            summary,

            f,

            ensure_ascii=False,

            indent=2

        )

    print("\n评测完成")

    print(

        json.dumps(

            summary,

            ensure_ascii=False,

            indent=2

        )

    )

if __name__ == "__main__":

    main()