"""SetR requirement-coverage diagnostic v2.3.

Purpose
-------
Use the requirements already produced by the SetR-style zero-shot selector.
Do NOT re-decompose the query.

For each requirement, score support from each Dense Top-5 passage:
    0 = no support
    1 = weak/background
    2 = sufficient partial/direct support
    3 = strong/direct support

Support rule is aligned with the human facet annotation protocol:
- directly readable from passage => supported
- one short direct inference/calculation using question + passage => supported
- external knowledge => not supported

Prediction:
- selected set sufficient iff every generated requirement has max support >= 2
  among selected passages.
- if a missing requirement has support >= 2 in an unselected Top-5 passage:
      predicted selector_limited
- if a missing requirement has no support >= 2 anywhere in Top-5:
      predicted retrieval_limited

Gold evaluation classification comes ONLY from v2.1 and is not shown to scorer.

Important:
This diagnostic can detect failures only if SetR's own generated requirements
contain the truly missing information need. If it predicts "sufficient" on a
gold failure, that indicates requirement omission and/or support overestimation.

Run:
    python3 tests/diagnose_setr_requirement_coverage_v23.py

First run: up to 49 Qwen Flash calls; cached thereafter.
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


DEFAULT_POOL = PROJECT_ROOT / "tests" / "retrieval_pool_v1.csv"
DEFAULT_SETR = (
    PROJECT_ROOT
    / "tests"
    / "results"
    / "setr_zeroshot_baseline_v20.json"
)
DEFAULT_DIAG = (
    PROJECT_ROOT
    / "tests"
    / "results"
    / "setr_failure_diagnostic_v21.json"
)
DEFAULT_CACHE = (
    PROJECT_ROOT
    / ".cache"
    / "rag"
    / "setr_requirement_support_v23.json"
)
DEFAULT_OUTPUT = (
    PROJECT_ROOT
    / "tests"
    / "results"
    / "setr_requirement_coverage_v23.json"
)

VERSION = "setr_requirement_coverage_v23"
SUPPORT_THRESHOLD = 2


def strip_json_fence(text: str) -> str:
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, count=1)
        text = re.sub(r"\s*```$", "", text, count=1)
    return text.strip()


def load_pool(path: Path) -> Dict[str, Dict[str, Dict]]:
    out: Dict[str, Dict[str, Dict]] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            out.setdefault(row["question_id"], {})[
                row["chunk_id"]
            ] = row
    return out


def normalize_matrix(
    raw,
    n_req: int,
    n_cand: int,
) -> List[List[int]]:
    """Accept a few common JSON shapes and return req x candidate matrix."""

    if isinstance(raw, dict):
        for key in ("support_matrix", "matrix", "scores", "support"):
            if key in raw:
                raw = raw[key]
                break

    if isinstance(raw, dict):
        # requirement-indexed dict: {"r1":[...], "r2":[...]}
        vals = list(raw.values())
        if all(isinstance(x, list) for x in vals):
            raw = vals

    if not isinstance(raw, list):
        raise ValueError(f"matrix is not list: {type(raw).__name__}")

    matrix = []

    for row in raw:
        if isinstance(row, dict):
            # candidate-indexed dict inside row
            row = list(row.values())

        if not isinstance(row, list):
            raise ValueError("matrix row is not list")

        converted = []
        for x in row:
            if isinstance(x, bool):
                x = int(x)
            if isinstance(x, str):
                x = x.strip()
                if not re.fullmatch(r"-?\d+(?:\.\d+)?", x):
                    raise ValueError(f"non-numeric score: {x!r}")
                x = float(x)

            if not isinstance(x, (int, float)):
                raise ValueError(f"invalid score type: {type(x).__name__}")

            xi = int(round(float(x)))
            if xi < 0 or xi > 3:
                raise ValueError(f"score outside 0..3: {x}")
            converted.append(xi)

        matrix.append(converted)

    # Exact expected shape.
    if len(matrix) == n_req and all(len(r) == n_cand for r in matrix):
        return matrix

    # Transposed candidate x requirement shape.
    if len(matrix) == n_cand and all(len(r) == n_req for r in matrix):
        return [
            [matrix[c][r] for c in range(n_cand)]
            for r in range(n_req)
        ]

    raise ValueError(
        f"shape=({len(matrix)}, "
        f"{[len(r) for r in matrix]}), "
        f"expected=({n_req},{n_cand})"
    )


class RequirementSupportScorer:
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

    def score(
        self,
        qid: str,
        question: str,
        requirements: Sequence[str],
        candidate_ids: Sequence[str],
        candidate_texts: Sequence[str],
    ) -> List[List[int]]:
        cached = self.cache.get(qid)
        if (
            isinstance(cached, dict)
            and cached.get("version") == VERSION
            and cached.get("model") == self.model
            and cached.get("question") == question
            and cached.get("requirements") == list(requirements)
            and cached.get("candidate_ids") == list(candidate_ids)
            and cached.get("matrix")
        ):
            return cached["matrix"]

        req_text = "\n".join(
            f"R{i+1}: {r}"
            for i, r in enumerate(requirements)
        )
        cand_text = "\n\n".join(
            f"C{i+1} [{cid}]\n{text}"
            for i, (cid, text) in enumerate(
                zip(candidate_ids, candidate_texts)
            )
        )

        prompt = f"""
