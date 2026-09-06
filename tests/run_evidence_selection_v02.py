"""Evidence Selection v0.2

Purpose
-------
Diagnose whether v0/v0.1 failed because the coverage hypothesis is weak or
because embedding cosine is a poor estimator of "need -> chunk support".

Selection-time inputs ONLY:
    question
    query-only predicted information needs
    Dense Top-5 candidates
    embeddings
    LLM support scores over (need, candidate) pairs

Never used by the selector:
    reference_answer
    gold facets
    relevance labels

Gold facets are loaded only for evaluation.

Methods
-------
Dense@3
Dense@5 ceiling
Tuned MMR@3 (lambda=0.1 from v0.1 Dev sweep)
Embedding-Coverage@3
LLM-Coverage@3
LLM-Coverage-Adaptive

Run from project root:
    python3 tests/run_evidence_selection_v02.py
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Dict, List, Sequence

import numpy as np
from dotenv import load_dotenv
from openai import OpenAI

PROJECT_ROOT_FOR_IMPORT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT_FOR_IMPORT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT_FOR_IMPORT))

from rag.config import GENERATION_MODEL, PROJECT_ROOT
from rag.retrievers import DenseRetriever, load_chunks_from_jsonl


DEFAULT_BENCHMARK = (
    PROJECT_ROOT / "tests" / "benchmarks" / "datastructureqa_dev_v1.jsonl"
)
DEFAULT_FACETS = (
    PROJECT_ROOT
    / "tests"
    / "benchmarks"
    / "datastructureqa_dev_v1_facets_8q_v1.jsonl"
)
DEFAULT_KNOWLEDGE = PROJECT_ROOT / "knowledge_base" / "ds_chunks.jsonl"
DEFAULT_DECOMP_CACHE = (
    PROJECT_ROOT
    / ".cache"
    / "rag"
    / "evidence_selector_v01_decompositions.json"
)
DEFAULT_SUPPORT_CACHE = (
    PROJECT_ROOT
    / ".cache"
    / "rag"
    / "evidence_selector_v02_llm_support.json"
)
DEFAULT_OUTPUT = (
    PROJECT_ROOT
    / "tests"
    / "results"
    / "evidence_selection_v02.json"
)

MMR_LAMBDA = 0.1
ALPHA_REL = 0.45
BETA_GAIN = 0.45
GAMMA_RED = 0.10


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


def strip_json_fence(text: str) -> str:
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, count=1)
        text = re.sub(r"\s*```$", "", text, count=1)
    return text.strip()


def l2_normalize(x: np.ndarray) -> np.ndarray:
    x = np.asarray(x, dtype=np.float32)
    norms = np.linalg.norm(x, axis=-1, keepdims=True)
    return np.divide(
        x,
        norms,
        out=np.zeros_like(x, dtype=np.float32),
        where=norms != 0,
    )


def normalize_1d(x: np.ndarray) -> np.ndarray:
    x = np.asarray(x, dtype=np.float32)
    lo = float(x.min())
    hi = float(x.max())
    if hi - lo < 1e-8:
        return np.ones_like(x)
    return (x - lo) / (hi - lo)


def normalize_rows(x: np.ndarray) -> np.ndarray:
    x = np.asarray(x, dtype=np.float32)
    y = np.zeros_like(x)
    for i in range(x.shape[0]):
        lo = float(x[i].min())
        hi = float(x[i].max())
        if hi - lo < 1e-8:
            y[i] = 1.0
        else:
            y[i] = (x[i] - lo) / (hi - lo)
    return y


def candidate_embeddings(
    candidate_ids: Sequence[str],
    chunk_map: Dict[str, Dict],
) -> np.ndarray:
    vecs = []
    for cid in candidate_ids:
        emb = chunk_map[cid].get("embedding")
        if emb is None:
            raise RuntimeError(f"{cid}: missing cached document embedding")
        vecs.append(np.asarray(emb, dtype=np.float32))
    return np.stack(vecs)


class QueryFacetDecomposer:
    """Reuse v0.1's stricter query-only decomposition, WITHOUT cosine dedup."""

    VERSION = "v01_minimal_nonredundant"

    def __init__(self, model: str, cache_path: Path) -> None:
        load_dotenv(PROJECT_ROOT / ".env", override=False)
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

    def decompose(self, qid: str, query: str) -> List[str]:
        item = self.cache.get(qid)
        if (
            isinstance(item, dict)
            and item.get("query") == query
            and item.get("model") == self.model
            and item.get("version") == self.VERSION
            and item.get("facets")
        ):
            return [str(x) for x in item["facets"]]

        prompt = f"""
只根据用户问题，把它拆成最少数量、互不重叠的检索信息需求。
不要回答问题，不使用标准答案、知识库内容或外部资料。

规则：
1. 每个信息需求描述“需要寻找哪一类证据”，不是答案。
2. 覆盖问题中所有明确要求。
3. 多个并列对象、多个明确指标可以分别拆分。
4. 不要产生可由其他需求简单合并得到的总括性重复需求。
5. 输出1~5个需求。
6. 只输出JSON：
{{"facets":["需求1","需求2"]}}

用户问题：
{query}
""".strip()

        rsp = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {
                    "role": "system",
                    "content": "只做检索查询拆解，不回答问题。",
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.0,
            extra_body={"enable_thinking": False},
        )
        obj = json.loads(
            strip_json_fence(rsp.choices[0].message.content)
        )
        facets = [
            str(x).strip()
            for x in obj.get("facets", [])
            if str(x).strip()
        ]
        if not facets:
            facets = [query]
        facets = facets[:5]

        self.cache[qid] = {
            "query": query,
            "model": self.model,
            "version": self.VERSION,
            "facets": facets,
        }
        self._save()
        return facets


