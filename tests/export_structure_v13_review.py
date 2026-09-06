"""Export only the unjudged candidates produced by structure diagnostic v1.3.

Run:
    python3 tests/export_structure_v13_review.py

Output:
    tests/annotations/structure_v13_unjudged_review.csv

Human labels:
    0 = unrelated / not useful for answering the question
    1 = useful partial/background evidence, not sufficient alone
    2 = sufficient evidence by itself for the reference answer

Do not change method code until these pairs are adjudicated.
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

DEFAULT_DIAGNOSTIC = (
    PROJECT_ROOT
    / "tests"
    / "results"
    / "structure_expansion_diagnostic_v13.json"
)
DEFAULT_BENCHMARK = (
    PROJECT_ROOT
    / "tests"
    / "benchmarks"
    / "datastructureqa_dev_v1.jsonl"
)
DEFAULT_OUTPUT = (
    PROJECT_ROOT
    / "tests"
    / "annotations"
    / "structure_v13_unjudged_review.csv"
)


def load_jsonl(path: Path):
    out = {}
    with path.open("r", encoding="utf-8") as f:
        for raw in f:
            if not raw.strip():
                continue
            obj = json.loads(raw)
            out[obj["id"]] = obj
    return out


def main() -> None:
    diagnostic = json.loads(
        DEFAULT_DIAGNOSTIC.read_text(encoding="utf-8")
    )
    benchmark = load_jsonl(DEFAULT_BENCHMARK)

    rows = []

    for q in diagnostic["per_query"]:
        qid = q["id"]
        b = benchmark[qid]

        for cand in q["new_candidates"]:
            if cand.get("judged"):
                continue

            rows.append(
                {
                    "question_id": qid,
                    "question": q["question"],
                    "reference_answer": b.get("reference_answer", ""),
                    "chunk_id": cand["chunk_id"],
                    "chapter": cand.get("chapter", ""),
                    "section": cand.get("section", ""),
                    "source_file": cand.get("source_file", ""),
                    "chunk_text": cand.get("text", ""),
                    "seed_chunk_id": cand.get("seed_chunk_id", ""),
                    "relation": cand.get("relation", ""),
                    "relevance_label": "",
                    "annotation_note": "",
                }
            )

    DEFAULT_OUTPUT.parent.mkdir(parents=True, exist_ok=True)

    fields = [
        "question_id",
        "question",
        "reference_answer",
        "chunk_id",
        "chapter",
        "section",
        "source_file",
        "chunk_text",
        "seed_chunk_id",
        "relation",
        "relevance_label",
        "annotation_note",
    ]

    with DEFAULT_OUTPUT.open(
        "w",
        encoding="utf-8-sig",
        newline="",
    ) as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    print("===== STRUCTURE V1.3 REVIEW EXPORT =====")
    print("pairs =", len(rows))
    print(
        "questions =",
        len({r["question_id"] for r in rows}),
    )
    print("output =", DEFAULT_OUTPUT)

    print("\nPairs by question:")
    counts = {}
    for r in rows:
        counts[r["question_id"]] = (
            counts.get(r["question_id"], 0) + 1
        )
    for qid in sorted(counts):
        print(f"{qid}: {counts[qid]}")


if __name__ == "__main__":
    main()
