"""Diagnose SetR-style zero-shot failures v2.1.

No API calls. No data modification.

Classifies every query into:
1) solved:
   SetR-style selector covers all gold facets.
2) retrieval_limited:
   even the UNION of all Dense Top-5 candidates cannot cover every facet.
3) selector_limited:
   Dense Top-5 contains sufficient evidence for all facets, but SetR-style
   selection misses one or more facets.

For selector-limited cases, computes a gold-aware minimal-cardinality oracle
subset within Dense Top-5. This oracle is EVALUATION ONLY.

For retrieval-limited cases, lists missing facets and known relevant chunks
outside Dense Top-5 that support them.

Run:
    python3 tests/diagnose_setr_failures_v21.py
"""
from __future__ import annotations

import argparse
import csv
import itertools
import json
from pathlib import Path
from typing import Dict, List, Sequence, Set

PROJECT_ROOT = Path(__file__).resolve().parents[1]

DEFAULT_BENCHMARK = (
    PROJECT_ROOT / "tests" / "benchmarks" / "datastructureqa_dev_v1.jsonl"
)
DEFAULT_POOL = PROJECT_ROOT / "tests" / "retrieval_pool_v1.csv"
DEFAULT_FACETS = (
    PROJECT_ROOT
    / "tests"
    / "annotations"
    / "datastructureqa_dev_v18_facets_reviewed.jsonl"
)
DEFAULT_SETR = (
    PROJECT_ROOT
    / "tests"
    / "results"
    / "setr_zeroshot_baseline_v20.json"
)
DEFAULT_OUTPUT = (
    PROJECT_ROOT
    / "tests"
    / "results"
    / "setr_failure_diagnostic_v21.json"
)


def load_jsonl(path: Path) -> Dict[str, Dict]:
    out = {}
    with path.open("r", encoding="utf-8") as f:
        for raw in f:
            if raw.strip():
                obj = json.loads(raw)
                out[obj["id"]] = obj
    return out


def load_pool(path: Path) -> Dict[str, Dict[str, Dict]]:
    out: Dict[str, Dict[str, Dict]] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            out.setdefault(row["question_id"], {})[
                row["chunk_id"]
            ] = row
    return out


def dense5_ids(pool_q: Dict[str, Dict]) -> List[str]:
    ranked = []
    for cid, row in pool_q.items():
        raw = str(row.get("dense_rank", "")).strip()
        if not raw:
            continue
        try:
            rank = int(float(raw))
        except ValueError:
            continue
        if 1 <= rank <= 5:
            ranked.append((rank, cid))
    ranked.sort()
    return [cid for _, cid in ranked]


def facet_coverage(
    ids: Sequence[str],
    support: Dict[str, List[str]],
    valid_facets: Set[str],
) -> Set[str]:
    covered = set()
    for cid in ids:
        covered.update(support.get(cid, []))
    return covered & valid_facets