class LLMSupportScorer:
    """Score how strongly each candidate supports each predicted need.

    One LLM call per query, cached. Scores:
        0 = unrelated / no usable support
        1 = weak background only
        2 = useful partial or inferable support
        3 = strong direct support
    """

    VERSION = "v02_support_0_3"

    def __init__(self, model: str, cache_path: Path) -> None:
        load_dotenv(PROJECT_ROOT / ".env", override=False)
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

    @staticmethod
    def _signature(
        query: str,
        facets: Sequence[str],
        candidate_ids: Sequence[str],
        candidate_texts: Sequence[str],
    ) -> str:
        payload = json.dumps(
            {
                "query": query,
                "facets": list(facets),
                "candidate_ids": list(candidate_ids),
                "candidate_texts": list(candidate_texts),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def score(
        self,
        qid: str,
        query: str,
        facets: Sequence[str],
        candidate_ids: Sequence[str],
        candidate_texts: Sequence[str],
    ) -> np.ndarray:
        sig = self._signature(
            query, facets, candidate_ids, candidate_texts
        )
        cached = self.cache.get(qid)
        if (
            isinstance(cached, dict)
            and cached.get("model") == self.model
            and cached.get("version") == self.VERSION
            and cached.get("signature") == sig
            and isinstance(cached.get("matrix"), list)
        ):
            return np.asarray(cached["matrix"], dtype=np.float32)

        need_lines = "\n".join(
            f"N{i+1}: {facet}"
            for i, facet in enumerate(facets)
        )
        cand_lines = "\n\n".join(
            f"C{i+1} [{cid}]\n{text}"
            for i, (cid, text) in enumerate(
                zip(candidate_ids, candidate_texts)
            )
        )

        prompt = f"""
你正在评估检索证据，不是在回答问题。

用户问题：
{query}

待满足的信息需求：
{need_lines}

候选证据：
{cand_lines}

请独立判断每条候选证据对每个信息需求的“支撑强度”。

评分：
0 = 无关，不能提供可用证据
1 = 只有弱背景关系，不能实质支撑该需求
2 = 提供有用的部分证据，或结合用户问题即可做一步直接推导
3 = 直接、强力地支撑该信息需求

严格要求：
- 只能依据“用户问题 + 候选证据”评分。
- 不使用标准答案，不补充候选证据之外的外部知识。
- 不因为关键词相似就给高分。
- 同一候选可以支持多个需求。
- 不要选择最终答案，只输出评分矩阵。

只输出以下JSON格式：
{{
  "scores": [
    [N1对C1, N1对C2, ...],
    [N2对C1, N2对C2, ...]
  ]
}}
""".strip()

        rsp = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "你是严格的RAG证据支撑判定器。"
                        "只评估证据，不回答用户问题。"
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.0,
            extra_body={"enable_thinking": False},
        )

        expected = (len(facets), len(candidate_ids))
        matrix = None
        last_error = None

        for attempt in range(3):
            if attempt == 0:
                content = rsp.choices[0].message.content
            else:
                repair_prompt = (
                    prompt
                    + "\n\n【格式纠正】\n"
                    + f"你上一次输出格式不正确。当前必须输出一个 "
                    + f"{expected[0]} 行 × {expected[1]} 列的 scores 矩阵。\n"
                    + f"必须恰好有 {expected[0]} 个信息需求，每个需求必须恰好给 "
                    + f"{expected[1]} 个候选 C1~C{expected[1]} 的分数。\n"
                    + "禁止省略候选，禁止合并候选，禁止输出解释。\n"
                    + "每个值只能是 0、1、2、3。"
                )

                retry_rsp = self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {
                            "role": "system",
                            "content": (
                                "你是严格的RAG证据支撑判定器。"
                                "必须严格遵守JSON矩阵尺寸。"
                            ),
                        },
                        {"role": "user", "content": repair_prompt},
                    ],
                    temperature=0.0,
                    extra_body={"enable_thinking": False},
                )
                content = retry_rsp.choices[0].message.content

            try:
                obj = json.loads(strip_json_fence(content))
                candidate_matrix = np.asarray(
                    obj.get("scores"),
                    dtype=np.float32,
                )

                if candidate_matrix.shape != expected:
                    raise ValueError(
                        f"shape={candidate_matrix.shape}, "
                        f"expected={expected}"
                    )

                if (
                    np.any(candidate_matrix < 0)
                    or np.any(candidate_matrix > 3)
                ):
                    raise ValueError(
                        "support scores must be in [0,3]"
                    )

                matrix = candidate_matrix
                break

            except Exception as exc:
                last_error = exc
                print(
                    f"  WARNING: {qid} support output invalid "
                    f"(attempt {attempt + 1}/3): {exc}"
                )

        if matrix is None:
            raise RuntimeError(
                f"{qid}: failed to obtain valid LLM support matrix "
                f"after 3 attempts: {last_error}"
            )

        matrix = matrix / 3.0

        self.cache[qid] = {
            "model": self.model,
            "version": self.VERSION,
            "signature": sig,
            "facets": list(facets),
            "candidate_ids": list(candidate_ids),
            "matrix": matrix.tolist(),
        }
        self._save()
        return matrix


