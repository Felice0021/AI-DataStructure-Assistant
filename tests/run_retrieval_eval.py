"""统一检索评测脚本。

在同一测试集上以统一口径评测任意实现 BaseRetriever 接口的检索器
（Dense / BM25 / 未来的 Hybrid），计算 Recall@1/3/5、MRR@3/5、
nDCG@3/5 和检索耗时，并把实验配置与指标落盘为 JSON。

用法（任意目录均可，脚本自动定位项目根）:
    python tests/run_retrieval_eval.py --retriever dense
    python tests/run_retrieval_eval.py --retriever bm25 --k1 1.5 --b 0.75

输出:
    tests/results/{retriever}_{时间戳}/per_query_results.jsonl
    tests/results/{retriever}_{时间戳}/summary.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List

# 让脚本在任意目录下都能导入项目包
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _load_env_file(path: Path) -> None:
    """轻量加载 .env（不依赖 python-dotenv），供 Dense 读取 API Key。"""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"\''))


# 与 rag/main.py 保持一致：只读取项目根目录 .env
_load_env_file(PROJECT_ROOT / ".env")

from rag.config import DEFAULT_TOP_K, KNOWLEDGE_BASE_PATH  # noqa: E402
from rag.retrievers import (  # noqa: E402
    BM25Retriever,
    DenseRetriever,
    load_chunks_from_jsonl,
)
from tests.metrics import (  # noqa: E402
    as_list,
    avg_latency,
    hit_at_k,
    mrr_at_k,
    ndcg_at_k,
    p95_latency,
    recall_at_k,
)


DEFAULT_QUESTION_FILE = PROJECT_ROOT / "tests" / "test_questions_50.jsonl"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "tests" / "results"

# 指标切点固定为 1/3/5；检索深度取 max(top_k, 5) 保证 @5 可算
MIN_RETRIEVAL_DEPTH = 5


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="统一检索评测")
    parser.add_argument(
        "--retriever",
        choices=("dense", "bm25"),
        required=True,
        help="检索器类型；新增 Hybrid 时在此扩展",
    )
    parser.add_argument("--top-k", type=int, default=DEFAULT_TOP_K,
                        help="实验配置里记录的 top_k（默认 3）")
    parser.add_argument("--k1", type=float, default=1.5)
    parser.add_argument("--b", type=float, default=0.75)
    parser.add_argument("--knowledge-file", type=Path, default=KNOWLEDGE_BASE_PATH)
    parser.add_argument("--question-file", type=Path, default=DEFAULT_QUESTION_FILE)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
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


def build_retriever(name: str, args: argparse.Namespace):
    """按名称构建检索器；索引统一在 prepare(chunks) 中建立。"""
    if name == "dense":
        return DenseRetriever()
    if name == "bm25":
        return BM25Retriever(k1=args.k1, b=args.b)
    raise ValueError(f"未知 retriever：{name}")


def rel_path(path: Path) -> str:
    """优先返回相对项目根的路径，便于实验配置可移植。"""
    try:
        return str(Path(path).resolve().relative_to(PROJECT_ROOT.resolve()))
    except ValueError:
        return str(Path(path).resolve())


def main() -> None:
    args = parse_args()
    if args.top_k <= 0:
        raise ValueError("--top-k 必须大于 0")

    questions = load_jsonl(args.question_file)

    # ---------- 加载知识库 ----------
    # JSONL 文件读取不计入 index_build_latency_ms。
    chunks = load_chunks_from_jsonl(args.knowledge_file)

    # ---------- 统一索引构建计时 ----------
    # Dense 与 BM25 都只统计 prepare(chunks)：
    # Dense: 加载/生成 document embedding cache；
    # BM25: 分词、统计词频并建立 BM25 index。
    retriever = build_retriever(args.retriever, args)
    build_start = time.perf_counter()
    retriever.prepare(chunks)
    index_build_ms = (time.perf_counter() - build_start) * 1000

    # ---------- 逐题检索与指标 ----------
    retrieval_depth = max(args.top_k, MIN_RETRIEVAL_DEPTH)
    per_query: List[Dict] = []
    latencies: List[float] = []

    for item in questions:
        is_out = bool(item.get("is_out_of_scope", False))
        # Benchmark v1 优先使用人工复核后的 gold；
        # 在标注完成前保持对 expected_chunk_id 的向后兼容。
        expected = as_list(
            item.get("gold_chunk_ids", item.get("expected_chunk_id"))
        )
        primary_gold = as_list(item.get("primary_gold_chunk_ids"))

        start = time.perf_counter()
        retrieved = retriever.retrieve(item["question"], chunks,
                                       top_k=retrieval_depth)
        latency_ms = (time.perf_counter() - start) * 1000
        latencies.append(latency_ms)

        retrieved_ids = [r.get("chunk_id") for r in retrieved]

        record = {
            "id": item.get("id"),
            "question": item["question"],
            "query_type": item.get("type", ""),
            "expected_chapter": item.get("expected_chapter", ""),
            "is_out_of_scope": is_out,
            "expected_chunk_ids": expected,
            "gold_chunk_ids": expected,
            "primary_gold_chunk_ids": primary_gold,
            "retrieved_chunk_ids": retrieved_ids,
            "retrieval_scores": [round(float(r["score"]), 6) for r in retrieved],
            "top1_score": (round(float(retrieved[0]["score"]), 6)
                           if retrieved else None),
            "latency_ms": round(latency_ms, 3),
        }

        if is_out or not expected:
            # 范围外 / 无标注题：不参与指标，仅保留检索信息供阈值校准
            record.update({
                "recall@1": None, "recall@3": None, "recall@5": None,
                "mrr@3": None, "mrr@5": None,
                "ndcg@3": None, "ndcg@5": None,
                "hit@1": None, "hit@3": None, "hit@5": None,
            })
        else:
            record.update({
                "recall@1": recall_at_k(retrieved_ids, expected, 1),
                "recall@3": recall_at_k(retrieved_ids, expected, 3),
                "recall@5": recall_at_k(retrieved_ids, expected, 5),
                "mrr@3": mrr_at_k(retrieved_ids, expected, 3),
                "mrr@5": mrr_at_k(retrieved_ids, expected, 5),
                "ndcg@3": ndcg_at_k(retrieved_ids, expected, 3),
                "ndcg@5": ndcg_at_k(retrieved_ids, expected, 5),
                # primary_gold 尚未建立时保持 None，避免把“未标注”
                # 错误解释成 Hit=0。
                "hit@1": (
                    hit_at_k(retrieved_ids, primary_gold, 1)
                    if primary_gold else None
                ),
                "hit@3": (
                    hit_at_k(retrieved_ids, primary_gold, 3)
                    if primary_gold else None
                ),
                "hit@5": (
                    hit_at_k(retrieved_ids, primary_gold, 5)
                    if primary_gold else None
                ),
            })

        per_query.append(record)

    # ---------- 输出目录 ----------
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = args.output_dir / f"{args.retriever}_{timestamp}"
    out_dir.mkdir(parents=True, exist_ok=True)

    per_query_file = out_dir / "per_query_results.jsonl"
    with per_query_file.open("w", encoding="utf-8") as file:
        for record in per_query:
            file.write(json.dumps(record, ensure_ascii=False) + "\n")

    # ---------- 汇总指标（仅范围内且有标注的题） ----------
    in_scope = [r for r in per_query
                if not r["is_out_of_scope"] and r["recall@5"] is not None]

    def metric_mean(field: str, records=None):
        records = in_scope if records is None else records
        values = [
            r[field] for r in records
            if r.get(field) is not None
        ]
        return round(sum(values) / len(values), 4) if values else None

    metrics = {
        "recall@1": metric_mean("recall@1"),
        "recall@3": metric_mean("recall@3"),
        "recall@5": metric_mean("recall@5"),
        "mrr@3": metric_mean("mrr@3"),
        "mrr@5": metric_mean("mrr@5"),
        "ndcg@3": metric_mean("ndcg@3"),
        "ndcg@5": metric_mean("ndcg@5"),
        "hit@1": metric_mean("hit@1"),
        "hit@3": metric_mean("hit@3"),
        "hit@5": metric_mean("hit@5"),
        "avg_retrieval_latency_ms": round(avg_latency(latencies), 3),
        "p95_retrieval_latency_ms": round(p95_latency(latencies), 3),
        "index_build_latency_ms": round(index_build_ms, 3),
    }

    # ---------- 按题型 / 章节分组 ----------
    group_metric_fields = (
        "recall@1", "recall@3", "recall@5",
        "mrr@3", "mrr@5",
        "ndcg@3", "ndcg@5",
        "hit@1", "hit@3", "hit@5",
    )

    def summarize_groups(field: str):
        labels = sorted({
            str(r.get(field) or "UNKNOWN")
            for r in in_scope
        })
        result = {}
        for label in labels:
            records = [
                r for r in in_scope
                if str(r.get(field) or "UNKNOWN") == label
            ]
            result[label] = {
                "count": len(records),
                **{
                    metric: metric_mean(metric, records)
                    for metric in group_metric_fields
                },
            }
        return result

    grouped_metrics = {
        "by_query_type": summarize_groups("query_type"),
        "by_chapter": summarize_groups("expected_chapter"),
    }

    # 检索错误典型案例（top5 未完全召回期望 chunk 的题）
    failures = [
        {
            "id": r["id"],
            "question": r["question"],
            "expected_chunk_ids": r["expected_chunk_ids"],
            "top5_chunk_ids": r["retrieved_chunk_ids"][:5],
            "recall@5": r["recall@5"],
        }
        for r in in_scope
        if r["recall@5"] < 1.0
    ]

    config = retriever.get_config()
    experiment = {
        "retriever": args.retriever,
        "top_k": args.top_k,
        "retrieval_depth": retrieval_depth,
        "dataset": rel_path(args.question_file),
        "knowledge_base": rel_path(args.knowledge_file),
        "knowledge_chunk_count": len(chunks),
        "params": config,
        "timestamp": timestamp,
    }

    summary = {
        "experiment": experiment,
        "metrics": metrics,
        "grouped_metrics": grouped_metrics,
        "failures": failures,
        "total": len(per_query),
        "in_scope_total": len(in_scope),
        "out_of_scope_total": sum(
            1 for r in per_query if r["is_out_of_scope"]
        ),
        "unscored_total": sum(
            1 for r in per_query
            if not r["is_out_of_scope"] and r["recall@5"] is None
        ),
    }

    summary_file = out_dir / "summary.json"
    with summary_file.open("w", encoding="utf-8") as file:
        json.dump(summary, file, ensure_ascii=False, indent=2)

    # ---------- 控制台输出 ----------
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"每题明细：{per_query_file}")
    print(f"汇总JSON：{summary_file}")


if __name__ == "__main__":
    main()