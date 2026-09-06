"""Paired analysis for adaptive evidence budget v1.9.

Input:
    tests/results/adaptive_budget_v17_full_facets.json

No API calls. No data modification.

Compares:
    adaptive_prefix vs dense@3
    need_anchor_set vs dense@2
    need_anchor_set vs dense@3
    adaptive_prefix vs need_anchor_set

Reports:
- AvgK difference
- mean FacetRecall difference
- FullFacet win/tie/loss
- PrimaryHit win/tie/loss on primary-eligible questions
- GoldRecall difference
- per-query win/loss IDs
- paired bootstrap 95% CI for mean FacetRecall difference
- paired bootstrap 95% CI for mean K difference

Run:
    python3 tests/analyze_adaptive_budget_v19.py
"""
from __future__ import annotations

import argparse
import json
import random
from pathlib import Path
from typing import Dict, List, Tuple

PROJECT_ROOT = Path(__file__).resolve().parents[1]

DEFAULT_INPUT = (
    PROJECT_ROOT
    / "tests"
    / "results"
    / "adaptive_budget_v17_full_facets.json"
)
DEFAULT_OUTPUT = (
    PROJECT_ROOT
    / "tests"
    / "results"
    / "adaptive_budget_v19_paired.json"
)

BOOTSTRAP_N = 20000
SEED = 20260902


def percentile(xs: List[float], p: float) -> float:
    if not xs:
        return 0.0
    ys = sorted(xs)
    if len(ys) == 1:
        return ys[0]
    pos = (len(ys) - 1) * p
    lo = int(pos)
    hi = min(lo + 1, len(ys) - 1)
    frac = pos - lo
    return ys[lo] * (1 - frac) + ys[hi] * frac


def bootstrap_ci(
    diffs: List[float],
    n: int = BOOTSTRAP_N,
    seed: int = SEED,
) -> Tuple[float, float]:
    rng = random.Random(seed)
    m = len(diffs)
    means = []
    for _ in range(n):
        s = 0.0
        for _ in range(m):
            s += diffs[rng.randrange(m)]
        means.append(s / m)
    return percentile(means, 0.025), percentile(means, 0.975)


def cmp_numeric(a: float, b: float, eps: float = 1e-9) -> str:
    if a > b + eps:
        return "win"
    if a < b - eps:
        return "loss"
    return "tie"


def cmp_bool(a, b) -> str:
    if a is None or b is None:
        return "na"
    if bool(a) and not bool(b):
        return "win"
    if not bool(a) and bool(b):
        return "loss"
    return "tie"


