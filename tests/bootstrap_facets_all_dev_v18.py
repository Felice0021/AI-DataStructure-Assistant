"""Bootstrap answer-facet annotations for ALL in-scope Dev queries (v1.8).

Purpose
-------
Expand the current 8 manually reviewed facet annotations to all 49 in-scope
Dev questions.

IMPORTANT:
- This is EVALUATION annotation only.
- reference_answer and relevance labels ARE allowed here.
- These facets must NEVER be fed into retrieval/selection methods.

Existing reviewed facet rows are copied unchanged.
Only missing questions are drafted by the LLM.

Outputs
-------
tests/annotations/datastructureqa_dev_v18_facets_draft.jsonl
tests/annotations/datastructureqa_dev_v18_facets_report.json

Run
---
python3 tests/bootstrap_facets_all_dev_v18.py

The first run may make ~41 Qwen Flash calls. Results are cached.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
from pathlib import Path
from typing import Dict, List, Sequence

from dotenv import load_dotenv
from openai import OpenAI

PROJECT_ROOT_FOR_IMPORT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT_FOR_IMPORT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT_FOR_IMPORT))

from rag.config import GENERATION_MODEL, PROJECT_ROOT


DEFAULT_BENCHMARK = (
    PROJECT_ROOT / "tests" / "benchmarks" / "datastructureqa_dev_v1.jsonl"
)
DEFAULT_POOL = PROJECT_ROOT / "tests" / "retrieval_pool_v1.csv"
DEFAULT_EXISTING = (
    PROJECT_ROOT
    / "tests"
    / "benchmarks"
    / "datastructureqa_dev_v1_facets_8q_v1.jsonl"
)
DEFAULT_CACHE = (
    PROJECT_ROOT
    / ".cache"
    / "rag"
    / "facets_all_dev_v18_drafts.json"
)
DEFAULT_OUTPUT = (
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

VERSION = "v18_all_dev_facet_bootstrap"


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


def load_pool(path: Path) -> Dict[str, Dict[str, Dict]]:
    by_qid: Dict[str, Dict[str, Dict]] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            qid = row["question_id"]
            cid = row["chunk_id"]
            by_qid.setdefault(qid, {})[cid] = row
    return by_qid


def strip_json_fence(text: str) -> str:
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, count=1)
        text = re.sub(r"\s*```$", "", text, count=1)
    return text.strip()


def normalize_draft(
    qid: str,
    question: str,
    raw: Dict,
    relevant_chunks: Sequence[Dict],
) -> Dict:
    facets_raw = raw.get("facets", [])
    facets = []

    for i, item in enumerate(facets_raw, 1):
        if isinstance(item, str):
            desc = item.strip()
            fid = f"f{i}"
        elif isinstance(item, dict):
            desc = str(
                item.get("description")
                or item.get("text")
                or item.get("facet")
                or ""
            ).strip()
            fid = str(item.get("facet_id") or f"f{i}").strip()
        else:
            continue

        if not desc:
            continue

        facets.append(
            {
                "facet_id": fid,
                "description": desc,
            }
        )

    if not facets:
        raise ValueError(f"{qid}: no valid facets")

    # Canonicalize IDs to f1..fN for easier review.
    id_map = {}
    canonical = []
    for i, item in enumerate(facets, 1):
        new_id = f"f{i}"
        id_map[item["facet_id"]] = new_id
        canonical.append(
            {
                "facet_id": new_id,
                "description": item["description"],
            }
        )
    facets = canonical
    facet_ids = {x["facet_id"] for x in facets}

    valid_chunk_ids = {
        str(x["chunk_id"]) for x in relevant_chunks
    }

    raw_support = raw.get("chunk_support", {})
    support: Dict[str, List[str]] = {}

    if isinstance(raw_support, dict):
        for cid, fids in raw_support.items():
            cid = str(cid)
            if cid not in valid_chunk_ids:
                continue
            if not isinstance(fids, list):
                continue

            mapped = []
            for fid in fids:
                fid = str(fid)
                canon = id_map.get(fid, fid)
                if canon in facet_ids and canon not in mapped:
                    mapped.append(canon)
            support[cid] = mapped

    # Ensure every relevant chunk is explicitly represented,
    # even if it supports no core facet.
    for cid in valid_chunk_ids:
        support.setdefault(cid, [])

    return {
        "id": qid,
        "question": question,
        "facets": facets,
        "chunk_support": support,
        "review_status": "needs_human_review",
        "annotation_source": "llm_bootstrap_v18",
    }


def validate_row(
    row: Dict,
    relevant_chunks: Sequence[Dict],
) -> List[Dict]:
    warnings = []

    facet_ids = {
        str(x["facet_id"])
        for x in row.get("facets", [])
    }
    support = row.get("chunk_support", {})

    covered_facets = set()
    for cid, fids in support.items():
        covered_facets.update(fids)

    for fid in sorted(facet_ids - covered_facets):
        warnings.append(
            {
                "type": "facet_without_support",
                "facet_id": fid,
            }
        )

    for chunk in relevant_chunks:
        cid = str(chunk["chunk_id"])
        label = int(chunk["relevance_label"])
        mapped = set(support.get(cid, []))

        if label == 2 and mapped != facet_ids:
            warnings.append(
                {
                    "type": "label2_not_cover_all_facets",
                    "chunk_id": cid,
                    "mapped": sorted(mapped),
                    "expected": sorted(facet_ids),
                }
            )

        # Label-1 chunks may legitimately support all facets,
        # but flag for human inspection because this may indicate
        # that the chunk should actually be label 2.
        if label == 1 and facet_ids and mapped == facet_ids:
            warnings.append(
                {
                    "type": "label1_maps_all_facets",
                    "chunk_id": cid,
                }
            )

    return warnings


class FacetBootstrapper:
    def __init__(self, model: str, cache_path: Path) -> None:
        key = os.getenv("DASHSCOPE_API_KEY")
        if not key:
            raise RuntimeError("DASHSCOPE_API_KEY is not set")

        self.model = model
        self.cache_path = cache_path
        self.client = OpenAI(
            api_key=key,
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        )

        self.cache = {}
        if cache_path.exists():
            try:
                self.cache = json.loads(
                    cache_path.read_text(encoding="utf-8")
                )
            except Exception:
                self.cache = {}

    def _save(self) -> None:
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.cache_path.write_text(
            json.dumps(self.cache, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def draft(
        self,
        qid: str,
        question: str,
        reference_answer: str,
        relevant_chunks: Sequence[Dict],
    ) -> Dict:
        cached = self.cache.get(qid)
        if (
            isinstance(cached, dict)
            and cached.get("version") == VERSION
            and cached.get("model") == self.model
            and cached.get("question") == question
            and cached.get("draft")
        ):
            return cached["draft"]

        chunk_text = "\n\n".join(
            (
                f"[{x['chunk_id']}] relevance_label={x['relevance_label']}\n"
                f"{x['chunk_text']}"
            )
            for x in relevant_chunks
        )

        prompt = f"""
