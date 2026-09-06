"""Prepare DataStructureQA Dev v1 and evaluate pooled BM25/Dense baselines.

Run from the project root:
    python3 tests/prepare_benchmark_v1.py

This script:
1. Strictly validates the manually labeled retrieval pool.
2. Freezes DataStructureQA Dev v1 without editing the original 50 questions.
3. Converts relevance labels:
       0 -> irrelevant
       1 -> supporting gold
       2 -> primary gold (sufficient alone)
4. Reconstructs BM25/Dense Top-5 directly from pool ranks, so Dense API is
   NOT called again.
5. Reports Recall/MRR/binary nDCG, graded nDCG, Primary Hit, grouped metrics,
   retriever complementarity, and the first research-direction diagnostic.

Important:
The pool contains BM25 Top-5 ∪ Dense Top-5 ∪ legacy gold. It is sufficient
for re-evaluating these two baselines. A future new method may retrieve
unjudged chunks; those chunks must be adjudicated before a formal comparison.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import subprocess
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Sequence


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_QUESTIONS = PROJECT_ROOT / "tests" / "test_questions_50.jsonl"
DEFAULT_POOL = PROJECT_ROOT / "tests" / "retrieval_pool_v1.csv"
DEFAULT_KB = PROJECT_ROOT / "knowledge_base" / "ds_chunks.jsonl"
DEFAULT_BENCHMARK = (
    PROJECT_ROOT / "tests" / "benchmarks" / "datastructureqa_dev_v1.jsonl"
)
DEFAULT_META = (
    PROJECT_ROOT / "tests" / "benchmarks" / "datastructureqa_dev_v1_meta.json"
)
DEFAULT_REPORT = (
    PROJECT_ROOT / "tests" / "results" / "benchmark_v1_pooled_baselines.json"
)
KS = (1, 3, 5)


def load_jsonl(path: Path) -> List[Dict]:
    records: List[Dict] = []
    with path.open("r", encoding="utf-8") as f:
        for line_no, raw in enumerate(f, 1):
            line = raw.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise RuntimeError(
                    f"{path} line {line_no} is invalid JSON: {exc}"
                ) from exc
    return records


def as_list(value) -> List:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def current_git_commit() -> str | None:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=PROJECT_ROOT,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def parse_label(raw: str, row_no: int) -> int:
    value = (raw or "").strip()
    if value == "":
        raise RuntimeError(
            f"annotation CSV row {row_no}: relevance_label is blank"
        )
    try:
        label = int(value)
    except ValueError as exc:
        raise RuntimeError(
            f"annotation CSV row {row_no}: invalid relevance_label={value!r}"
        ) from exc
    if label not in (0, 1, 2):
        raise RuntimeError(
            f"annotation CSV row {row_no}: label must be 0/1/2, got {label}"
        )
    return label


def parse_rank(raw: str) -> int | None:
    value = (raw or "").strip()
    if not value:
        return None
    rank = int(float(value))
    if rank <= 0:
        raise RuntimeError(f"rank must be positive, got {raw!r}")
    return rank


def recall_at_k(retrieved: Sequence[str], gold: Sequence[str], k: int) -> float:
    gold_set = set(gold)
    if not gold_set:
        return 0.0
    return len(set(retrieved[:k]) & gold_set) / len(gold_set)


def hit_at_k(retrieved: Sequence[str], gold: Sequence[str], k: int) -> float:
    gold_set = set(gold)
    if not gold_set:
        return 0.0
    return float(bool(set(retrieved[:k]) & gold_set))


def mrr_at_k(retrieved: Sequence[str], gold: Sequence[str], k: int) -> float:
    gold_set = set(gold)
    if not gold_set:
        return 0.0
    for rank, cid in enumerate(retrieved[:k], 1):
        if cid in gold_set:
            return 1.0 / rank
    return 0.0


def binary_ndcg_at_k(
    retrieved: Sequence[str], gold: Sequence[str], k: int
) -> float:
    gold_set = set(gold)
    if not gold_set:
        return 0.0

    dcg = sum(
        1.0 / math.log2(rank + 1)
        for rank, cid in enumerate(retrieved[:k], 1)
        if cid in gold_set
    )
    ideal_hits = min(k, len(gold_set))
    idcg = sum(
        1.0 / math.log2(rank + 1)
        for rank in range(1, ideal_hits + 1)
    )
    return dcg / idcg if idcg else 0.0


def graded_ndcg_at_k(
    retrieved: Sequence[str], judgments: Dict[str, int], k: int
) -> float:
    """Standard graded nDCG with gain = 2^rel - 1."""
    def gain(rel: int) -> float:
        return float((2 ** rel) - 1)

    dcg = sum(
        gain(judgments.get(cid, 0)) / math.log2(rank + 1)
        for rank, cid in enumerate(retrieved[:k], 1)
    )
    ideal_labels = sorted(judgments.values(), reverse=True)[:k]
    idcg = sum(
        gain(rel) / math.log2(rank + 1)
        for rank, rel in enumerate(ideal_labels, 1)
    )
    return dcg / idcg if idcg else 0.0


def mean(values: Sequence[float]) -> float | None:
    return round(sum(values) / len(values), 4) if values else None


def freeze_benchmark(
    questions_path: Path,
    pool_path: Path,
    knowledge_path: Path,
    benchmark_path: Path,
    meta_path: Path,
):
    questions_raw = load_jsonl(questions_path)
    chunks_raw = load_jsonl(knowledge_path)

    questions: Dict[str, Dict] = {}
    for item in questions_raw:
        qid = str(item.get("id", "")).strip()
        if not qid:
            raise RuntimeError("question without id")
        if qid in questions:
            raise RuntimeError(f"duplicate question id: {qid}")
        questions[qid] = item

    chunk_ids = set()
    for chunk in chunks_raw:
        cid = str(chunk.get("chunk_id", "")).strip()
        if not cid:
            raise RuntimeError("knowledge chunk without chunk_id")
        if cid in chunk_ids:
            raise RuntimeError(f"duplicate knowledge chunk_id: {cid}")
        chunk_ids.add(cid)

    judgments: Dict[str, Dict[str, int]] = defaultdict(dict)
    notes: Dict[str, Dict[str, str]] = defaultdict(dict)
    ranks: Dict[str, Dict[str, Dict[int, str]]] = {
        "bm25": defaultdict(dict),
        "dense": defaultdict(dict),
    }
    label_counts: Counter[int] = Counter()
    pair_count = 0

    with pool_path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        required = {
            "question_id",
            "question",
            "chunk_id",
            "bm25_rank",
            "dense_rank",
            "relevance_label",
            "annotation_note",
        }
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise RuntimeError(f"annotation CSV missing columns: {sorted(missing)}")

        for row_no, row in enumerate(reader, 2):
            qid = (row.get("question_id") or "").strip()
            cid = (row.get("chunk_id") or "").strip()

            if qid not in questions:
                raise RuntimeError(
                    f"annotation row {row_no}: unknown question_id={qid!r}"
                )
            if cid not in chunk_ids:
                raise RuntimeError(
                    f"annotation row {row_no}: unknown chunk_id={cid!r}"
                )
            if cid in judgments[qid]:
                raise RuntimeError(f"duplicate judged pair: ({qid}, {cid})")

            canonical_q = str(questions[qid].get("question", "")).strip()
            if (row.get("question") or "").strip() != canonical_q:
                raise RuntimeError(
                    f"annotation row {row_no}: question text mismatch for {qid}"
                )

            label = parse_label(row.get("relevance_label", ""), row_no)
            judgments[qid][cid] = label
            label_counts[label] += 1
            pair_count += 1

            note = (row.get("annotation_note") or "").strip()
            if note:
                notes[qid][cid] = note

            for name in ("bm25", "dense"):
                rank = parse_rank(row.get(f"{name}_rank", ""))
                if rank is not None:
                    if rank in ranks[name][qid]:
                        raise RuntimeError(
                            f"{qid}: duplicate {name} rank {rank}"
                        )
                    ranks[name][qid][rank] = cid

    missing_questions = sorted(set(questions) - set(judgments))
    if missing_questions:
        raise RuntimeError(
            "questions missing from annotation pool: "
            + ", ".join(missing_questions)
        )

    # The original pool was constructed from Top-5 of each baseline.
    for name in ("bm25", "dense"):
        for qid in questions:
            got = sorted(ranks[name][qid])
            expected = list(range(1, 6))
            if got != expected:
                raise RuntimeError(
                    f"{qid}: {name} ranks must be exactly 1..5, got {got}"
                )

    benchmark_records: List[Dict] = []
    changed_gold_questions: List[Dict] = []
    no_primary_questions: List[str] = []
    judged_counts: List[int] = []
    gold_counts: List[int] = []
    primary_counts: List[int] = []

    for qid, original in questions.items():
        is_oos = bool(original.get("is_out_of_scope", False))
        qj = judgments[qid]

        judged = sorted(qj)
        supporting = sorted(cid for cid, rel in qj.items() if rel == 1)
        primary = sorted(cid for cid, rel in qj.items() if rel == 2)
        gold = sorted(supporting + primary)
        legacy = sorted(set(as_list(original.get("expected_chunk_id"))))

        if is_oos and gold:
            raise RuntimeError(
                f"{qid} is out-of-scope but has relevant judged chunks: {gold}"
            )
        if not is_oos and not gold:
            raise RuntimeError(
                f"{qid} is in-scope but has no label-1/2 evidence"
            )
        if not is_oos and not primary:
            no_primary_questions.append(qid)

        if set(gold) != set(legacy):
            changed_gold_questions.append(
                {
                    "id": qid,
                    "legacy_expected_chunk_ids": legacy,
                    "gold_chunk_ids": gold,
                    "added": sorted(set(gold) - set(legacy)),
                    "removed": sorted(set(legacy) - set(gold)),
                }
            )

        record = {
            "id": qid,
            "question": original.get("question", ""),
            "type": original.get("type", ""),
            "reference_answer": original.get("reference_answer", ""),
            "expected_chapter": original.get("expected_chapter", ""),
            "expected_source": original.get("expected_source", ""),
            "is_out_of_scope": is_oos,
            "gold_chunk_ids": gold,
            "primary_gold_chunk_ids": primary,
            "supporting_gold_chunk_ids": supporting,
            "legacy_expected_chunk_ids": legacy,
            "judged_chunk_ids": judged,
            "relevance_judgments": {cid: qj[cid] for cid in judged},
            "has_single_chunk_sufficient_evidence": bool(primary),
            "requires_evidence_combination": bool(gold) and not bool(primary),
        }
        if notes[qid]:
            record["annotation_notes"] = {
                cid: notes[qid][cid] for cid in sorted(notes[qid])
            }

        benchmark_records.append(record)
        judged_counts.append(len(judged))
        if not is_oos:
            gold_counts.append(len(gold))
            primary_counts.append(len(primary))

    benchmark_path.parent.mkdir(parents=True, exist_ok=True)
    with benchmark_path.open("w", encoding="utf-8") as f:
        for record in benchmark_records:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    in_scope_total = sum(
        not bool(q.get("is_out_of_scope", False)) for q in questions_raw
    )
    out_of_scope_total = len(questions_raw) - in_scope_total

    meta = {
        "benchmark": "DataStructureQA",
        "split": "dev",
        "version": "v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "git_commit": current_git_commit(),
        "annotation_policy": {
            "0": "irrelevant",
            "1": "useful supporting evidence but insufficient alone",
            "2": "primary evidence basically sufficient alone",
            "gold_chunk_ids": "relevance_label >= 1",
            "primary_gold_chunk_ids": "relevance_label == 2",
        },
        "judgment_scope": (
            "BM25 Top-5 union Dense Top-5 union legacy expected chunks"
        ),
        "formal_evaluation_warning": (
            "The pool is not exhaustive for future methods. If a new method "
            "retrieves unjudged chunks, adjudicate them before formal comparison."
        ),
        "counts": {
            "questions": len(benchmark_records),
            "in_scope": in_scope_total,
            "out_of_scope": out_of_scope_total,
            "judged_pairs": pair_count,
            "label_0": label_counts[0],
            "label_1": label_counts[1],
            "label_2": label_counts[2],
            "changed_gold_questions": len(changed_gold_questions),
            "questions_without_primary_gold": len(no_primary_questions),
        },
        "statistics": {
            "avg_judged_chunks_per_question": round(
                sum(judged_counts) / len(judged_counts), 4
            ),
            "avg_gold_chunks_per_in_scope_question": round(
                sum(gold_counts) / len(gold_counts), 4
            ),
            "avg_primary_chunks_per_in_scope_question": round(
                sum(primary_counts) / len(primary_counts), 4
            ),
        },
        "questions_without_primary_gold": no_primary_questions,
        "gold_changes": changed_gold_questions,
        "sha256": {
            "questions": sha256_file(questions_path),
            "pool": sha256_file(pool_path),
            "knowledge": sha256_file(knowledge_path),
            "benchmark": sha256_file(benchmark_path),
        },
    }

    meta_path.parent.mkdir(parents=True, exist_ok=True)
    with meta_path.open("w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    return benchmark_records, ranks, meta


def evaluate_one(
    benchmark: Sequence[Dict],
    rank_map: Dict[str, Dict[int, str]],
):
    per_query: List[Dict] = []

    for q in benchmark:
        qid = q["id"]
        retrieved = [
            rank_map[qid][rank]
            for rank in sorted(rank_map[qid])
        ]
        if q["is_out_of_scope"]:
            per_query.append(
                {
                    "id": qid,
                    "query_type": q["type"],
                    "is_out_of_scope": True,
                    "retrieved_chunk_ids": retrieved,
                }
            )
            continue

        gold = q["gold_chunk_ids"]
        primary = q["primary_gold_chunk_ids"]
        judgments = q["relevance_judgments"]

        row = {
            "id": qid,
            "query_type": q["type"],
            "question": q["question"],
            "is_out_of_scope": False,
            "gold_count": len(gold),
            "primary_count": len(primary),
            "retrieved_chunk_ids": retrieved,
        }

        for k in KS:
            row[f"recall@{k}"] = recall_at_k(retrieved, gold, k)
            row[f"hit@{k}"] = hit_at_k(retrieved, gold, k)
            row[f"binary_ndcg@{k}"] = binary_ndcg_at_k(
                retrieved, gold, k
            )
            row[f"graded_ndcg@{k}"] = graded_ndcg_at_k(
                retrieved, judgments, k
            )
            row[f"judgment_coverage@{k}"] = (
                sum(cid in judgments for cid in retrieved[:k]) / k
            )
            row[f"primary_hit@{k}"] = (
                hit_at_k(retrieved, primary, k) if primary else None
            )

        row["mrr@3"] = mrr_at_k(retrieved, gold, 3)
        row["mrr@5"] = mrr_at_k(retrieved, gold, 5)
        row["primary_mrr@5"] = (
            mrr_at_k(retrieved, primary, 5) if primary else None
        )
        per_query.append(row)

    scored = [r for r in per_query if not r["is_out_of_scope"]]
    primary_scored = [r for r in scored if r["primary_count"] > 0]

    def metric(field: str, records: Sequence[Dict] = scored):
        values = [r[field] for r in records if r.get(field) is not None]
        return mean(values)

    overall = {}
    for k in KS:
        overall[f"recall@{k}"] = metric(f"recall@{k}")
        overall[f"hit@{k}"] = metric(f"hit@{k}")
        overall[f"binary_ndcg@{k}"] = metric(f"binary_ndcg@{k}")
        overall[f"graded_ndcg@{k}"] = metric(f"graded_ndcg@{k}")
        overall[f"primary_hit@{k}"] = metric(
            f"primary_hit@{k}", primary_scored
        )
        overall[f"judgment_coverage@{k}"] = metric(
            f"judgment_coverage@{k}"
        )

    overall["mrr@3"] = metric("mrr@3")
    overall["mrr@5"] = metric("mrr@5")
    overall["primary_mrr@5"] = metric(
        "primary_mrr@5", primary_scored
    )
    overall["scored_queries"] = len(scored)
    overall["primary_scored_queries"] = len(primary_scored)

    grouped = {}
    query_types = sorted({r["query_type"] for r in scored})
    for qtype in query_types:
        subset = [r for r in scored if r["query_type"] == qtype]
        primary_subset = [r for r in subset if r["primary_count"] > 0]

        def submetric(field: str, records=subset):
            values = [r[field] for r in records if r.get(field) is not None]
            return mean(values)

        grouped[qtype] = {
            "count": len(subset),
            "primary_scored": len(primary_subset),
            "recall@1": submetric("recall@1"),
            "recall@3": submetric("recall@3"),
            "recall@5": submetric("recall@5"),
            "graded_ndcg@3": submetric("graded_ndcg@3"),
            "graded_ndcg@5": submetric("graded_ndcg@5"),
            "primary_hit@1": submetric(
                "primary_hit@1", primary_subset
            ),
            "primary_hit@3": submetric(
                "primary_hit@3", primary_subset
            ),
            "primary_hit@5": submetric(
                "primary_hit@5", primary_subset
            ),
        }

    return {
        "overall": overall,
        "by_query_type": grouped,
        "per_query": per_query,
    }


def compare_retrievers(
    benchmark: Sequence[Dict],
    bm25_eval: Dict,
    dense_eval: Dict,
):
    b = {
        r["id"]: r
        for r in bm25_eval["per_query"]
        if not r["is_out_of_scope"]
    }
    d = {
        r["id"]: r
        for r in dense_eval["per_query"]
        if not r["is_out_of_scope"]
    }

    complementarity = {}
    for k in KS:
        categories = Counter()
        oracle_recall = []
        for q in benchmark:
            if q["is_out_of_scope"]:
                continue
            qid = q["id"]
            b_hit = b[qid][f"hit@{k}"] > 0
            d_hit = d[qid][f"hit@{k}"] > 0

            if b_hit and d_hit:
                categories["both"] += 1
            elif b_hit:
                categories["bm25_only"] += 1
            elif d_hit:
                categories["dense_only"] += 1
            else:
                categories["neither"] += 1

            oracle_recall.append(
                max(b[qid][f"recall@{k}"], d[qid][f"recall@{k}"])
            )

        complementarity[f"@{k}"] = {
            "both": categories["both"],
            "bm25_only": categories["bm25_only"],
            "dense_only": categories["dense_only"],
            "neither": categories["neither"],
            "oracle_mean_recall": mean(oracle_recall),
        }

    ranking_gap = []
    incomplete_coverage = []
    no_single_sufficient = []

    for q in benchmark:
        if q["is_out_of_scope"]:
            continue
        qid = q["id"]
        dr = d[qid]

        if not q["primary_gold_chunk_ids"]:
            no_single_sufficient.append(qid)
        elif dr["recall@5"] > 0 and dr["primary_hit@1"] == 0:
            ranking_gap.append(qid)

        if dr["recall@5"] < 1.0:
            incomplete_coverage.append(qid)

    dense_overall = dense_eval["overall"]
    gate = {
        "dense_recall@5": dense_overall["recall@5"],
        "dense_primary_hit@1": dense_overall["primary_hit@1"],
        "dense_primary_hit@3": dense_overall["primary_hit@3"],
        "dense_primary_hit@5": dense_overall["primary_hit@5"],
        "dense_graded_ndcg@3": dense_overall["graded_ndcg@3"],
        "dense_graded_ndcg@5": dense_overall["graded_ndcg@5"],
        "recall5_minus_primary_hit1": (
            round(
                dense_overall["recall@5"]
                - dense_overall["primary_hit@1"],
                4,
            )
            if dense_overall["primary_hit@1"] is not None
            else None
        ),
        "ranking_gap_query_count": len(ranking_gap),
        "ranking_gap_query_ids": ranking_gap,
        "incomplete_gold_coverage_query_count": len(incomplete_coverage),
        "incomplete_gold_coverage_query_ids": incomplete_coverage,
        "no_single_sufficient_evidence_query_count": len(
            no_single_sufficient
        ),
        "no_single_sufficient_evidence_query_ids": no_single_sufficient,
        "interpretation_note": (
            "A large Recall@5 vs Primary-Hit@1 gap supports a ranking/evidence-"
            "quality problem. Many queries without any label-2 chunk support a "
            "multi-evidence coverage problem. These are diagnostics, not yet a "
            "formal paper claim."
        ),
    }

    return {
        "complementarity": complementarity,
        "direction_gate": gate,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Freeze DataStructureQA Dev v1 and recompute pooled baselines"
    )
    parser.add_argument("--questions", type=Path, default=DEFAULT_QUESTIONS)
    parser.add_argument("--pool", type=Path, default=DEFAULT_POOL)
    parser.add_argument("--knowledge", type=Path, default=DEFAULT_KB)
    parser.add_argument("--benchmark", type=Path, default=DEFAULT_BENCHMARK)
    parser.add_argument("--meta", type=Path, default=DEFAULT_META)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()

    benchmark, ranks, meta = freeze_benchmark(
        args.questions,
        args.pool,
        args.knowledge,
        args.benchmark,
        args.meta,
    )

    bm25_eval = evaluate_one(benchmark, ranks["bm25"])
    dense_eval = evaluate_one(benchmark, ranks["dense"])
    comparison = compare_retrievers(benchmark, bm25_eval, dense_eval)

    report = {
        "benchmark": {
            "name": "DataStructureQA",
            "split": "dev",
            "version": "v1",
            "benchmark_file": str(args.benchmark),
            "benchmark_sha256": sha256_file(args.benchmark),
            "judgment_scope": meta["judgment_scope"],
            "formal_evaluation_warning": meta["formal_evaluation_warning"],
        },
        "bm25": bm25_eval,
        "dense": dense_eval,
        "comparison": comparison,
    }

    args.report.parent.mkdir(parents=True, exist_ok=True)
    with args.report.open("w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print("\n===== BENCHMARK FREEZE =====")
    counts = meta["counts"]
    print(
        f"questions={counts['questions']} "
        f"in_scope={counts['in_scope']} "
        f"out_of_scope={counts['out_of_scope']}"
    )
    print(
        f"judged_pairs={counts['judged_pairs']} "
        f"labels(0/1/2)="
        f"{counts['label_0']}/{counts['label_1']}/{counts['label_2']}"
    )
    print(f"changed_gold_questions={counts['changed_gold_questions']}")
    print(
        "questions_without_primary_gold="
        f"{counts['questions_without_primary_gold']}"
    )
    if meta["questions_without_primary_gold"]:
        print(
            "no_primary_ids="
            + ",".join(meta["questions_without_primary_gold"])
        )

    print("\n===== NEW BASELINES =====")
    for name, result in (("BM25", bm25_eval), ("Dense", dense_eval)):
        m = result["overall"]
        print(
            f"{name}: "
            f"Recall@1/3/5={m['recall@1']}/{m['recall@3']}/{m['recall@5']}  "
            f"PrimaryHit@1/3/5="
            f"{m['primary_hit@1']}/{m['primary_hit@3']}/{m['primary_hit@5']}  "
            f"graded-nDCG@3/5="
            f"{m['graded_ndcg@3']}/{m['graded_ndcg@5']}  "
            f"MRR@5={m['mrr@5']}"
        )

    print("\n===== DIRECTION GATE =====")
    gate = comparison["direction_gate"]
    for key in (
        "dense_recall@5",
        "dense_primary_hit@1",
        "dense_primary_hit@3",
        "dense_primary_hit@5",
        "dense_graded_ndcg@3",
        "dense_graded_ndcg@5",
        "recall5_minus_primary_hit1",
        "ranking_gap_query_count",
        "incomplete_gold_coverage_query_count",
        "no_single_sufficient_evidence_query_count",
    ):
        print(f"{key}={gate[key]}")

    print("\nDense ranking-gap IDs:")
    print(",".join(gate["ranking_gap_query_ids"]) or "(none)")
    print("Dense incomplete-coverage IDs:")
    print(",".join(gate["incomplete_gold_coverage_query_ids"]) or "(none)")

    print("\n===== COMPLEMENTARITY =====")
    for k, item in comparison["complementarity"].items():
        print(
            f"{k}: both={item['both']} "
            f"bm25_only={item['bm25_only']} "
            f"dense_only={item['dense_only']} "
            f"neither={item['neither']} "
            f"oracle_recall={item['oracle_mean_recall']}"
        )

    print("\nFiles:")
    print(f"benchmark: {args.benchmark}")
    print(f"metadata : {args.meta}")
    print(f"report   : {args.report}")
    print(
        "\nNOTE: do not use pooled graded judgments to score a future method "
        "until any newly retrieved unjudged chunks have been adjudicated."
    )


if __name__ == "__main__":
    main()
