"""Apply human review decisions for Facet v1.8 (v1.8.1).

This patch:
1. edits facet definitions/mappings for reviewed warning cases;
2. updates overly strong relevance labels in retrieval_pool_v1.csv;
3. adds q017/ds_ch04_0010 as a newly adjudicated label-1 evidence chunk;
4. marks the 17 inspected questions as human-reviewed;
5. writes a checked facet file for subsequent Dev diagnostics;
6. validates facet/pool consistency without calling any API.

Inputs
------
tests/annotations/datastructureqa_dev_v18_facets_draft.jsonl
tests/retrieval_pool_v1.csv
tests/benchmarks/datastructureqa_dev_v1.jsonl
knowledge_base/ds_chunks.jsonl

Outputs
-------
tests/annotations/datastructureqa_dev_v18_facets_reviewed.jsonl
(backups of modified source files are created once)

After this script:
    python3 tests/prepare_benchmark_v1.py

Then use the reviewed facet file for v1.7 evaluation.
"""
from __future__ import annotations

import csv
import json
import shutil
from pathlib import Path
from typing import Dict, List

PROJECT_ROOT = Path(__file__).resolve().parents[1]

DRAFT = (
    PROJECT_ROOT
    / "tests"
    / "annotations"
    / "datastructureqa_dev_v18_facets_draft.jsonl"
)
POOL = PROJECT_ROOT / "tests" / "retrieval_pool_v1.csv"
BENCHMARK = (
    PROJECT_ROOT
    / "tests"
    / "benchmarks"
    / "datastructureqa_dev_v1.jsonl"
)
KNOWLEDGE = PROJECT_ROOT / "knowledge_base" / "ds_chunks.jsonl"

OUTPUT = (
    PROJECT_ROOT
    / "tests"
    / "annotations"
    / "datastructureqa_dev_v18_facets_reviewed.jsonl"
)

DRAFT_BAK = DRAFT.with_suffix(DRAFT.suffix + ".before_v181_review.bak")
POOL_BAK = POOL.with_suffix(POOL.suffix + ".before_v181_review.bak")

REVIEWED_QIDS = {
    "q003", "q008", "q014", "q015", "q016", "q017",
    "q019", "q021", "q030", "q031", "q034", "q037",
    "q040", "q046", "q047", "q048", "q049",
}

# Human review: these previous label=2 chunks are useful but not independently
# sufficient for the full question, so they become label=1.
LABEL_UPDATES = {
    ("q008", "ds_ch02_0017"): 1,
    ("q016", "ds_ch04_0004"): 1,
    ("q016", "ds_ch04_0026"): 1,
    ("q017", "ds_ch04_0034"): 1,
    ("q019", "ds_ch04_0027"): 1,
    ("q021", "ds_ch05_0005"): 1,
    ("q046", "ds_ch11_0031"): 1,
    ("q047", "ds_ch11_0011"): 1,
    ("q047", "ds_ch11_0032"): 1,
    ("q048", "ds_ch11_0049"): 1,
}

# Newly discovered relevant evidence omitted by the old BM25/Dense Top-5 pool.
NEW_RELEVANT = {
    ("q017", "ds_ch04_0010"): {
        "label": 1,
        "note": (
            "Facet v1.8.1 review: BF worst-case O(n*m), "
            "partial evidence for complexity-change question."
        ),
    }
}


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


