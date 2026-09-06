"""Bootstrap human-reviewable answer-facet annotations for DataStructureQA Dev v1.

Purpose
-------
The current relevance labels (0/1/2) tell us whether a chunk is relevant or
individually sufficient, but they do not tell us *which parts of the answer*
each partial chunk supports. Evidence-set methods therefore need a separate,
human-reviewed facet annotation.

This script uses an LLM only to create a DRAFT from:
    question + reference_answer + human-relevant chunks (label 1/2)

The reference answer is treated as authoritative. The draft MUST be manually
reviewed before it is used as gold evaluation data.

Importantly, these gold facets are for EVALUATION ONLY. A retrieval method must
not read reference_answer or gold facets at inference time.

Run from project root:
    python3 tests/bootstrap_facets_v1.py

Outputs:
    tests/annotations/datastructureqa_dev_v1_facets_draft.jsonl
    tests/annotations/datastructureqa_dev_v1_facet_review.csv
    tests/annotations/datastructureqa_dev_v1_facet_bootstrap_meta.json
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Dict, List

from openai import OpenAI


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from rag.config import GENERATION_MODEL

DEFAULT_BENCHMARK = (
    PROJECT_ROOT / "tests" / "benchmarks" / "datastructureqa_dev_v1.jsonl"
)
DEFAULT_POOL = PROJECT_ROOT / "tests" / "retrieval_pool_v1.csv"
DEFAULT_DRAFT = (
    PROJECT_ROOT
    / "tests"
    / "annotations"
    / "datastructureqa_dev_v1_facets_draft.jsonl"
)
DEFAULT_REVIEW = (
    PROJECT_ROOT
    / "tests"
    / "annotations"
    / "datastructureqa_dev_v1_facet_review.csv"
)
DEFAULT_META = (
    PROJECT_ROOT
    / "tests"
    / "annotations"
    / "datastructureqa_dev_v1_facet_bootstrap_meta.json"
)

DEFAULT_MODEL = GENERATION_MODEL


def load_env(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(
            key.strip(),
            value.strip().strip("\"'"),
        )


def load_jsonl(path: Path) -> List[Dict]:
    records = []
    with path.open("r", encoding="utf-8") as f:
        for line_no, raw in enumerate(f, 1):
            line = raw.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise RuntimeError(
                    f"{path} line {line_no}: invalid JSON: {exc}"
                ) from exc
    return records


def strip_json_fence(text: str) -> str:
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, count=1)
        text = re.sub(r"\s*```$", "", text, count=1)
    return text.strip()


def load_relevant_pool(path: Path) -> Dict[str, List[Dict]]:
    by_qid: Dict[str, List[Dict]] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row_no, row in enumerate(reader, 2):
            raw = (row.get("relevance_label") or "").strip()
            if raw == "":
                raise RuntimeError(
                    f"{path} row {row_no}: relevance_label is blank"
                )
            label = int(raw)
            if label not in (0, 1, 2):
                raise RuntimeError(
                    f"{path} row {row_no}: invalid label={label}"
                )
            if label == 0:
                continue

            qid = (row.get("question_id") or "").strip()
            by_qid.setdefault(qid, []).append(
                {
                    "chunk_id": (row.get("chunk_id") or "").strip(),
                    "human_relevance_label": label,
                    "chapter": row.get("chapter", ""),
                    "section": row.get("section", ""),
                    "content_type": row.get("content_type", ""),
                    "text": row.get("chunk_text", ""),
                }
            )
    return by_qid


def build_prompt(question: Dict, chunks: List[Dict]) -> str:
    chunk_blocks = []
    for chunk in chunks:
        chunk_blocks.append(
            "\n".join(
                [
                    f"chunk_id: {chunk['chunk_id']}",
                    f"human_label: {chunk['human_relevance_label']}",
                    f"chapter: {chunk['chapter']}",
                    f"section: {chunk['section']}",
                    f"text: {chunk['text']}",
                ]
            )
        )

    chunks_text = "\n\n---\n\n".join(chunk_blocks)

    return f"""
你正在为一个信息检索/RAG基准创建“答案要点（answer facets）”人工复核草稿。

【重要约束】
1. reference_answer 是唯一权威答案。禁止补充 reference_answer 中没有的信息。
2. 把 reference_answer 拆成 1~5 个“原子答案要点”。
3. 每个 facet 应尽量满足：
   - 表达一个独立、可判断是否被证据支持的信息需求；
   - 不与其他 facet 重复；
   - 所有 facet 合起来完整覆盖 reference_answer；
   - 不要因为某个 chunk 的写法而改变答案要点。
4. 然后判断每个已由人工判为相关(label=1或2)的 chunk 支持哪些 facet。
5. 支持关系按“question + chunk 是否足以得到该 facet”判断：
   - 可以直接读取答案；
   - 也允许无需外部知识的一步直接推理或计算，例如：
     “必须从头遍历”可支持线性访问复杂度 O(n)；
     “长度等于最外层元素个数”结合题目中的具体广义表可推出具体长度。
   - 禁止依赖 chunk 与问题之外的外部知识补全答案。