你正在为RAG评测构造“答案要点（answer facets）”人工标注草稿。
这是评测标注，不是检索阶段，因此可以使用参考答案和人工相关性标签。

问题：
{question}

参考答案：
{reference_answer}

人工判定为相关的chunks：
{chunk_text}

任务：
1. 把参考答案拆成最少数量、互不重叠、答案必需的核心要点。
2. 每个要点应当能独立判断“某个证据是否支持了这一部分答案”。
3. 不要生成仅仅重复问题措辞的总括性要点。
4. 一般1~5个facet。
5. 对每个相关chunk，标出它支持哪些facet。

证据支持规则：
- 如果facet可以直接从chunk中读出，算支持。
- 如果结合“用户问题 + chunk”即可做一步非常直接的推导/计算，也算支持。
- 不允许依赖外部知识补全。
- relevance_label=1 表示“有用的部分证据”，允许一个核心facet都不支持，只提供背景。
- relevance_label=2 表示“该chunk单独基本足以回答完整问题”，原则上应支持全部核心facet。
- 不要为了让label=1看起来有用而强行映射facet。

只输出JSON：
{{
  "facets": [
    {{"facet_id":"f1","description":"要点1"}},
    {{"facet_id":"f2","description":"要点2"}}
  ],
  "chunk_support": {{
    "chunk_id_1": ["f1"],
    "chunk_id_2": ["f1","f2"]
  }}
}}
""".strip()

        last_error = None
        for attempt in range(3):
            rsp = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "你是严格的数据集标注助手。"
                            "只构造RAG评测facet和证据映射。"
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0.0,
                extra_body={"enable_thinking": False},
            )

            try:
                raw = json.loads(
                    strip_json_fence(rsp.choices[0].message.content)
                )
                draft = normalize_draft(
                    qid,
                    question,
                    raw,
                    relevant_chunks,
                )
                self.cache[qid] = {
                    "version": VERSION,
                    "model": self.model,
                    "question": question,
                    "draft": draft,
                }
                self._save()
                return draft
            except Exception as exc:
                last_error = exc
                print(
                    f"  WARNING {qid} attempt {attempt+1}/3: {exc}"
                )

        raise RuntimeError(
            f"{qid}: failed to draft facets: {last_error}"
        )


def main() -> None:
    load_dotenv(PROJECT_ROOT / ".env", override=False)

    ap = argparse.ArgumentParser()
    ap.add_argument("--benchmark", type=Path, default=DEFAULT_BENCHMARK)
    ap.add_argument("--pool", type=Path, default=DEFAULT_POOL)
    ap.add_argument("--existing", type=Path, default=DEFAULT_EXISTING)
    ap.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    ap.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    ap.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = ap.parse_args()

    benchmark = [
        x for x in load_jsonl(args.benchmark)
        if not x.get("is_out_of_scope", False)
    ]
    pool = load_pool(args.pool)

    existing_rows = {}
    if args.existing.exists():
        existing_rows = {
            x["id"]: x for x in load_jsonl(args.existing)
        }

    bootstrapper = FacetBootstrapper(
        GENERATION_MODEL,
        args.cache,
    )

    all_rows = []
    report = {
        "generation_model": GENERATION_MODEL,
        "question_count": len(benchmark),
        "existing_reviewed_count": 0,
        "new_draft_count": 0,
        "warnings": [],
        "per_question": {},
    }

    for pos, q in enumerate(benchmark, 1):
        qid = q["id"]

        gold_ids = [
            str(x) for x in q.get("gold_chunk_ids", [])
        ]

        relevant_chunks = []
        for cid in gold_ids:
            row = pool.get(qid, {}).get(cid)
            if row is None:
                raise RuntimeError(
                    f"{qid}: gold chunk {cid} missing from pool"
                )

            label = str(row.get("relevance_label", "")).strip()
            if label not in {"1", "2"}:
                raise RuntimeError(
                    f"{qid}/{cid}: gold has label={label!r}"
                )

            relevant_chunks.append(
                {
                    "chunk_id": cid,
                    "relevance_label": int(label),
                    "chunk_text": row["chunk_text"],
                }
            )

        if qid in existing_rows:
            row = existing_rows[qid]
            source = "existing_reviewed"
            report["existing_reviewed_count"] += 1
        else:
            row = bootstrapper.draft(
                qid,
                q["question"],
                q.get("reference_answer", ""),
                relevant_chunks,
            )
            source = "new_llm_draft"
            report["new_draft_count"] += 1

        warnings = validate_row(
            row,
            relevant_chunks,
        )

        report["per_question"][qid] = {
            "source": source,
            "facet_count": len(row.get("facets", [])),
            "relevant_chunk_count": len(relevant_chunks),
            "warning_count": len(warnings),
            "warnings": warnings,
        }

        for warning in warnings:
            report["warnings"].append(
                {
                    "question_id": qid,
                    **warning,
                }
            )

        all_rows.append(row)

        print(
            f"[{pos}/{len(benchmark)}] {qid} "
            f"source={source} "
            f"facets={len(row.get('facets', []))} "
            f"relevant_chunks={len(relevant_chunks)} "
            f"warnings={len(warnings)}"
        )

    args.output.parent.mkdir(parents=True, exist_ok=True)

    with args.output.open("w", encoding="utf-8") as f:
        for row in all_rows:
            f.write(
                json.dumps(row, ensure_ascii=False)
                + "\n"
            )

    args.report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    warning_counts = {}
    for warning in report["warnings"]:
        t = warning["type"]
        warning_counts[t] = warning_counts.get(t, 0) + 1

    total_facets = sum(
        len(x.get("facets", []))
        for x in all_rows
    )

    print("\n===== FACET BOOTSTRAP V1.8 =====")
    print("questions =", len(all_rows))
    print(
        "existing_reviewed =",
        report["existing_reviewed_count"],
    )
    print(
        "new_llm_drafts =",
        report["new_draft_count"],
    )
    print("total_facets =", total_facets)
    print(
        "avg_facets_per_question =",
        round(total_facets / len(all_rows), 4),
    )
    print("warning_count =", len(report["warnings"]))
    print("warning_types =", warning_counts)
    print("output =", args.output)
    print("report =", args.report)


if __name__ == "__main__":
    main()
