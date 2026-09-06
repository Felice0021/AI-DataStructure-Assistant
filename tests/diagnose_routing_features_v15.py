"""Routing Feature Diagnostic v1.5

Goal
----
Analyze whether query-only / retrieval-time observable features differ among:
    structure_win
    deeper_dense_win
    tie

No LLM/API calls.
No gold labels are used to compute features.
Outcome labels from v1.4 are joined only AFTER feature extraction for analysis.

Inputs
------
tests/results/structure_expansion_diagnostic_v13.json
tests/results/structure_vs_deeper_dense_v14.json
.cache/rag/structure_v13_support.json
knowledge_base/ds_chunks.jsonl

Run
---
python3 tests/diagnose_routing_features_v15.py
"""
from __future__ import annotations

import argparse
import json
import math
import re
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Sequence

PROJECT_ROOT_FOR_IMPORT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT_FOR_IMPORT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT_FOR_IMPORT))

from rag.config import PROJECT_ROOT
from rag.retrievers import load_chunks_from_jsonl


DEFAULT_V13 = (
    PROJECT_ROOT
    / "tests"
    / "results"
    / "structure_expansion_diagnostic_v13.json"
)
DEFAULT_V14 = (
    PROJECT_ROOT
    / "tests"
    / "results"
    / "structure_vs_deeper_dense_v14.json"
)
DEFAULT_SUPPORT = (
    PROJECT_ROOT
    / ".cache"
    / "rag"
    / "structure_v13_support.json"
)
DEFAULT_KNOWLEDGE = (
    PROJECT_ROOT
    / "knowledge_base"
    / "ds_chunks.jsonl"
)
DEFAULT_OUTPUT = (
    PROJECT_ROOT
    / "tests"
    / "results"
    / "routing_features_v15.json"
)

CHUNK_ID_RE = re.compile(r"^(?P<prefix>.+?)_(?P<num>\d+)$")
SECTION_FAMILY_RE = re.compile(r"^\s*(\d+(?:\.\d+)*)")

SUPPORT_THRESHOLD = 2.0 / 3.0
STRONG_THRESHOLD = 0.999
LOW_MARGIN_THRESHOLD = 0.20
MAX_STRUCTURE_DISTANCE = 4


def load_json(path: Path) -> Dict:
    return json.loads(path.read_text(encoding="utf-8"))


def section_family(section: object) -> Optional[str]:
    s = str(section or "").strip()
    if not s:
        return None
    m = SECTION_FAMILY_RE.match(s)
    return m.group(1) if m else None


def chunk_ordinal(chunk_id: str) -> Optional[int]:
    m = CHUNK_ID_RE.match(chunk_id)
    return int(m.group("num")) if m else None


def same_nonempty(a: object, b: object) -> bool:
    sa = str(a or "").strip()
    sb = str(b or "").strip()
    return bool(sa and sb and sa == sb)


def structural_neighbors(
    anchor_id: str,
    dense_ids: Sequence[str],
    chunk_map: Dict[str, Dict],
    chunks: Sequence[Dict],
) -> List[str]:
    seed = chunk_map[anchor_id]
    sf = section_family(seed.get("section"))
    if not sf:
        return []

    a = chunk_ordinal(anchor_id)
    if a is None:
        return []

    dense_set = set(dense_ids)
    out = []

    for cand in chunks:
        cid = str(cand["chunk_id"])
        if cid == anchor_id or cid in dense_set:
            continue

        if not same_nonempty(
            seed.get("source_file"),
            cand.get("source_file"),
        ):
            continue
        if not same_nonempty(
            seed.get("chapter"),
            cand.get("chapter"),
        ):
            continue

        cf = section_family(cand.get("section"))
        if cf != sf:
            continue

        b = chunk_ordinal(cid)
        if b is None:
            continue

        dist = abs(a - b)
        if 1 <= dist <= MAX_STRUCTURE_DISTANCE:
            out.append(cid)

    return sorted(set(out))


