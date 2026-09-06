"""Stratified SetR-style failure analysis v2.4.

No API calls. No data modification.

Purpose
-------
Before designing a comparison-specific method, quantify whether the five
SetR-style failures are genuinely concentrated in comparison questions.

Reports:
- failure rate by benchmark question type
- SetR FacetRecall / FullFacet / AvgK by type
- comparison vs non-comparison 2x2 table
- two-sided Fisher exact test
- failure rate by gold facet count
- failure rate by SetR-generated requirement count

Inputs
------
tests/benchmarks/datastructureqa_dev_v1.jsonl
tests/annotations/datastructureqa_dev_v18_facets_reviewed.jsonl
tests/results/setr_zeroshot_baseline_v20.json
tests/results/setr_failure_diagnostic_v21.json

Run
---
python3 tests/analyze_setr_failure_strata_v24.py
"""
from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Dict, Iterable, List

PROJECT_ROOT = Path(__file__).resolve().parents[1]

DEFAULT_BENCHMARK = (
    PROJECT_ROOT / "tests" / "benchmarks" / "datastructureqa_dev_v1.jsonl"
)
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
DEFAULT_DIAG = (
    PROJECT_ROOT
    / "tests"
    / "results"
    / "setr_failure_diagnostic_v21.json"
)
DEFAULT_OUTPUT = (
    PROJECT_ROOT
    / "tests"
    / "results"
    / "setr_failure_strata_v24.json"
)


def load_jsonl(path: Path) -> Dict[str, Dict]:
    out = {}
    with path.open("r", encoding="utf-8") as f:
        for raw in f:
            if raw.strip():
                obj = json.loads(raw)
                out[obj["id"]] = obj
    return out


def fisher_two_sided(a: int, b: int, c: int, d: int) -> float:
    """Two-sided Fisher exact p-value for [[a,b],[c,d]].

    Rows are fixed:
        comparison:     fail=a, solved=b
        non-comparison: fail=c, solved=d
    """
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
    eps = 1e-15

    for x in range(lo, hi + 1):
        px = prob(x)
        if px <= p_obs + eps:
            p += px

    return min(1.0, p)


