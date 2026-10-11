from __future__ import annotations

import csv
import hashlib
import json
import random
from collections import Counter, defaultdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]

BENCHMARK = PROJECT_ROOT / "tests/benchmarks/heldout/heldout_100_v1.jsonl"
MASTER_POOL = PROJECT_ROOT / "tests/annotations/heldout/heldout_retrieval_pool_v1.csv"
BLIND_OUT = PROJECT_ROOT / "tests/annotations/heldout/heldout_annotation_blind_v1.csv"
FACET_OUT = PROJECT_ROOT / "tests/annotations/heldout/heldout_annotation_facets_v1.csv"

SHUFFLE_SEED = 20260914


def load_jsonl(path: Path):
    rows = []
    with path.open("r", encoding="utf-8") as f:
        for line_no, raw in enumerate(f, 1):
            line = raw.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise RuntimeError(
                    f"{path} line {line_no}: invalid JSON: {exc}"
                ) from exc
    return rows


questions = load_jsonl(BENCHMARK)
qmap = {q["id"]: q for q in questions}

if len(questions) != 100 or len(qmap) != 100:
    raise RuntimeError("benchmark must contain exactly 100 unique questions")

with MASTER_POOL.open("r", encoding="utf-8-sig", newline="") as f:
    master_rows = list(csv.DictReader(f))

if not master_rows:
    raise RuntimeError("master retrieval pool is empty")

required_master = {
    "question_id",
    "question",
    "chunk_id",
    "chapter",
    "section",
    "content_type",
    "source_file",
    "chunk_text",
    "bm25_rank",
    "bm25_score",
    "dense_rank",
    "dense_score",
    "relevance_label",
    "annotation_note",
}

missing = required_master - set(master_rows[0])
if missing:
    raise RuntimeError(f"master pool missing columns: {sorted(missing)}")

# ---------- 基础完整性 ----------
pairs = [(r["question_id"], r["chunk_id"]) for r in master_rows]

if len(pairs) != len(set(pairs)):
    raise RuntimeError("duplicate question-chunk pairs in master pool")

expected_qids = {f"h{i:03d}" for i in range(1, 101)}
actual_qids = {r["question_id"] for r in master_rows}

if actual_qids != expected_qids:
    raise RuntimeError(
        f"question IDs mismatch: missing={sorted(expected_qids - actual_qids)}, "
        f"extra={sorted(actual_qids - expected_qids)}"
    )

if any(r["relevance_label"].strip() for r in master_rows):
    raise RuntimeError("master pool already contains relevance labels")

# ---------- facet catalog ----------
facet_rows = []

for qid in sorted(qmap):
    q = qmap[qid]
    facets = q["core_facets"]

    for i, facet in enumerate(facets, 1):
        facet_rows.append({
            "question_id": qid,
            "facet_id": f"F{i}",
            "facet_text": facet,
        })

with FACET_OUT.open("w", encoding="utf-8-sig", newline="") as f:
    writer = csv.DictWriter(
        f,
        fieldnames=["question_id", "facet_id", "facet_text"],
    )
    writer.writeheader()
    writer.writerows(facet_rows)

# ---------- 每题独立、确定性随机打乱 ----------
by_question = defaultdict(list)
for row in master_rows:
    by_question[row["question_id"]].append(row)

blind_rows = []

for qid in sorted(by_question):
    q = qmap[qid]
    rows = list(by_question[qid])

    # 每题使用独立、可复现随机种子
    seed_material = f"{SHUFFLE_SEED}:{qid}".encode("utf-8")
    qseed = int(hashlib.sha256(seed_material).hexdigest()[:16], 16)
    rng = random.Random(qseed)
    rng.shuffle(rows)

    facet_schema = " || ".join(
        f"F{i}={text}"
        for i, text in enumerate(q["core_facets"], 1)
    )

    for candidate_no, row in enumerate(rows, 1):
        blind_rows.append({
            "question_id": qid,
            "candidate_id": f"C{candidate_no:02d}",
            "question": q["question"],
            "reference_answer": q["reference_answer"],
            "facet_schema": facet_schema,
            "chunk_id": row["chunk_id"],
            "chapter": row["chapter"],
            "section": row["section"],
            "content_type": row["content_type"],
            "source_file": row["source_file"],
            "chunk_text": row["chunk_text"],

            # 待人工填写
            "relevance_label": "",
            "supported_facets": "",
            "annotation_note": "",
        })

blind_fields = [
    "question_id",
    "candidate_id",
    "question",
    "reference_answer",
    "facet_schema",
    "chunk_id",
    "chapter",
    "section",
    "content_type",
    "source_file",
    "chunk_text",
    "relevance_label",
    "supported_facets",
    "annotation_note",
]

with BLIND_OUT.open("w", encoding="utf-8-sig", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=blind_fields)
    writer.writeheader()
    writer.writerows(blind_rows)

# ---------- 最终盲态审计 ----------
errors = []

if len(blind_rows) != len(master_rows):
    errors.append(
        f"blind/master row mismatch: {len(blind_rows)} != {len(master_rows)}"
    )

blind_pairs = [
    (r["question_id"], r["chunk_id"])
    for r in blind_rows
]

if set(blind_pairs) != set(pairs):
    errors.append("blind package changed candidate pair set")

if len(blind_pairs) != len(set(blind_pairs)):
    errors.append("blind package contains duplicate pairs")

for forbidden in [
    "bm25_rank",
    "bm25_score",
    "dense_rank",
    "dense_score",
    "current_gold",
]:
    if forbidden in blind_fields:
        errors.append(f"forbidden retrieval signal leaked: {forbidden}")

if any(r["relevance_label"] for r in blind_rows):
    errors.append("relevance labels are not empty")

if any(r["supported_facets"] for r in blind_rows):
    errors.append("supported_facets are not empty")

counts = Counter(r["question_id"] for r in blind_rows)

print("===== BLIND ANNOTATION PACKAGE AUDIT =====")
print("questions =", len(counts))
print("pairs =", len(blind_rows))
print("unique_pairs =", len(set(blind_pairs)))
print("avg_candidates =", round(len(blind_rows) / len(counts), 2))
print("min_candidates =", min(counts.values()))
print("max_candidates =", max(counts.values()))
print("facet_rows =", len(facet_rows))
print("shuffle_seed =", SHUFFLE_SEED)
print("blind_file =", BLIND_OUT.relative_to(PROJECT_ROOT))
print("facet_file =", FACET_OUT.relative_to(PROJECT_ROOT))

print("\nvisible_columns =")
for field in blind_fields:
    print(" -", field)

if errors:
    print("\n===== ERRORS =====")
    for e in errors:
        print("-", e)
    raise SystemExit(1)

print("\nBLIND_PACKAGE_AUDIT=PASS")