def save_jsonl(path: Path, rows: List[Dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def load_csv(path: Path):
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        fields = list(reader.fieldnames or [])
    return fields, rows


def save_csv(path: Path, fields: List[str], rows: List[Dict]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=fields,
            extrasaction="ignore",
        )
        writer.writeheader()
        writer.writerows(rows)


def facet(fid: str, desc: str) -> Dict:
    return {"facet_id": fid, "description": desc}


def apply_facet_edits(by_id: Dict[str, Dict]) -> None:
    # q008: facets are correct; label correction only.

    # q014: the final single-stack result follows directly in one step from
    # the described postfix evaluation procedure, so ds_ch03_0015 supports f3.
    by_id["q014"]["chunk_support"]["ds_ch03_0015"] = [
        "f1", "f2", "f3"
    ]

    # q016: facets/mappings are already sensible; the issue is label strength.

    # q017: split the compound "complexity change" facet so evidence for
    # BF complexity and KMP complexity can be represented independently.
    q = by_id["q017"]
    q["facets"] = [
        facet(
            "f1",
            "核心改进机制：利用已匹配的前缀信息，使主串指针不回溯，"
            "模式串尽可能向右滑动",
        ),
        facet(
            "f2",
            "BF算法最坏时间复杂度为 O(n*m)",
        ),
        facet(
            "f3",
            "KMP算法时间复杂度为 O(n+m)",
        ),
    ]
    q["chunk_support"] = {
        "ds_ch04_0009": ["f1"],
        "ds_ch04_0010": ["f2"],
        "ds_ch04_0011": ["f1"],
        "ds_ch04_0012": ["f1"],
        "ds_ch04_0013": ["f1"],
        "ds_ch04_0014": ["f1", "f3"],
        "ds_ch04_0015": [],
        "ds_ch04_0030": ["f1"],
        "ds_ch04_0034": ["f1", "f3"],
        "ds_ch04_0039": ["f3"],
    }

    # q019/q021: facets are correct; label correction only.

    # q030: ds_ch03_0045 explains queue/child processing but not the full
    # initialization + loop algorithm, so do not map all facets to it.
    by_id["q030"]["chunk_support"]["ds_ch03_0045"] = ["f3"]

    # q034: ds_ch07_0015 clearly supports recursive traversal of unvisited
    # neighbors, but does not explicitly provide the visited-marking step.
    by_id["q034"]["chunk_support"]["ds_ch07_0015"] = ["f2"]

    # q046: LLM bootstrap missed obvious direct support.
    q = by_id["q046"]
    q["chunk_support"]["ds_ch11_0002"] = ["f1", "f2", "f3"]
    q["chunk_support"]["ds_ch11_0031"] = ["f1", "f3"]

    # q047: facets/mappings are correct; both formerly label-2 chunks only
    # provide the loser-tree complexity and not the k-1 baseline.

    # q048: the replacement-selection rule directly supports variable-length
    # run generation through one-step inference.
    by_id["q048"]["chunk_support"]["ds_ch11_0022"] = ["f1"]

    # q049: question explicitly asks WHY virtual runs are needed and their
    # WEIGHT. "leaf-only / no physical I/O" is useful auxiliary information,
    # not a core answer requirement, so remove it from core facets.
    q = by_id["q049"]
    q["facets"] = [
        facet(
            "f1",
            "当现有归并段数量不满足严格k叉归并树构造条件时，"
            "需要补充虚归并段以正确构造归并树并计算WPL",
        ),
        facet(
            "f2",
            "虚归并段的权值为0",
        ),
    ]
    q["chunk_support"] = {
        "ds_ch11_0027": ["f1", "f2"],
        "ds_ch11_0028": [],
        "ds_ch11_0029": [],
        "ds_ch11_0034": ["f1"],
        "ds_ch11_0041": ["f2"],
        "ds_ch11_0042": [],
    }


def validate_facets_against_pool(
    facet_rows: List[Dict],
    pool_rows: List[Dict],
) -> List[Dict]:
    pool = {
        (r["question_id"], r["chunk_id"]): r
        for r in pool_rows
    }

    warnings = []

    for row in facet_rows:
        qid = row["id"]
        facet_ids = {
            str(x["facet_id"])
            for x in row.get("facets", [])
        }
        support = row.get("chunk_support", {})

        # Relevant chunks are authoritative from the current pool.
        relevant = [
            r for r in pool_rows
            if r["question_id"] == qid
            and str(r.get("relevance_label", "")).strip() in {"1", "2"}
        ]

        relevant_ids = {r["chunk_id"] for r in relevant}

        # Every relevant chunk should have an explicit support entry.
        for cid in relevant_ids:
            support.setdefault(cid, [])

        # Remove stale mappings to chunks that are no longer relevant.
        for cid in list(support):
            if cid not in relevant_ids:
                del support[cid]

        covered = set()
        for fids in support.values():
            covered.update(
                fid for fid in fids if fid in facet_ids
            )

        for fid in sorted(facet_ids - covered):
            warnings.append(
                {
                    "question_id": qid,
                    "type": "facet_without_support",
                    "facet_id": fid,
                }
            )

        for r in relevant:
            cid = r["chunk_id"]
            label = int(r["relevance_label"])
            mapped = set(support.get(cid, []))

            bad = sorted(mapped - facet_ids)
            if bad:
                warnings.append(
                    {
                        "question_id": qid,
                        "type": "unknown_facet_mapping",
                        "chunk_id": cid,
                        "facets": bad,
                    }
                )

            if label == 2 and mapped != facet_ids:
                warnings.append(
                    {
                        "question_id": qid,
                        "type": "label2_not_cover_all_facets",
                        "chunk_id": cid,
                        "mapped": sorted(mapped),
                        "expected": sorted(facet_ids),
                    }
                )

        row["chunk_support"] = support

    return warnings


def main() -> None:
    for path in (DRAFT, POOL, BENCHMARK, KNOWLEDGE):
        if not path.exists():
            raise SystemExit(f"ERROR: missing {path}")

    if not DRAFT_BAK.exists():
        shutil.copy2(DRAFT, DRAFT_BAK)
        print("backup:", DRAFT_BAK)

    if not POOL_BAK.exists():
        shutil.copy2(POOL, POOL_BAK)
        print("backup:", POOL_BAK)

    facet_rows = load_jsonl(DRAFT)
    by_id = {r["id"]: r for r in facet_rows}

    missing_review = sorted(REVIEWED_QIDS - set(by_id))
    if missing_review:
        raise SystemExit(
            f"ERROR: reviewed qids absent from facet draft: {missing_review}"
        )

    pool_fields, pool_rows = load_csv(POOL)
    benchmark = {r["id"]: r for r in load_jsonl(BENCHMARK)}
    chunks = {
        r["chunk_id"]: r for r in load_jsonl(KNOWLEDGE)
    }

    # Apply relevance-label decisions.
    pool_index = {
        (r["question_id"], r["chunk_id"]): r
        for r in pool_rows
    }

    changed_labels = []
    for key, new_label in LABEL_UPDATES.items():
        if key not in pool_index:
            raise SystemExit(f"ERROR: label-update pair missing: {key}")

        r = pool_index[key]
        old = str(r.get("relevance_label", "")).strip()
        if old != str(new_label):
            r["relevance_label"] = str(new_label)
            note = str(r.get("annotation_note", "")).strip()
            suffix = (
                "Facet v1.8.1 human review: useful partial evidence, "
                "not independently sufficient for the complete question."
            )
            r["annotation_note"] = (
                f"{note}; {suffix}" if note else suffix
            )
            changed_labels.append((key, old, str(new_label)))

    # Add/update q017 BF-complexity evidence.
    added_pairs = []
    for key, spec in NEW_RELEVANT.items():
        qid, cid = key

        if cid not in chunks:
            raise SystemExit(f"ERROR: knowledge chunk missing: {cid}")

        if key in pool_index:
            r = pool_index[key]
            old = str(r.get("relevance_label", "")).strip()
            r["relevance_label"] = str(spec["label"])
            r["annotation_note"] = spec["note"]
            if old != str(spec["label"]):
                changed_labels.append(
                    (key, old, str(spec["label"]))
                )
            continue

        q = benchmark[qid]
        c = chunks[cid]

        new_row = {field: "" for field in pool_fields}

        values = {
            "question_id": qid,
            "question": q["question"],
            "reference_answer": q.get("reference_answer", ""),
            "chunk_id": cid,
            "chapter": c.get("chapter", ""),
            "section": c.get("section", ""),
            "content_type": c.get("content_type", ""),
            "source_file": c.get("source_file", ""),
            "chunk_text": c.get("text", ""),
            "current_gold": "False",
            "bm25_rank": "",
            "bm25_score": "",
            "dense_rank": "",
            "dense_score": "",
            "relevance_label": str(spec["label"]),
            "annotation_note": spec["note"],
        }

        for k, v in values.items():
            if k in new_row:
                new_row[k] = v

        pool_rows.append(new_row)
        pool_index[key] = new_row
        added_pairs.append(key)

    apply_facet_edits(by_id)

    # Mark the manually inspected 17 questions.
    for qid in REVIEWED_QIDS:
        row = by_id[qid]
        row["review_status"] = "human_reviewed_v181"
        row["annotation_source"] = (
            "human_review_v181"
            if row.get("annotation_source") == "llm_bootstrap_v18"
            else row.get("annotation_source", "human_review_v181")
        )

    # Preserve original file order.
    reviewed_rows = [by_id[r["id"]] for r in facet_rows]

    warnings = validate_facets_against_pool(
        reviewed_rows,
        pool_rows,
    )

    # Save after validation has canonicalized relevant support entries.
    save_csv(POOL, pool_fields, pool_rows)
    save_jsonl(OUTPUT, reviewed_rows)

    warning_types = {}
    for w in warnings:
        warning_types[w["type"]] = (
            warning_types.get(w["type"], 0) + 1
        )

    print("\n===== FACET V1.8.1 HUMAN REVIEW PATCH =====")
    print("reviewed_questions =", len(REVIEWED_QIDS))
    print("label_changes =", len(changed_labels))
    for x in changed_labels:
        print("  ", x)
    print("new_pool_pairs =", len(added_pairs))
    for x in added_pairs:
        print("  ", x)
    print("validation_warnings =", len(warnings))
    print("warning_types =", warning_types)

    if warnings:
        print("\nWARNINGS:")
        for w in warnings:
            print(" ", w)

    print("\nreviewed_facets =", OUTPUT)
    print("updated_pool =", POOL)
    print(
        "\nNEXT: run `python3 tests/prepare_benchmark_v1.py` "
        "to rebuild gold IDs from the updated pool."
    )


if __name__ == "__main__":
    main()
