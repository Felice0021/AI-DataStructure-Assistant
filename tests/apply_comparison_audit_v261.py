"""Apply conservative comparison-gold audit decisions v2.6.1.

This script does NOT alter retrieval_pool_v1.csv or benchmark questions.
It writes a new facet file and preserves the previous reviewed file.

Clear audit decisions applied:
- q011: "both are restricted linear lists" is auxiliary, not a core difference.
- q023: fast-transpose mechanism is not required by a question asking only
        for time complexities; keep only the complexity statement as core.
- q038: B+ leaf linking/range traversal is auxiliary to a question explicitly
        scoped to "record-information storage"; remove f4 from FullFacet core.

Ambiguous broad-scope questions are NOT silently changed:
- q039 ("各有什么特点")
- q048 ("相比有什么不同")
They retain current reference-defined core facets, but receive audit metadata
warning that exhaustive completeness is scope-sensitive.

Output:
tests/annotations/datastructureqa_dev_v182_comparison_audited.jsonl

Run:
python3 tests/apply_comparison_audit_v261.py
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List

PROJECT_ROOT = Path(__file__).resolve().parents[1]

INPUT = (
    PROJECT_ROOT
    / "tests"
    / "annotations"
    / "datastructureqa_dev_v18_facets_reviewed.jsonl"
)
OUTPUT = (
    PROJECT_ROOT
    / "tests"
    / "annotations"
    / "datastructureqa_dev_v182_comparison_audited.jsonl"
)


def load_jsonl(path: Path) -> List[Dict]:
    rows = []
    with path.open("r", encoding="utf-8") as f:
        for raw in f:
            if raw.strip():
                rows.append(json.loads(raw))
    return rows


def facet_id(item, idx: int) -> str:
    if isinstance(item, dict):
        return str(item.get("facet_id") or f"f{idx}")
    return f"f{idx}"


def facet_text(item) -> str:
    if isinstance(item, str):
        return item.strip()
    if isinstance(item, dict):
        return str(
            item.get("description")
            or item.get("text")
            or item.get("facet")
            or item.get("content")
            or ""
        ).strip()
    return str(item).strip()


def canonical_facet(fid: str, text: str) -> Dict:
    return {"facet_id": fid, "description": text}


def remove_core_facet(row: Dict, fid_to_remove: str, reason: str) -> None:
    facets = row.get("facets", [])
    new_facets = []
    removed = None

    for i, item in enumerate(facets, 1):
        fid = facet_id(item, i)
        text = facet_text(item)
        if fid == fid_to_remove:
            removed = canonical_facet(fid, text)
        else:
            new_facets.append(canonical_facet(fid, text))

    if removed is None:
        raise RuntimeError(
            f"{row['id']}: core facet {fid_to_remove} not found"
        )

    row["facets"] = new_facets

    # Preserve the information as auxiliary evaluation metadata.
    aux = row.setdefault("auxiliary_facets", [])
    aux.append(
        {
            **removed,
            "audit_reason": reason,
        }
    )

    aux_support = row.setdefault("auxiliary_chunk_support", {})

    support = row.get("chunk_support", {})
    for cid, fids in list(support.items()):
        if not isinstance(fids, list):
            continue
        if fid_to_remove in fids:
            aux_support.setdefault(cid, [])
            if fid_to_remove not in aux_support[cid]:
                aux_support[cid].append(fid_to_remove)
        support[cid] = [
            fid for fid in fids
            if fid != fid_to_remove
        ]

    row["chunk_support"] = support


def rewrite_core_facet(row: Dict, fid_target: str, new_text: str) -> None:
    facets = row.get("facets", [])
    rewritten = False
    new_facets = []

    for i, item in enumerate(facets, 1):
        fid = facet_id(item, i)
        text = facet_text(item)
        if fid == fid_target:
            text = new_text
            rewritten = True
        new_facets.append(canonical_facet(fid, text))

    if not rewritten:
        raise RuntimeError(
            f"{row['id']}: facet {fid_target} not found for rewrite"
        )

    row["facets"] = new_facets


def validate(rows: List[Dict]) -> List[Dict]:
    warnings = []

    for row in rows:
        qid = row["id"]
        facets = row.get("facets", [])

        ids = []
        for i, item in enumerate(facets, 1):
            fid = facet_id(item, i)
            text = facet_text(item)

            if not text:
                warnings.append(
                    {
                        "id": qid,
                        "type": "empty_facet_text",
                        "facet_id": fid,
                    }
                )
            ids.append(fid)

        if len(ids) != len(set(ids)):
            warnings.append(
                {
                    "id": qid,
                    "type": "duplicate_facet_ids",
                    "facet_ids": ids,
                }
            )

        valid = set(ids)
        for cid, fids in row.get("chunk_support", {}).items():
            unknown = [
                fid for fid in fids
                if fid not in valid
            ]
            if unknown:
                warnings.append(
                    {
                        "id": qid,
                        "type": "unknown_core_mapping",
                        "chunk_id": cid,
                        "unknown": unknown,
                    }
                )

    return warnings


def main() -> None:
    if not INPUT.exists():
        raise SystemExit(f"ERROR missing input: {INPUT}")

    rows = load_jsonl(INPUT)
    by_id = {x["id"]: x for x in rows}

    # q011: shared commonality is useful context but not a "主要区别".
    remove_core_facet(
        by_id["q011"],
        "f3",
        (
            "Question asks for the main differences between stack and queue. "
            "Their shared status as restricted linear lists is useful context "
            "but not required to establish the difference."
        ),
    )

    # q023: the query asks only for two complexities.
    rewrite_core_facet(
        by_id["q023"],
        "f2",
        (
            "稀疏矩阵快速转置算法的时间复杂度为 O(n+t)，"
            "其中 n 为列数，t 为非零元个数。"
        ),
    )

    # q038: leaf linking/range traversal is outside the explicit scope
    # "在存储记录信息上".
    remove_core_facet(
        by_id["q038"],
        "f4",
        (
            "Question is explicitly scoped to the core difference in "
            "record-information storage. Leaf-node linking/range traversal "
            "is a useful B+ tree property but not required for FullFacet."
        ),
    )

    # Preserve ambiguity rather than tuning the gold to current failures.
    by_id["q039"]["comparison_scope_audit"] = {
        "status": "broad_scope_retained",
        "note": (
            "The wording '各有什么特点' is open-ended. Current core facets "
            "remain reference-answer-defined for this Dev benchmark, but "
            "FullFacet should not be interpreted as the unique exhaustive "
            "set of all valid characteristics."
        ),
    }

    by_id["q048"]["comparison_scope_audit"] = {
        "status": "broad_scope_retained",
        "note": (
            "The wording '相比有什么不同' is broad. f2 (fewer initial runs "
            "under the same memory budget) is retained because it appears in "
            "the frozen reference answer, but its status as universally "
            "mandatory should be made explicit in future held-out questions."
        ),
    }

    # Record provenance on all comparison-audited rows that changed.
    for qid in ("q011", "q023", "q038", "q039", "q048"):
        by_id[qid]["comparison_audit_version"] = "v2.6.1"

    # Preserve input order.
    output_rows = [by_id[x["id"]] for x in rows]

    warnings = validate(output_rows)

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open("w", encoding="utf-8") as f:
        for row in output_rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    print("===== COMPARISON AUDIT PATCH V2.6.1 =====")
    print("input =", INPUT)
    print("output =", OUTPUT)
    print("clear_core_changes = ['q011:f3->aux', 'q023:f2_rewrite', 'q038:f4->aux']")
    print("scope_ambiguous_retained = ['q039', 'q048']")
    print("validation_warnings =", len(warnings))
    if warnings:
        for w in warnings:
            print(" ", w)


if __name__ == "__main__":
    main()