6. human_label=1 可能只是有用背景、规则或类比证据，因此允许不直接映射任何核心 facet。
7. human_label=2 表示人工认为该 chunk 单独基本足以回答问题；
   理论上应覆盖全部核心 facet。如果明显冲突，正常输出，
   后续程序会标记供人工复核。
7. 仅输出 JSON，不要输出解释、Markdown 或代码块。

【问题】
{question['question']}

【标准答案】
{question['reference_answer']}

【人工已判相关的候选证据】
{chunks_text}

【严格输出格式】
{{
  "facets": [
    {{
      "facet_id": "f1",
      "text": "一个原子答案要点"
    }}
  ],
  "chunk_support": [
    {{
      "chunk_id": "原chunk_id",
      "facet_ids": ["f1"]
    }}
  ]
}}
""".strip()


def call_llm(
    client: OpenAI,
    model: str,
    prompt: str,
    retries: int,
) -> Dict:
    last_error = None
    for attempt in range(1, retries + 1):
        try:
            completion = client.chat.completions.create(
                model=model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "你是严谨的信息检索标注助手。"
                            "严格依据用户给出的标准答案和证据工作。"
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0.0,
                extra_body={"enable_thinking": False},
            )
            text = completion.choices[0].message.content
            return json.loads(strip_json_fence(text))
        except Exception as exc:  # noqa: BLE001 - API/parse retry boundary
            last_error = exc
            if attempt < retries:
                time.sleep(1.5 * attempt)
    raise RuntimeError(f"LLM call failed after {retries} attempts: {last_error}")


def normalize_result(
    qid: str,
    chunks: List[Dict],
    result: Dict,
) -> tuple[List[Dict], Dict[str, List[str]], List[str]]:
    warnings: List[str] = []

    raw_facets = result.get("facets")
    if not isinstance(raw_facets, list) or not raw_facets:
        raise RuntimeError(f"{qid}: missing/non-list facets")

    facets: List[Dict] = []
    facet_ids = set()
    for idx, raw in enumerate(raw_facets, 1):
        if not isinstance(raw, dict):
            raise RuntimeError(f"{qid}: facet #{idx} is not an object")
        fid = str(raw.get("facet_id") or f"f{idx}").strip()
        text = str(raw.get("text") or "").strip()
        if not text:
            raise RuntimeError(f"{qid}: empty facet text")
        if fid in facet_ids:
            fid = f"f{idx}"
        facet_ids.add(fid)
        facets.append({"facet_id": fid, "text": text})

    if len(facets) > 5:
        warnings.append("facet_count_gt_5")

    chunk_ids = {c["chunk_id"] for c in chunks}
    support: Dict[str, List[str]] = {cid: [] for cid in chunk_ids}

    raw_support = result.get("chunk_support", [])
    if not isinstance(raw_support, list):
        raise RuntimeError(f"{qid}: chunk_support is not a list")

    for item in raw_support:
        if not isinstance(item, dict):
            continue
        cid = str(item.get("chunk_id") or "").strip()
        if cid not in chunk_ids:
            warnings.append(f"unknown_chunk_from_llm:{cid}")
            continue
        ids = item.get("facet_ids", [])
        if not isinstance(ids, list):
            ids = []
        clean = []
        for fid in ids:
            fid = str(fid).strip()
            if fid in facet_ids and fid not in clean:
                clean.append(fid)
            elif fid:
                warnings.append(f"unknown_facet_from_llm:{cid}:{fid}")
        support[cid] = clean

    # Diagnostics for human review.
    supported_facets = {
        fid
        for ids in support.values()
        for fid in ids
    }
    for fid in facet_ids:
        if fid not in supported_facets:
            warnings.append(f"facet_without_support:{fid}")

    all_facets = set(facet_ids)
    for chunk in chunks:
        cid = chunk["chunk_id"]
        mapped = set(support[cid])
        label = chunk["human_relevance_label"]
        if label == 2 and mapped != all_facets:
            warnings.append(
                f"primary_chunk_not_cover_all_facets:{cid}"
            )
        if label == 1 and mapped == all_facets and all_facets:
            warnings.append(
                f"supporting_chunk_maps_all_facets:{cid}"
            )

    return facets, support, sorted(set(warnings))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Bootstrap answer-facet annotations for human review"
    )
    parser.add_argument("--benchmark", type=Path, default=DEFAULT_BENCHMARK)
    parser.add_argument("--pool", type=Path, default=DEFAULT_POOL)
    parser.add_argument("--draft", type=Path, default=DEFAULT_DRAFT)
    parser.add_argument("--review", type=Path, default=DEFAULT_REVIEW)
    parser.add_argument("--meta", type=Path, default=DEFAULT_META)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument(
        "--only",
        nargs="*",
        default=None,
        help="Optional question ids, e.g. --only q006 q024",
    )
    args = parser.parse_args()

    load_env(PROJECT_ROOT / ".env")
    api_key = os.getenv("DASHSCOPE_API_KEY")
    if not api_key:
        raise RuntimeError("DASHSCOPE_API_KEY is not set")

    client = OpenAI(
        api_key=api_key,
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    )

    benchmark = load_jsonl(args.benchmark)
    relevant_pool = load_relevant_pool(args.pool)

    only = set(args.only or [])
    targets = [
        q for q in benchmark
        if not q.get("is_out_of_scope", False)
        and (not only or q["id"] in only)
    ]

    if only:
        known = {q["id"] for q in targets}
        missing = sorted(only - known)
        if missing:
            raise RuntimeError(f"unknown/out-of-scope --only ids: {missing}")

    args.draft.parent.mkdir(parents=True, exist_ok=True)
    args.review.parent.mkdir(parents=True, exist_ok=True)

    draft_records: List[Dict] = []
    warning_counter: Counter[str] = Counter()

    for index, q in enumerate(targets, 1):
        qid = q["id"]
        chunks = relevant_pool.get(qid, [])
        if not chunks:
            raise RuntimeError(f"{qid}: no human-relevant chunks in pool")

        print(f"[{index}/{len(targets)}] {qid}: bootstrapping facets ...")
        result = call_llm(
            client,
            args.model,
            build_prompt(q, chunks),
            args.retries,
        )
        facets, support, warnings = normalize_result(
            qid, chunks, result
        )

        for warning in warnings:
            warning_counter[warning.split(":", 1)[0]] += 1

        draft_records.append(
            {
                "id": qid,
                "question": q["question"],
                "query_type": q.get("type", ""),
                "reference_answer": q["reference_answer"],
                "facets": facets,
                "chunk_support": support,
                "primary_gold_chunk_ids": q.get(
                    "primary_gold_chunk_ids", []
                ),
                "supporting_gold_chunk_ids": q.get(
                    "supporting_gold_chunk_ids", []
                ),
                "bootstrap_warnings": warnings,
                "review_status": "pending",
                "reviewer_note": "",
            }
        )

    with args.draft.open("w", encoding="utf-8") as f:
        for record in draft_records:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    review_fields = [
        "question_id",
        "question",
        "query_type",
        "facet_id",
        "facet_text",
        "supporting_chunk_ids",
        "primary_chunk_ids_supporting_facet",
        "bootstrap_warnings",
        "facet_valid",
        "reviewer_note",
    ]

    with args.review.open(
        "w",
        encoding="utf-8-sig",
        newline="",
    ) as f:
        writer = csv.DictWriter(f, fieldnames=review_fields)
        writer.writeheader()

        for record in draft_records:
            support = record["chunk_support"]
            primary = set(record["primary_gold_chunk_ids"])

            for facet in record["facets"]:
                fid = facet["facet_id"]
                supporting = sorted(
                    cid
                    for cid, ids in support.items()
                    if fid in ids
                )
                primary_support = sorted(
                    cid for cid in supporting if cid in primary
                )

                writer.writerow(
                    {
                        "question_id": record["id"],
                        "question": record["question"],
                        "query_type": record["query_type"],
                        "facet_id": fid,
                        "facet_text": facet["text"],
                        "supporting_chunk_ids": "|".join(supporting),
                        "primary_chunk_ids_supporting_facet": "|".join(
                            primary_support
                        ),
                        "bootstrap_warnings": "|".join(
                            record["bootstrap_warnings"]
                        ),
                        "facet_valid": "",
                        "reviewer_note": "",
                    }
                )

    facet_counts = [len(r["facets"]) for r in draft_records]
    meta = {
        "model": args.model,
        "questions_processed": len(draft_records),
        "total_facets": sum(facet_counts),
        "avg_facets_per_question": (
            round(sum(facet_counts) / len(facet_counts), 4)
            if facet_counts else 0
        ),
        "warning_categories": dict(warning_counter),
        "gold_usage_policy": (
            "reference_answer and human relevance labels are used ONLY to "
            "bootstrap evaluation annotations; they must never be exposed to "
            "the retrieval/selection method at inference time."
        ),
        "review_requirement": (
            "All generated facets and chunk-to-facet mappings are drafts and "
            "must be human-reviewed before being treated as benchmark gold."
        ),
    }
    with args.meta.open("w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    print("\n===== FACET BOOTSTRAP =====")
    print(f"questions={meta['questions_processed']}")
    print(f"total_facets={meta['total_facets']}")
    print(
        "avg_facets_per_question="
        f"{meta['avg_facets_per_question']}"
    )
    print(f"warning_categories={meta['warning_categories']}")
    print("\nFiles:")
    print(f"draft : {args.draft}")
    print(f"review: {args.review}")
    print(f"meta  : {args.meta}")
    print(
        "\nIMPORTANT: this is a bootstrap draft. "
        "Do not use it as gold until human review is complete."
    )


if __name__ == "__main__":
    main()