def mmr_select(
    relevance: np.ndarray,
    chunk_sim: np.ndarray,
    k: int,
    lam: float,
) -> List[int]:
    n = len(relevance)
    if not n:
        return []
    selected = [0]
    remaining = set(range(1, n))

    while remaining and len(selected) < min(k, n):
        best = None
        best_score = -1e30
        for idx in remaining:
            red = max(float(chunk_sim[idx, j]) for j in selected)
            score = lam * float(relevance[idx]) - (1-lam) * red
            if score > best_score:
                best_score = score
                best = idx
        selected.append(best)
        remaining.remove(best)
    return selected


def coverage_select(
    relevance: np.ndarray,
    support: np.ndarray,
    chunk_sim: np.ndarray,
    k: int,
) -> List[int]:
    n = len(relevance)
    if not n:
        return []

    selected = [0]
    remaining = set(range(1, n))
    covered = support[:, 0].copy()

    while remaining and len(selected) < min(k, n):
        best = None
        best_score = -1e30

        for idx in remaining:
            gain = float(
                np.maximum(support[:, idx] - covered, 0.0).mean()
            )
            red = max(float(chunk_sim[idx, j]) for j in selected)
            score = (
                ALPHA_REL * float(relevance[idx])
                + BETA_GAIN * gain
                - GAMMA_RED * red
            )
            if score > best_score:
                best_score = score
                best = idx

        selected.append(best)
        remaining.remove(best)
        covered = np.maximum(covered, support[:, best])

    return selected