你正在评估RAG候选证据对“已经给定的信息需求”的支撑程度。
不要重新生成或修改信息需求。

用户问题：
{question}

信息需求：
{req_text}

Dense Top-5候选：
{cand_text}

请逐一判断每个 requirement × candidate 的证据支撑程度：

0 = 完全不支持，或仅主题相关
1 = 只有弱背景信息，不能实际回答该需求
2 = 能直接支持该需求的主要内容；或结合“问题 + 该证据”做一步非常直接的推导/计算即可得到
3 = 对该需求有完整、明确、直接的支持

规则：
- 允许一步直接推导、简单计算、直接阅读代码得到算法行为。
- 不允许依赖外部知识补全。
- 不要因为你自己知道答案而提高分数。
- 只评估证据，不回答问题。

共有 {len(requirements)} 个requirements，5个candidates。
只输出JSON：
{{
  "support_matrix": [
    [R1对C1的0-3分, R1对C2的分, ..., R1对C5的分],
    ...
  ]
}}
矩阵必须严格为 {len(requirements)} 行 × 5 列。
""".strip()

        last_error = None

        for attempt in range(3):
            extra = ""
            if attempt:
                extra = (
                    f"\n\n格式纠正：必须严格输出 "
                    f"{len(requirements)}x5 的整数矩阵，值只能为0/1/2/3。"
                )

            rsp = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "你是严格的RAG证据支撑评分器。"
                            "不得重写需求，不得使用外部知识。"
                        ),
                    },
                    {"role": "user", "content": prompt + extra},
                ],
                temperature=0.0,
                extra_body={"enable_thinking": False},
            )

            try:
                obj = json.loads(
                    strip_json_fence(rsp.choices[0].message.content)
                )
                matrix = normalize_matrix(
                    obj,
                    len(requirements),
                    len(candidate_ids),
                )

                self.cache[qid] = {
                    "version": VERSION,
                    "model": self.model,
                    "question": question,
                    "requirements": list(requirements),
                    "candidate_ids": list(candidate_ids),
                    "matrix": matrix,
                }
                self._save()
                return matrix

            except Exception as exc:
                last_error = exc
                print(
                    f"  WARNING {qid} support attempt "
                    f"{attempt+1}/3: {exc}"
                )

        raise RuntimeError(
            f"{qid}: support scoring failed: {last_error}"
        )


def main() -> None:
    load_dotenv(PROJECT_ROOT / ".env", override=False)

    ap = argparse.ArgumentParser()
    ap.add_argument("--pool", type=Path, default=DEFAULT_POOL)
    ap.add_argument("--setr", type=Path, default=DEFAULT_SETR)
    ap.add_argument("--diag", type=Path, default=DEFAULT_DIAG)
    ap.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    ap.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = ap.parse_args()

    pool = load_pool(args.pool)

    setr = json.loads(args.setr.read_text(encoding="utf-8"))
    diag = json.loads(args.diag.read_text(encoding="utf-8"))

    setr_by_id = {
        x["id"]: x
        for x in setr["per_query"]
    }
    gold_class = {
        x["id"]: x["classification"]
        for x in diag["per_query"]
    }
    dense5_by_id = {
        x["id"]: x["dense_top5_ids"]
        for x in diag["per_query"]
    }

    scorer = RequirementSupportScorer(
        GENERATION_MODEL,
        args.cache,
    )

    rows = []

    # positive class = any failure (selector/retrieval limited)
    tp = fp = tn = fn = 0

    class_correct = 0
    class_total = 0

    for pos, qid in enumerate(gold_class, 1):
        s = setr_by_id[qid]
        requirements = [
            str(x).strip()
            for x in s.get("requirements", [])
            if str(x).strip()
        ]

        if not requirements:
            raise RuntimeError(
                f"{qid}: SetR result has no requirements"
            )

        candidate_ids = [
            str(x) for x in dense5_by_id[qid]
        ]

        texts = []
        for cid in candidate_ids:
            prow = pool.get(qid, {}).get(cid)
            if prow is None:
                raise RuntimeError(
                    f"{qid}: missing pool row for {cid}"
                )
            texts.append(prow["chunk_text"])

        matrix = scorer.score(
            qid,
            s["question"],
            requirements,
            candidate_ids,
            texts,
        )

        selected = set(
            str(x) for x in s["setr_selected_ids"]
        )
        selected_indices = [
            i for i, cid in enumerate(candidate_ids)
            if cid in selected
        ]

        missing_req_indices = []
        req_details = []

        for r_idx, req in enumerate(requirements):
            selected_best = max(
                (matrix[r_idx][i] for i in selected_indices),
                default=0,
            )
            top5_best = max(matrix[r_idx])

            selected_supported = (
                selected_best >= SUPPORT_THRESHOLD
            )
            top5_supported = (
                top5_best >= SUPPORT_THRESHOLD
            )

            if not selected_supported:
                missing_req_indices.append(r_idx)

            supporting_unselected = [
                candidate_ids[i]
                for i, score in enumerate(matrix[r_idx])
                if score >= SUPPORT_THRESHOLD
                and candidate_ids[i] not in selected
            ]

            req_details.append(
                {
                    "requirement": req,
                    "selected_best_support": selected_best,
                    "top5_best_support": top5_best,
                    "selected_supported": selected_supported,
                    "top5_supported": top5_supported,
                    "supporting_unselected_ids": supporting_unselected,
                    "scores": matrix[r_idx],
                }
            )

        if not missing_req_indices:
            pred_class = "solved"
        else:
            all_missing_have_top5_support = all(
                req_details[i]["top5_supported"]
                for i in missing_req_indices
            )

            if all_missing_have_top5_support:
                pred_class = "selector_limited"
            else:
                pred_class = "retrieval_limited"

        gold = gold_class[qid]

        gold_fail = gold != "solved"
        pred_fail = pred_class != "solved"

        if gold_fail and pred_fail:
            outcome = "TP"
            tp += 1
        elif not gold_fail and pred_fail:
            outcome = "FP"
            fp += 1
        elif not gold_fail and not pred_fail:
            outcome = "TN"
            tn += 1
        else:
            outcome = "FN"
            fn += 1

        if gold_fail:
            class_total += 1
            if pred_class == gold:
                class_correct += 1

        row = {
            "id": qid,
            "question": s["question"],
            "gold_class": gold,
            "predicted_class": pred_class,
            "outcome": outcome,
            "requirements": requirements,
            "selected_ids": list(selected),
            "candidate_ids": candidate_ids,
            "support_matrix": matrix,
            "missing_requirement_indices": missing_req_indices,
            "missing_requirements": [
                requirements[i]
                for i in missing_req_indices
            ],
            "requirement_details": req_details,
        }
        rows.append(row)

        print(
            f"[{pos}/{len(gold_class)}] {qid} "
            f"gold={gold} pred={pred_class} => {outcome}"
        )
        for i in missing_req_indices:
            d = req_details[i]
            print(
                "  missing:",
                d["requirement"],
                "| selected_best=",
                d["selected_best_support"],
                "top5_best=",
                d["top5_best_support"],
                "unselected_support=",
                d["supporting_unselected_ids"],
            )

    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    specificity = tn / (tn + fp) if (tn + fp) else 0.0
    accuracy = (tp + tn) / len(rows) if rows else 0.0
    f1 = (
        2 * precision * recall / (precision + recall)
        if precision + recall
        else 0.0
    )

    summary = {
        "query_count": len(rows),
        "support_threshold": SUPPORT_THRESHOLD,
        "tp": tp,
        "fp": fp,
        "tn": tn,
        "fn": fn,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "specificity": round(specificity, 4),
        "accuracy": round(accuracy, 4),
        "f1": round(f1, 4),
        "failure_type_accuracy": (
            round(class_correct / class_total, 4)
            if class_total
            else None
        ),
        "true_positive_ids": [
            x["id"] for x in rows if x["outcome"] == "TP"
        ],
        "false_positive_ids": [
            x["id"] for x in rows if x["outcome"] == "FP"
        ],
        "false_negative_ids": [
            x["id"] for x in rows if x["outcome"] == "FN"
        ],
        "failure_type_errors": [
            {
                "id": x["id"],
                "gold": x["gold_class"],
                "predicted": x["predicted_class"],
            }
            for x in rows
            if x["gold_class"] != "solved"
            and x["gold_class"] != x["predicted_class"]
        ],
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(
            {
                "config": {
                    "model": GENERATION_MODEL,
                    "version": VERSION,
                    "requirements_source": (
                        "SetR-style selector v2.0, generated before evaluation"
                    ),
                    "uses_gold_for_prediction": False,
                    "uses_reference_for_prediction": False,
                    "uses_eval_facets_for_prediction": False,
                    "one_step_inference_allowed": True,
                },
                "summary": summary,
                "per_query": rows,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print("\n===== SETR REQUIREMENT COVERAGE V2.3 =====")
    for k, v in summary.items():
        print(f"{k}={v}")

    print("\n===== GOLD FAILURE DETAILS =====")
    for x in rows:
        if x["gold_class"] == "solved":
            continue
        print(
            "\n",
            x["id"],
            "gold=", x["gold_class"],
            "pred=", x["predicted_class"],
        )
        print(" requirements:", x["requirements"])
        print(" selected:", x["selected_ids"])
        print(" missing:", x["missing_requirements"])
        for d in x["requirement_details"]:
            print(
                "  ",
                d["requirement"],
                "selected_best=", d["selected_best_support"],
                "top5_best=", d["top5_best_support"],
                "unselected=", d["supporting_unselected_ids"],
            )

    print("\noutput:", args.output)


if __name__ == "__main__":
    main()
