"""Adaptive Evidence Budget Diagnostic v1.7

Goal
----
Evaluate adaptive evidence-set construction on ALL in-scope Dev queries,
without selecting queries using gold labels.

Methods
-------
Dense@1..5
AdaptivePrefix:
    follow Dense order; stop at the smallest k >= 2 for which every
    query-only predicted need has support >= 2/3; otherwise use Dense@5.

NeedAnchorSet:
    if every predicted need has support >= 2/3 somewhere in Dense Top-5:
        select Dense top-1 plus the strongest-support candidate for each need
        (deduplicated, Dense-rank tie-break).
    otherwise:
        fall back to Dense@5.

Selection-time inputs ONLY:
    question
    query-only predicted needs
    Dense Top-5 candidates
    LLM need->candidate support scores

Gold/reference are used ONLY for evaluation.

Existing v1.3/v0.2 decompositions and support matrices are reused when
candidate IDs match. Remaining queries are cached after first run.

Run
---
python3 tests/diagnose_adaptive_budget_v17.py
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

import numpy as np
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
    / "benchmarks"
    / "datastructureqa_dev_v1_facets_8q_v1.jsonl"
)
DEFAULT_V13 = (
    PROJECT_ROOT
    / "tests"
    / "results"
    / "structure_expansion_diagnostic_v13.json"
)
DEFAULT_V13_SUPPORT = (
    PROJECT_ROOT
    / ".cache"
    / "rag"
    / "structure_v13_support.json"
)
DEFAULT_V02 = (
    PROJECT_ROOT
    / "tests"
    / "results"
    / "evidence_selection_v02.json"
)
DEFAULT_DECOMP_CACHE = (
    PROJECT_ROOT
    / ".cache"
    / "rag"
    / "adaptive_v17_decompositions.json"
)
DEFAULT_SUPPORT_CACHE = (
    PROJECT_ROOT
    / ".cache"
    / "rag"
    / "adaptive_v17_support.json"
)
DEFAULT_OUTPUT = (
    PROJECT_ROOT
    / "tests"
    / "results"
    / "adaptive_budget_v17.json"
)

DECOMP_VERSION = "v17_minimal_nonredundant"
SUPPORT_VERSION = "v17_support_0_3"

SUPPORT_THRESHOLD = 2.0 / 3.0
MIN_PREFIX_K = 2
MAX_K = 5


def load_jsonl_list(path: Path) -> List[Dict]:
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


def load_json(path: Path) -> Dict:
    return json.loads(path.read_text(encoding="utf-8"))


def load_pool_dense(path: Path) -> Dict[str, List[Dict]]:
    by_qid: Dict[str, List[Dict]] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            raw_rank = str(row.get("dense_rank", "")).strip()
            if not raw_rank:
                continue
            try:
                rank = int(float(raw_rank))
            except ValueError:
                continue
            if not 1 <= rank <= 5:
                continue

            item = {
                "chunk_id": row["chunk_id"],
                "rank": rank,
                "score": float(row["dense_score"]),
                "text": row["chunk_text"],
            }
            by_qid.setdefault(row["question_id"], []).append(item)

    for qid in by_qid:
        by_qid[qid].sort(key=lambda x: x["rank"])

    return by_qid


def strip_json_fence(text: str) -> str:
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, count=1)
        text = re.sub(r"\s*```$", "", text, count=1)
    return text.strip()


class QueryDecomposer:
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
                self.cache = load_json(cache_path)
            except Exception:
                self.cache = {}

    def _save(self) -> None:
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.cache_path.write_text(
            json.dumps(self.cache, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def get(self, qid: str, query: str) -> List[str]:
        x = self.cache.get(qid)
        if (
            isinstance(x, dict)
            and x.get("query") == query
            and x.get("model") == self.model
            and x.get("version") == DECOMP_VERSION
            and x.get("needs")
        ):
            return [str(v) for v in x["needs"]]

        prompt = f"""
只根据用户问题，把它拆成最少数量、互不重叠的检索信息需求。
不要回答问题，不使用标准答案、知识库内容或外部资料。

规则：
1. 每个信息需求描述“需要寻找哪一类证据”，不是答案。
2. 覆盖问题中所有明确要求。
3. 多个并列对象、多个明确指标可以分别拆分。
4. 不要生成可由其他需求简单合并得到的总括性重复需求。
5. 如果问题只要求一个核心事实，就只输出一个需求。
6. 输出1~5个需求。
7. 只输出JSON：
{{"facets":["需求1","需求2"]}}