def mean(xs: Sequence[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def safe_stdev(xs: Sequence[float]) -> float:
    return statistics.pstdev(xs) if len(xs) > 1 else 0.0


def group_summary(rows: List[Dict], feature_names: List[str]) -> Dict:
    grouped = defaultdict(list)
    for row in rows:
        grouped[row["outcome"]].append(row)

    result = {}
    for outcome in ("structure_win", "deeper_dense_win", "tie"):
        group = grouped.get(outcome, [])
        stats = {"count": len(group)}

        for feature in feature_names:
            vals = [
                float(x["features"][feature])
                for x in group
            ]
            stats[feature] = {
                "mean": round(mean(vals), 4),
                "min": round(min(vals), 4) if vals else None,
                "max": round(max(vals), 4) if vals else None,
            }

        result[outcome] = stats

    return result


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--v13", type=Path, default=DEFAULT_V13)
    ap.add_argument("--v14", type=Path, default=DEFAULT_V14)
    ap.add_argument("--support", type=Path, default=DEFAULT_SUPPORT)
    ap.add_argument("--knowledge", type=Path, default=DEFAULT_KNOWLEDGE)
    ap.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = ap.parse_args()

    v13 = load_json(args.v13)
    v14 = load_json(args.v14)
    support_cache = load_json(args.support)

    chunks = load_chunks_from_jsonl(args.knowledge)
    chunk_map = {
        str(x["chunk_id"]): x
        for x in chunks
    }

    v14_by_id = {
        x["id"]: x
        for x in v14["per_query"]
    }

    rows = []

    for q in v13["per_query"]:
        qid = q["id"]
        if qid not in v14_by_id:
            raise RuntimeError(f"{qid}: missing v1.4 outcome")
        if qid not in support_cache:
            raise RuntimeError(f"{qid}: missing support cache")

        # -------------------------------------------------------------
        # FEATURE EXTRACTION BELOW USES NO GOLD / OUTCOME.
        # -------------------------------------------------------------
        needs = list(q["needs"])
        dense_ids = list(q["dense_ids"])
        anchor_details = list(q["anchor_details"])

        cache_item = support_cache[qid]
        support = cache_item["matrix"]

        if len(support) != len(needs):
            raise RuntimeError(
                f"{qid}: support rows={len(support)}, needs={len(needs)}"
            )

        best_supports = []
        second_supports = []
        margins = []
        zero_candidate_need_count = 0
        below_threshold_need_count = 0
        partial_need_count = 0
        strong_need_count = 0
        low_margin_need_count = 0

        for row in support:
            vals = sorted(
                [float(v) for v in row],
                reverse=True,
            )
            best = vals[0] if vals else 0.0
            second = vals[1] if len(vals) > 1 else 0.0
            margin = best - second

            best_supports.append(best)
            second_supports.append(second)
            margins.append(margin)

            if best <= 1e-9:
                zero_candidate_need_count += 1
            if best + 1e-6 < SUPPORT_THRESHOLD:
                below_threshold_need_count += 1
            elif best + 1e-6 < STRONG_THRESHOLD:
                partial_need_count += 1
            else:
                strong_need_count += 1

            if margin < LOW_MARGIN_THRESHOLD:
                low_margin_need_count += 1

        anchor_ids = []
        anchor_ranks = []
        fallback_count = 0

        for d in anchor_details:
            cid = str(d["anchor_chunk_id"])
            if cid not in anchor_ids:
                anchor_ids.append(cid)
            anchor_ranks.append(float(d["dense_rank"]))
            if d.get("fallback"):
                fallback_count += 1

        anchor_collision_count = max(
            0,
            len(needs) - len(anchor_ids),
        )

        family_neighbor_union = set()
        expandable_anchor_count = 0
        anchor_neighbor_counts = {}

        for cid in anchor_ids:
            neighbors = structural_neighbors(
                cid,
                dense_ids,
                chunk_map,
                chunks,
            )
            anchor_neighbor_counts[cid] = len(neighbors)
            if neighbors:
                expandable_anchor_count += 1
                family_neighbor_union.update(neighbors)

        # Query-only conceptual routing signals.
        semantic_gap_need_count = below_threshold_need_count
        structure_opportunity = int(expandable_anchor_count > 0)

        if semantic_gap_need_count > 0 and structure_opportunity:
            route_signal = "both"
        elif semantic_gap_need_count > 0:
            route_signal = "semantic"
        elif structure_opportunity:
            route_signal = "structure"
        else:
            route_signal = "none"

        features = {
            "need_count": len(needs),
            "unique_anchor_count": len(anchor_ids),
            "anchor_collision_count": anchor_collision_count,
            "fallback_need_count": fallback_count,
            "zero_candidate_need_count": zero_candidate_need_count,
            "below_threshold_need_count": below_threshold_need_count,
            "partial_need_count": partial_need_count,
            "strong_need_count": strong_need_count,
            "mean_best_support": mean(best_supports),
            "min_best_support": min(best_supports) if best_supports else 0.0,
            "mean_support_margin": mean(margins),
            "min_support_margin": min(margins) if margins else 0.0,
            "low_margin_need_count": low_margin_need_count,
            "mean_anchor_dense_rank": mean(anchor_ranks),
            "max_anchor_dense_rank": max(anchor_ranks) if anchor_ranks else 0.0,
            "expandable_anchor_count": expandable_anchor_count,
            "structural_neighbor_count": len(family_neighbor_union),
            "structure_opportunity": structure_opportunity,
            "semantic_gap_need_count": semantic_gap_need_count,
        }

        # -------------------------------------------------------------
        # OUTCOME JOIN HAPPENS ONLY AFTER FEATURE EXTRACTION.
        # -------------------------------------------------------------
        outcome_row = v14_by_id[qid]
        outcome = outcome_row["outcome"]

        rows.append(
            {
                "id": qid,
                "question": q["question"],
                "outcome": outcome,
                "route_signal": route_signal,
                "features": {
                    k: (
                        round(float(v), 4)
                        if isinstance(v, (float, int))
                        else v
                    )
                    for k, v in features.items()
                },
                "anchor_neighbor_counts": anchor_neighbor_counts,
                "dense_budget_recall": outcome_row[
                    "dense_budget_recall"
                ],
                "structure_recall": outcome_row[
                    "structure_recall"
                ],
            }
        )

    feature_names = [
        "need_count",
        "unique_anchor_count",
        "anchor_collision_count",
        "fallback_need_count",
        "zero_candidate_need_count",
        "below_threshold_need_count",
        "partial_need_count",
        "strong_need_count",
        "mean_best_support",
        "min_best_support",
        "mean_support_margin",
        "min_support_margin",
        "low_margin_need_count",
        "mean_anchor_dense_rank",
        "max_anchor_dense_rank",
        "expandable_anchor_count",
        "structural_neighbor_count",
    ]

    groups = group_summary(rows, feature_names)

    route_outcome = defaultdict(Counter)
    for row in rows:
        route_outcome[row["route_signal"]][row["outcome"]] += 1

    route_outcome_json = {
        route: dict(counter)
        for route, counter in route_outcome.items()
    }

    # Print compact per-query table.
    print(
        "qid\toutcome\troute\tneeds\tanchors\tfallback\t"
        "gap\tstrong\tbest_min\tmargin_mean\tanchor_rank_mean\t"
        "expandable\tneighbors"
    )

    for row in rows:
        f = row["features"]
        print(
            f"{row['id']}\t"
            f"{row['outcome']}\t"
            f"{row['route_signal']}\t"
            f"{f['need_count']}\t"
            f"{f['unique_anchor_count']}\t"
            f"{f['fallback_need_count']}\t"
            f"{f['below_threshold_need_count']}\t"
            f"{f['strong_need_count']}\t"
            f"{f['min_best_support']}\t"
            f"{f['mean_support_margin']}\t"
            f"{f['mean_anchor_dense_rank']}\t"
            f"{f['expandable_anchor_count']}\t"
            f"{f['structural_neighbor_count']}"
        )

    print("\n===== GROUP MEANS =====")
    for outcome in ("structure_win", "deeper_dense_win", "tie"):
        g = groups[outcome]
        print(f"\n[{outcome}] n={g['count']}")
        for feature in feature_names:
            x = g[feature]
            print(
                f"{feature}: "
                f"mean={x['mean']} "
                f"range=[{x['min']},{x['max']}]"
            )

    print("\n===== QUERY-ONLY ROUTE SIGNAL VS OUTCOME =====")
    for route in ("semantic", "structure", "both", "none"):
        print(
            f"{route}: "
            f"{route_outcome_json.get(route, {})}"
        )

    # Report strongest descriptive separations only; no fitted classifier.
    print("\n===== DESCRIPTIVE CHECKS =====")

    for feature in (
        "below_threshold_need_count",
        "fallback_need_count",
        "mean_anchor_dense_rank",
        "structural_neighbor_count",
        "mean_support_margin",
    ):
        print(feature)
        for outcome in ("structure_win", "deeper_dense_win", "tie"):
            x = groups[outcome][feature]
            print(
                f"  {outcome}: mean={x['mean']} "
                f"range=[{x['min']},{x['max']}]"
            )

    output = {
        "config": {
            "support_threshold": SUPPORT_THRESHOLD,
            "strong_threshold": STRONG_THRESHOLD,
            "low_margin_threshold": LOW_MARGIN_THRESHOLD,
            "max_structure_distance": MAX_STRUCTURE_DISTANCE,
            "feature_extraction_uses_gold": False,
            "classifier_fitted": False,
        },
        "per_query": rows,
        "group_summary": groups,
        "route_signal_vs_outcome": route_outcome_json,
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
