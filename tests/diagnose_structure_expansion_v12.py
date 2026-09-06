"""Structure Expansion Diagnostic v1.2
Need-conditioned structure expansion.

Key change from v1/v1.1:
    Do NOT expand around every Dense Top-5 candidate.

Instead:
    query-only predicted needs
        -> cached LLM support matrix from evidence_selection_v02.json
        -> choose the strongest Dense anchor for each need
        -> expand only around those anchors
        -> same source + chapter + numeric section family

This reuses the already-computed v0.2 support matrix and makes NO LLM calls.

This is still diagnostic:
newly expanded unjudged chunks are never treated as irrelevant.

Run:
    python3 tests/diagnose_structure_expansion_v12.py --only-multi
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
from rag.retrievers import load_chunks_from_jsonl


DEFAULT_BENCHMARK = (
    PROJECT_ROOT / "tests" / "benchmarks" / "datastructureqa_dev_v1.jsonl"
)
DEFAULT_POOL = PROJECT_ROOT / "tests" / "retrieval_pool_v1.csv"
DEFAULT_KNOWLEDGE = PROJECT_ROOT / "knowledge_base" / "ds_chunks.jsonl"
DEFAULT_V02 = (
    PROJECT_ROOT
    / "tests"
    / "results"
    / "evidence_selection_v02.json"
)
DEFAULT_OUTPUT = (
    PROJECT_ROOT
    / "tests"
    / "results"
    / "structure_expansion_diagnostic_v12.json"
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


def load_json(path: Path) -> Dict:
    return json.loads(path.read_text(encoding="utf-8"))


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


def choose_need_anchors(
    candidate_ids: Sequence[str],
    predicted_needs: Sequence[str],
    support_matrix: Sequence[Sequence[float]],
    *,
    min_support: float,
    top_per_need: int,
) -> Tuple[List[str], List[Dict]]:
    """Choose strongest Dense anchor(s) for each predicted need.

    Ties are broken by Dense rank because candidate_ids preserve Dense order.
    A single candidate may anchor multiple needs.
    """
    if len(support_matrix) != len(predicted_needs):
        raise RuntimeError(
            "support row count does not match predicted needs: "
            f"{len(support_matrix)} vs {len(predicted_needs)}"
        )

    chosen_ids: List[str] = []
    details: List[Dict] = []

    for need_idx, (need, row) in enumerate(
        zip(predicted_needs, support_matrix), 1
    ):
        if len(row) != len(candidate_ids):
            raise RuntimeError(
                f"need {need_idx}: support width={len(row)}, "
                f"candidate_count={len(candidate_ids)}"
            )

        ranked = sorted(
            range(len(candidate_ids)),
            key=lambda i: (-float(row[i]), i),
        )

        valid = [
            i for i in ranked
            if float(row[i]) + 1e-6 >= min_support
        ]

        # If no candidate reaches threshold, keep only the best-scoring
        # candidate as a weak fallback so the need is not silently dropped.
        fallback = False
        if not valid:
            valid = ranked[:1]
            fallback = True

        selected = valid[:top_per_need]

        for i in selected:
            cid = candidate_ids[i]
            if cid not in chosen_ids:
                chosen_ids.append(cid)

            details.append(
                {
                    "need_index": need_idx,
                    "need": need,
                    "anchor_chunk_id": cid,
                    "dense_rank": i + 1,
                    "support": round(float(row[i]), 4),
                    "fallback_below_threshold": fallback,
                }
            )

    return chosen_ids, details


def structural_relation(
    seed: Dict,
    cand: Dict,
    *,
    max_distance: int,
) -> Optional[Tuple[float, str]]:
    if seed["chunk_id"] == cand["chunk_id"]:
        return None

    if not same_nonempty(seed.get("source_file"), cand.get("source_file")):
        return None
    if not same_nonempty(seed.get("chapter"), cand.get("chapter")):
        return None

    seed_family = section_family(seed.get("section"))
    cand_family = section_family(cand.get("section"))

    # v1.2 deliberately requires a numeric hierarchy family.
    # Broad chapter adjacency and generic "章节习题" are excluded.
    if not seed_family or not cand_family:
        return None
    if seed_family != cand_family:
        return None

    a = chunk_ordinal(str(seed["chunk_id"]))
    b = chunk_ordinal(str(cand["chunk_id"]))
    if a is None or b is None:
        return None

    dist = abs(a - b)
    if dist == 0 or dist > max_distance:
        return None

    seed_sec = str(seed.get("section") or "").strip()
    cand_sec = str(cand.get("section") or "").strip()
    exact = seed_sec == cand_sec

    score = (6.0 if exact else 5.0) - 0.25 * dist
    relation = (
        f"same_section_distance{dist}"
        if exact
        else f"same_section_family_{seed_family}_distance{dist}"
    )
    return score, relation


def expand_from_anchors(
    dense_ids: Sequence[str],
    anchor_ids: Sequence[str],
    chunk_map: Dict[str, Dict],
    chunks: Sequence[Dict],
    *,
    max_distance: int,
    max_new: int,
) -> Tuple[List[str], List[Dict]]:
    dense_set = set(dense_ids)
    best_by_chunk: Dict[str, Dict] = {}

    for anchor_order, seed_id in enumerate(anchor_ids, 1):
        seed = chunk_map[seed_id]

        for cand in chunks:
            cid = str(cand["chunk_id"])
            if cid in dense_set:
                continue

            relation = structural_relation(
                seed,
                cand,
                max_distance=max_distance,
            )
            if relation is None:
                continue

            rel_score, rel_name = relation
            score = rel_score + (len(anchor_ids) - anchor_order + 1) * 0.01

            record = {
                "chunk_id": cid,
                "score": score,
                "relation": rel_name,
                "seed_chunk_id": seed_id,
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

    expanded_ids = list(dense_ids) + [x["chunk_id"] for x in ranked]
    return expanded_ids, ranked


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
    ap.add_argument("--v02", type=Path, default=DEFAULT_V02)
    ap.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    ap.add_argument("--only-multi", action="store_true")

    # Fixed diagnostic settings.
    ap.add_argument("--min-support", type=float, default=2.0 / 3.0)
    ap.add_argument("--top-per-need", type=int, default=1)
    ap.add_argument("--max-distance", type=int, default=4)
    ap.add_argument("--max-new", type=int, default=5)
    args = ap.parse_args()

    benchmark = {
        x["id"]: x
        for x in load_jsonl(args.benchmark)
        if not x.get("is_out_of_scope", False)
    }

    if args.only_multi:
        benchmark = {
            qid: q
            for qid, q in benchmark.items()
            if qid in MULTI_IDS
        }

    judgments = load_judgments(args.pool)
    chunks = load_chunks_from_jsonl(args.knowledge)
    chunk_map = {str(x["chunk_id"]): x for x in chunks}

    v02 = load_json(args.v02)
    v02_by_id = {
        x["id"]: x
        for x in v02.get("per_query", [])
    }

    missing = sorted(set(benchmark) - set(v02_by_id))
    if missing:
        if args.only_multi:
            raise RuntimeError(
                f"v0.2 results missing required multi-evidence queries: {missing}"
            )
        # The current v0.2 file contains only the 7 multi-evidence queries.
        # For all-query mode we evaluate only available v0.2 records.
        benchmark = {
            qid: q
            for qid, q in benchmark.items()
            if qid in v02_by_id
        }

    rows = []

    for qid, q in benchmark.items():
        v = v02_by_id[qid]
        dense_ids = [str(x) for x in v["candidate_ids"]]
        needs = [str(x) for x in v["predicted_needs"]]
        support_matrix = v["llm_support_matrix"]

        anchor_ids, anchor_details = choose_need_anchors(
            dense_ids,
            needs,
            support_matrix,
            min_support=args.min_support,
            top_per_need=args.top_per_need,
        )

        expanded_ids, new_records = expand_from_anchors(
            dense_ids,
            anchor_ids,
            chunk_map,
            chunks,
            max_distance=args.max_distance,
            max_new=args.max_new,
        )

        gold_ids = [str(x) for x in q.get("gold_chunk_ids", [])]
        primary_ids = [
            str(x) for x in q.get("primary_gold_chunk_ids", [])
        ]

        dense_gold = set(dense_ids) & set(gold_ids)
        expanded_gold = set(expanded_ids) & set(gold_ids)
        recovered = sorted(expanded_gold - dense_gold)

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
            "predicted_needs": needs,
            "dense_ids": dense_ids,
            "anchor_ids": anchor_ids,
            "anchor_details": anchor_details,
            "expanded_ids": expanded_ids,
            "new_candidates": annotated_new,
            "new_candidate_count": len(annotated_new),
            "gold_ids": gold_ids,
            "dense_known_gold_recall": round(
                recall(dense_ids, gold_ids), 4
            ),
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

        print("need-conditioned anchors:")
        for d in anchor_details:
            print(
                f"  N{d['need_index']} -> {d['anchor_chunk_id']} "
                f"(rank={d['dense_rank']}, support={d['support']}, "
                f"fallback={d['fallback_below_threshold']})"
            )
            print("    need:", d["need"])

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
    expanded_mean = sum(
        x["expanded_known_gold_recall"] for x in rows
    ) / n

    total_new = sum(x["new_candidate_count"] for x in rows)
    unjudged_pairs = [
        (x["id"], cid)
        for x in rows
        for cid in x["unjudged_new_ids"]
    ]

    recovered_queries = [
        x["id"] for x in rows if x["recovered_known_gold_ids"]
    ]
    primary_gain_queries = [
        x["id"]
        for x in rows
        if not x["dense_primary_hit"] and x["expanded_primary_hit"]
    ]

    unique_anchor_counts = [len(x["anchor_ids"]) for x in rows]

    summary = {
        "queries": n,
        "min_support": round(args.min_support, 4),
        "top_per_need": args.top_per_need,
        "max_distance": args.max_distance,
        "max_new": args.max_new,
        "mean_unique_anchors_per_query": round(
            sum(unique_anchor_counts) / n, 4
        ),
        "total_new_candidates": total_new,
        "avg_new_candidates_per_query": round(total_new / n, 4),
        "mean_dense_known_gold_recall": round(dense_mean, 4),
        "mean_expanded_known_gold_recall": round(expanded_mean, 4),
        "known_gold_recall_gain": round(
            expanded_mean - dense_mean, 4
        ),
        "queries_with_recovered_known_gold": recovered_queries,
        "recovered_query_count": len(recovered_queries),
        "queries_with_primary_hit_gain": primary_gain_queries,
        "unjudged_new_pair_count": len(unjudged_pairs),
        "IMPORTANT": (
            "Diagnostic only. Newly expanded unjudged chunks must be "
            "adjudicated before formal effectiveness comparison."
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

    print("\n===== STRUCTURE EXPANSION DIAGNOSTIC V1.2 =====")
    for k, v in summary.items():
        print(f"{k}={v}")

    print("\noutput:", args.output)


if __name__ == "__main__":
    main()