def summarize_group(rows: Iterable[Dict]) -> Dict:
    rows = list(rows)
    n = len(rows)
    if not n:
        return {
            "n": 0,
            "failures": 0,
            "failure_rate": None,
        }

    failures = sum(x["classification"] != "solved" for x in rows)
    selector = sum(x["classification"] == "selector_limited" for x in rows)
    retrieval = sum(x["classification"] == "retrieval_limited" for x in rows)

    return {
        "n": n,
        "failures": failures,
        "failure_rate": round(failures / n, 4),
        "selector_limited": selector,
        "retrieval_limited": retrieval,
        "mean_setr_facet_recall": round(
            sum(x["setr_facet_recall"] for x in rows) / n,
            4,
        ),
        "setr_full_facet_rate": round(
            sum(x["setr_full_facet"] for x in rows) / n,
            4,
        ),
        "mean_setr_k": round(
            sum(x["setr_k"] for x in rows) / n,
            4,
        ),
        "ids": [x["id"] for x in rows],
        "failure_ids": [
            x["id"] for x in rows
            if x["classification"] != "solved"
        ],
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--benchmark", type=Path, default=DEFAULT_BENCHMARK)
    ap.add_argument("--facets", type=Path, default=DEFAULT_FACETS)
    ap.add_argument("--setr", type=Path, default=DEFAULT_SETR)
    ap.add_argument("--diag", type=Path, default=DEFAULT_DIAG)
    ap.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = ap.parse_args()

    benchmark = load_jsonl(args.benchmark)
    facets = load_jsonl(args.facets)

    setr = json.loads(args.setr.read_text(encoding="utf-8"))
    diag = json.loads(args.diag.read_text(encoding="utf-8"))

    setr_by_id = {x["id"]: x for x in setr["per_query"]}
    diag_by_id = {x["id"]: x for x in diag["per_query"]}

    rows: List[Dict] = []

    for qid, q in benchmark.items():
        if q.get("is_out_of_scope", False):
            continue

        s = setr_by_id[qid]
        d = diag_by_id[qid]
        f = facets[qid]

        qtype = str(q.get("type", "unknown")).strip() or "unknown"

        rows.append(
            {
                "id": qid,
                "type": qtype,
                "is_comparison": qtype.lower() == "comparison",
                "classification": d["classification"],
                "setr_facet_recall": float(
                    s["setr_zeroshot"]["facet_recall"]
                ),
                "setr_full_facet": bool(
                    s["setr_zeroshot"]["full_facet_coverage"]
                ),
                "setr_k": int(s["setr_zeroshot"]["k"]),
                "facet_count": len(f.get("facets", [])),
                "requirement_count": len(s.get("requirements", [])),
            }
        )

    by_type: Dict[str, List[Dict]] = defaultdict(list)
    by_facet_count: Dict[int, List[Dict]] = defaultdict(list)
    by_req_count: Dict[int, List[Dict]] = defaultdict(list)

    for x in rows:
        by_type[x["type"]].append(x)
        by_facet_count[x["facet_count"]].append(x)
        by_req_count[x["requirement_count"]].append(x)

    type_summary = {
        key: summarize_group(by_type[key])
        for key in sorted(by_type)
    }
    facet_summary = {
        str(key): summarize_group(by_facet_count[key])
        for key in sorted(by_facet_count)
    }
    req_summary = {
        str(key): summarize_group(by_req_count[key])
        for key in sorted(by_req_count)
    }

    comparison_rows = [x for x in rows if x["is_comparison"]]
    noncomparison_rows = [x for x in rows if not x["is_comparison"]]

    comp = summarize_group(comparison_rows)
    noncomp = summarize_group(noncomparison_rows)

    a = comp["failures"]
    b = comp["n"] - comp["failures"]
    c = noncomp["failures"]
    d = noncomp["n"] - noncomp["failures"]

    fisher_p = fisher_two_sided(a, b, c, d)

    risk_ratio = None
    if comp["n"] and noncomp["n"]:
        r1 = a / comp["n"]
        r0 = c / noncomp["n"]
        if r0 > 0:
            risk_ratio = r1 / r0
        elif r1 > 0:
            risk_ratio = float("inf")

    print("===== SETR FAILURE STRATA V2.4 =====")
    print("queries =", len(rows))
    print("failures =", sum(x["classification"] != "solved" for x in rows))
    print()

    print("===== BY QUESTION TYPE =====")
    for key, s in type_summary.items():
        print(
            f"{key}: "
            f"n={s['n']} "
            f"fail={s['failures']} "
            f"rate={s['failure_rate']} "
            f"selector={s.get('selector_limited', 0)} "
            f"retrieval={s.get('retrieval_limited', 0)} "
            f"Facet={s.get('mean_setr_facet_recall')} "
            f"Full={s.get('setr_full_facet_rate')} "
            f"AvgK={s.get('mean_setr_k')} "
            f"failure_ids={s.get('failure_ids')}"
        )

    print()
    print("===== COMPARISON VS NON-COMPARISON =====")
    print(
        "comparison:",
        f"n={comp['n']}",
        f"fail={comp['failures']}",
        f"rate={comp['failure_rate']}",
        f"failure_ids={comp['failure_ids']}",
    )
    print(
        "non_comparison:",
        f"n={noncomp['n']}",
        f"fail={noncomp['failures']}",
        f"rate={noncomp['failure_rate']}",
        f"failure_ids={noncomp['failure_ids']}",
    )
    print(
        "2x2 =",
        [[a, b], [c, d]],
        "(rows: comparison/non-comparison; cols: fail/solved)",
    )
    print("fisher_exact_two_sided_p =", round(fisher_p, 6))
    print(
        "failure_risk_ratio =",
        "inf" if risk_ratio == float("inf")
        else (round(risk_ratio, 4) if risk_ratio is not None else None),
    )

    print()
    print("===== BY GOLD FACET COUNT =====")
    for key, s in facet_summary.items():
        print(
            f"facets={key}: "
            f"n={s['n']} fail={s['failures']} "
            f"rate={s['failure_rate']} "
            f"failure_ids={s.get('failure_ids')}"
        )

    print()
    print("===== BY SETR REQUIREMENT COUNT =====")
    for key, s in req_summary.items():
        print(
            f"requirements={key}: "
            f"n={s['n']} fail={s['failures']} "
            f"rate={s['failure_rate']} "
            f"failure_ids={s.get('failure_ids')}"
        )

    output = {
        "summary": {
            "query_count": len(rows),
            "failure_count": sum(
                x["classification"] != "solved" for x in rows
            ),
        },
        "by_question_type": type_summary,
        "comparison_vs_noncomparison": {
            "comparison": comp,
            "noncomparison": noncomp,
            "contingency_table": [[a, b], [c, d]],
            "fisher_exact_two_sided_p": fisher_p,
            "failure_risk_ratio": risk_ratio,
            "note": (
                "Exploratory Dev-set diagnostic only; not a held-out "
                "hypothesis test."
            ),
        },
        "by_gold_facet_count": facet_summary,
        "by_setr_requirement_count": req_summary,
        "per_query": rows,
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(output, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print()
    print("output:", args.output)


if __name__ == "__main__":
    main()
