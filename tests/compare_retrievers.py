"""比较两个检索器的逐查询表现，分析互补性与理想路由上界。"""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def load_jsonl(path: Path):
    records = []
    with path.open("r", encoding="utf-8") as f:
        for line_no, raw in enumerate(f, 1):
            line = raw.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise RuntimeError(
                    f"{path} 第 {line_no} 行 JSON 格式错误: {exc}"
                ) from exc
    return records


def as_list(value):
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def recall_at_k(retrieved, gold, k):
    gold = set(gold)
    if not gold:
        return None
    return len(set(retrieved[:k]) & gold) / len(gold)


def any_hit_at_k(retrieved, gold, k):
    gold = set(gold)
    if not gold:
        return None
    return int(bool(set(retrieved[:k]) & gold))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--bm25", type=Path, required=True)
    parser.add_argument("--dense", type=Path, required=True)
    parser.add_argument(
        "--questions",
        type=Path,
        default=PROJECT_ROOT / "tests/test_questions_50.jsonl",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "tests/retriever_comparison.json",
    )
    args = parser.parse_args()

    questions = {
        x["id"]: x for x in load_jsonl(args.questions)
    }
    bm25 = {
        x["id"]: x for x in load_jsonl(args.bm25)
    }
    dense = {
        x["id"]: x for x in load_jsonl(args.dense)
    }

    ks = (1, 3, 5)
    details = []

    category_counts = {
        k: Counter() for k in ks
    }

    oracle_recall_sum = {
        k: 0.0 for k in ks
    }
    bm25_recall_sum = {
        k: 0.0 for k in ks
    }
    dense_recall_sum = {
        k: 0.0 for k in ks
    }

    by_type = {
        k: defaultdict(Counter)
        for k in ks
    }

    scored = 0

    for qid, q in questions.items():
        if q.get("is_out_of_scope", False):
            continue

        gold = as_list(
            q.get("gold_chunk_ids", q.get("expected_chunk_id"))
        )
        if not gold:
            continue

        if qid not in bm25 or qid not in dense:
            raise RuntimeError(f"{qid} 缺少检索结果")

        b_ids = bm25[qid]["retrieved_chunk_ids"]
        d_ids = dense[qid]["retrieved_chunk_ids"]
        query_type = q.get("type", "UNKNOWN")

        record = {
            "id": qid,
            "question": q["question"],
            "query_type": query_type,
            "gold_chunk_ids": gold,
            "bm25_top5": b_ids[:5],
            "dense_top5": d_ids[:5],
        }

        for k in ks:
            b_hit = any_hit_at_k(b_ids, gold, k)
            d_hit = any_hit_at_k(d_ids, gold, k)

            if b_hit and d_hit:
                category = "both"
            elif b_hit:
                category = "bm25_only"
            elif d_hit:
                category = "dense_only"
            else:
                category = "neither"

            category_counts[k][category] += 1
            by_type[k][query_type][category] += 1

            b_recall = recall_at_k(b_ids, gold, k)
            d_recall = recall_at_k(d_ids, gold, k)

            # oracle routing：假设知道每题应该选 BM25 还是 Dense，
            # 取两者该题 Recall@K 中较高的一个。
            oracle = max(b_recall, d_recall)

            bm25_recall_sum[k] += b_recall
            dense_recall_sum[k] += d_recall
            oracle_recall_sum[k] += oracle

            record[f"@{k}"] = {
                "category": category,
                "bm25_recall": round(b_recall, 4),
                "dense_recall": round(d_recall, 4),
                "oracle_recall": round(oracle, 4),
            }

        details.append(record)
        scored += 1

    summary = {
        "scored_queries": scored,
        "note": (
            "当前仍使用未冻结的 expected/gold 标注，"
            "结果仅用于 Experiment 0 诊断。"
        ),
        "by_k": {},
    }

    for k in ks:
        summary["by_k"][f"@{k}"] = {
            "categories": {
                name: category_counts[k].get(name, 0)
                for name in (
                    "both",
                    "bm25_only",
                    "dense_only",
                    "neither",
                )
            },
            "bm25_mean_recall": round(
                bm25_recall_sum[k] / scored, 4
            ),
            "dense_mean_recall": round(
                dense_recall_sum[k] / scored, 4
            ),
            "oracle_routing_mean_recall": round(
                oracle_recall_sum[k] / scored, 4
            ),
            "oracle_gain_over_dense": round(
                (
                    oracle_recall_sum[k]
                    - dense_recall_sum[k]
                ) / scored,
                4,
            ),
            "by_query_type": {
                qtype: {
                    name: counts.get(name, 0)
                    for name in (
                        "both",
                        "bm25_only",
                        "dense_only",
                        "neither",
                    )
                }
                for qtype, counts
                in sorted(by_type[k].items())
            },
        }

    output = {
        "summary": summary,
        "per_query": details,
    }

    with args.output.open("w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"\n完整结果: {args.output}")


if __name__ == "__main__":
    main()
