"""Re-evaluate SetR and structured comparison method after gold audit v2.7.

No API calls. No data modification.

Uses the audited facet file:
tests/annotations/datastructureqa_dev_v182_comparison_audited.jsonl

Recomputes:
- SetR-style zero-shot metrics on all 49 in-scope questions
- failure classifications under audited core facets
- comparison vs non-comparison failure concentration
- Fisher exact test
- structured contrastive v2.5 metrics on the 10 comparison questions
- paired SetR vs structured comparison results

Run:
    python3 tests/reevaluate_after_comparison_audit_v27.py
"""
from __future__ import annotations

import argparse
import csv
import itertools
import json
import math
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
    / "datastructureqa_dev_v182_comparison_audited.jsonl"
)
DEFAULT_SETR = (
    PROJECT_ROOT
    / "tests"
    / "results"
    / "setr_zeroshot_baseline_v20.json"
)
DEFAULT_STRUCT = (
    PROJECT_ROOT
    / "tests"
    / "results"
    / "structured_contrastive_v25.json"
)
DEFAULT_OUTPUT = (
    PROJECT_ROOT
    / "tests"
    / "results"
    / "comparison_audit_reeval_v27.json"
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


def facet_ids(frow: Dict) -> Set[str]:
    out = set()
    for i, item in enumerate(frow.get("facets", []), 1):
        if isinstance(item, dict):
            out.add(str(item.get("facet_id") or f"f{i}"))
        else:
            out.add(f"f{i}")
    return out


def covered_facets(
    selected_ids: Sequence[str],
    frow: Dict,
) -> Set[str]:
    valid = facet_ids(frow)
    support = frow.get("chunk_support", {})
    covered = set()
    for cid in selected_ids:
        covered.update(str(x) for x in support.get(cid, []))
    return covered & valid


def evaluate_selection(
    selected_ids: Sequence[str],
    frow: Dict,
) -> Dict:
    valid = facet_ids(frow)
    covered = covered_facets(selected_ids, frow)

    recall = (
        len(covered) / len(valid)
        if valid
        else 0.0
    )

    return {
        "k": len(selected_ids),
        "facet_recall": recall,
        "full_facet": (
            abs(recall - 1.0) < 1e-12
        ),
        "covered_facets": sorted(covered),
        "missing_facets": sorted(valid - covered),
    }


def classify(
    selected_ids: Sequence[str],
    top5_ids: Sequence[str],
    frow: Dict,
) -> str:
    valid = facet_ids(frow)
    selected_cov = covered_facets(selected_ids, frow)
    top5_cov = covered_facets(top5_ids, frow)

    if selected_cov == valid:
        return "solved"
    if top5_cov == valid:
        return "selector_limited"
    return "retrieval_limited"


def fisher_two_sided(a: int, b: int, c: int, d: int) -> float:
    n1 = a + b
    n2 = c + d
    k = a + c
    n = n1 + n2

    lo = max(0, k - n2)
    hi = min(n1, k)

    def prob(x: int) -> float:
        return (
            math.comb(n1, x)
            * math.comb(n2, k - x)
            / math.comb(n, k)
        )

    p_obs = prob(a)
    p = 0.0
    for x in range(lo, hi + 1):
        px = prob(x)
        if px <= p_obs + 1e-15:
            p += px

    return min(1.0, p)


def aggregate(rows: List[Dict], key: str) -> Dict:
    vals = [x[key] for x in rows]
    n = len(vals)

    return {
        "n": n,
        "mean_k": round(
            sum(x["k"] for x in vals) / n,
            4,
        ),
        "mean_facet_recall": round(
            sum(x["facet_recall"] for x in vals) / n,
            4,
        ),
        "full_facet_rate": round(
            sum(bool(x["full_facet"]) for x in vals) / n,
            4,
        ),
        "full_count": sum(
            bool(x["full_facet"]) for x in vals
        ),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--benchmark", type=Path, default=DEFAULT_BENCHMARK)
    ap.add_argument("--pool", type=Path, default=DEFAULT_POOL)
    ap.add_argument("--facets", type=Path, default=DEFAULT_FACETS)
    ap.add_argument("--setr", type=Path, default=DEFAULT_SETR)
    ap.add_argument("--structured", type=Path, default=DEFAULT_STRUCT)
    ap.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = ap.parse_args()

    benchmark = load_jsonl(args.benchmark)
    pool = load_pool(args.pool)
    facets = load_jsonl(args.facets)

    setr_raw = json.loads(args.setr.read_text(encoding="utf-8"))
    struct_raw = json.loads(
        args.structured.read_text(encoding="utf-8")
    )

    setr_by_id = {
        x["id"]: x
        for x in setr_raw["per_query"]
    }
    struct_by_id = {
        x["id"]: x
        for x in struct_raw["per_query"]
    }

    rows = []

    for qid, q in benchmark.items():
        if q.get("is_out_of_scope", False):
            continue

        if qid not in setr_by_id:
            raise RuntimeError(f"{qid}: missing SetR result")
        if qid not in facets:
            raise RuntimeError(f"{qid}: missing audited facets")

        s = setr_by_id[qid]
        selected = [
            str(x) for x in s["setr_selected_ids"]
        ]
        top5 = dense5_ids(pool[qid])

        if len(top5) != 5:
            raise RuntimeError(
                f"{qid}: expected Dense Top5, got {len(top5)}"
            )

        setr_eval = evaluate_selection(
            selected,
            facets[qid],
        )

        cls = classify(
            selected,
            top5,
            facets[qid],
        )

        row = {
            "id": qid,
            "type": str(q.get("type", "unknown")),
            "is_comparison": (
                str(q.get("type", "")).lower()
                == "comparison"
            ),
            "classification": cls,
            "setr": setr_eval,
        }

        if qid in struct_by_id:
            st = struct_by_id[qid]
            structured_selected = [
                str(x)
                for x in st["structured_selected_ids"]
            ]
            row["structured"] = evaluate_selection(
                structured_selected,
                facets[qid],
            )
            row["structured_selected_ids"] = structured_selected

        rows.append(row)

    all_setr = aggregate(rows, "setr")

    comparison = [
        x for x in rows if x["is_comparison"]
    ]
    noncomparison = [
        x for x in rows if not x["is_comparison"]
    ]

    comp_fail = [
        x for x in comparison
        if x["classification"] != "solved"
    ]
    noncomp_fail = [
        x for x in noncomparison
        if x["classification"] != "solved"
    ]

    a = len(comp_fail)
    b = len(comparison) - a
    c = len(noncomp_fail)
    d = len(noncomparison) - c

    fisher_p = fisher_two_sided(a, b, c, d)

    comparison_setr = aggregate(
        comparison,
        "setr",
    )

    struct_rows = [
        x for x in comparison
        if "structured" in x
    ]
    comparison_structured = aggregate(
        struct_rows,
        "structured",
    )

    paired = {
        "facet_wins": [],
        "facet_ties": [],
        "facet_losses": [],
        "full_wins": [],
        "full_ties": [],
        "full_losses": [],
    }

    for x in struct_rows:
        aeval = x["structured"]
        beval = x["setr"]

        diff = (
            aeval["facet_recall"]
            - beval["facet_recall"]
        )
        if diff > 1e-12:
            paired["facet_wins"].append(x["id"])
        elif diff < -1e-12:
            paired["facet_losses"].append(x["id"])
        else:
            paired["facet_ties"].append(x["id"])

        af = bool(aeval["full_facet"])
        bf = bool(beval["full_facet"])

        if af and not bf:
            paired["full_wins"].append(x["id"])
        elif bf and not af:
            paired["full_losses"].append(x["id"])
        else:
            paired["full_ties"].append(x["id"])

    failure_ids = [
        x["id"] for x in rows
        if x["classification"] != "solved"
    ]
    selector_ids = [
        x["id"] for x in rows
        if x["classification"] == "selector_limited"
    ]
    retrieval_ids = [
        x["id"] for x in rows
        if x["classification"] == "retrieval_limited"
    ]

    summary = {
        "setr_all49": all_setr,
        "failure_count": len(failure_ids),
        "failure_ids": failure_ids,
        "selector_limited_ids": selector_ids,
        "retrieval_limited_ids": retrieval_ids,
        "comparison": {
            "n": len(comparison),
            "failures": len(comp_fail),
            "failure_rate": round(
                len(comp_fail) / len(comparison),
                4,
            ),
            "failure_ids": [
                x["id"] for x in comp_fail
            ],
            "setr": comparison_setr,
            "structured_v25": comparison_structured,
        },
        "noncomparison": {
            "n": len(noncomparison),
            "failures": len(noncomp_fail),
            "failure_rate": round(
                len(noncomp_fail) / len(noncomparison),
                4,
            ),
            "failure_ids": [
                x["id"] for x in noncomp_fail
            ],
        },
        "comparison_vs_noncomparison": {
            "contingency_table": [[a, b], [c, d]],
            "fisher_exact_two_sided_p": fisher_p,
        },
        "structured_vs_setr_paired": paired,
    }

    args.output.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    args.output.write_text(
        json.dumps(
            {
                "config": {
                    "facet_file": str(args.facets),
                    "note": (
                        "Post-audit Dev re-evaluation. "
                        "No API calls; no retuning."
                    ),
                },
                "summary": summary,
                "per_query": rows,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print("===== POST-AUDIT RE-EVALUATION V2.7 =====")
    print("SetR all49 =", all_setr)
    print("failure_count =", len(failure_ids))
    print("failure_ids =", failure_ids)
    print("selector_limited_ids =", selector_ids)
    print("retrieval_limited_ids =", retrieval_ids)

    print("\n===== COMPARISON VS NON-COMPARISON =====")
    print(
        "comparison:",
        f"n={len(comparison)}",
        f"fail={len(comp_fail)}",
        f"rate={round(len(comp_fail)/len(comparison),4)}",
        f"ids={[x['id'] for x in comp_fail]}",
    )
    print(
        "noncomparison:",
        f"n={len(noncomparison)}",
        f"fail={len(noncomp_fail)}",
        f"rate={round(len(noncomp_fail)/len(noncomparison),4)}",
        f"ids={[x['id'] for x in noncomp_fail]}",
    )
    print(
        "2x2 =",
        [[a, b], [c, d]],
    )
    print(
        "fisher_exact_two_sided_p =",
        round(fisher_p, 6),
    )

    print("\n===== COMPARISON METHOD METRICS =====")
    print("SetR =", comparison_setr)
    print("Structured v2.5 =", comparison_structured)

    print("\n===== STRUCTURED VS SETR PAIRED =====")
    print(
        "Facet W/T/L =",
        len(paired["facet_wins"]),
        "/",
        len(paired["facet_ties"]),
        "/",
        len(paired["facet_losses"]),
    )
    print("Facet wins =", paired["facet_wins"])
    print("Facet losses =", paired["facet_losses"])
    print(
        "FullFacet W/T/L =",
        len(paired["full_wins"]),
        "/",
        len(paired["full_ties"]),
        "/",
        len(paired["full_losses"]),
    )
    print("Full wins =", paired["full_wins"])
    print("Full losses =", paired["full_losses"])

    print("\noutput =", args.output)


if __name__ == "__main__":
    main()
