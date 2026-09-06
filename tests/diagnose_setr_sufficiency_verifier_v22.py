"""Post-selection sufficiency verifier diagnostic v2.2.

Goal
----
Given ONLY:
    question
    SetR-style selected passages

decide whether the selected evidence set is sufficient to answer the question,
and if not, describe the missing information requirements.

The verifier never sees:
    reference answer
    gold chunk IDs
    relevance labels
    evaluation facets
    unselected passages

Evaluation labels come from the human-reviewed facet annotations:
    sufficient gold = selected set has FullFacet=True
    insufficient gold = FullFacet=False

This is a detection-only diagnostic. It does NOT repair anything yet.

Outputs
-------
tests/results/setr_sufficiency_verifier_v22.json

Run
---
python3 tests/diagnose_setr_sufficiency_verifier_v22.py

First run: up to 49 Qwen Flash calls, then cached.
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
DEFAULT_CACHE = (
    PROJECT_ROOT
    / ".cache"
    / "rag"
    / "setr_sufficiency_verifier_v22.json"
)
DEFAULT_OUTPUT = (
    PROJECT_ROOT
    / "tests"
    / "results"
    / "setr_sufficiency_verifier_v22.json"
)

VERSION = "setr_sufficiency_verifier_v22"


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


class SufficiencyVerifier:
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

    def verify(
        self,
        qid: str,
        question: str,
        selected_ids: Sequence[str],
        selected_texts: Sequence[str],
    ) -> Dict:
        cached = self.cache.get(qid)
        if (
            isinstance(cached, dict)
            and cached.get("version") == VERSION
            and cached.get("model") == self.model
            and cached.get("question") == question
            and cached.get("selected_ids") == list(selected_ids)
        ):
            return cached

        evidence = "\n\n".join(
            f"[{cid}]\n{text}"
            for cid, text in zip(selected_ids, selected_texts)
        )

        prompt = f"""
你正在检查一个RAG系统已经选出的证据集合是否足以回答用户问题。

用户问题：
{question}

当前已选证据：
{evidence}

请严格判断：
1. 先识别这个问题完整回答所必需的信息点。
2. 只依据“当前已选证据”判断这些信息点是否都有明确支撑。
3. 如果任一必需信息点缺失、只有模糊背景、或需要外部知识才能补全，则判定 insufficient。
4. 不因为证据看起来相关就判定 sufficient。
5. 不使用外部知识补全答案。
6. 不要直接回答用户问题。

只输出JSON：
{{
  "sufficient": true,
  "missing_requirements": []
}}

