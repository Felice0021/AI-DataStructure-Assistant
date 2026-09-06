"""Experiment 0.6: coverage-aware evidence-set selection on multi-evidence queries.

This is intentionally a diagnostic experiment, not yet production code.

Selection-time inputs:
    query
    Dense Top-5 candidates
    query-only LLM decomposition
    embedding similarities

NEVER used at selection time:
    reference answer
    gold facets
    gold relevance labels

Gold facets are loaded only after selection for evaluation.

Comparisons:
    Dense@3
    Dense@5 (candidate-pool ceiling reference)
    Dense + MMR@3
    Coverage-aware@3
    Coverage-aware adaptive

Run from project root:
    python3 tests/run_evidence_selection_v0.py
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path

PROJECT_ROOT_FOR_IMPORT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT_FOR_IMPORT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT_FOR_IMPORT))

from typing import Dict, List, Sequence

import numpy as np
from openai import OpenAI
from dotenv import load_dotenv

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
    / "evidence_selector_v0_decompositions.json"
)
DEFAULT_OUTPUT = (
    PROJECT_ROOT
    / "tests"
    / "results"
    / "evidence_selection_v0.json"
)


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
                    f"{path} line {line_no}: invalid JSON: {exc}"
                ) from exc
    return records


def strip_json_fence(text: str) -> str:
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, count=1)
        text = re.sub(r"\s*```$", "", text, count=1)
    return text.strip()


def normalize_1d(values: np.ndarray) -> np.ndarray:
    values = np.asarray(values, dtype=np.float32)
    lo = float(values.min())
    hi = float(values.max())
    if hi - lo < 1e-8:
        return np.ones_like(values, dtype=np.float32)
    return (values - lo) / (hi - lo)


def normalize_rows(matrix: np.ndarray) -> np.ndarray:
    """Min-max normalize each row across candidates."""
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


def l2_normalize(matrix: np.ndarray) -> np.ndarray:
    matrix = np.asarray(matrix, dtype=np.float32)
    norms = np.linalg.norm(matrix, axis=-1, keepdims=True)
    return np.divide(
        matrix,
        norms,
        out=np.zeros_like(matrix, dtype=np.float32),
        where=norms != 0,
    )


class QueryFacetDecomposer:
    """Training-free query-only information-need decomposition."""

    def __init__(
        self,
        *,
        model: str,
        cache_path: Path,
    ) -> None:
        load_dotenv(PROJECT_ROOT / ".env", override=False)

        import os
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
            and isinstance(cached.get("facets"), list)
            and cached["facets"]
        ):
            return [str(x) for x in cached["facets"]]

        prompt = f"""
只根据下面的用户问题，把它拆成 1~5 个检索所需的“信息需求”。
这是检索阶段，严禁回答问题，也不能使用标准答案或外部知识。

要求：
1. 每个信息需求表达问题要求寻找的一类证据，而不是答案内容。
2. 不要把一个天然完整的小问题拆得过细。
3. 若问题包含“分别、区别、为什么、流程+复杂度”等多个要求，应拆成互补的信息需求。
4. 保留题目中的实体/算法名称，避免改写得过于抽象。
5. 仅输出 JSON：
{{"facets": ["信息需求1", "信息需求2"]}}

