"""Experiment 0.6 v0.1: stronger decomposition + tuned MMR baseline.

Changes from v0:
1. Query decomposition explicitly requires minimal, non-overlapping information
   needs and forbids redundant aggregate needs.
2. A conservative semantic dedup step removes near-duplicate predicted facets.
3. MMR lambda is swept globally on the current Dev multi-evidence subset
   (0.1 ... 0.9), then ONE global best lambda is selected.
4. Coverage weights are NOT tuned in this round.

Gold facets are used only for evaluation and Dev baseline selection. They are
never exposed to the evidence selector at inference time.

Run:
    python3 tests/run_evidence_selection_v01.py
"""
from __future__ import annotations

import argparse
import json
import math
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
DEFAULT_CACHE = (
    PROJECT_ROOT
    / ".cache"
    / "rag"
    / "evidence_selector_v01_decompositions.json"
)
DEFAULT_OUTPUT = (
    PROJECT_ROOT
    / "tests"
    / "results"
    / "evidence_selection_v01.json"
)

DECOMPOSITION_VERSION = "v01_minimal_nonredundant"
MMR_LAMBDAS = tuple(round(x / 10, 1) for x in range(1, 10))
KS = (1, 3, 5)


def load_jsonl(path: Path) -> List[Dict]:
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


def strip_json_fence(text: str) -> str:
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, count=1)
        text = re.sub(r"\s*```$", "", text, count=1)
    return text.strip()


def l2_normalize(matrix: np.ndarray) -> np.ndarray:
    matrix = np.asarray(matrix, dtype=np.float32)
    norms = np.linalg.norm(matrix, axis=-1, keepdims=True)
    return np.divide(
        matrix,
        norms,
        out=np.zeros_like(matrix, dtype=np.float32),
        where=norms != 0,
    )


def normalize_1d(values: np.ndarray) -> np.ndarray:
    values = np.asarray(values, dtype=np.float32)
    lo = float(values.min())
    hi = float(values.max())
    if hi - lo < 1e-8:
        return np.ones_like(values, dtype=np.float32)
    return (values - lo) / (hi - lo)


def normalize_rows(matrix: np.ndarray) -> np.ndarray:
    matrix = np.asarray(matrix, dtype=np.float32)
    result = np.zeros_like(matrix, dtype=np.float32)
    for i in range(matrix.shape[0]):
        row = matrix[i]
        lo = float(row.min())
        hi = float(row.max())
        if hi - lo < 1e-8:
            result[i] = 1.0
        else:
            result[i] = (row - lo) / (hi - lo)
    return result


