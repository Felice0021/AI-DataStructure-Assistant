"""Merge adjudicated Structure v1.3 review rows into retrieval_pool_v1.csv.

Safety:
- creates a .before_structure_v13_review.bak backup once
- never overwrites an existing judged pair
- verifies all review labels are 0/1/2
- preserves the retrieval_pool_v1.csv column schema
- appends only genuinely new (question_id, chunk_id) pairs

Run:
    python3 tests/merge_structure_v13_review.py
"""
from __future__ import annotations

import csv
import shutil
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

POOL = PROJECT_ROOT / "tests" / "retrieval_pool_v1.csv"
REVIEW = (
    PROJECT_ROOT
    / "tests"
    / "annotations"
    / "structure_v13_unjudged_review.csv"
)
BACKUP = POOL.with_suffix(
    POOL.suffix + ".before_structure_v13_review.bak"
)


def read_csv(path: Path):
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        fields = list(reader.fieldnames or [])
    return fields, rows


def main() -> None:
    if not POOL.exists():
        raise SystemExit(f"ERROR: missing pool: {POOL}")
    if not REVIEW.exists():
        raise SystemExit(f"ERROR: missing review: {REVIEW}")

    pool_fields, pool_rows = read_csv(POOL)
    _, review_rows = read_csv(REVIEW)

    if not pool_fields:
        raise SystemExit("ERROR: retrieval pool has no header")

    required_pool = {
        "question_id",
        "question",
        "reference_answer",
        "chunk_id",
        "chapter",
        "section",
        "content_type",
        "source_file",
        "chunk_text",
        "current_gold",
        "bm25_rank",
        "bm25_score",
        "dense_rank",
        "dense_score",
        "relevance_label",
        "annotation_note",
    }
    missing = sorted(required_pool - set(pool_fields))
    if missing:
        raise SystemExit(
            f"ERROR: pool missing required columns: {missing}"
        )

    existing = {
        (r["question_id"], r["chunk_id"]): r
        for r in pool_rows
    }

    review_keys = set()
    for r in review_rows:
        key = (r["question_id"], r["chunk_id"])

        if key in review_keys:
            raise SystemExit(f"ERROR: duplicate review pair: {key}")
        review_keys.add(key)

        label = str(r.get("relevance_label", "")).strip()
        if label not in {"0", "1", "2"}:
            raise SystemExit(
                f"ERROR: invalid relevance_label={label!r} for {key}"
            )

        if key in existing:
            old_label = str(
                existing[key].get("relevance_label", "")
            ).strip()
            raise SystemExit(
                f"ERROR: pair already exists in pool: {key}, "
                f"existing label={old_label!r}. No merge performed."
            )

    if not BACKUP.exists():
        shutil.copy2(POOL, BACKUP)
        print("backup:", BACKUP)
    else:
        print("backup already exists:", BACKUP)

    new_rows = []

    for r in review_rows:
        out = {field: "" for field in pool_fields}

        for field in (
            "question_id",
            "question",
            "reference_answer",
            "chunk_id",
            "chapter",
            "section",
            "content_type",
            "source_file",
            "chunk_text",
            "relevance_label",
            "annotation_note",
        ):
            if field in out:
                out[field] = r.get(field, "")

        out["bm25_rank"] = ""
        out["bm25_score"] = ""
        out["dense_rank"] = ""
        out["dense_score"] = ""
        out["current_gold"] = "False"

        new_rows.append(out)

    merged = pool_rows + new_rows

    with POOL.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=pool_fields,
            extrasaction="ignore",
        )
        writer.writeheader()
        writer.writerows(merged)

    counts = {0: 0, 1: 0, 2: 0}
    for r in review_rows:
        counts[int(r["relevance_label"])] += 1

    print("===== STRUCTURE V1.3 REVIEW MERGE =====")
    print("pool_rows_before =", len(pool_rows))
    print("rows_appended =", len(new_rows))
    print("pool_rows_after =", len(merged))
    print("review_labels =", counts)
    print("pool =", POOL)


if __name__ == "__main__":
    main()