用户问题：
{query}
""".strip()

        completion = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {
                    "role": "system",
                    "content": "你是信息检索查询分析器，只拆解查询，不回答问题。",
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

        facets = [
            str(x).strip()
            for x in facets
            if str(x).strip()
        ]
        if not facets:
            facets = [query]
        facets = facets[:5]

        self.cache[qid] = {
            "query": query,
            "model": self.model,
            "facets": facets,
        }
        self._save()
        return facets


def candidate_embeddings(
    candidate_ids: Sequence[str],
    chunk_map: Dict[str, Dict],
) -> np.ndarray:
    vectors = []
    for cid in candidate_ids:
        chunk = chunk_map[cid]
        embedding = chunk.get("embedding")
        if embedding is None:
            raise RuntimeError(f"{cid}: document embedding missing")
        vectors.append(np.asarray(embedding, dtype=np.float32))
    return np.stack(vectors, axis=0)


def pairwise_similarity(matrix: np.ndarray) -> np.ndarray:
    normed = l2_normalize(matrix)
    return normed @ normed.T


def mmr_select(
    candidate_ids: Sequence[str],
    relevance: np.ndarray,
    chunk_sim: np.ndarray,
    *,
    k: int,
    lambda_rel: float,
) -> List[int]:
    """Standard MMR; Dense top-1 is used as the initial anchor."""
    n = len(candidate_ids)
    if n == 0 or k <= 0:
        return []

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
    candidate_ids: Sequence[str],
    relevance: np.ndarray,
    facet_sim: np.ndarray,
    chunk_sim: np.ndarray,
    *,
    k: int,
    alpha_rel: float,
    beta_gain: float,
    gamma_red: float,
) -> List[int]:
    """Greedy fixed-budget coverage-aware selection.

    The first evidence is Dense top-1. Later evidence maximizes:
        relevance + marginal predicted-facet coverage - redundancy
    """
    n = len(candidate_ids)
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
    candidate_ids: Sequence[str],
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
    """Greedy selection with a relative predicted-coverage stopping rule."""
    n = len(candidate_ids)
    if n == 0:
        return []

    selected = [0]
    remaining = set(range(1, n))
    covered = facet_sim[:, 0].copy()

    def predicted_coverage() -> float:
        # facet_sim is row-normalized to [0,1] within the candidate pool.
        return float(np.mean(covered >= coverage_target))

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
            if predicted_coverage() >= 1.0:
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

    # Evidence redundancy: average pairwise cosine similarity.
    indices = [
        candidate_ids.index(cid)
        for cid in selected_ids
    ]
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


def aggregate(records: Sequence[Dict], method: str) -> Dict:
    values = [r["methods"][method] for r in records]
    if not values:
        return {}

    return {
        "queries": len(values),
        "mean_facet_recall": round(
            sum(x["facet_recall"] for x in values) / len(values),
            4,
        ),
        "full_coverage_rate": round(
            sum(bool(x["full_facet_coverage"]) for x in values)
            / len(values),
            4,
        ),
        "mean_gold_chunk_recall": round(
            sum(x["gold_chunk_recall"] for x in values) / len(values),
            4,
        ),
        "mean_selected_count": round(
            sum(x["selected_count"] for x in values) / len(values),
            4,
        ),
        "mean_evidence_redundancy": round(
            sum(x["evidence_redundancy"] for x in values) / len(values),
            4,
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--benchmark", type=Path, default=DEFAULT_BENCHMARK)
    parser.add_argument("--facets", type=Path, default=DEFAULT_FACETS)
    parser.add_argument("--knowledge", type=Path, default=DEFAULT_KNOWLEDGE)
    parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--candidate-k", type=int, default=5)
    parser.add_argument("--select-k", type=int, default=3)
    parser.add_argument("--mmr-lambda", type=float, default=0.7)

    # v0 weights: intentionally fixed before looking at v0 results.
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
            "Experiment v0 must use Dense Top-5 only, because the current "
            "human judgment pool is guaranteed only for Dense Top-5."
        )

    load_dotenv(PROJECT_ROOT / ".env", override=False)

    benchmark = {
        x["id"]: x for x in load_jsonl(args.benchmark)
    }
    facet_records = {
        x["id"]: x for x in load_jsonl(args.facets)
    }

    target_ids = [
        qid
        for qid, q in benchmark.items()
        if not q.get("is_out_of_scope", False)
        and not q.get("primary_gold_chunk_ids")
        and qid in facet_records
    ]

    print("multi-evidence queries:", target_ids)
    print("count:", len(target_ids))

    if len(target_ids) != 7:
        print(
            "WARNING: expected 7 current multi-evidence queries, got",
            len(target_ids),
        )

    chunks = load_chunks_from_jsonl(args.knowledge)
    chunk_map = {str(x["chunk_id"]): x for x in chunks}

    dense = DenseRetriever()
    dense.prepare(chunks, use_cache=True)

    decomposer = QueryFacetDecomposer(
        model=GENERATION_MODEL,
        cache_path=args.cache,
    )

    results: List[Dict] = []

    for pos, qid in enumerate(target_ids, 1):
        q = benchmark[qid]
        query = q["question"]

        print(f"\n[{pos}/{len(target_ids)}] {qid}: {query}")

        predicted_facets = decomposer.decompose(qid, query)
        print("  predicted facets:")
        for facet in predicted_facets:
            print("   -", facet)

        retrieved = dense.retrieve(
            query=query,
            chunks=chunks,
            top_k=args.candidate_k,
        )
        candidate_ids = [
            str(x["chunk_id"])
            for x in retrieved
        ]
        retrieval_scores = np.asarray(
            [float(x["score"]) for x in retrieved],
            dtype=np.float32,
        )
        relevance = normalize_1d(retrieval_scores)

        cand_matrix = candidate_embeddings(
            candidate_ids,
            chunk_map,
        )
        cand_normed = l2_normalize(cand_matrix)
        chunk_sim = cand_normed @ cand_normed.T

        # Diagnostic v0 uses the retriever's existing embedding API so no new
        # embedding model is introduced.
        facet_embeddings = np.asarray(
            dense._embed_texts(
                predicted_facets,
                text_type="query",
            ),
            dtype=np.float32,
        )
        facet_normed = l2_normalize(facet_embeddings)
        raw_facet_sim = facet_normed @ cand_normed.T
        facet_sim = normalize_rows(raw_facet_sim)

        dense3_idx = list(
            range(min(args.select_k, len(candidate_ids)))
        )
        dense5_idx = list(range(len(candidate_ids)))

        mmr_idx = mmr_select(
            candidate_ids,
            relevance,
            chunk_sim,
            k=args.select_k,
            lambda_rel=args.mmr_lambda,
        )

        coverage_idx = coverage_select(
            candidate_ids,
            relevance,
            facet_sim,
            chunk_sim,
            k=args.select_k,
            alpha_rel=args.alpha_rel,
            beta_gain=args.beta_gain,
            gamma_red=args.gamma_red,
        )

        adaptive_idx = adaptive_coverage_select(
            candidate_ids,
            relevance,
            facet_sim,
            chunk_sim,
            min_k=args.adaptive_min_k,
            max_k=args.adaptive_max_k,
            alpha_rel=args.alpha_rel,
            beta_gain=args.beta_gain,
            gamma_red=args.gamma_red,
            coverage_target=args.coverage_target,
            min_gain=args.min_gain,
        )

        selections = {
            "dense@3": dense3_idx,
            "dense@5_ceiling": dense5_idx,
            "mmr@3": mmr_idx,
            "coverage@3": coverage_idx,
            "coverage_adaptive": adaptive_idx,
        }

        methods = {}
        for name, indices in selections.items():
            selected_ids = [candidate_ids[i] for i in indices]
            methods[name] = evaluate_selection(
                selected_ids,
                facet_records[qid],
                q,
                cand_matrix,
                candidate_ids,
            )

        result = {
            "id": qid,
            "question": query,
            "predicted_facets": predicted_facets,
            "candidate_ids": candidate_ids,
            "candidate_scores": [
                round(float(x), 6)
                for x in retrieval_scores
            ],
            "methods": methods,
        }
        results.append(result)

        print(
            "  FacetRecall:",
            "Dense3=", methods["dense@3"]["facet_recall"],
            "MMR3=", methods["mmr@3"]["facet_recall"],
            "Coverage3=", methods["coverage@3"]["facet_recall"],
            "Adaptive=", methods["coverage_adaptive"]["facet_recall"],
            f"(k={methods['coverage_adaptive']['selected_count']})",
            "Dense5 ceiling=",
            methods["dense@5_ceiling"]["facet_recall"],
        )

    method_names = (
        "dense@3",
        "dense@5_ceiling",
        "mmr@3",
        "coverage@3",
        "coverage_adaptive",
    )
    summary = {
        name: aggregate(results, name)
        for name in method_names
    }

    # Pairwise wins on the main fixed-budget comparison.
    coverage_wins_dense = sum(
        r["methods"]["coverage@3"]["facet_recall"]
        > r["methods"]["dense@3"]["facet_recall"]
        for r in results
    )
    coverage_ties_dense = sum(
        r["methods"]["coverage@3"]["facet_recall"]
        == r["methods"]["dense@3"]["facet_recall"]
        for r in results
    )
    coverage_wins_mmr = sum(
        r["methods"]["coverage@3"]["facet_recall"]
        > r["methods"]["mmr@3"]["facet_recall"]
        for r in results
    )

    gate = {
        "coverage_wins_dense_queries": coverage_wins_dense,
        "coverage_ties_dense_queries": coverage_ties_dense,
        "coverage_wins_mmr_queries": coverage_wins_mmr,
        "candidate_pool_limited_queries": [
            r["id"]
            for r in results
            if not r["methods"]["dense@5_ceiling"][
                "full_facet_coverage"
            ]
        ],
        "interpretation": (
            "For the core idea to remain promising, coverage@3 should improve "
            "mean facet recall and/or full-coverage rate over both Dense@3 and "
            "MMR@3 without using gold facets. Queries whose Dense@5 ceiling is "
            "below 1.0 are candidate-recall limited and cannot be solved by "
            "re-ranking/selection alone."
        ),
    }

    payload = {
        "config": {
            "generation_model": GENERATION_MODEL,
            "candidate_k": args.candidate_k,
            "select_k": args.select_k,
            "mmr_lambda": args.mmr_lambda,
            "alpha_rel": args.alpha_rel,
            "beta_gain": args.beta_gain,
            "gamma_red": args.gamma_red,
            "adaptive_min_k": args.adaptive_min_k,
            "adaptive_max_k": args.adaptive_max_k,
            "coverage_target": args.coverage_target,
            "min_gain": args.min_gain,
            "selection_uses_gold": False,
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

    print("\n===== EVIDENCE SELECTION V0 =====")
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
    print(
        "coverage_wins_dense_queries=",
        gate["coverage_wins_dense_queries"],
    )
    print(
        "coverage_ties_dense_queries=",
        gate["coverage_ties_dense_queries"],
    )
    print(
        "coverage_wins_mmr_queries=",
        gate["coverage_wins_mmr_queries"],
    )
    print(
        "candidate_pool_limited_queries=",
        gate["candidate_pool_limited_queries"],
    )
    print("\noutput:", args.output)


if __name__ == "__main__":
    main()