def adaptive_select(
    relevance: np.ndarray,
    support: np.ndarray,
    chunk_sim: np.ndarray,
    min_k: int = 2,
    max_k: int = 5,
    coverage_target: float = 2.0 / 3.0,
    min_gain: float = 0.05,
) -> List[int]:
    n = len(relevance)
    if not n:
        return []

    selected = [0]
    remaining = set(range(1, n))
    covered = support[:, 0].copy()

    while remaining and len(selected) < min(max_k, n):
        scored = []
        for idx in remaining:
            gain = float(
                np.maximum(support[:, idx] - covered, 0.0).mean()
            )
            red = max(float(chunk_sim[idx, j]) for j in selected)
            score = (
                ALPHA_REL * float(relevance[idx])
                + BETA_GAIN * gain
                - GAMMA_RED * red
            )
            scored.append((score, gain, idx))

        scored.sort(reverse=True)
        _, best_gain, best = scored[0]

        if len(selected) >= min_k:
            if bool(np.all(covered >= coverage_target)):
                break
            if best_gain < min_gain:
                break

        selected.append(best)
        remaining.remove(best)
        covered = np.maximum(covered, support[:, best])

    return selected


def evaluate(
    selected_ids: Sequence[str],
    facet_record: Dict,
    benchmark_record: Dict,
    candidate_matrix: np.ndarray,
    candidate_ids: Sequence[str],
) -> Dict:
    gold_facets = {
        str(x["facet_id"]) for x in facet_record["facets"]
    }
    covered = set()
    chunk_support = facet_record.get("chunk_support", {})

    for cid in selected_ids:
        covered.update(chunk_support.get(cid, []))
    covered &= gold_facets

    gold_chunks = set(benchmark_record.get("gold_chunk_ids", []))
    selected_set = set(selected_ids)

    facet_recall = (
        len(covered) / len(gold_facets) if gold_facets else 0.0
    )
    gold_recall = (
        len(selected_set & gold_chunks) / len(gold_chunks)
        if gold_chunks else 0.0
    )

    inds = [candidate_ids.index(x) for x in selected_ids]
    if len(inds) <= 1:
        redundancy = 0.0
    else:
        norm = l2_normalize(candidate_matrix)
        vals = [
            float(norm[inds[i]] @ norm[inds[j]])
            for i in range(len(inds))
            for j in range(i+1, len(inds))
        ]
        redundancy = sum(vals) / len(vals)

    return {
        "selected_chunk_ids": list(selected_ids),
        "selected_count": len(selected_ids),
        "facet_recall": round(facet_recall, 4),
        "full_facet_coverage": abs(facet_recall - 1.0) < 1e-9,
        "gold_chunk_recall": round(gold_recall, 4),
        "evidence_redundancy": round(redundancy, 4),
        "covered_gold_facet_ids": sorted(covered),
    }