class QueryFacetDecomposer:
    def __init__(self, model: str, cache_path: Path) -> None:
        load_dotenv(PROJECT_ROOT / ".env", override=False)
        api_key = os.getenv("DASHSCOPE_API_KEY")
        if not api_key:
            raise RuntimeError("DASHSCOPE_API_KEY is not set")

        self.model = model
        self.cache_path = cache_path
        self.client = OpenAI(
            api_key=api_key,
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        )

        self.cache: Dict[str, Dict] = {}
        if cache_path.exists():
            try:
                self.cache = json.loads(
                    cache_path.read_text(encoding="utf-8")
                )
            except (json.JSONDecodeError, OSError):
                self.cache = {}

    def _save(self) -> None:
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.cache_path.write_text(
            json.dumps(self.cache, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def decompose(self, qid: str, query: str) -> List[str]:
        cached = self.cache.get(qid)
        if (
            isinstance(cached, dict)
            and cached.get("query") == query
            and cached.get("model") == self.model
            and cached.get("version") == DECOMPOSITION_VERSION
            and isinstance(cached.get("facets"), list)
            and cached["facets"]
        ):
            return [str(x) for x in cached["facets"]]

        prompt = f"""
你是信息检索阶段的查询分析器。

只根据下面的“用户问题”，把它拆成最少数量、互不重叠的检索信息需求。
严禁回答问题，严禁使用任何标准答案、知识库内容或外部知识。

要求：
1. 每个信息需求表示“需要去找哪一类证据”，而不是答案内容。
2. 只在用户问题确实要求多个独立方面时拆分。
3. 输出 1~5 个信息需求，数量越少越好，但必须覆盖问题所有明确要求。
4. 信息需求之间必须尽量互补、非冗余。
5. 如果已经拆成“A的性质”和“B的性质”，不要再额外输出“A与B的核心区别”
   这种可由前两个需求合并得到的总括性需求。
6. 如果已经拆成“最好复杂度”和“最坏复杂度”，不要再输出一个总括的
   “时间复杂度”需求。
7. 保留题目中的算法、数据结构和限定条件，避免抽象化。
8. 仅输出 JSON，不要输出解释或 Markdown：
{{"facets": ["信息需求1", "信息需求2"]}}

用户问题：
{query}
""".strip()

        completion = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "你只做检索查询拆解，不回答问题。"
                        "输出最小且非冗余的信息需求集合。"
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.0,
            extra_body={"enable_thinking": False},
        )

        payload = json.loads(
            strip_json_fence(completion.choices[0].message.content)
        )
        facets = payload.get("facets")
        if not isinstance(facets, list):
            raise RuntimeError(f"{qid}: invalid decomposition payload")

        facets = [str(x).strip() for x in facets if str(x).strip()]
        if not facets:
            facets = [query]
        facets = facets[:5]

        self.cache[qid] = {
            "query": query,
            "model": self.model,
            "version": DECOMPOSITION_VERSION,
            "facets": facets,
        }
        self._save()
        return facets


def semantic_dedup(
    facets: Sequence[str],
    embeddings: np.ndarray,
    threshold: float,
) -> Tuple[List[str], np.ndarray, List[Dict]]:
    """Conservatively remove near-duplicate predicted facets.

    Greedy order is the LLM's output order. A later facet is dropped only if
    its cosine similarity to an already kept facet exceeds the fixed threshold.
    """
    if len(facets) <= 1:
        return list(facets), embeddings, []

    normed = l2_normalize(embeddings)
    kept_indices: List[int] = []
    dropped: List[Dict] = []

    for idx, facet in enumerate(facets):
        if not kept_indices:
            kept_indices.append(idx)
            continue

        sims = [
            float(normed[idx] @ normed[j])
            for j in kept_indices
        ]
        best_pos = int(np.argmax(sims))
        best_sim = sims[best_pos]
        best_kept_idx = kept_indices[best_pos]

        if best_sim >= threshold:
            dropped.append(
                {
                    "dropped": facet,
                    "kept": facets[best_kept_idx],
                    "cosine": round(best_sim, 4),
                }
            )
        else:
            kept_indices.append(idx)

    kept_facets = [facets[i] for i in kept_indices]
    kept_embeddings = embeddings[kept_indices]
    return kept_facets, kept_embeddings, dropped


def candidate_embeddings(
    candidate_ids: Sequence[str],
    chunk_map: Dict[str, Dict],
) -> np.ndarray:
    vectors = []
    for cid in candidate_ids:
        embedding = chunk_map[cid].get("embedding")
        if embedding is None:
            raise RuntimeError(f"{cid}: document embedding missing")
        vectors.append(np.asarray(embedding, dtype=np.float32))
    return np.stack(vectors, axis=0)


def mmr_select(
    relevance: np.ndarray,
    chunk_sim: np.ndarray,
    *,
    k: int,
    lambda_rel: float,
) -> List[int]:
    n = len(relevance)
    if n == 0 or k <= 0:
        return []

    # Keep Dense top-1 as the common first evidence for a controlled comparison.
    selected = [0]
    remaining = set(range(1, n))

    while remaining and len(selected) < min(k, n):
        best_idx = None
        best_score = -float("inf")

        for idx in remaining:
            redundancy = max(
                float(chunk_sim[idx, chosen])
                for chosen in selected
            )
            score = (
                lambda_rel * float(relevance[idx])
                - (1.0 - lambda_rel) * redundancy
            )
            if score > best_score:
                best_score = score
                best_idx = idx

        assert best_idx is not None
        selected.append(best_idx)
        remaining.remove(best_idx)

    return selected


def coverage_select(
    relevance: np.ndarray,
    facet_sim: np.ndarray,
    chunk_sim: np.ndarray,
    *,
    k: int,
    alpha_rel: float,
    beta_gain: float,
    gamma_red: float,
) -> List[int]:
    n = len(relevance)
    if n == 0 or k <= 0:
        return []

    selected = [0]
    remaining = set(range(1, n))
    covered = facet_sim[:, 0].copy()

    while remaining and len(selected) < min(k, n):
        best_idx = None
        best_score = -float("inf")

        for idx in remaining:
            marginal_gain = float(
                np.maximum(facet_sim[:, idx] - covered, 0.0).mean()
            )
            redundancy = max(
                float(chunk_sim[idx, chosen])
                for chosen in selected
            )
            score = (
                alpha_rel * float(relevance[idx])
                + beta_gain * marginal_gain
                - gamma_red * redundancy
            )
            if score > best_score:
                best_score = score
                best_idx = idx

        assert best_idx is not None
        selected.append(best_idx)
        remaining.remove(best_idx)
        covered = np.maximum(covered, facet_sim[:, best_idx])

    return selected


def adaptive_coverage_select(
    relevance: np.ndarray,
    facet_sim: np.ndarray,
    chunk_sim: np.ndarray,
    *,
    min_k: int,
    max_k: int,
    alpha_rel: float,
    beta_gain: float,
    gamma_red: float,
    coverage_target: float,
    min_gain: float,
) -> List[int]:
    n = len(relevance)
    if n == 0:
        return []

    selected = [0]
    remaining = set(range(1, n))
    covered = facet_sim[:, 0].copy()

    def all_predicted_needs_covered() -> bool:
        return bool(np.all(covered >= coverage_target))

    while remaining and len(selected) < min(max_k, n):
        scored = []
        for idx in remaining:
            gain = float(
                np.maximum(facet_sim[:, idx] - covered, 0.0).mean()
            )
            redundancy = max(
                float(chunk_sim[idx, chosen])
                for chosen in selected
            )
            score = (
                alpha_rel * float(relevance[idx])
                + beta_gain * gain
                - gamma_red * redundancy
            )
            scored.append((score, gain, idx))

        scored.sort(reverse=True)
        _, best_gain, best_idx = scored[0]

        if len(selected) >= min_k:
            if all_predicted_needs_covered():
                break
            if best_gain < min_gain:
                break

        selected.append(best_idx)
        remaining.remove(best_idx)
        covered = np.maximum(covered, facet_sim[:, best_idx])

    return selected


def evaluate_selection(
    selected_ids: Sequence[str],
    facet_record: Dict,
    benchmark_record: Dict,
    candidate_matrix: np.ndarray,
    candidate_ids: Sequence[str],
) -> Dict:
    gold_facets = {
        str(item["facet_id"])
        for item in facet_record["facets"]
    }

    covered = set()
    support = facet_record.get("chunk_support", {})
    for cid in selected_ids:
        covered.update(str(x) for x in support.get(cid, []))
    covered &= gold_facets

    gold_chunks = set(benchmark_record.get("gold_chunk_ids", []))
    selected_set = set(selected_ids)

    facet_recall = (
        len(covered) / len(gold_facets)
        if gold_facets else 0.0
    )
    gold_recall = (
        len(selected_set & gold_chunks) / len(gold_chunks)
        if gold_chunks else 0.0
    )

    indices = [candidate_ids.index(cid) for cid in selected_ids]
    if len(indices) <= 1:
        redundancy = 0.0
    else:
        normed = l2_normalize(candidate_matrix)
        sims = []
        for i in range(len(indices)):
            for j in range(i + 1, len(indices)):
                sims.append(
                    float(normed[indices[i]] @ normed[indices[j]])
                )
        redundancy = sum(sims) / len(sims)

    return {
        "selected_chunk_ids": list(selected_ids),
        "selected_count": len(selected_ids),
        "gold_facets": len(gold_facets),
        "covered_gold_facets": len(covered),
        "covered_gold_facet_ids": sorted(covered),
        "facet_recall": round(facet_recall, 4),
        "full_facet_coverage": facet_recall >= 1.0 - 1e-9,
        "gold_chunk_recall": round(gold_recall, 4),
        "evidence_redundancy": round(redundancy, 4),
    }


def aggregate(results: Sequence[Dict], method: str) -> Dict:
    values = [r["methods"][method] for r in results]
    return {
        "queries": len(values),
        "mean_facet_recall": round(
            sum(x["facet_recall"] for x in values) / len(values), 4
        ),
        "full_coverage_rate": round(
            sum(bool(x["full_facet_coverage"]) for x in values)
            / len(values),
            4,
        ),
        "mean_gold_chunk_recall": round(
            sum(x["gold_chunk_recall"] for x in values) / len(values), 4
        ),
        "mean_selected_count": round(
            sum(x["selected_count"] for x in values) / len(values), 4
        ),
        "mean_evidence_redundancy": round(
            sum(x["evidence_redundancy"] for x in values) / len(values), 4
        ),
    }


def choose_best_mmr_lambda(
    lambda_summaries: Dict[float, Dict],
) -> float:
    """One global Dev lambda. Never choose lambda per query."""
    return max(
        lambda_summaries,
        key=lambda lam: (
            lambda_summaries[lam]["mean_facet_recall"],
            lambda_summaries[lam]["full_coverage_rate"],
            -lambda_summaries[lam]["mean_evidence_redundancy"],
            lam,
        ),
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--benchmark", type=Path, default=DEFAULT_BENCHMARK)
    parser.add_argument("--facets", type=Path, default=DEFAULT_FACETS)
    parser.add_argument("--knowledge", type=Path, default=DEFAULT_KNOWLEDGE)
    parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)

    parser.add_argument("--candidate-k", type=int, default=5)
    parser.add_argument("--select-k", type=int, default=3)

    # Fixed before seeing v0.1 results.
    parser.add_argument("--facet-dedup-threshold", type=float, default=0.92)
    parser.add_argument("--alpha-rel", type=float, default=0.45)
    parser.add_argument("--beta-gain", type=float, default=0.45)
    parser.add_argument("--gamma-red", type=float, default=0.10)

    parser.add_argument("--adaptive-min-k", type=int, default=2)
    parser.add_argument("--adaptive-max-k", type=int, default=5)
    parser.add_argument("--coverage-target", type=float, default=0.90)
    parser.add_argument("--min-gain", type=float, default=0.03)
    args = parser.parse_args()

    if args.candidate_k != 5:
        raise RuntimeError(
            "v0.1 must stay inside Dense Top-5 because only that pool is fully "
            "judged for the current diagnostic."
        )

    load_dotenv(PROJECT_ROOT / ".env", override=False)

    benchmark = {x["id"]: x for x in load_jsonl(args.benchmark)}
    facets = {x["id"]: x for x in load_jsonl(args.facets)}

    target_ids = [
        qid
        for qid, q in benchmark.items()
        if not q.get("is_out_of_scope", False)
        and not q.get("primary_gold_chunk_ids")
        and qid in facets
    ]

    print("multi-evidence queries:", target_ids)
    print("count:", len(target_ids))

    chunks = load_chunks_from_jsonl(args.knowledge)
    chunk_map = {str(x["chunk_id"]): x for x in chunks}

    dense = DenseRetriever()
    dense.prepare(chunks, use_cache=True)

    decomposer = QueryFacetDecomposer(
        model=GENERATION_MODEL,
        cache_path=args.cache,
    )

    # First pass stores query/candidate/facet representations once.
    prepared: List[Dict] = []

    for pos, qid in enumerate(target_ids, 1):
        q = benchmark[qid]
        query = q["question"]
        print(f"\n[{pos}/{len(target_ids)}] {qid}: {query}")

        raw_predicted = decomposer.decompose(qid, query)
        raw_facet_embeddings = np.asarray(
            dense._embed_texts(raw_predicted, text_type="query"),
            dtype=np.float32,
        )

        predicted, facet_embeddings, dropped = semantic_dedup(
            raw_predicted,
            raw_facet_embeddings,
            threshold=args.facet_dedup_threshold,
        )

        print("  predicted facets:")
        for x in predicted:
            print("   -", x)
        if dropped:
            print("  semantic dedup:")
            for x in dropped:
                print(
                    f"   drop={x['dropped']} | keep={x['kept']} "
                    f"| cos={x['cosine']}"
                )

        retrieved = dense.retrieve(
            query=query,
            chunks=chunks,
            top_k=args.candidate_k,
        )
        candidate_ids = [str(x["chunk_id"]) for x in retrieved]
        retrieval_scores = np.asarray(
            [float(x["score"]) for x in retrieved],
            dtype=np.float32,
        )
        relevance = normalize_1d(retrieval_scores)

        cand_matrix = candidate_embeddings(candidate_ids, chunk_map)
        cand_normed = l2_normalize(cand_matrix)
        chunk_sim = cand_normed @ cand_normed.T

        facet_normed = l2_normalize(facet_embeddings)
        raw_facet_sim = facet_normed @ cand_normed.T
        facet_sim = normalize_rows(raw_facet_sim)

        prepared.append(
            {
                "id": qid,
                "question": query,
                "raw_predicted_facets": raw_predicted,
                "predicted_facets": predicted,
                "dedup_dropped": dropped,
                "candidate_ids": candidate_ids,
                "candidate_scores": retrieval_scores,
                "relevance": relevance,
                "candidate_matrix": cand_matrix,
                "chunk_sim": chunk_sim,
                "facet_sim": facet_sim,
            }
        )

    # ---------- MMR global Dev sweep ----------
    mmr_lambda_summaries: Dict[float, Dict] = {}
    mmr_per_lambda_methods: Dict[float, List[Dict]] = {}

    for lam in MMR_LAMBDAS:
        tmp_results = []
        for item in prepared:
            qid = item["id"]
            idx = mmr_select(
                item["relevance"],
                item["chunk_sim"],
                k=args.select_k,
                lambda_rel=lam,
            )
            ids = [item["candidate_ids"][i] for i in idx]
            metric = evaluate_selection(
                ids,
                facets[qid],
                benchmark[qid],
                item["candidate_matrix"],
                item["candidate_ids"],
            )
            tmp_results.append({"methods": {"mmr": metric}})

        summary = aggregate(tmp_results, "mmr")
        mmr_lambda_summaries[lam] = summary
        mmr_per_lambda_methods[lam] = [
            x["methods"]["mmr"] for x in tmp_results
        ]

    best_mmr_lambda = choose_best_mmr_lambda(mmr_lambda_summaries)

    print("\n===== MMR LAMBDA SWEEP =====")
    for lam in MMR_LAMBDAS:
        x = mmr_lambda_summaries[lam]
        flag = "  <-- best" if lam == best_mmr_lambda else ""
        print(
            f"lambda={lam:.1f}: "
            f"FacetRecall={x['mean_facet_recall']} "
            f"FullCoverage={x['full_coverage_rate']} "
            f"Redundancy={x['mean_evidence_redundancy']}"
            f"{flag}"
        )

    # ---------- Main comparison using ONE best global MMR lambda ----------
    results: List[Dict] = []

    for item_idx, item in enumerate(prepared):
        qid = item["id"]
        candidate_ids = item["candidate_ids"]

        dense3_idx = list(range(min(args.select_k, len(candidate_ids))))
        dense5_idx = list(range(len(candidate_ids)))

        coverage_idx = coverage_select(
            item["relevance"],
            item["facet_sim"],
            item["chunk_sim"],
            k=args.select_k,
            alpha_rel=args.alpha_rel,
            beta_gain=args.beta_gain,
            gamma_red=args.gamma_red,
        )

        adaptive_idx = adaptive_coverage_select(
            item["relevance"],
            item["facet_sim"],
            item["chunk_sim"],
            min_k=args.adaptive_min_k,
            max_k=args.adaptive_max_k,
            alpha_rel=args.alpha_rel,
            beta_gain=args.beta_gain,
            gamma_red=args.gamma_red,
            coverage_target=args.coverage_target,
            min_gain=args.min_gain,
        )

        best_mmr_metric = mmr_per_lambda_methods[best_mmr_lambda][item_idx]

        methods = {
            "dense@3": evaluate_selection(
                [candidate_ids[i] for i in dense3_idx],
                facets[qid],
                benchmark[qid],
                item["candidate_matrix"],
                candidate_ids,
            ),
            "dense@5_ceiling": evaluate_selection(
                [candidate_ids[i] for i in dense5_idx],
                facets[qid],
                benchmark[qid],
                item["candidate_matrix"],
                candidate_ids,
            ),
            "best_mmr@3": best_mmr_metric,
            "coverage@3": evaluate_selection(
                [candidate_ids[i] for i in coverage_idx],
                facets[qid],
                benchmark[qid],
                item["candidate_matrix"],
                candidate_ids,
            ),
            "coverage_adaptive": evaluate_selection(
                [candidate_ids[i] for i in adaptive_idx],
                facets[qid],
                benchmark[qid],
                item["candidate_matrix"],
                candidate_ids,
            ),
        }

        print(
            f"\n{qid} FacetRecall: "
            f"Dense3={methods['dense@3']['facet_recall']} "
            f"BestMMR3={methods['best_mmr@3']['facet_recall']} "
            f"Coverage3={methods['coverage@3']['facet_recall']} "
            f"Adaptive={methods['coverage_adaptive']['facet_recall']} "
            f"(k={methods['coverage_adaptive']['selected_count']}) "
            f"Dense5={methods['dense@5_ceiling']['facet_recall']}"
        )

        results.append(
            {
                "id": qid,
                "question": item["question"],
                "raw_predicted_facets": item["raw_predicted_facets"],
                "predicted_facets": item["predicted_facets"],
                "dedup_dropped": item["dedup_dropped"],
                "candidate_ids": candidate_ids,
                "candidate_scores": [
                    round(float(x), 6)
                    for x in item["candidate_scores"]
                ],
                "methods": methods,
            }
        )

    method_names = (
        "dense@3",
        "dense@5_ceiling",
        "best_mmr@3",
        "coverage@3",
        "coverage_adaptive",
    )
    summary = {name: aggregate(results, name) for name in method_names}

    gate = {
        "best_mmr_lambda": best_mmr_lambda,
        "coverage_wins_dense_queries": sum(
            r["methods"]["coverage@3"]["facet_recall"]
            > r["methods"]["dense@3"]["facet_recall"]
            for r in results
        ),
        "coverage_loses_dense_queries": sum(
            r["methods"]["coverage@3"]["facet_recall"]
            < r["methods"]["dense@3"]["facet_recall"]
            for r in results
        ),
        "coverage_wins_best_mmr_queries": sum(
            r["methods"]["coverage@3"]["facet_recall"]
            > r["methods"]["best_mmr@3"]["facet_recall"]
            for r in results
        ),
        "coverage_loses_best_mmr_queries": sum(
            r["methods"]["coverage@3"]["facet_recall"]
            < r["methods"]["best_mmr@3"]["facet_recall"]
            for r in results
        ),
        "candidate_pool_limited_queries": [
            r["id"]
            for r in results
            if not r["methods"]["dense@5_ceiling"]["full_facet_coverage"]
        ],
        "dedup_affected_queries": [
            r["id"] for r in results if r["dedup_dropped"]
        ],
    }

    payload = {
        "config": {
            "generation_model": GENERATION_MODEL,
            "decomposition_version": DECOMPOSITION_VERSION,
            "facet_dedup_threshold": args.facet_dedup_threshold,
            "candidate_k": args.candidate_k,
            "select_k": args.select_k,
            "mmr_lambdas": list(MMR_LAMBDAS),
            "best_mmr_lambda": best_mmr_lambda,
            "alpha_rel": args.alpha_rel,
            "beta_gain": args.beta_gain,
            "gamma_red": args.gamma_red,
            "adaptive_min_k": args.adaptive_min_k,
            "adaptive_max_k": args.adaptive_max_k,
            "coverage_target": args.coverage_target,
            "min_gain": args.min_gain,
            "selection_uses_gold": False,
            "note": (
                "Gold facets are used only for Dev evaluation and global MMR "
                "lambda selection, never as selector inputs."
            ),
        },
        "mmr_lambda_sweep": {
            str(k): v for k, v in mmr_lambda_summaries.items()
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

    print("\n===== EVIDENCE SELECTION V0.1 =====")
    for name in method_names:
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
    for key, value in gate.items():
        print(f"{key}={value}")

    print("\noutput:", args.output)


if __name__ == "__main__":
    main()
