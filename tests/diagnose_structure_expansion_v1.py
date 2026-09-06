"""Diagnostic v1: structure-guided candidate expansion.

Goal
----
Before implementing a full structure-aware selector, test whether local
document structure can recover known relevant evidence missed by Dense Top-5.

This is a DIAGNOSTIC, not a formal metric:
- Dense Top-5 is fully judged.
- Newly expanded chunks may be unjudged.
- We report known-gold recovery and explicitly count unjudged expansions.
- Unjudged expansions are NEVER treated as non-relevant.

No LLM calls are made.

Run:
    python3 tests/diagnose_structure_expansion_v1.py

Optional:
    python3 tests/diagnose_structure_expansion_v1.py --only-multi
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from dotenv import load_dotenv

PROJECT_ROOT_FOR_IMPORT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT_FOR_IMPORT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT_FOR_IMPORT))

from rag.config import PROJECT_ROOT
from rag.retrievers import DenseRetriever, load_chunks_from_jsonl


DEFAULT_BENCHMARK = (
    PROJECT_ROOT / "tests" / "benchmarks" / "datastructureqa_dev_v1.jsonl"
)
DEFAULT_POOL = PROJECT_ROOT / "tests" / "retrieval_pool_v1.csv"
DEFAULT_KNOWLEDGE = PROJECT_ROOT / "knowledge_base" / "ds_chunks.jsonl"
DEFAULT_OUTPUT = (
    PROJECT_ROOT
    / "tests"
    / "results"
    / "structure_expansion_diagnostic_v1.json"
)

MULTI_IDS = {"q006", "q029", "q032", "q038", "q039", "q041", "q043"}

CHUNK_ID_RE = re.compile(r"^(?P<prefix>.+?)_(?P<num>\d+)$")


def load_jsonl(path: Path) -> List[Dict]:
    rows = []
    with path.open("r", encoding="utf-8") as f:
        for no, raw in enumerate(f, 1):
            if not raw.strip():
                continue
            try:
                rows.append(json.loads(raw))
            except json.JSONDecodeError as exc:
                raise RuntimeError(f"{path}:{no}: {exc}") from exc
    return rows


def load_judgments(path: Path) -> Dict[Tuple[str, str], Dict]:
    result = {}
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            result[(row["question_id"], row["chunk_id"])] = row
    return result


def chunk_ordinal(chunk_id: str) -> Optional[int]:
    m = CHUNK_ID_RE.match(chunk_id)
    if not m:
        return None
    return int(m.group("num"))


def same_nonempty(a: object, b: object) -> bool:
    sa = str(a or "").strip()
    sb = str(b or "").strip()
    return bool(sa and sb and sa == sb)


def structural_relation_score(seed: Dict, cand: Dict) -> Optional[Tuple[float, str]]:
    """Return a conservative local-structure relation score.

    Strongest:
      same source + same chapter + same section + nearby chunk ordinal
    Then:
      same source + same chapter + immediately adjacent ordinal

    We intentionally avoid broad chapter-wide expansion.
    """
    if seed["chunk_id"] == cand["chunk_id"]:
        return None

    if not same_nonempty(seed.get("source_file"), cand.get("source_file")):
        return None

    if not same_nonempty(seed.get("chapter"), cand.get("chapter")):
        return None

    a = chunk_ordinal(str(seed["chunk_id"]))
    b = chunk_ordinal(str(cand["chunk_id"]))
    if a is None or b is None:
        return None

    dist = abs(a - b)
    if dist == 0:
        return None

    same_section = same_nonempty(seed.get("section"), cand.get("section"))

    if same_section and dist == 1:
        return (4.0, "same_section_adjacent")
    if same_section and dist == 2:
        return (3.0, "same_section_distance2")
    if same_section and dist <= 4:
        return (2.0, f"same_section_distance{dist}")
    if dist == 1:
        return (1.5, "same_chapter_adjacent")

    return None


def expand_candidates(
    dense_ids: Sequence[str],
    chunk_map: Dict[str, Dict],
    chunks: Sequence[Dict],
    *,
    max_new: int,
) -> Tuple[List[str], List[Dict]]:
    dense_set = set(dense_ids)
    scored: Dict[str, Dict] = {}

    for seed_rank, seed_id in enumerate(dense_ids, 1):
        seed = chunk_map[seed_id]

        for cand in chunks:
            cid = str(cand["chunk_id"])
            if cid in dense_set:
                continue

            relation = structural_relation_score(seed, cand)
            if relation is None:
                continue

            rel_score, relation_name = relation

            # Earlier Dense seeds get a tiny deterministic preference.
            score = rel_score + (6 - seed_rank) * 0.01

            old = scored.get(cid)
            record = {
                "chunk_id": cid,
                "score": score,
                "relation": relation_name,
                "seed_chunk_id": seed_id,
                "seed_rank": seed_rank,
                "chapter": cand.get("chapter"),
                "section": cand.get("section"),
                "source_file": cand.get("source_file"),
                "text": cand.get("text", ""),
            }

            if old is None or score > old["score"]:
                scored[cid] = record

    ranked = sorted(
        scored.values(),
        key=lambda x: (-x["score"], x["chunk_id"]),
    )[:max_new]

    return list(dense_ids) + [x["chunk_id"] for x in ranked], ranked


def recall(ids: Sequence[str], gold: Sequence[str]) -> float:
    g = set(gold)
    if not g:
        return 0.0
    return len(set(ids) & g) / len(g)


def hit(ids: Sequence[str], gold: Sequence[str]) -> bool:
    return bool(set(ids) & set(gold))


def main() -> None:
    load_dotenv(PROJECT_ROOT / ".env", override=False)

    ap = argparse.ArgumentParser()
    ap.add_argument("--benchmark", type=Path, default=DEFAULT_BENCHMARK)
    ap.add_argument("--pool", type=Path, default=DEFAULT_POOL)
    ap.add_argument("--knowledge", type=Path, default=DEFAULT_KNOWLEDGE)
    ap.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    ap.add_argument("--dense-k", type=int, default=5)
    ap.add_argument("--max-new", type=int, default=5)
    ap.add_argument("--only-multi", action="store_true")
    args = ap.parse_args()

    benchmark = [
        x for x in load_jsonl(args.benchmark)
        if not x.get("is_out_of_scope", False)
    ]
    if args.only_multi:
        benchmark = [x for x in benchmark if x["id"] in MULTI_IDS]

    judgments = load_judgments(args.pool)

    chunks = load_chunks_from_jsonl(args.knowledge)
    chunk_map = {str(x["chunk_id"]): x for x in chunks}

    dense = DenseRetriever()
    dense.prepare(chunks, use_cache=True)

    rows = []

    for no, q in enumerate(benchmark, 1):
        qid = q["id"]
        retrieved = dense.retrieve(
            query=q["question"],
            chunks=chunks,
            top_k=args.dense_k,
        )
        dense_ids = [str(x["chunk_id"]) for x in retrieved]

        expanded_ids, expansion_records = expand_candidates(
            dense_ids,
            chunk_map,
            chunks,
            max_new=args.max_new,
        )

        gold_ids = [str(x) for x in q.get("gold_chunk_ids", [])]
        primary_ids = [
            str(x) for x in q.get("primary_gold_chunk_ids", [])
        ]

        dense_gold = set(dense_ids) & set(gold_ids)
        expanded_gold = set(expanded_ids) & set(gold_ids)
        recovered_gold = sorted(expanded_gold - dense_gold)

        new_records = []
        unjudged = []

        for rec in expansion_records:
            cid = rec["chunk_id"]
            judged = judgments.get((qid, cid))

            item = dict(rec)
            if judged is None:
                item["judged"] = False
                item["relevance_label"] = None
                item["annotation_note"] = ""
                unjudged.append(cid)
            else:
                item["judged"] = True
                item["relevance_label"] = judged.get("relevance_label")
                item["annotation_note"] = judged.get(
                    "annotation_note", ""
                )
            item["is_known_gold"] = cid in set(gold_ids)
            item["is_primary_gold"] = cid in set(primary_ids)
            new_records.append(item)

        row = {
            "id": qid,
            "question": q["question"],
            "dense_ids": dense_ids,
            "expanded_ids": expanded_ids,
            "new_candidates": new_records,
            "gold_ids": gold_ids,
            "primary_gold_ids": primary_ids,
            "dense_known_gold_recall": round(
                recall(dense_ids, gold_ids), 4
            ),
            "expanded_known_gold_recall": round(
                recall(expanded_ids, gold_ids), 4
            ),
            "dense_primary_hit": hit(dense_ids, primary_ids),
            "expanded_primary_hit": hit(expanded_ids, primary_ids),
            "recovered_known_gold_ids": recovered_gold,
            "unjudged_new_ids": unjudged,
        }
        rows.append(row)

        interesting = (
            qid in MULTI_IDS
            or bool(recovered_gold)
            or bool(unjudged)
        )
        if interesting:
            print("\n" + "=" * 80)
            print(f"{qid}: {q['question']}")
            print("Dense Top5:", dense_ids)
            print(
                "known GoldRecall:",
                row["dense_known_gold_recall"],
                "->",
                row["expanded_known_gold_recall"],
            )
            print("recovered known gold:", recovered_gold or "[]")
            print("new structural candidates:")

            for item in new_records:
                print(
                    " ",
                    item["chunk_id"],
                    f"via={item['relation']}",
                    f"seed={item['seed_chunk_id']}",
                    f"judged={item['judged']}",
                    f"label={item['relevance_label']}",
                    f"KNOWN_GOLD={item['is_known_gold']}",
                )
                print("    ", str(item["text"])[:180])

    n = len(rows)
    dense_mean = sum(
        x["dense_known_gold_recall"] for x in rows
    ) / n
    expanded_mean = sum(
        x["expanded_known_gold_recall"] for x in rows
    ) / n

    recovered_queries = [
        x["id"] for x in rows if x["recovered_known_gold_ids"]
    ]

    primary_gain_queries = [
        x["id"] for x in rows
        if (not x["dense_primary_hit"] and x["expanded_primary_hit"])
    ]

    all_unjudged_pairs = [
        (x["id"], cid)
        for x in rows
        for cid in x["unjudged_new_ids"]
    ]

    summary = {
        "queries": n,
        "dense_k": args.dense_k,
        "max_new": args.max_new,
        "mean_dense_known_gold_recall": round(dense_mean, 4),
        "mean_expanded_known_gold_recall": round(expanded_mean, 4),
        "known_gold_recall_gain": round(expanded_mean - dense_mean, 4),
        "queries_with_recovered_known_gold": recovered_queries,
        "recovered_query_count": len(recovered_queries),
        "queries_with_primary_hit_gain": primary_gain_queries,
        "unjudged_new_pair_count": len(all_unjudged_pairs),
        "IMPORTANT": (
            "Known-gold gain is diagnostic only. Expanded unjudged chunks "
            "must be adjudicated before formal comparison."
        ),
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(
            {"summary": summary, "per_query": rows},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print("\n===== STRUCTURE EXPANSION DIAGNOSTIC V1 =====")
    for k, v in summary.items():
        print(f"{k}={v}")

    print("\noutput:", args.output)


if __name__ == "__main__":
    main()
