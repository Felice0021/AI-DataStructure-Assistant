"""Fairness diagnostic: Structure Expansion vs deeper Dense retrieval.

Purpose
-------
Check whether v1.3's recovered gold chunks are genuinely helped by structure,
or would be recovered simply by increasing Dense retrieval depth.

For each of the 14 v1.3 diagnostic queries:
- Dense@5 recall
- Dense@K_budget where K_budget == size of structure-expanded candidate pool
- Structure-expanded recall
- exact Dense rank of every structure-recovered gold chunk

This makes NO new relevance judgments. It only evaluates against the current
adjudicated gold set.

Run:
    python3 tests/compare_structure_vs_deeper_dense_v14.py
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
DEFAULT_KNOWLEDGE = PROJECT_ROOT / "knowledge_base" / "ds_chunks.jsonl"
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
    / "structure_vs_deeper_dense_v14.json"
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

    rows: List[Dict] = []

    for pos, old in enumerate(v13["per_query"], 1):
        qid = old["id"]
        q = benchmark[qid]
        query = q["question"]
        gold_ids = [str(x) for x in q.get("gold_chunk_ids", [])]

        structure_ids = [str(x) for x in old["expanded_ids"]]
        structure_k = len(structure_ids)

        # Retrieve the whole corpus once so exact Dense ranks are available.
        ranked = dense.retrieve(
            query=query,
            chunks=chunks,
            top_k=len(chunks),
        )
        full_dense_ids = [str(x["chunk_id"]) for x in ranked]
        rank_map = {
            cid: rank
            for rank, cid in enumerate(full_dense_ids, 1)
        }

        dense5_ids = full_dense_ids[:5]
        dense_budget_ids = full_dense_ids[:structure_k]

        dense5_recall = recall(dense5_ids, gold_ids)
        budget_recall = recall(dense_budget_ids, gold_ids)
        structure_recall = recall(structure_ids, gold_ids)

        recovered = [
            str(x)
            for x in old.get("recovered_known_gold_ids", [])
        ]

        recovered_ranks = {
            cid: rank_map.get(cid)
            for cid in recovered
        }

        if structure_recall > budget_recall:
            outcome = "structure_win"
        elif structure_recall < budget_recall:
            outcome = "deeper_dense_win"
        else:
            outcome = "tie"

        row = {
            "id": qid,
            "question": query,
            "gold_count": len(gold_ids),
            "structure_k": structure_k,
            "dense5_recall": round(dense5_recall, 4),
            "dense_budget_recall": round(budget_recall, 4),
            "structure_recall": round(structure_recall, 4),
            "outcome": outcome,
            "structure_recovered_gold_ids": recovered,
            "structure_recovered_gold_dense_ranks": recovered_ranks,
        }
        rows.append(row)

        print("\n" + "=" * 80)
        print(f"[{pos}/{len(v13['per_query'])}] {qid}: {query}")
        print(
            f"K: Dense5=5, budget-matched Dense={structure_k}, "
            f"Structure={structure_k}"
        )
        print(
            "Recall:",
            f"Dense5={row['dense5_recall']}",
            f"Dense@{structure_k}={row['dense_budget_recall']}",
            f"Structure={row['structure_recall']}",
            f"=> {outcome}",
        )

        if recovered:
            print("structure-recovered gold Dense ranks:")
            for cid in recovered:
                print(
                    f"  {cid}: Dense rank={rank_map.get(cid)}"
                )

    n = len(rows)

    mean_dense5 = sum(x["dense5_recall"] for x in rows) / n
    mean_budget = sum(x["dense_budget_recall"] for x in rows) / n
    mean_structure = sum(x["structure_recall"] for x in rows) / n

    wins = [x["id"] for x in rows if x["outcome"] == "structure_win"]
    losses = [
        x["id"] for x in rows if x["outcome"] == "deeper_dense_win"
    ]
    ties = [x["id"] for x in rows if x["outcome"] == "tie"]

    recovered_rank_pairs = []
    for x in rows:
        for cid, rank in x[
            "structure_recovered_gold_dense_ranks"
        ].items():
            recovered_rank_pairs.append(
                {
                    "question_id": x["id"],
                    "chunk_id": cid,
                    "dense_rank": rank,
                    "structure_k": x["structure_k"],
                    "outside_budget_matched_dense": (
                        rank is None or rank > x["structure_k"]
                    ),
                }
            )

    outside = [
        x
        for x in recovered_rank_pairs
        if x["outside_budget_matched_dense"]
    ]

    summary = {
        "queries": n,
        "mean_dense5_recall": round(mean_dense5, 4),
        "mean_budget_matched_dense_recall": round(mean_budget, 4),
        "mean_structure_recall": round(mean_structure, 4),
        "structure_gain_vs_dense5": round(
            mean_structure - mean_dense5, 4
        ),
        "structure_gain_vs_budget_matched_dense": round(
            mean_structure - mean_budget, 4
        ),
        "structure_win_queries": wins,
        "structure_win_count": len(wins),
        "deeper_dense_win_queries": losses,
        "deeper_dense_win_count": len(losses),
        "tie_queries": ties,
        "recovered_gold_pair_count": len(recovered_rank_pairs),
        "recovered_gold_outside_budget_dense_count": len(outside),
        "recovered_gold_outside_budget_dense_pairs": outside,
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(
            {
                "summary": summary,
                "per_query": rows,
                "recovered_gold_rank_analysis": recovered_rank_pairs,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print("\n===== STRUCTURE VS DEEPER DENSE V1.4 =====")
    for k, v in summary.items():
        print(f"{k}={v}")

    print("\noutput:", args.output)


if __name__ == "__main__":
    main()
