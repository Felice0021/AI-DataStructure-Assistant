"""Structure Expansion Diagnostic v1.1

Refines v1 by replacing broad "same chapter adjacency" with explicit section
families extracted from structured metadata.

Examples:
    "9.5 开放定址法" -> family "9.5"
    "9.5 探测堆积"   -> family "9.5"
    "10.4.2 建堆原理" -> family "10.4.2"

Expansion rule:
    same source_file
    + same chapter
    + same numeric section family
    + local chunk distance <= 4

For non-numeric sections (e.g. "章节习题"), only exact-section neighbors within
distance <= 2 are allowed.

No broad same-chapter fallback is used.

This is still a diagnostic:
new unjudged chunks are NEVER scored as irrelevant.

Run:
    python3 tests/diagnose_structure_expansion_v11.py --only-multi
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
    / "structure_expansion_diagnostic_v11.json"
)

MULTI_IDS = {"q006", "q029", "q032", "q038", "q039", "q041", "q043"}

CHUNK_ID_RE = re.compile(r"^(?P<prefix>.+?)_(?P<num>\d+)$")
SECTION_FAMILY_RE = re.compile(r"^\s*(\d+(?:\.\d+)*)")


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
    out = {}
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            out[(row["question_id"], row["chunk_id"])] = row
    return out


def chunk_ordinal(chunk_id: str) -> Optional[int]:
    m = CHUNK_ID_RE.match(chunk_id)
    return int(m.group("num")) if m else None


def section_family(section: object) -> Optional[str]:
    s = str(section or "").strip()
    if not s:
        return None
    m = SECTION_FAMILY_RE.match(s)
    return m.group(1) if m else None


def same_nonempty(a: object, b: object) -> bool:
    sa = str(a or "").strip()
    sb = str(b or "").strip()
    return bool(sa and sb and sa == sb)


def structural_relation(
    seed: Dict,
    cand: Dict,
) -> Optional[Tuple[float, str]]:
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

    seed_sec = str(seed.get("section") or "").strip()
    cand_sec = str(cand.get("section") or "").strip()
    seed_family = section_family(seed_sec)
    cand_family = section_family(cand_sec)

    # Primary hierarchy rule: same numbered subsection family.
    if (
        seed_family
        and cand_family
        and seed_family == cand_family
        and dist <= 4
    ):
        # Exact section title is strongest, then nearby family members.
        exact = seed_sec == cand_sec
        score = (6.0 if exact else 5.0) - 0.25 * dist
        rel = (
            f"same_section_distance{dist}"
            if exact
            else f"same_section_family_{seed_family}_distance{dist}"
        )
        return score, rel

    # Non-numeric sections such as "章节习题": exact section only, very local.
    if (
        not seed_family
        and not cand_family
        and seed_sec
        and seed_sec == cand_sec
        and dist <= 2
    ):
        return 3.0 - 0.25 * dist, f"same_nonnumeric_section_distance{dist}"

    return None


def expand_candidates(
    dense_ids: Sequence[str],
    chunk_map: Dict[str, Dict],
    chunks: Sequence[Dict],
    max_new: int,
) -> Tuple[List[str], List[Dict]]:
    dense_set = set(dense_ids)
    best_by_chunk: Dict[str, Dict] = {}

    for seed_rank, seed_id in enumerate(dense_ids, 1):
        seed = chunk_map[seed_id]

        for cand in chunks:
            cid = str(cand["chunk_id"])
            if cid in dense_set:
                continue

            relation = structural_relation(seed, cand)
            if relation is None:
                continue

            rel_score, rel_name = relation

            # Tiny deterministic preference for earlier Dense seeds.
            score = rel_score + (6 - seed_rank) * 0.01

            record = {
                "chunk_id": cid,
                "score": score,
                "relation": rel_name,
                "seed_chunk_id": seed_id,
                "seed_rank": seed_rank,
                "section_family": section_family(cand.get("section")),
                "chapter": cand.get("chapter"),
                "section": cand.get("section"),
                "source_file": cand.get("source_file"),
                "text": cand.get("text", ""),
            }

            old = best_by_chunk.get(cid)
            if old is None or record["score"] > old["score"]:
                best_by_chunk[cid] = record

    ranked = sorted(
        best_by_chunk.values(),
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

    for q in benchmark:
        qid = q["id"]

        retrieved = dense.retrieve(
            query=q["question"],
            chunks=chunks,
            top_k=args.dense_k,
        )
        dense_ids = [str(x["chunk_id"]) for x in retrieved]

        expanded_ids, new_records = expand_candidates(
            dense_ids,
            chunk_map,
            chunks,
            args.max_new,
        )

        gold_ids = [str(x) for x in q.get("gold_chunk_ids", [])]
        primary_ids = [str(x) for x in q.get("primary_gold_chunk_ids", [])]

        before = set(dense_ids) & set(gold_ids)
        after = set(expanded_ids) & set(gold_ids)
        recovered = sorted(after - before)

        annotated_new = []
        unjudged = []

        for rec in new_records:
            cid = rec["chunk_id"]
            j = judgments.get((qid, cid))
            item = dict(rec)

            if j is None:
                item["judged"] = False
                item["relevance_label"] = None
                unjudged.append(cid)
            else:
                item["judged"] = True
                item["relevance_label"] = j.get("relevance_label")

            item["is_known_gold"] = cid in set(gold_ids)
            item["is_primary_gold"] = cid in set(primary_ids)
            annotated_new.append(item)

        row = {
            "id": qid,
            "question": q["question"],
            "dense_ids": dense_ids,
            "expanded_ids": expanded_ids,
            "new_candidates": annotated_new,
            "new_candidate_count": len(annotated_new),
            "gold_ids": gold_ids,
            "dense_known_gold_recall": round(recall(dense_ids, gold_ids), 4),
            "expanded_known_gold_recall": round(
                recall(expanded_ids, gold_ids), 4
            ),
            "recovered_known_gold_ids": recovered,
            "dense_primary_hit": hit(dense_ids, primary_ids),
            "expanded_primary_hit": hit(expanded_ids, primary_ids),
            "unjudged_new_ids": unjudged,
        }
        rows.append(row)

        print("\n" + "=" * 80)
        print(f"{qid}: {q['question']}")
        print("Dense Top5:", dense_ids)
        print(
            "known GoldRecall:",
            row["dense_known_gold_recall"],
            "->",
            row["expanded_known_gold_recall"],
        )
        print("recovered known gold:", recovered or "[]")
        print("new structural candidates:")

        if not annotated_new:
            print("  []")
        for item in annotated_new:
            print(
                " ",
                item["chunk_id"],
                f"via={item['relation']}",
                f"seed={item['seed_chunk_id']}",
                f"section={item['section']}",
                f"judged={item['judged']}",
                f"label={item['relevance_label']}",
                f"KNOWN_GOLD={item['is_known_gold']}",
            )
            print("    ", str(item["text"])[:180])

    n = len(rows)
    dense_mean = sum(x["dense_known_gold_recall"] for x in rows) / n
    expanded_mean = sum(x["expanded_known_gold_recall"] for x in rows) / n

    recovered_queries = [
        x["id"] for x in rows if x["recovered_known_gold_ids"]
    ]
    primary_gain_queries = [
        x["id"]
        for x in rows
        if not x["dense_primary_hit"] and x["expanded_primary_hit"]
    ]
    unjudged_pairs = [
        (x["id"], cid)
        for x in rows
        for cid in x["unjudged_new_ids"]
    ]
    total_new = sum(x["new_candidate_count"] for x in rows)

    summary = {
        "queries": n,
        "dense_k": args.dense_k,
        "max_new": args.max_new,
        "total_new_candidates": total_new,
        "avg_new_candidates_per_query": round(total_new / n, 4),
        "mean_dense_known_gold_recall": round(dense_mean, 4),
        "mean_expanded_known_gold_recall": round(expanded_mean, 4),
        "known_gold_recall_gain": round(expanded_mean - dense_mean, 4),
        "queries_with_recovered_known_gold": recovered_queries,
        "recovered_query_count": len(recovered_queries),
        "queries_with_primary_hit_gain": primary_gain_queries,
        "unjudged_new_pair_count": len(unjudged_pairs),
        "IMPORTANT": (
            "Diagnostic only. Newly expanded unjudged chunks must be "
            "adjudicated before any formal effectiveness comparison."
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

    print("\n===== STRUCTURE EXPANSION DIAGNOSTIC V1.1 =====")
    for k, v in summary.items():
        print(f"{k}={v}")
    print("\noutput:", args.output)


if __name__ == "__main__":
    main()