如果不充分：
{{
  "sufficient": false,
  "missing_requirements": ["缺失信息1", "缺失信息2"]
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
                            "你是严格的RAG证据充分性验证器。"
                            "只能判断证据是否完整，不回答原问题。"
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0.0,
                extra_body={"enable_thinking": False},
            )

            try:
                obj = json.loads(
                    strip_json_fence(rsp.choices[0].message.content)
                )

                sufficient = obj.get("sufficient")
                if not isinstance(sufficient, bool):
                    raise ValueError(
                        f"sufficient is not bool: {sufficient!r}"
                    )

                missing = obj.get("missing_requirements", [])
                if not isinstance(missing, list):
                    raise ValueError(
                        "missing_requirements is not a list"
                    )

                missing = [
                    str(x).strip()
                    for x in missing
                    if str(x).strip()
                ]

                if sufficient and missing:
                    raise ValueError(
                        "sufficient=true but missing_requirements nonempty"
                    )
                if not sufficient and not missing:
                    raise ValueError(
                        "sufficient=false but missing_requirements empty"
                    )

                result = {
                    "version": VERSION,
                    "model": self.model,
                    "question": question,
                    "selected_ids": list(selected_ids),
                    "sufficient": sufficient,
                    "missing_requirements": missing,
                }

                self.cache[qid] = result
                self._save()
                return result

            except Exception as exc:
                last_error = exc
                print(
                    f"  WARNING {qid} attempt {attempt+1}/3: {exc}"
                )

        raise RuntimeError(
            f"{qid}: verification failed: {last_error}"
        )


def main() -> None:
    load_dotenv(PROJECT_ROOT / ".env", override=False)

    ap = argparse.ArgumentParser()
    ap.add_argument("--pool", type=Path, default=DEFAULT_POOL)
    ap.add_argument("--setr", type=Path, default=DEFAULT_SETR)
    ap.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    ap.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = ap.parse_args()

    pool = load_pool(args.pool)
    setr = json.loads(args.setr.read_text(encoding="utf-8"))

    verifier = SufficiencyVerifier(
        GENERATION_MODEL,
        args.cache,
    )

    rows = []

    # positive class = insufficient / failure requiring repair
    tp = fp = tn = fn = 0

    for pos, x in enumerate(setr["per_query"], 1):
        qid = x["id"]
        selected_ids = [
            str(v) for v in x["setr_selected_ids"]
        ]

        selected_texts = []
        for cid in selected_ids:
            prow = pool.get(qid, {}).get(cid)
            if prow is None:
                raise RuntimeError(
                    f"{qid}: selected chunk not in pool: {cid}"
                )
            selected_texts.append(prow["chunk_text"])

        result = verifier.verify(
            qid,
            x["question"],
            selected_ids,
            selected_texts,
        )

        # Human-reviewed evaluation label from v2.0 result.
        full = bool(
            x["setr_zeroshot"]["full_facet_coverage"]
        )
        gold_insufficient = not full
        pred_insufficient = not result["sufficient"]

        if gold_insufficient and pred_insufficient:
            outcome = "TP"
            tp += 1
        elif not gold_insufficient and pred_insufficient:
            outcome = "FP"
            fp += 1
        elif not gold_insufficient and not pred_insufficient:
            outcome = "TN"
            tn += 1
        else:
            outcome = "FN"
            fn += 1

        row = {
            "id": qid,
            "question": x["question"],
            "selected_ids": selected_ids,
            "gold_full_facet": full,
            "gold_insufficient": gold_insufficient,
            "predicted_sufficient": result["sufficient"],
            "predicted_insufficient": pred_insufficient,
            "missing_requirements": result["missing_requirements"],
            "outcome": outcome,
        }
        rows.append(row)

        print(
            f"[{pos}/{len(setr['per_query'])}] {qid} "
            f"gold={'INSUF' if gold_insufficient else 'SUF'} "
            f"pred={'INSUF' if pred_insufficient else 'SUF'} "
            f"=> {outcome}"
        )
        if result["missing_requirements"]:
            for m in result["missing_requirements"]:
                print("  missing:", m)

    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    specificity = tn / (tn + fp) if (tn + fp) else 0.0
    accuracy = (tp + tn) / len(rows) if rows else 0.0
    f1 = (
        2 * precision * recall / (precision + recall)
        if (precision + recall)
        else 0.0
    )

    false_positive_ids = [
        x["id"] for x in rows if x["outcome"] == "FP"
    ]
    false_negative_ids = [
        x["id"] for x in rows if x["outcome"] == "FN"
    ]
    true_positive_ids = [
        x["id"] for x in rows if x["outcome"] == "TP"
    ]

    summary = {
        "query_count": len(rows),
        "positive_class": "insufficient evidence set",
        "tp": tp,
        "fp": fp,
        "tn": tn,
        "fn": fn,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "specificity": round(specificity, 4),
        "accuracy": round(accuracy, 4),
        "f1": round(f1, 4),
        "true_positive_ids": true_positive_ids,
        "false_positive_ids": false_positive_ids,
        "false_negative_ids": false_negative_ids,
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(
            {
                "config": {
                    "model": GENERATION_MODEL,
                    "version": VERSION,
                    "verifier_uses_gold": False,
                    "verifier_uses_reference": False,
                    "verifier_uses_eval_facets": False,
                    "verifier_sees_unselected_candidates": False,
                },
                "summary": summary,
                "per_query": rows,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print("\n===== SETR SUFFICIENCY VERIFIER V2.2 =====")
    for k, v in summary.items():
        print(f"{k}={v}")

    print("\n===== ERROR DETAILS =====")
    for x in rows:
        if x["outcome"] in {"FP", "FN"}:
            print("\n", x["id"], x["outcome"])
            print(" question:", x["question"])
            print(" selected:", x["selected_ids"])
            print(
                " verifier missing:",
                x["missing_requirements"],
            )

    print("\noutput:", args.output)


if __name__ == "__main__":
    main()