def paired_compare(
    rows: List[Dict],
    method: str,
    baseline: str,
) -> Dict:
    facet_diffs = []
    k_diffs = []
    gold_diffs = []

    facet_counts = {"win": 0, "tie": 0, "loss": 0}
    full_counts = {"win": 0, "tie": 0, "loss": 0}
    primary_counts = {"win": 0, "tie": 0, "loss": 0}

    facet_win_ids = []
    facet_loss_ids = []
    full_win_ids = []
    full_loss_ids = []
    primary_win_ids = []
    primary_loss_ids = []

    per_query = []

    for row in rows:
        qid = row["id"]
        a = row["methods"][method]
        b = row["methods"][baseline]

        af = float(a["facet_recall"])
        bf = float(b["facet_recall"])
        ak = float(a["k"])
        bk = float(b["k"])
        ag = float(a["gold_recall"])
        bg = float(b["gold_recall"])

        facet_diffs.append(af - bf)
        k_diffs.append(ak - bk)
        gold_diffs.append(ag - bg)

        fc = cmp_numeric(af, bf)
        facet_counts[fc] += 1
        if fc == "win":
            facet_win_ids.append(qid)
        elif fc == "loss":
            facet_loss_ids.append(qid)

        fullc = cmp_bool(
            a["full_facet_coverage"],
            b["full_facet_coverage"],
        )
        full_counts[fullc] += 1
        if fullc == "win":
            full_win_ids.append(qid)
        elif fullc == "loss":
            full_loss_ids.append(qid)

        pc = "na"
        if a["has_primary_gold"] and b["has_primary_gold"]:
            pc = cmp_bool(a["primary_hit"], b["primary_hit"])
            primary_counts[pc] += 1
            if pc == "win":
                primary_win_ids.append(qid)
            elif pc == "loss":
                primary_loss_ids.append(qid)

        per_query.append(
            {
                "id": qid,
                "facet_diff": round(af - bf, 4),
                "k_diff": round(ak - bk, 4),
                "gold_recall_diff": round(ag - bg, 4),
                "facet_outcome": fc,
                "full_facet_outcome": fullc,
                "primary_outcome": pc,
            }
        )

    facet_ci = bootstrap_ci(facet_diffs, seed=SEED)
    k_ci = bootstrap_ci(k_diffs, seed=SEED + 1)

    return {
        "method": method,
        "baseline": baseline,
        "query_count": len(rows),
        "mean_facet_recall_diff": round(
            sum(facet_diffs) / len(facet_diffs), 4
        ),
        "facet_recall_diff_bootstrap_95ci": [
            round(facet_ci[0], 4),
            round(facet_ci[1], 4),
        ],
        "facet_win_tie_loss": facet_counts,
        "facet_win_ids": facet_win_ids,
        "facet_loss_ids": facet_loss_ids,
        "full_facet_win_tie_loss": full_counts,
        "full_facet_win_ids": full_win_ids,
        "full_facet_loss_ids": full_loss_ids,
        "primary_win_tie_loss": primary_counts,
        "primary_win_ids": primary_win_ids,
        "primary_loss_ids": primary_loss_ids,
        "mean_k_diff": round(
            sum(k_diffs) / len(k_diffs), 4
        ),
        "k_diff_bootstrap_95ci": [
            round(k_ci[0], 4),
            round(k_ci[1], 4),
        ],
        "mean_gold_recall_diff": round(
            sum(gold_diffs) / len(gold_diffs), 4
        ),
        "per_query": per_query,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    ap.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = ap.parse_args()

    data = json.loads(args.input.read_text(encoding="utf-8"))
    rows = data["per_query"]

    comparisons = [
        ("adaptive_prefix", "dense@3"),
        ("need_anchor_set", "dense@2"),
        ("need_anchor_set", "dense@3"),
        ("adaptive_prefix", "need_anchor_set"),
    ]

    results = {}

    for method, baseline in comparisons:
        key = f"{method}_vs_{baseline}"
        r = paired_compare(rows, method, baseline)
        results[key] = r

        print("\n" + "=" * 80)
        print(f"{method} vs {baseline}")
        print(
            "FacetRecall diff =",
            r["mean_facet_recall_diff"],
            "95% CI =",
            r["facet_recall_diff_bootstrap_95ci"],
        )
        print(
            "Facet W/T/L =",
            r["facet_win_tie_loss"],
        )
        print(
            "FullFacet W/T/L =",
            r["full_facet_win_tie_loss"],
        )
        print(
            "Primary W/T/L =",
            r["primary_win_tie_loss"],
        )
        print(
            "AvgK diff =",
            r["mean_k_diff"],
            "95% CI =",
            r["k_diff_bootstrap_95ci"],
        )
        print(
            "GoldRecall diff =",
            r["mean_gold_recall_diff"],
        )
        print("Facet wins:", r["facet_win_ids"])
        print("Facet losses:", r["facet_loss_ids"])
        print("FullFacet wins:", r["full_facet_win_ids"])
        print("FullFacet losses:", r["full_facet_loss_ids"])
        print("Primary losses:", r["primary_loss_ids"])

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(
            {
                "bootstrap_n": BOOTSTRAP_N,
                "seed": SEED,
                "comparisons": results,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print("\n===== ADAPTIVE BUDGET PAIRED ANALYSIS V1.9 =====")
    print("output =", args.output)


if __name__ == "__main__":
    main()