def aggregate(results: Sequence[Dict], method: str) -> Dict:
    vals = [x["methods"][method] for x in results]
    return {
        "mean_facet_recall": round(
            sum(x["facet_recall"] for x in vals) / len(vals), 4
        ),
        "full_coverage_rate": round(
            sum(x["full_facet_coverage"] for x in vals) / len(vals), 4
        ),
        "mean_gold_chunk_recall": round(
            sum(x["gold_chunk_recall"] for x in vals) / len(vals), 4
        ),
        "mean_selected_count": round(
            sum(x["selected_count"] for x in vals) / len(vals), 4
        ),
        "mean_evidence_redundancy": round(
            sum(x["evidence_redundancy"] for x in vals) / len(vals), 4
        ),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--benchmark", type=Path, default=DEFAULT_BENCHMARK)
    ap.add_argument("--facets", type=Path, default=DEFAULT_FACETS)
    ap.add_argument("--knowledge", type=Path, default=DEFAULT_KNOWLEDGE)
    ap.add_argument("--decomp-cache", type=Path, default=DEFAULT_DECOMP_CACHE)
    ap.add_argument("--support-cache", type=Path, default=DEFAULT_SUPPORT_CACHE)
    ap.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = ap.parse_args()

    load_dotenv(PROJECT_ROOT / ".env", override=False)

    bench = {x["id"]: x for x in load_jsonl(args.benchmark)}
    gold_facets = {x["id"]: x for x in load_jsonl(args.facets)}

    target_ids = [
        qid for qid, q in bench.items()
        if not q.get("is_out_of_scope", False)
        and not q.get("primary_gold_chunk_ids")
        and qid in gold_facets
    ]

    print("multi-evidence queries:", target_ids)
    print("count:", len(target_ids))

    chunks = load_chunks_from_jsonl(args.knowledge)
    chunk_map = {str(x["chunk_id"]): x for x in chunks}

    dense = DenseRetriever()
    dense.prepare(chunks, use_cache=True)

    decomposer = QueryFacetDecomposer(
        GENERATION_MODEL, args.decomp_cache
    )
    support_scorer = LLMSupportScorer(
        GENERATION_MODEL, args.support_cache
    )

    results = []

    for no, qid in enumerate(target_ids, 1):
        q = bench[qid]
        query = q["question"]
        print(f"\n[{no}/{len(target_ids)}] {qid}: {query}")

        # IMPORTANT: use raw v0.1 facets. No semantic cosine dedup.
        predicted = decomposer.decompose(qid, query)
        print("  predicted needs:")
        for i, need in enumerate(predicted, 1):
            print(f"   N{i}: {need}")

        retrieved = dense.retrieve(
            query=query,
            chunks=chunks,
            top_k=5,
        )
        candidate_ids = [str(x["chunk_id"]) for x in retrieved]
        candidate_texts = [
            str(chunk_map[cid]["text"]) for cid in candidate_ids
        ]
        raw_scores = np.asarray(
            [float(x["score"]) for x in retrieved],
            dtype=np.float32,
        )
        relevance = normalize_1d(raw_scores)

        cand_matrix = candidate_embeddings(candidate_ids, chunk_map)
        cand_norm = l2_normalize(cand_matrix)
        chunk_sim = cand_norm @ cand_norm.T

        # Embedding support estimator, retained only as diagnostic control.
        need_emb = np.asarray(
            dense._embed_texts(predicted, text_type="query"),
            dtype=np.float32,
        )
        raw_embed_support = l2_normalize(need_emb) @ cand_norm.T
        embed_support = normalize_rows(raw_embed_support)

        # LLM support estimator: no reference answer or gold is supplied.
        llm_support = support_scorer.score(
            qid,
            query,
            predicted,
            candidate_ids,
            candidate_texts,
        )

        print("  LLM support matrix (rows=needs, cols=C1..C5):")
        for i, row in enumerate(llm_support, 1):
            print(
                f"   N{i}:",
                [round(float(v), 3) for v in row],
            )

        dense3_idx = [0, 1, 2]
        dense5_idx = list(range(5))
        mmr_idx = mmr_select(
            relevance, chunk_sim, 3, MMR_LAMBDA
        )
        embed_idx = coverage_select(
            relevance, embed_support, chunk_sim, 3
        )
        llm_idx = coverage_select(
            relevance, llm_support, chunk_sim, 3
        )
        adaptive_idx = adaptive_select(
            relevance, llm_support, chunk_sim
        )

        idxs = {
            "dense@3": dense3_idx,
            "dense@5_ceiling": dense5_idx,
            "best_mmr@3": mmr_idx,
            "coverage_embed@3": embed_idx,
            "coverage_llm@3": llm_idx,
            "coverage_llm_adaptive": adaptive_idx,
        }

        methods = {}
        for method, inds in idxs.items():
            ids = [candidate_ids[i] for i in inds]
            methods[method] = evaluate(
                ids,
                gold_facets[qid],
                q,
                cand_matrix,
                candidate_ids,
            )

        print(
            "  FacetRecall:",
            f"Dense={methods['dense@3']['facet_recall']}",
            f"MMR={methods['best_mmr@3']['facet_recall']}",
            f"EmbedCov={methods['coverage_embed@3']['facet_recall']}",
            f"LLMCov={methods['coverage_llm@3']['facet_recall']}",
            (
                "LLMAdaptive="
                f"{methods['coverage_llm_adaptive']['facet_recall']}"
                f"(k={methods['coverage_llm_adaptive']['selected_count']})"
            ),
            f"Dense5={methods['dense@5_ceiling']['facet_recall']}",
        )

        results.append(
            {
                "id": qid,
                "question": query,
                "predicted_needs": predicted,
                "candidate_ids": candidate_ids,
                "candidate_scores": [
                    round(float(x), 6) for x in raw_scores
                ],
                "llm_support_matrix": llm_support.tolist(),
                "methods": methods,
            }
        )

    names = [
        "dense@3",
        "dense@5_ceiling",
        "best_mmr@3",
        "coverage_embed@3",
        "coverage_llm@3",
        "coverage_llm_adaptive",
    ]
    summary = {name: aggregate(results, name) for name in names}

    gate = {
        "mmr_lambda": MMR_LAMBDA,
        "llm_coverage_wins_dense": sum(
            r["methods"]["coverage_llm@3"]["facet_recall"]
            > r["methods"]["dense@3"]["facet_recall"]
            for r in results
        ),
        "llm_coverage_loses_dense": sum(
            r["methods"]["coverage_llm@3"]["facet_recall"]
            < r["methods"]["dense@3"]["facet_recall"]
            for r in results
        ),
        "llm_coverage_wins_mmr": sum(
            r["methods"]["coverage_llm@3"]["facet_recall"]
            > r["methods"]["best_mmr@3"]["facet_recall"]
            for r in results
        ),
        "llm_coverage_loses_mmr": sum(
            r["methods"]["coverage_llm@3"]["facet_recall"]
            < r["methods"]["best_mmr@3"]["facet_recall"]
            for r in results
        ),
        "llm_beats_embed": sum(
            r["methods"]["coverage_llm@3"]["facet_recall"]
            > r["methods"]["coverage_embed@3"]["facet_recall"]
            for r in results
        ),
        "candidate_pool_limited_queries": [
            r["id"]
            for r in results
            if not r["methods"]["dense@5_ceiling"][
                "full_facet_coverage"
            ]
        ],
    }

    payload = {
        "config": {
            "generation_model": GENERATION_MODEL,
            "candidate_k": 5,
            "select_k": 3,
            "mmr_lambda": MMR_LAMBDA,
            "alpha_rel": ALPHA_REL,
            "beta_gain": BETA_GAIN,
            "gamma_red": GAMMA_RED,
            "semantic_dedup": False,
            "selection_uses_gold": False,
            "llm_support_scale": "0/1/2/3 normalized to [0,1]",
        },
        "summary": summary,
        "gate": gate,
        "per_query": results,
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print("\n===== EVIDENCE SELECTION V0.2 =====")
    for name in names:
        x = summary[name]
        print(
            f"{name}: "
            f"FacetRecall={x['mean_facet_recall']} "
            f"FullCoverage={x['full_coverage_rate']} "
            f"GoldChunkRecall={x['mean_gold_chunk_recall']} "
            f"AvgK={x['mean_selected_count']} "
            f"Redundancy={x['mean_evidence_redundancy']}"
        )

    print("\n===== GATE =====")
    for k, v in gate.items():
        print(f"{k}={v}")

    print("\noutput:", args.output)


if __name__ == "__main__":
    main()