用户问题：
{query}
""".strip()

        rsp = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {
                    "role": "system",
                    "content": "只做检索需求拆解，不回答问题。",
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.0,
            extra_body={"enable_thinking": False},
        )

        obj = json.loads(strip_json_fence(rsp.choices[0].message.content))
        needs = [
            str(v).strip()
            for v in obj.get("facets", [])
            if str(v).strip()
        ]
        if not needs:
            needs = [query]
        needs = needs[:5]

        self.cache[qid] = {
            "query": query,
            "model": self.model,
            "version": DECOMP_VERSION,
            "needs": needs,
        }
        self._save()
        return needs


class SupportScorer:
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
                self.cache = load_json(cache_path)
            except Exception:
                self.cache = {}

    def _save(self) -> None:
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.cache_path.write_text(
            json.dumps(self.cache, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    @staticmethod
    def signature(
        query: str,
        needs: Sequence[str],
        ids: Sequence[str],
        texts: Sequence[str],
    ) -> str:
        payload = json.dumps(
            {
                "query": query,
                "needs": list(needs),
                "candidate_ids": list(ids),
                "candidate_texts": list(texts),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @staticmethod
    def _scalar(v):
        if isinstance(v, dict):
            for key in ("score", "value", "support"):
                if key in v:
                    return SupportScorer._scalar(v[key])
            raise ValueError(f"cannot extract scalar: {v}")
        return float(v)

    @classmethod
    def _row(cls, row, width: int):
        if isinstance(row, list):
            return [cls._scalar(v) for v in row]

        if not isinstance(row, dict):
            raise ValueError(f"unsupported row type: {type(row)}")

        for key in ("scores", "values"):
            if key in row:
                inner = row[key]
                if isinstance(inner, list):
                    return [cls._scalar(v) for v in inner]
                if isinstance(inner, dict):
                    row = inner
                    break

        vals = []
        for j in range(width):
            found = False
            for key in (f"C{j+1}", f"c{j+1}", str(j+1)):
                if key in row:
                    vals.append(cls._scalar(row[key]))
                    found = True
                    break
            if not found:
                vals = []
                break
        if vals:
            return vals

        vals = []
        for value in row.values():
            try:
                vals.append(cls._scalar(value))
            except Exception:
                pass
        if not vals:
            raise ValueError(f"cannot parse row: {row}")
        return vals

    @classmethod
    def parse_matrix(cls, raw, expected: Tuple[int, int]) -> np.ndarray:
        if isinstance(raw, dict):
            rows = []
            for i in range(expected[0]):
                found = False
                for key in (f"N{i+1}", f"n{i+1}", str(i+1)):
                    if key in raw:
                        rows.append(cls._row(raw[key], expected[1]))
                        found = True
                        break
                if not found:
                    rows = []
                    break
            if rows:
                raw = rows
            else:
                raw = [
                    cls._row(v, expected[1])
                    for v in raw.values()
                ]
        elif (
            isinstance(raw, list)
            and raw
            and all(isinstance(v, dict) for v in raw)
        ):
            raw = [cls._row(v, expected[1]) for v in raw]

        arr = np.asarray(raw, dtype=np.float32)

        if arr.shape == (expected[1], expected[0]):
            arr = arr.T

        if arr.shape != expected:
            raise ValueError(f"shape={arr.shape}, expected={expected}")
        if np.any(arr < 0) or np.any(arr > 3):
            raise ValueError("support values must be 0..3")
        return arr / 3.0

    def get(
        self,
        qid: str,
        query: str,
        needs: Sequence[str],
        ids: Sequence[str],
        texts: Sequence[str],
    ) -> np.ndarray:
        sig = self.signature(query, needs, ids, texts)
        x = self.cache.get(qid)
        if (
            isinstance(x, dict)
            and x.get("model") == self.model
            and x.get("version") == SUPPORT_VERSION
            and x.get("signature") == sig
            and x.get("matrix")
        ):
            return np.asarray(x["matrix"], dtype=np.float32)

        need_lines = "\n".join(
            f"N{i+1}: {need}" for i, need in enumerate(needs)
        )
        cand_lines = "\n\n".join(
            f"C{i+1} [{cid}]\n{text}"
            for i, (cid, text) in enumerate(zip(ids, texts))
        )

        base_prompt = f"""
你正在评估检索证据，不是在回答问题。

用户问题：
{query}

