"""Inspect Facet Bootstrap v1.8 warnings and audit-risk cases.

No API calls. No data modification.

Outputs
-------
tests/annotations/facet_v18_review.md
tests/annotations/facet_v18_review_summary.json

Run
---
python3 tests/inspect_facet_warnings_v181.py
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Dict, List

PROJECT_ROOT = Path(__file__).resolve().parents[1]

DEFAULT_BENCHMARK = (
    PROJECT_ROOT / "tests" / "benchmarks" / "datastructureqa_dev_v1.jsonl"
)
DEFAULT_POOL = PROJECT_ROOT / "tests" / "retrieval_pool_v1.csv"
DEFAULT_DRAFT = (
    PROJECT_ROOT
    / "tests"
    / "annotations"
    / "datastructureqa_dev_v18_facets_draft.jsonl"
)
DEFAULT_REPORT = (
    PROJECT_ROOT
    / "tests"
    / "annotations"
    / "datastructureqa_dev_v18_facets_report.json"
)
DEFAULT_MD = (
    PROJECT_ROOT
    / "tests"
    / "annotations"
    / "facet_v18_review.md"
)
DEFAULT_SUMMARY = (
    PROJECT_ROOT
    / "tests"
    / "annotations"
    / "facet_v18_review_summary.json"
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


def compact_warning(w: Dict) -> str:
    t = w["type"]
    if t == "label2_not_cover_all_facets":
        return (
            f"{t}: {w['chunk_id']} mapped={w.get('mapped')} "
            f"expected={w.get('expected')}"
        )
    if t == "facet_without_support":
        return f"{t}: {w['facet_id']}"
    if t == "label1_maps_all_facets":
        return f"{t}: {w['chunk_id']}"
    return json.dumps(w, ensure_ascii=False)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--benchmark", type=Path, default=DEFAULT_BENCHMARK)
    ap.add_argument("--pool", type=Path, default=DEFAULT_POOL)
    ap.add_argument("--draft", type=Path, default=DEFAULT_DRAFT)
    ap.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    ap.add_argument("--output", type=Path, default=DEFAULT_MD)
    ap.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY)
    args = ap.parse_args()

    benchmark = load_jsonl(args.benchmark)
    drafts = load_jsonl(args.draft)
    pool = load_pool(args.pool)
    report = json.loads(args.report.read_text(encoding="utf-8"))

    warning_qids = {
        x["question_id"]
        for x in report.get("warnings", [])
    }

    # Extra audit flags even when schema validation emitted no warning.
    audit_flags: Dict[str, List[str]] = {}

    for qid, row in drafts.items():
        if row.get("annotation_source") != "llm_bootstrap_v18":
            continue

        facet_count = len(row.get("facets", []))
        gold_ids = benchmark[qid].get("gold_chunk_ids", [])
        relevant_count = len(gold_ids)

        flags = []

        if facet_count >= 4:
            flags.append(f"many_facets={facet_count}")

        if relevant_count == 1 and facet_count >= 3:
            flags.append(
                f"single_relevant_chunk_but_facets={facet_count}"
            )

        support = row.get("chunk_support", {})
        facet_ids = {
            str(x["facet_id"])
            for x in row.get("facets", [])
        }

        nonempty_support_chunks = sum(
            bool(set(v) & facet_ids)
            for v in support.values()
        )
        if relevant_count >= 3 and nonempty_support_chunks <= 1:
            flags.append(
                "support_concentrated_in_at_most_one_chunk"
            )

        if flags:
            audit_flags[qid] = flags

    review_qids = sorted(warning_qids | set(audit_flags))

    warnings_by_qid: Dict[str, List[Dict]] = {}
    for w in report.get("warnings", []):
        warnings_by_qid.setdefault(
            w["question_id"], []
        ).append(w)

    lines = []
    lines.append("# Facet v1.8 Human Review")
    lines.append("")
    lines.append(
        "This file is for human review only. "
        "Do not use facets as retrieval/selection inputs."
    )
    lines.append("")
    lines.append(
        f"- warning questions: {len(warning_qids)}"
    )
    lines.append(
        f"- extra audit questions: "
        f"{len(set(audit_flags) - warning_qids)}"
    )
    lines.append(
        f"- total review questions: {len(review_qids)}"
    )
    lines.append("")

    summary = {
        "warning_question_ids": sorted(warning_qids),
        "audit_only_question_ids": sorted(
            set(audit_flags) - warning_qids
        ),
        "review_question_ids": review_qids,
        "per_question": {},
    }

    for qid in review_qids:
        q = benchmark[qid]
        row = drafts[qid]
        facets = row.get("facets", [])
        support = row.get("chunk_support", {})

        lines.append("---")
        lines.append("")
        lines.append(f"## {qid}")
        lines.append("")
        lines.append(f"**Question:** {q['question']}")
        lines.append("")
        lines.append(
            f"**Reference answer:** "
            f"{q.get('reference_answer', '')}"
        )
        lines.append("")

        ws = warnings_by_qid.get(qid, [])
        af = audit_flags.get(qid, [])

        if ws:
            lines.append("**Warnings:**")
            lines.append("")
            for w in ws:
                lines.append(
                    f"- `{compact_warning(w)}`"
                )
            lines.append("")

        if af:
            lines.append("**Audit flags:**")
            lines.append("")
            for x in af:
                lines.append(f"- `{x}`")
            lines.append("")

        lines.append("**Facets:**")
        lines.append("")
        for facet in facets:
            lines.append(
                f"- `{facet['facet_id']}` "
                f"{facet['description']}"
            )
        lines.append("")

        lines.append("**Relevant chunks and mappings:**")
        lines.append("")

        gold_ids = [
            str(x)
            for x in q.get("gold_chunk_ids", [])
        ]

        chunk_entries = []

        for cid in gold_ids:
            prow = pool[qid][cid]
            label = prow["relevance_label"]
            mapped = support.get(cid, [])

            lines.append(
                f"### `{cid}` — label={label}, "
                f"mapped={mapped}"
            )
            lines.append("")
            lines.append(
                prow["chunk_text"].strip()
            )
            lines.append("")

            chunk_entries.append(
                {
                    "chunk_id": cid,
                    "label": int(label),
                    "mapped_facets": mapped,
                    "chunk_text": prow["chunk_text"],
                }
            )

        lines.append("**Human decision:**")
        lines.append("")
        lines.append(
            "- [ ] facets correct as-is"
        )
        lines.append(
            "- [ ] facet descriptions need edit/merge/split"
        )
        lines.append(
            "- [ ] chunk→facet mappings need correction"
        )
        lines.append(
            "- [ ] relevance label needs reconsideration"
        )
        lines.append(
            "- Notes:"
        )
        lines.append("")

        summary["per_question"][qid] = {
            "warnings": ws,
            "audit_flags": af,
            "facets": facets,
            "chunks": chunk_entries,
        }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        "\n".join(lines),
        encoding="utf-8",
    )
    args.summary.write_text(
        json.dumps(
            summary,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print("===== FACET V1.8 REVIEW EXPORT =====")
    print("warning_questions =", len(warning_qids))
    print(
        "audit_only_questions =",
        len(set(audit_flags) - warning_qids),
    )
    print("review_questions =", len(review_qids))
    print(
        "warning_question_ids =",
        sorted(warning_qids),
    )
    print(
        "audit_only_question_ids =",
        sorted(set(audit_flags) - warning_qids),
    )
    print("output =", args.output)
    print("summary =", args.summary)


if __name__ == "__main__":
    main()
