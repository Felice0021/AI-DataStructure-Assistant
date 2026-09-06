"""SetR-style zero-shot set-selection baseline v2.0.

Purpose
-------
Evaluate a strong prior-art-inspired baseline on exactly the same Dense Top-5
candidate pool used by NeedAnchorSet.

This is NOT an implementation of the trained SETR model. It is a transparent
zero-shot LLM baseline inspired by SetR's published information-requirement
identification + set-wise passage selection procedure.

Selection input:
    question + Dense Top-5 passages only

Selection does NOT see:
    reference answer
    relevance labels
    gold chunks
    evaluation facets

Evaluation:
    AvgK
    GoldRecall
    PrimaryHit
    FacetRecall
    FullFacet

It also performs paired comparisons against NeedAnchorSet, Dense@2 and Dense@3.

Run
---
python3 tests/run_setr_zeroshot_baseline_v20.py

First run: up to 49 Qwen Flash calls.
Cached thereafter.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import random
import re
import sys
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

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
DEFAULT_FACETS = (
    PROJECT_ROOT
    / "tests"
    / "annotations"
    / "datastructureqa_dev_v18_facets_reviewed.jsonl"
)
DEFAULT_V17 = (
    PROJECT_ROOT
    / "tests"
    / "results"
    / "adaptive_budget_v17_full_facets.json"
)
DEFAULT_CACHE = (
    PROJECT_ROOT
    / ".cache"
    / "rag"
    / "setr_zeroshot_v20.json"
)
DEFAULT_OUTPUT = (
    PROJECT_ROOT
    / "tests"
    / "results"
    / "setr_zeroshot_baseline_v20.json"
)

VERSION = "setr_style_zeroshot_v20"
BOOTSTRAP_N = 20000
SEED = 20260902


def load_jsonl(path: Path) -> Dict[str, Dict]:
    out = {}
    with path.open("r", encoding="utf-8") as f:
        for no, raw in enumerate(f, 1):
            if not raw.strip():
                continue
            try:
                obj = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise RuntimeError(f"{path}:{no}: {exc}") from exc
            out[obj["id"]] = obj
    return out


def load_dense5(path: Path) -> Dict[str, List[Dict]]:
    out: Dict[str, List[Dict]] = {}

    with path.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            raw = str(row.get("dense_rank", "")).strip()
            if not raw:
                continue
            try:
                rank = int(float(raw))
            except ValueError:
                continue
            if not 1 <= rank <= 5:
                continue

            out.setdefault(row["question_id"], []).append(
                {
                    "chunk_id": row["chunk_id"],
                    "rank": rank,
                    "text": row["chunk_text"],
                }
            )

    for qid in out:
        out[qid].sort(key=lambda x: x["rank"])

    return out


def strip_json_fence(text: str) -> str:
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, count=1)
        text = re.sub(r"\s*```$", "", text, count=1)
    return text.strip()


class ZeroShotSetSelector:
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

    def select(
        self,
        qid: str,
        question: str,
        candidates: Sequence[Dict],
    ) -> Dict:
        candidate_ids = [x["chunk_id"] for x in candidates]

        cached = self.cache.get(qid)
        if (
            isinstance(cached, dict)
            and cached.get("version") == VERSION
            and cached.get("model") == self.model
            and cached.get("question") == question
            and cached.get("candidate_ids") == candidate_ids
            and cached.get("selected_ids")
        ):
            return cached

        passages = "\n\n".join(
            f"[{x['chunk_id']}]\n{x['text']}"
            for x in candidates
        )

        prompt = f"""
你正在为RAG系统从候选证据中选择一个“小而充分”的证据集合。

用户问题：
{question}

候选证据：
{passages}

请按以下原则完成：
1. 先识别回答该问题真正需要满足的、互不重复的信息需求。
2. 判断每条候选证据分别能支持哪些信息需求。
3. 选择一个证据子集，使它们作为一个集合尽可能完整覆盖这些信息需求。
4. 避免选择只重复已有信息、没有新增回答价值的证据。
5. 在覆盖充分的前提下，证据数量应尽可能少。
6. 不要求固定选择几条；1到5条均可。
7. 只能选择上面给出的chunk_id。
8. 不使用外部知识，不回答原问题。

