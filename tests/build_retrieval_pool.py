"""构建人工相关性标注候选池。

候选集合：
    BM25 Top-N ∪ Dense Top-N ∪ 当前 gold

重复运行时会保留已有 relevance_label / annotation_note。
"""
from __future__ import annotations

import argparse
import csv
import json
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


def load_old_annotations(path: Path):
    if not path.exists():
        return {}

    annotations = {}
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            key = (row["question_id"], row["chunk_id"])
            annotations[key] = {
                "relevance_label": row.get("relevance_label", ""),
                "annotation_note": row.get("annotation_note", ""),
            }
    return annotations


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--questions", type=Path,
                        default=PROJECT_ROOT / "tests/test_questions_50.jsonl")
    parser.add_argument("--knowledge", type=Path,
                        default=PROJECT_ROOT / "knowledge_base/ds_chunks.jsonl")
    parser.add_argument("--bm25-results", type=Path, required=True)
    parser.add_argument("--dense-results", type=Path, required=True)
    parser.add_argument("--depth", type=int, default=5)
    parser.add_argument("--output", type=Path,
                        default=PROJECT_ROOT / "tests/retrieval_pool_v1.csv")
    args = parser.parse_args()

    questions = {x["id"]: x for x in load_jsonl(args.questions)}
    chunks = {x["chunk_id"]: x for x in load_jsonl(args.knowledge)}
    bm25 = {x["id"]: x for x in load_jsonl(args.bm25_results)}
    dense = {x["id"]: x for x in load_jsonl(args.dense_results)}

    old_annotations = load_old_annotations(args.output)

    rows = []
    gold_only_added = 0
    preserved_annotations = 0

    for qid, q in questions.items():
        if qid not in bm25 or qid not in dense:
            raise RuntimeError(f"{qid} 缺少 BM25 或 Dense 结果")

        candidates = {}

        def add_result(record, prefix):
            ids = record.get("retrieved_chunk_ids", [])[:args.depth]
            scores = record.get("retrieval_scores", [])[:args.depth]

            for rank, cid in enumerate(ids, 1):
                candidates.setdefault(cid, {})
                candidates[cid][f"{prefix}_rank"] = rank
                if rank <= len(scores):
                    candidates[cid][f"{prefix}_score"] = scores[rank - 1]

        add_result(bm25[qid], "bm25")
        add_result(dense[qid], "dense")

        current_gold = set(q.get("expected_chunk_id", []))

        # 原 gold 必须全部进入人工审核池
        for cid in current_gold:
            if cid not in candidates:
                gold_only_added += 1
            candidates.setdefault(cid, {})

        for cid in candidates:
            if cid not in chunks:
                raise RuntimeError(f"知识库中不存在 chunk_id: {cid}")

        def sort_key(item):
            cid, meta = item
            is_gold = cid in current_gold
            both = "bm25_rank" in meta and "dense_rank" in meta
            best_rank = min(
                meta.get("bm25_rank", 999),
                meta.get("dense_rank", 999),
            )
            # 原 gold 优先，其次双路命中，再按最好排名
            return (not is_gold, not both, best_rank, cid)

        for cid, meta in sorted(candidates.items(), key=sort_key):
            chunk = chunks[cid]
            old = old_annotations.get((qid, cid), {})

            if old.get("relevance_label", "") != "":
                preserved_annotations += 1

            rows.append({
                "question_id": qid,
                "question": q["question"],
                "query_type": q.get("type", ""),
                "is_out_of_scope": q.get("is_out_of_scope", False),
                "reference_answer": q.get("reference_answer", ""),
                "chunk_id": cid,
                "chapter": chunk.get("chapter", ""),
                "section": chunk.get("section", ""),
                "content_type": chunk.get("content_type", ""),
                "source_file": chunk.get("source_file", ""),
                "chunk_text": chunk.get("text", ""),
                "current_gold": cid in current_gold,
                "bm25_rank": meta.get("bm25_rank", ""),
                "bm25_score": meta.get("bm25_score", ""),
                "dense_rank": meta.get("dense_rank", ""),
                "dense_score": meta.get("dense_score", ""),
                "relevance_label": old.get("relevance_label", ""),
                "annotation_note": old.get("annotation_note", ""),
            })

    fields = [
        "question_id", "question", "query_type", "is_out_of_scope",
        "reference_answer", "chunk_id", "chapter", "section",
        "content_type", "source_file", "chunk_text", "current_gold",
        "bm25_rank", "bm25_score", "dense_rank", "dense_score",
        "relevance_label", "annotation_note",
    ]

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    print(f"Pooling file: {args.output}")
    print(f"questions = {len(questions)}")
    print(f"question-chunk pairs = {len(rows)}")
    print(f"avg candidates/question = {len(rows) / len(questions):.2f}")
    print(f"current gold added outside BM25/Dense Top{args.depth} = {gold_only_added}")
    print(f"preserved existing annotations = {preserved_annotations}")


if __name__ == "__main__":
    main()