信息需求：
{need_lines}

候选证据：
{cand_lines}

对每条候选证据支持每个信息需求的强度评分：
0 = 无关
1 = 只有弱背景
2 = 有用的部分证据，或结合问题可一步直接推导
3 = 直接、强力支撑

要求：
- 只能依据用户问题和候选证据。
- 不使用标准答案或外部知识。
- 不因关键词相似自动给高分。
- 同一候选可支持多个需求。
- 只输出JSON：
{{"scores":[[...],[...]]}}
""".strip()

        expected = (len(needs), len(ids))
        matrix = None
        last_error = None

        for attempt in range(3):
            prompt = base_prompt
            if attempt:
                prompt += (
                    "\n\n格式纠正："
                    f"必须输出恰好{expected[0]}行×{expected[1]}列，"
                    "每个值只能为0、1、2、3。"
                )

            rsp = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": "只做RAG证据支撑评分，不回答问题。",
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
                matrix = self.parse_matrix(
                    obj.get("scores"),
                    expected,
                )
                break
            except Exception as exc:
                last_error = exc
                print(
                    f"  WARNING {qid} support attempt "
                    f"{attempt+1}/3: {exc}"
                )

        if matrix is None:
            raise RuntimeError(f"{qid}: support failed: {last_error}")

        self.cache[qid] = {
            "model": self.model,
            "version": SUPPORT_VERSION,
            "signature": sig,
            "needs": list(needs),
            "candidate_ids": list(ids),
            "matrix": matrix.tolist(),
        }
        self._save()
        return matrix


def seed_from_previous(
    qid: str,
    query: str,
    ids: Sequence[str],
    v13_by_id: Dict[str, Dict],
    v13_support: Dict[str, Dict],
    v02_by_id: Dict[str, Dict],
):
    """Return (needs, matrix, source) when previous artifacts exactly match."""
    if qid in v13_by_id and qid in v13_support:
        q = v13_by_id[qid]
        s = v13_support[qid]
        prior_ids = [str(v) for v in q["dense_ids"]]
        support_ids = [str(v) for v in s.get("candidate_ids", [])]

        if prior_ids == list(ids) and support_ids == list(ids):
            needs = [str(v) for v in q["needs"]]
            matrix = np.asarray(s["matrix"], dtype=np.float32)
            if matrix.shape == (len(needs), len(ids)):
                return needs, matrix, "v13"

    if qid in v02_by_id:
        q = v02_by_id[qid]
        prior_ids = [str(v) for v in q["candidate_ids"]]
        if prior_ids == list(ids):
            needs = [str(v) for v in q["predicted_needs"]]
            matrix = np.asarray(
                q["llm_support_matrix"],
                dtype=np.float32,
            )
            if matrix.shape == (len(needs), len(ids)):
                return needs, matrix, "v02"

    return None


def dense_prefix(k: int) -> List[int]:
    return list(range(k))


def adaptive_prefix(support: np.ndarray) -> List[int]:
    n = support.shape[1]
    for k in range(MIN_PREFIX_K, min(MAX_K, n) + 1):
        covered = np.max(support[:, :k], axis=1)
        if bool(np.all(covered + 1e-6 >= SUPPORT_THRESHOLD)):
            return list(range(k))
    return list(range(min(MAX_K, n)))


def need_anchor_set(support: np.ndarray) -> List[int]:
    """Top-1 Dense anchor + best candidate per predicted need.

    If any need is unsupported in Top-5, fall back to Dense@5.
    """
    n_needs, n_cands = support.shape

    best_indices = []
    for i in range(n_needs):
        row = support[i]
        best = max(
            range(n_cands),
            key=lambda j: (float(row[j]), -j),
        )
        if float(row[best]) + 1e-6 < SUPPORT_THRESHOLD:
            return list(range(min(MAX_K, n_cands)))
        best_indices.append(best)

    selected = {0}
    selected.update(best_indices)

    return sorted(selected)


def evaluate_set(
    selected_ids: Sequence[str],
    benchmark_row: Dict,
    facet_row: Dict | None,
) -> Dict:
    selected = set(selected_ids)
    gold = set(str(x) for x in benchmark_row.get("gold_chunk_ids", []))
    primary = set(
        str(x) for x in benchmark_row.get("primary_gold_chunk_ids", [])
    )

    gold_recall = len(selected & gold) / len(gold) if gold else 0.0

    result = {
        "k": len(selected_ids),
        "gold_recall": round(gold_recall, 4),
        "any_gold_hit": bool(selected & gold),
        "has_primary_gold": bool(primary),
        "primary_hit": bool(selected & primary) if primary else None,
    }

    if facet_row is not None:
        facet_ids = {
            str(x["facet_id"])
            for x in facet_row.get("facets", [])
        }
        covered = set()
        support_map = facet_row.get("chunk_support", {})
        for cid in selected_ids:
            covered.update(support_map.get(cid, []))
        covered &= facet_ids

        fr = len(covered) / len(facet_ids) if facet_ids else 0.0
        result["facet_recall"] = round(fr, 4)
        result["full_facet_coverage"] = (
            abs(fr - 1.0) < 1e-9
        )

    return result


def aggregate(rows: List[Dict], method: str) -> Dict:
    vals = [r["methods"][method] for r in rows]
    primary_vals = [
        x for x in vals
        if x["has_primary_gold"]
    ]
    facet_vals = [
        x for x in vals
        if "facet_recall" in x
    ]

    out = {
        "mean_k": round(
            sum(x["k"] for x in vals) / len(vals), 4
        ),
        "mean_gold_recall": round(
            sum(x["gold_recall"] for x in vals) / len(vals), 4
        ),
        "any_gold_hit_rate": round(
            sum(x["any_gold_hit"] for x in vals) / len(vals), 4
        ),
        "primary_query_count": len(primary_vals),
        "primary_hit_rate": round(
            sum(bool(x["primary_hit"]) for x in primary_vals)
            / len(primary_vals),
            4,
        ) if primary_vals else None,
    }

    if facet_vals:
        out["facet_query_count"] = len(facet_vals)
        out["mean_facet_recall"] = round(
            sum(x["facet_recall"] for x in facet_vals)
            / len(facet_vals),
            4,
        )
        out["full_facet_coverage_rate"] = round(
            sum(bool(x["full_facet_coverage"]) for x in facet_vals)
            / len(facet_vals),
            4,
        )

    return out


def main() -> None:
    load_dotenv(PROJECT_ROOT / ".env", override=False)

    ap = argparse.ArgumentParser()
    ap.add_argument("--benchmark", type=Path, default=DEFAULT_BENCHMARK)
    ap.add_argument("--pool", type=Path, default=DEFAULT_POOL)
    ap.add_argument("--facets", type=Path, default=DEFAULT_FACETS)
    ap.add_argument("--v13", type=Path, default=DEFAULT_V13)
    ap.add_argument("--v13-support", type=Path, default=DEFAULT_V13_SUPPORT)
    ap.add_argument("--v02", type=Path, default=DEFAULT_V02)
    ap.add_argument("--decomp-cache", type=Path, default=DEFAULT_DECOMP_CACHE)
    ap.add_argument("--support-cache", type=Path, default=DEFAULT_SUPPORT_CACHE)
    ap.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = ap.parse_args()

    benchmark = {
        x["id"]: x
        for x in load_jsonl_list(args.benchmark)
        if not x.get("is_out_of_scope", False)
    }
    dense_pool = load_pool_dense(args.pool)

    facets = {}
    if args.facets.exists():
        facets = {
            x["id"]: x
            for x in load_jsonl_list(args.facets)
        }

    v13_by_id = {}
    if args.v13.exists():
        v13 = load_json(args.v13)
        v13_by_id = {
            x["id"]: x for x in v13.get("per_query", [])
        }

    v13_support = (
        load_json(args.v13_support)
        if args.v13_support.exists()
        else {}
    )

    v02_by_id = {}
    if args.v02.exists():
        v02 = load_json(args.v02)
        v02_by_id = {
            x["id"]: x for x in v02.get("per_query", [])
        }

    decomposer = QueryDecomposer(
        GENERATION_MODEL,
        args.decomp_cache,
    )
    scorer = SupportScorer(
        GENERATION_MODEL,
        args.support_cache,
    )

    rows = []

    for pos, (qid, q) in enumerate(benchmark.items(), 1):
        candidates = dense_pool.get(qid, [])
        if len(candidates) != 5:
            raise RuntimeError(
                f"{qid}: expected 5 Dense candidates in pool, "
                f"got {len(candidates)}"
            )

        ids = [str(x["chunk_id"]) for x in candidates]
        texts = [str(x["text"]) for x in candidates]

        prior = seed_from_previous(
            qid,
            q["question"],
            ids,
            v13_by_id,
            v13_support,
            v02_by_id,
        )

        if prior is not None:
            needs, support, source = prior
        else:
            needs = decomposer.get(qid, q["question"])
            support = scorer.get(
                qid,
                q["question"],
                needs,
                ids,
                texts,
            )
            source = "v17"

        method_indices = {
            "dense@1": dense_prefix(1),
            "dense@2": dense_prefix(2),
            "dense@3": dense_prefix(3),
            "dense@4": dense_prefix(4),
            "dense@5": dense_prefix(5),
            "adaptive_prefix": adaptive_prefix(support),
            "need_anchor_set": need_anchor_set(support),
        }

        methods = {}
        for name, inds in method_indices.items():
            selected_ids = [ids[i] for i in inds]
            methods[name] = evaluate_set(
                selected_ids,
                q,
                facets.get(qid),
            )

        rows.append(
            {
                "id": qid,
                "question": q["question"],
                "needs": needs,
                "support_source": source,
                "candidate_ids": ids,
                "support_matrix": support.tolist(),
                "methods": methods,
            }
        )

        print(
            f"[{pos}/{len(benchmark)}] {qid} "
            f"needs={len(needs)} source={source} | "
            f"PrefixK={methods['adaptive_prefix']['k']} "
            f"AnchorK={methods['need_anchor_set']['k']} "
            f"Primary="
            f"{methods['need_anchor_set']['primary_hit']}"
        )

    method_names = [
        "dense@1",
        "dense@2",
        "dense@3",
        "dense@4",
        "dense@5",
        "adaptive_prefix",
        "need_anchor_set",
    ]
    summary = {
        name: aggregate(rows, name)
        for name in method_names
    }

    # Direct efficiency comparisons to the nearest simple fixed-K baselines.
    apx = summary["adaptive_prefix"]
    nas = summary["need_anchor_set"]

    comparison = {
        "adaptive_prefix_mean_k": apx["mean_k"],
        "need_anchor_set_mean_k": nas["mean_k"],
        "adaptive_prefix_primary_hit": apx["primary_hit_rate"],
        "need_anchor_set_primary_hit": nas["primary_hit_rate"],
        "adaptive_prefix_gold_recall": apx["mean_gold_recall"],
        "need_anchor_set_gold_recall": nas["mean_gold_recall"],
        "dense2_primary_hit": summary["dense@2"]["primary_hit_rate"],
        "dense3_primary_hit": summary["dense@3"]["primary_hit_rate"],
        "dense5_primary_hit": summary["dense@5"]["primary_hit_rate"],
        "dense2_gold_recall": summary["dense@2"]["mean_gold_recall"],
        "dense3_gold_recall": summary["dense@3"]["mean_gold_recall"],
        "dense5_gold_recall": summary["dense@5"]["mean_gold_recall"],
    }

    if "mean_facet_recall" in nas:
        comparison.update(
            {
                "adaptive_prefix_facet_recall": apx[
                    "mean_facet_recall"
                ],
                "need_anchor_set_facet_recall": nas[
                    "mean_facet_recall"
                ],
                "dense3_facet_recall": summary["dense@3"][
                    "mean_facet_recall"
                ],
                "dense5_facet_recall": summary["dense@5"][
                    "mean_facet_recall"
                ],
            }
        )

    output = {
        "config": {
            "generation_model": GENERATION_MODEL,
            "support_threshold": SUPPORT_THRESHOLD,
            "min_prefix_k": MIN_PREFIX_K,
            "max_k": MAX_K,
            "selection_uses_gold": False,
            "query_count": len(rows),
        },
        "summary": summary,
        "comparison": comparison,
        "per_query": rows,
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(output, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print("\n===== ADAPTIVE EVIDENCE BUDGET V1.7 =====")
    for name in method_names:
        x = summary[name]
        print(
            f"{name}: "
            f"AvgK={x['mean_k']} "
            f"GoldRecall={x['mean_gold_recall']} "
            f"AnyHit={x['any_gold_hit_rate']} "
            f"PrimaryHit={x['primary_hit_rate']}"
            + (
                f" FacetRecall={x['mean_facet_recall']} "
                f"FullFacet={x['full_facet_coverage_rate']}"
                if "mean_facet_recall" in x
                else ""
            )
        )

    print("\n===== KEY COMPARISON =====")
    for k, v in comparison.items():
        print(f"{k}={v}")

    print("\noutput:", args.output)


if __name__ == "__main__":
    main()