只输出JSON：
{{
  "requirements": ["需求1", "需求2"],
  "selected_ids": ["chunk_id_1", "chunk_id_2"]
}}
""".strip()

        last_error = None

        for attempt in range(3):
            extra = ""
            if attempt:
                extra = (
                    "\n\n格式纠正：selected_ids必须是候选chunk_id的非空子集，"
                    "不要输出候选之外的ID。"
                )

            rsp = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "只做RAG集合级证据选择。"
                            "目标是完整覆盖信息需求，同时减少冗余证据。"
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

                requirements = [
                    str(x).strip()
                    for x in obj.get("requirements", [])
                    if str(x).strip()
                ]

                raw_ids = obj.get("selected_ids", [])
                if not isinstance(raw_ids, list):
                    raise ValueError("selected_ids is not a list")

                selected = []
                seen = set()
                allowed = set(candidate_ids)

                for x in raw_ids:
                    cid = str(x).strip()
                    if cid not in allowed:
                        raise ValueError(
                            f"invalid selected chunk id: {cid}"
                        )
                    if cid not in seen:
                        seen.add(cid)
                        selected.append(cid)

                if not selected:
                    raise ValueError("empty selected_ids")

                result = {
                    "version": VERSION,
                    "model": self.model,
                    "question": question,
                    "candidate_ids": candidate_ids,
                    "requirements": requirements,
                    "selected_ids": selected,
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
            f"{qid}: zero-shot set selection failed: {last_error}"
        )


def evaluate(
    selected_ids: Sequence[str],
    benchmark: Dict,
    facets: Dict,
) -> Dict:
    selected = set(selected_ids)
    gold = set(str(x) for x in benchmark.get("gold_chunk_ids", []))
    primary = set(
        str(x) for x in benchmark.get("primary_gold_chunk_ids", [])
    )

    facet_ids = {
        str(x["facet_id"])
        for x in facets.get("facets", [])
    }
    support = facets.get("chunk_support", {})

    covered = set()
    for cid in selected_ids:
        covered.update(support.get(cid, []))
    covered &= facet_ids

    facet_recall = (
        len(covered) / len(facet_ids)
        if facet_ids
        else 0.0
    )

    return {
        "k": len(selected_ids),
        "gold_recall": (
            len(selected & gold) / len(gold)
            if gold
            else 0.0
        ),
        "has_primary_gold": bool(primary),
        "primary_hit": (
            bool(selected & primary)
            if primary
            else None
        ),
        "facet_recall": facet_recall,
        "full_facet_coverage": (
            abs(facet_recall - 1.0) < 1e-9
        ),
    }


def aggregate(rows: List[Dict], key: str) -> Dict:
    vals = [x[key] for x in rows]
    pvals = [x for x in vals if x["has_primary_gold"]]

    return {
        "mean_k": round(
            sum(x["k"] for x in vals) / len(vals), 4
        ),
        "mean_gold_recall": round(
            sum(x["gold_recall"] for x in vals) / len(vals), 4
        ),
        "primary_hit_rate": round(
            sum(bool(x["primary_hit"]) for x in pvals) / len(pvals),
            4,
        ) if pvals else None,
        "mean_facet_recall": round(
            sum(x["facet_recall"] for x in vals) / len(vals), 4
        ),
        "full_facet_coverage_rate": round(
            sum(bool(x["full_facet_coverage"]) for x in vals)
            / len(vals),
            4,
        ),
    }


def percentile(xs: List[float], p: float) -> float:
    ys = sorted(xs)
    if len(ys) == 1:
        return ys[0]
    pos = (len(ys) - 1) * p
    lo = int(pos)
    hi = min(lo + 1, len(ys) - 1)
    frac = pos - lo
    return ys[lo] * (1.0 - frac) + ys[hi] * frac


def bootstrap_ci(
    diffs: List[float],
    seed: int,
) -> Tuple[float, float]:
    rng = random.Random(seed)
    n = len(diffs)
    means = []

    for _ in range(BOOTSTRAP_N):
        s = 0.0
        for _ in range(n):
            s += diffs[rng.randrange(n)]
        means.append(s / n)

    return (
        percentile(means, 0.025),
        percentile(means, 0.975),
    )


def paired(
    rows: List[Dict],
    method_key: str,
    baseline_key: str,
) -> Dict:
    fd = []
    kd = []
    wins = []
    losses = []

    for row in rows:
        a = row[method_key]
        b = row[baseline_key]

        diff = a["facet_recall"] - b["facet_recall"]
        fd.append(diff)
        kd.append(a["k"] - b["k"])

        if diff > 1e-9:
            wins.append(row["id"])
        elif diff < -1e-9:
            losses.append(row["id"])

    fci = bootstrap_ci(fd, SEED)
    kci = bootstrap_ci(kd, SEED + 1)

    return {
        "method": method_key,
        "baseline": baseline_key,
        "mean_facet_recall_diff": round(sum(fd) / len(fd), 4),
        "facet_diff_95ci": [
            round(fci[0], 4),
            round(fci[1], 4),
        ],
        "facet_win_count": len(wins),
        "facet_loss_count": len(losses),
        "facet_win_ids": wins,
        "facet_loss_ids": losses,
        "mean_k_diff": round(sum(kd) / len(kd), 4),
        "k_diff_95ci": [
            round(kci[0], 4),
            round(kci[1], 4),
        ],
    }


def main() -> None:
    load_dotenv(PROJECT_ROOT / ".env", override=False)

    ap = argparse.ArgumentParser()
    ap.add_argument("--benchmark", type=Path, default=DEFAULT_BENCHMARK)
    ap.add_argument("--pool", type=Path, default=DEFAULT_POOL)
    ap.add_argument("--facets", type=Path, default=DEFAULT_FACETS)
    ap.add_argument("--v17", type=Path, default=DEFAULT_V17)
    ap.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    ap.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = ap.parse_args()

    benchmark = load_jsonl(args.benchmark)
    facets = load_jsonl(args.facets)
    dense5 = load_dense5(args.pool)

    v17 = json.loads(args.v17.read_text(encoding="utf-8"))
    v17_by_id = {x["id"]: x for x in v17["per_query"]}

    selector = ZeroShotSetSelector(
        GENERATION_MODEL,
        args.cache,
    )

    rows = []

    qids = [
        qid
        for qid, q in benchmark.items()
        if not q.get("is_out_of_scope", False)
    ]

    for pos, qid in enumerate(qids, 1):
        q = benchmark[qid]
        candidates = dense5.get(qid, [])

        if len(candidates) != 5:
            raise RuntimeError(
                f"{qid}: expected Dense Top5, got {len(candidates)}"
            )

        sel = selector.select(
            qid,
            q["question"],
            candidates,
        )

        setr_eval = evaluate(
            sel["selected_ids"],
            q,
            facets[qid],
        )

        old = v17_by_id[qid]["methods"]

        row = {
            "id": qid,
            "question": q["question"],
            "requirements": sel["requirements"],
            "setr_selected_ids": sel["selected_ids"],
            "setr_zeroshot": setr_eval,
            "need_anchor_set": old["need_anchor_set"],
            "dense@2": old["dense@2"],
            "dense@3": old["dense@3"],
        }
        rows.append(row)

        print(
            f"[{pos}/{len(qids)}] {qid} "
            f"SetRK={setr_eval['k']} "
            f"Facet={setr_eval['facet_recall']:.4f} "
            f"Full={setr_eval['full_facet_coverage']} "
            f"Primary={setr_eval['primary_hit']}"
        )

    summaries = {
        key: aggregate(rows, key)
        for key in (
            "setr_zeroshot",
            "need_anchor_set",
            "dense@2",
            "dense@3",
        )
    }

    comparisons = {
        "need_anchor_vs_setr": paired(
            rows,
            "need_anchor_set",
            "setr_zeroshot",
        ),
        "setr_vs_dense2": paired(
            rows,
            "setr_zeroshot",
            "dense@2",
        ),
        "setr_vs_dense3": paired(
            rows,
            "setr_zeroshot",
            "dense@3",
        ),
    }

    output = {
        "config": {
            "model": GENERATION_MODEL,
            "version": VERSION,
            "query_count": len(rows),
            "selector_uses_gold": False,
            "selector_uses_reference_answer": False,
            "selector_uses_eval_facets": False,
            "note": (
                "Prior-art-inspired zero-shot SetR-style baseline; "
                "not the trained official SETR model."
            ),
        },
        "summary": summaries,
        "comparisons": comparisons,
        "per_query": rows,
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(output, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print("\n===== SETR-STYLE ZEROSHOT BASELINE V2.0 =====")
    for name, x in summaries.items():
        print(
            f"{name}: "
            f"AvgK={x['mean_k']} "
            f"FacetRecall={x['mean_facet_recall']} "
            f"FullFacet={x['full_facet_coverage_rate']} "
            f"PrimaryHit={x['primary_hit_rate']} "
            f"GoldRecall={x['mean_gold_recall']}"
        )

    print("\n===== PAIRED COMPARISONS =====")
    for name, x in comparisons.items():
        print(name)
        print(
            "  Facet diff=",
            x["mean_facet_recall_diff"],
            "95%CI=",
            x["facet_diff_95ci"],
        )
        print(
            "  W/L=",
            x["facet_win_count"],
            "/",
            x["facet_loss_count"],
        )
        print(
            "  K diff=",
            x["mean_k_diff"],
            "95%CI=",
            x["k_diff_95ci"],
        )
        print("  wins=", x["facet_win_ids"])
        print("  losses=", x["facet_loss_ids"])

    print("\noutput:", args.output)


if __name__ == "__main__":
    main()
