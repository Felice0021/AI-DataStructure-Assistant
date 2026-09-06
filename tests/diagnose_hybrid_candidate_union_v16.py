"""Hybrid Candidate Union Diagnostic v1.6

Purpose
-------
Test whether structure expansion provides complementary candidates beyond
deeper Dense retrieval.

For each query from v1.3:

1. semantic_pool:
       Dense@K_semantic
   where K_semantic equals the size of the v1.3 structure-expanded pool
   (same semantic budget as the v1.4 budget-matched baseline).

2. hybrid_pool:
       Dense@K_semantic
       UNION
       structure-only candidates discovered by v1.3

3. fairness baseline:
       Dense@len(hybrid_pool)

Compare known-gold recall:
    Hybrid@B vs Dense@B

No API calls.
No new relevance judgments.
Gold is used only for evaluation after candidate generation.

Run:
    python3 tests/diagnose_hybrid_candidate_union_v16.py
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Sequence

from dotenv import load_dotenv

PROJECT_ROOT_FOR_IMPORT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT_FOR_IMPORT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT_FOR_IMPORT))

from rag.config import PROJECT_ROOT
from rag.retrievers import DenseRetriever, load_chunks_from_jsonl


DEFAULT_BENCHMARK = (
    PROJECT_ROOT / "tests" / "benchmarks" / "datastructureqa_dev_v1.jsonl"
)
DEFAULT_KNOWLEDGE = (
    PROJECT_ROOT / "knowledge_base" / "ds_chunks.jsonl"
)
DEFAULT_V13 = (
    PROJECT_ROOT
    / "tests"
    / "results"
    / "structure_expansion_diagnostic_v13.json"
)
DEFAULT_OUTPUT = (
    PROJECT_ROOT
    / "tests"
    / "results"
    / "hybrid_candidate_union_v16.json"
)


def load_jsonl(path: Path) -> Dict[str, Dict]:
    out = {}
    with path.open("r", encoding="utf-8") as f:
        for raw in f:
            if not raw.strip():
                continue
            obj = json.loads(raw)
            out[obj["id"]] = obj
    return out


def recall(ids: Sequence[str], gold: Sequence[str]) -> float:
    g = set(gold)
    if not g:
        return 0.0
    return len(set(ids) & g) / len(g)


def stable_union(a: Sequence[str], b: Sequence[str]) -> List[str]:
    seen = set()
    out = []
    for x in list(a) + list(b):
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


def main() -> None:
    load_dotenv(PROJECT_ROOT / ".env", override=False)

    ap = argparse.ArgumentParser()
    ap.add_argument("--benchmark", type=Path, default=DEFAULT_BENCHMARK)
    ap.add_argument("--knowledge", type=Path, default=DEFAULT_KNOWLEDGE)
    ap.add_argument("--v13", type=Path, default=DEFAULT_V13)
    ap.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = ap.parse_args()

    benchmark = load_jsonl(args.benchmark)
    v13 = json.loads(args.v13.read_text(encoding="utf-8"))

    chunks = load_chunks_from_jsonl(args.knowledge)

    dense = DenseRetriever()
    dense.prepare(chunks, use_cache=True)

    rows = []

    for pos, qrow in enumerate(v13["per_query"], 1):
        qid = qrow["id"]
        q = benchmark[qid]
        query = q["question"]
        gold_ids = [str(x) for x in q.get("gold_chunk_ids", [])]

        dense5_ids = [str(x) for x in qrow["dense_ids"]]

        structure_pool_ids = [
            str(x) for x in qrow["expanded_ids"]
        ]
        structure_only_ids = [
            cid for cid in structure_pool_ids
            if cid not in set(dense5_ids)
        ]

        # Same semantic-expansion depth used by v1.4's budget-matched Dense.
        semantic_k = len(structure_pool_ids)

        ranked = dense.retrieve(
            query=query,
            chunks=chunks,
            top_k=len(chunks),
        )
        full_dense_ids = [str(x["chunk_id"]) for x in ranked]
        dense_rank = {
            cid: i
            for i, cid in enumerate(full_dense_ids, 1)
        }

        semantic_ids = full_dense_ids[:semantic_k]

        # Hybrid adds structure-only evidence to the semantic expansion.
        hybrid_ids = stable_union(
            semantic_ids,
            structure_only_ids,
        )
        hybrid_k = len(hybrid_ids)

        # Fairness baseline: same total number of candidate chunks.
        matched_dense_ids = full_dense_ids[:hybrid_k]

        dense5_recall = recall(dense5_ids, gold_ids)
        semantic_recall = recall(semantic_ids, gold_ids)
        hybrid_recall = recall(hybrid_ids, gold_ids)
        matched_dense_recall = recall(matched_dense_ids, gold_ids)

        if hybrid_recall > matched_dense_recall:
            outcome = "hybrid_win"
        elif hybrid_recall < matched_dense_recall:
            outcome = "dense_win"
        else:
            outcome = "tie"

        hybrid_added_gold = sorted(
            (set(hybrid_ids) - set(semantic_ids))
            & set(gold_ids)
        )

        added_gold_ranks = {
            cid: dense_rank.get(cid)
            for cid in hybrid_added_gold
        }

        row = {
            "id": qid,
            "question": query,
            "dense5_k": 5,
            "semantic_k": semantic_k,
            "hybrid_k": hybrid_k,
            "dense5_recall": round(dense5_recall, 4),
            "semantic_dense_recall": round(semantic_recall, 4),
            "hybrid_recall": round(hybrid_recall, 4),
            "budget_matched_dense_recall": round(
                matched_dense_recall, 4
            ),
            "outcome": outcome,
            "structure_only_ids": structure_only_ids,
            "hybrid_added_gold_ids": hybrid_added_gold,
            "hybrid_added_gold_dense_ranks": added_gold_ranks,
        }
        rows.append(row)

        print("\n" + "=" * 80)
        print(f"[{pos}/{len(v13['per_query'])}] {qid}: {query}")
        print(
            f"K: Dense5=5, semantic Dense={semantic_k}, "
            f"Hybrid={hybrid_k}, matched Dense={hybrid_k}"
        )
        print(
            "Recall:",
            f"Dense5={row['dense5_recall']}",
            f"Dense@{semantic_k}={row['semantic_dense_recall']}",
            f"Hybrid@{hybrid_k}={row['hybrid_recall']}",
            f"Dense@{hybrid_k}={row['budget_matched_dense_recall']}",
            f"=> {outcome}",
        )

        if hybrid_added_gold:
            print("gold added only by structure branch:")
            for cid in hybrid_added_gold:
                print(
                    f"  {cid}: Dense rank={dense_rank.get(cid)}"
                )

    n = len(rows)

    def avg(key: str) -> float:
        return sum(float(x[key]) for x in rows) / n

    wins = [x["id"] for x in rows if x["outcome"] == "hybrid_win"]
    losses = [x["id"] for x in rows if x["outcome"] == "dense_win"]
    ties = [x["id"] for x in rows if x["outcome"] == "tie"]

    added_gold_pairs = [
        {
            "question_id": x["id"],
            "chunk_id": cid,
            "dense_rank": rank,
            "semantic_k": x["semantic_k"],
            "hybrid_k": x["hybrid_k"],
            "outside_semantic_pool": (
                rank is None or rank > x["semantic_k"]
            ),
            "outside_budget_matched_dense": (
                rank is None or rank > x["hybrid_k"]
            ),
        }
        for x in rows
        for cid, rank in x["hybrid_added_gold_dense_ranks"].items()
    ]

    summary = {
        "queries": n,
        "mean_dense5_recall": round(avg("dense5_recall"), 4),
        "mean_semantic_dense_recall": round(
            avg("semantic_dense_recall"), 4
        ),
        "mean_hybrid_recall": round(avg("hybrid_recall"), 4),
        "mean_budget_matched_dense_recall": round(
            avg("budget_matched_dense_recall"), 4
        ),
        "hybrid_gain_vs_semantic_dense": round(
            avg("hybrid_recall") - avg("semantic_dense_recall"), 4
        ),
        "hybrid_gain_vs_budget_matched_dense": round(
            avg("hybrid_recall")
            - avg("budget_matched_dense_recall"),
            4,
        ),
        "hybrid_win_queries": wins,
        "hybrid_win_count": len(wins),
        "dense_win_queries": losses,
        "dense_win_count": len(losses),
        "tie_queries": ties,
        "mean_semantic_k": round(
            sum(x["semantic_k"] for x in rows) / n, 4
        ),
        "mean_hybrid_k": round(
            sum(x["hybrid_k"] for x in rows) / n, 4
        ),
        "structure_unique_gold_pair_count": len(added_gold_pairs),
        "structure_unique_gold_pairs": added_gold_pairs,
        "structure_unique_gold_outside_matched_dense_count": sum(
            1
            for x in added_gold_pairs
            if x["outside_budget_matched_dense"]
        ),
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(
            {
                "summary": summary,
                "per_query": rows,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print("\n===== HYBRID CANDIDATE UNION V1.6 =====")
    for k, v in summary.items():
        print(f"{k}={v}")

    print("\noutput:", args.output)


if __name__ == "__main__":
    main()