def minimal_cover_subset(
    candidate_ids: Sequence[str],
    support: Dict[str, List[str]],
    facets: Set[str],
):
    """Gold-aware oracle. Evaluation only."""
    for k in range(1, len(candidate_ids) + 1):
        for combo in itertools.combinations(candidate_ids, k):
            if facet_coverage(combo, support, facets) == facets:
                return list(combo)
    return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--benchmark", type=Path, default=DEFAULT_BENCHMARK)
    ap.add_argument("--pool", type=Path, default=DEFAULT_POOL)
    ap.add_argument("--facets", type=Path, default=DEFAULT_FACETS)
    ap.add_argument("--setr", type=Path, default=DEFAULT_SETR)
    ap.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = ap.parse_args()

    benchmark = load_jsonl(args.benchmark)
    pool = load_pool(args.pool)
    facets = load_jsonl(args.facets)

    setr = json.loads(args.setr.read_text(encoding="utf-8"))
    setr_by_id = {
        x["id"]: x
        for x in setr["per_query"]
    }

    rows = []
    counts = {
        "solved": 0,
        "retrieval_limited": 0,
        "selector_limited": 0,
    }

    print(
        "qid\tclass\tSetRFacet\tTop5Ceiling\t"
        "SetRK\tOracleK\tmissing_facets"
    )

    for qid, q in benchmark.items():
        if q.get("is_out_of_scope", False):
            continue

        if qid not in setr_by_id:
            raise RuntimeError(f"{qid}: missing SetR result")
        if qid not in facets:
            raise RuntimeError(f"{qid}: missing facet annotation")

        frow = facets[qid]
        facet_ids = {
            str(x["facet_id"])
            for x in frow.get("facets", [])
        }
        support = {
            str(cid): [str(x) for x in fs]
            for cid, fs in frow.get("chunk_support", {}).items()
        }

        top5 = dense5_ids(pool.get(qid, {}))
        if len(top5) != 5:
            raise RuntimeError(
                f"{qid}: expected 5 Dense candidates, got {len(top5)}"
            )

        srow = setr_by_id[qid]
        selected = [
            str(x) for x in srow["setr_selected_ids"]
        ]

        setr_cov = facet_coverage(
            selected,
            support,
            facet_ids,
        )
        top5_cov = facet_coverage(
            top5,
            support,
            facet_ids,
        )

        setr_recall = (
            len(setr_cov) / len(facet_ids)
            if facet_ids
            else 0.0
        )
        ceiling = (
            len(top5_cov) / len(facet_ids)
            if facet_ids
            else 0.0
        )

        missing_setr = sorted(facet_ids - setr_cov)
        missing_top5 = sorted(facet_ids - top5_cov)

        if setr_cov == facet_ids:
            cls = "solved"
        elif top5_cov != facet_ids:
            cls = "retrieval_limited"
        else:
            cls = "selector_limited"

        counts[cls] += 1

        oracle = None
        if top5_cov == facet_ids:
            oracle = minimal_cover_subset(
                top5,
                support,
                facet_ids,
            )

        # Relevant evidence outside Dense Top-5, grouped by missing facet.
        outside_relevant = []
        top5_set = set(top5)

        for cid, prow in pool.get(qid, {}).items():
            label = str(
                prow.get("relevance_label", "")
            ).strip()
            if label not in {"1", "2"}:
                continue
            if cid in top5_set:
                continue

            mapped = set(support.get(cid, []))
            useful_for_missing = sorted(
                mapped & set(missing_top5)
            )
            if useful_for_missing:
                outside_relevant.append(
                    {
                        "chunk_id": cid,
                        "label": int(label),
                        "supports_missing_facets": useful_for_missing,
                        "section": prow.get("section", ""),
                        "text": prow.get("chunk_text", ""),
                    }
                )

        # For selector-limited cases, identify Top-5 candidates belonging to
        # one minimal full-cover oracle but omitted by SetR.
        oracle_missing_from_setr = []
        if oracle is not None:
            oracle_missing_from_setr = [
                cid for cid in oracle
                if cid not in set(selected)
            ]

        row = {
            "id": qid,
            "question": q["question"],
            "classification": cls,
            "facet_ids": sorted(facet_ids),
            "dense_top5_ids": top5,
            "setr_selected_ids": selected,
            "setr_k": len(selected),
            "setr_covered_facets": sorted(setr_cov),
            "setr_facet_recall": round(setr_recall, 4),
            "top5_covered_facets": sorted(top5_cov),
            "top5_facet_ceiling": round(ceiling, 4),
            "setr_missing_facets": missing_setr,
            "top5_missing_facets": missing_top5,
            "minimal_top5_oracle_ids": oracle,
            "minimal_top5_oracle_k": (
                len(oracle) if oracle is not None else None
            ),
            "oracle_missing_from_setr": oracle_missing_from_setr,
            "known_relevant_outside_top5_for_missing_facets": outside_relevant,
        }
        rows.append(row)

        print(
            f"{qid}\t{cls}\t"
            f"{row['setr_facet_recall']}\t"
            f"{row['top5_facet_ceiling']}\t"
            f"{row['setr_k']}\t"
            f"{row['minimal_top5_oracle_k']}\t"
            f"{','.join(missing_setr)}"
        )

    failures = [
        x for x in rows
        if x["classification"] != "solved"
    ]

    print("\n===== SETR FAILURE DIAGNOSTIC V2.1 =====")
    print("queries =", len(rows))
    print("solved =", counts["solved"])
    print("retrieval_limited =", counts["retrieval_limited"])
    print("selector_limited =", counts["selector_limited"])
    print(
        "failure_ids =",
        [x["id"] for x in failures],
    )
    print(
        "retrieval_limited_ids =",
        [
            x["id"] for x in rows
            if x["classification"] == "retrieval_limited"
        ],
    )
    print(
        "selector_limited_ids =",
        [
            x["id"] for x in rows
            if x["classification"] == "selector_limited"
        ],
    )

    print("\n===== FAILURE DETAILS =====")
    for x in failures:
        print("\n", x["id"], x["classification"])
        print(" question:", x["question"])
        print(" SetR selected:", x["setr_selected_ids"])
        print(" SetR missing:", x["setr_missing_facets"])
        print(" Top5 ceiling:", x["top5_facet_ceiling"])

        if x["classification"] == "selector_limited":
            print(
                " minimal Top5 oracle:",
                x["minimal_top5_oracle_ids"],
            )
            print(
                " oracle missing from SetR:",
                x["oracle_missing_from_setr"],
            )
        else:
            print(
                " Top5 missing facets:",
                x["top5_missing_facets"],
            )
            print(" outside relevant evidence:")
            for e in x[
                "known_relevant_outside_top5_for_missing_facets"
            ]:
                print(
                    "  ",
                    e["chunk_id"],
                    "label=", e["label"],
                    "facets=", e["supports_missing_facets"],
                    "section=", e["section"],
                )

    output = {
        "summary": {
            "query_count": len(rows),
            **counts,
            "failure_ids": [x["id"] for x in failures],
        },
        "per_query": rows,
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(
            output,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print("\noutput:", args.output)


if __name__ == "__main__":
    main()
