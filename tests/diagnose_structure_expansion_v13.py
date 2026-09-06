"""Structure diagnostic v1.3 on the 14 Dense Top-5 incomplete-coverage queries.

Pipeline
--------
Query
 -> query-only information-need decomposition
 -> Dense Top-5
 -> LLM need->candidate support matrix
 -> strongest Dense anchor per need
 -> same numeric section-family expansion
 -> known-gold recovery diagnostic

Important:
- reference answers / gold facets / relevance labels are NEVER used for
  decomposition, support scoring, anchor selection, or expansion.
- gold_chunk_ids are used only AFTER expansion for diagnostic evaluation.
- newly expanded unjudged chunks are never treated as irrelevant.
- caches are reused from earlier experiments when signatures match.

This script intentionally targets only queries whose Dense Top-5 fails to
cover all known relevant chunks in Benchmark v1.

Run:
    python3 tests/diagnose_structure_expansion_v13.py
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
from typing import Dict, List, Optional, Sequence, Tuple

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
DEFAULT_POOL = PROJECT_ROOT / "tests" / "retrieval_pool_v1.csv"
DEFAULT_KNOWLEDGE = PROJECT_ROOT / "knowledge_base" / "ds_chunks.jsonl"

DEFAULT_DECOMP_CACHE = (
    PROJECT_ROOT
    / ".cache"
    / "rag"
    / "structure_v13_decompositions.json"
)
DEFAULT_SUPPORT_CACHE = (
    PROJECT_ROOT
    / ".cache"
    / "rag"
    / "structure_v13_support.json"
)
DEFAULT_OUTPUT = (
    PROJECT_ROOT
    / "tests"
    / "results"
    / "structure_expansion_diagnostic_v13.json"
)

INCOMPLETE_IDS = [
    "q006", "q007", "q008", "q014", "q017", "q022", "q034",
    "q037", "q039", "q042", "q046", "q048", "q049", "q050",
]

CHUNK_ID_RE = re.compile(r"^(?P<prefix>.+?)_(?P<num>\d+)$")
SECTION_FAMILY_RE = re.compile(r"^\s*(\d+(?:\.\d+)*)")

DECOMP_VERSION = "v13_minimal_nonredundant"
SUPPORT_VERSION = "v13_support_0_3"


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


def load_judgments(path: Path) -> Dict[Tuple[str, str], Dict]:
    out = {}
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            out[(row["question_id"], row["chunk_id"])] = row
    return out


def strip_json_fence(text: str) -> str:
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, count=1)
        text = re.sub(r"\s*```$", "", text, count=1)
    return text.strip()


def chunk_ordinal(chunk_id: str) -> Optional[int]:
    m = CHUNK_ID_RE.match(chunk_id)
    return int(m.group("num")) if m else None


def section_family(section: object) -> Optional[str]:
    s = str(section or "").strip()
    if not s:
        return None
    m = SECTION_FAMILY_RE.match(s)
    return m.group(1) if m else None


def same_nonempty(a: object, b: object) -> bool:
    sa = str(a or "").strip()
    sb = str(b or "").strip()
    return bool(sa and sb and sa == sb)


class QueryFacetDecomposer:
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

        self.cache: Dict[str, Dict] = {}
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
        cached = self.cache.get(qid)
        if (
            isinstance(cached, dict)
            and cached.get("query") == query
            and cached.get("model") == self.model
            and cached.get("version") == DECOMP_VERSION
            and cached.get("needs")
        ):
            return [str(x) for x in cached["needs"]]

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
        needs = [
            str(x).strip()
            for x in obj.get("facets", [])
            if str(x).strip()
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


class LLMSupportScorer:
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

        self.cache: Dict[str, Dict] = {}
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
    def signature(
        query: str,
        needs: Sequence[str],
        candidate_ids: Sequence[str],
        candidate_texts: Sequence[str],
    ) -> str:
        payload = json.dumps(
            {
                "query": query,
                "needs": list(needs),
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
        needs: Sequence[str],
        candidate_ids: Sequence[str],
        candidate_texts: Sequence[str],
    ) -> np.ndarray:
        sig = self.signature(
            query, needs, candidate_ids, candidate_texts
        )

        cached = self.cache.get(qid)
        if (
            isinstance(cached, dict)
            and cached.get("model") == self.model
            and cached.get("version") == SUPPORT_VERSION
            and cached.get("signature") == sig
            and isinstance(cached.get("matrix"), list)
        ):
            return np.asarray(cached["matrix"], dtype=np.float32)

        need_lines = "\n".join(
            f"N{i+1}: {x}" for i, x in enumerate(needs)
        )
        cand_lines = "\n\n".join(
            f"C{i+1} [{cid}]\n{text}"
            for i, (cid, text) in enumerate(
                zip(candidate_ids, candidate_texts)
            )
        )

        base_prompt = f"""
你正在评估检索证据，不是在回答问题。

用户问题：
{query}

待满足的信息需求：
{need_lines}

候选证据：
{cand_lines}

请独立判断每条候选证据对每个信息需求的支撑强度。

评分：
0 = 无关，不能提供可用证据
1 = 只有弱背景关系，不能实质支撑该需求
2 = 提供有用的部分证据，或结合用户问题即可做一步直接推导
3 = 直接、强力地支撑该信息需求

严格要求：
- 只能依据“用户问题 + 候选证据”评分。
- 不使用标准答案，不补充外部知识。
- 不因为关键词相似就给高分。
- 同一候选可以支持多个需求。
- 只输出JSON：
{{"scores":[[...],[...]]}}
""".strip()

        expected = (len(needs), len(candidate_ids))
        matrix = None
        last_error = None

        for attempt in range(3):
            prompt = base_prompt
            if attempt:
                prompt += (
                    "\n\n【格式纠正】\n"
                    f"必须输出 {expected[0]} 行 × {expected[1]} 列的 "
                    "scores 矩阵；每个值只能是0、1、2、3。"
                )

            rsp = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "你是严格的RAG证据支撑判定器。"
                            "只评估证据，不回答问题。"
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0.0,
                extra_body={"enable_thinking": False},
            )

            try:
                obj = json.loads(
                    strip_json_fence(
                        rsp.choices[0].message.content
                    )
                )

                raw = obj.get("scores")

                def scalar_value(v):
                    if isinstance(v, dict):
                        for key in ("score", "value", "support"):
                            if key in v:
                                return scalar_value(v[key])
                        raise ValueError(
                            f"cannot extract scalar from dict: {v}"
                        )
                    return float(v)

                def row_to_list(row):
                    # Already a normal list.
                    if isinstance(row, list):
                        return [
                            scalar_value(v)
                            for v in row
                        ]

                    if not isinstance(row, dict):
                        raise ValueError(
                            f"unsupported row type: {type(row)}"
                        )

                    # Common format:
                    # {"scores": [3, 0, 2, ...]}
                    for key in ("scores", "values"):
                        if key in row:
                            inner = row[key]

                            if isinstance(inner, list):
                                return [
                                    scalar_value(v)
                                    for v in inner
                                ]

                            if isinstance(inner, dict):
                                row = inner
                                break

                    # Common format:
                    # {"C1": 3, "C2": 0, ...}
                    vals = []
                    for j in range(expected[1]):
                        found = False
                        for key in (
                            f"C{j+1}",
                            f"c{j+1}",
                            str(j+1),
                        ):
                            if key in row:
                                vals.append(
                                    scalar_value(row[key])
                                )
                                found = True
                                break

                        if not found:
                            vals = []
                            break

                    if vals:
                        return vals

                    # Last fallback: keep numeric scalar fields
                    # in insertion order and ignore labels such as
                    # "need": "N1".
                    vals = []
                    for value in row.values():
                        try:
                            vals.append(
                                scalar_value(value)
                            )
                        except Exception:
                            pass

                    if not vals:
                        raise ValueError(
                            f"cannot parse score row: {row}"
                        )

                    return vals

                # Outer dict format:
                # {"N1": [...], "N2": [...]}
                if isinstance(raw, dict):
                    rows = []

                    for i in range(expected[0]):
                        found = False
                        for key in (
                            f"N{i+1}",
                            f"n{i+1}",
                            str(i+1),
                        ):
                            if key in raw:
                                rows.append(
                                    row_to_list(raw[key])
                                )
                                found = True
                                break

                        if not found:
                            rows = []
                            break

                    if rows:
                        raw = rows
                    else:
                        raw = [
                            row_to_list(v)
                            for v in raw.values()
                        ]

                # list[dict] format
                elif (
                    isinstance(raw, list)
                    and raw
                    and all(
                        isinstance(row, dict)
                        for row in raw
                    )
                ):
                    raw = [
                        row_to_list(row)
                        for row in raw
                    ]

                cand = np.asarray(
                    raw,
                    dtype=np.float32,
                )

                # Qwen occasionally returns candidates × needs
                # instead of needs × candidates.
                if cand.shape == (
                    expected[1],
                    expected[0],
                ):
                    print(
                        f"  NOTE: {qid} support matrix "
                        f"returned transposed {cand.shape}; "
                        f"auto-transposing to {expected}"
                    )
                    cand = cand.T

                if cand.shape != expected:
                    raise ValueError(
                        f"shape={cand.shape}, expected={expected}"
                    )

                if np.any(cand < 0) or np.any(cand > 3):
                    raise ValueError(
                        "scores must be in [0,3]"
                    )

                matrix = cand / 3.0
                break

            except Exception as exc:
                last_error = exc
                print(
                    f"  WARNING: {qid} support invalid "
                    f"(attempt {attempt+1}/3): {exc}"
                )

        if matrix is None:
            raise RuntimeError(
                f"{qid}: failed support matrix: {last_error}"
            )

        self.cache[qid] = {
            "model": self.model,
            "version": SUPPORT_VERSION,
            "signature": sig,
            "needs": list(needs),
            "candidate_ids": list(candidate_ids),
            "matrix": matrix.tolist(),
        }
        self._save()
        return matrix


def choose_need_anchors(
    candidate_ids: Sequence[str],
    needs: Sequence[str],
    support: np.ndarray,
    min_support: float,
) -> Tuple[List[str], List[Dict]]:
    anchors: List[str] = []
    details = []

    for nidx, (need, row) in enumerate(zip(needs, support), 1):
        ranked = sorted(
            range(len(candidate_ids)),
            key=lambda i: (-float(row[i]), i),
        )

        valid = [
            i for i in ranked
            if float(row[i]) + 1e-6 >= min_support
        ]

        fallback = False
        if not valid:
            valid = ranked[:1]
            fallback = True

        i = valid[0]
        cid = candidate_ids[i]
        if cid not in anchors:
            anchors.append(cid)

        details.append(
            {
                "need_index": nidx,
                "need": need,
                "anchor_chunk_id": cid,
                "dense_rank": i + 1,
                "support": round(float(row[i]), 4),
                "fallback": fallback,
            }
        )

    return anchors, details


def structural_relation(
    seed: Dict,
    cand: Dict,
    max_distance: int,
) -> Optional[Tuple[float, str]]:
    if seed["chunk_id"] == cand["chunk_id"]:
        return None

    if not same_nonempty(seed.get("source_file"), cand.get("source_file")):
        return None
    if not same_nonempty(seed.get("chapter"), cand.get("chapter")):
        return None

    sf = section_family(seed.get("section"))
    cf = section_family(cand.get("section"))
    if not sf or not cf or sf != cf:
        return None

    a = chunk_ordinal(str(seed["chunk_id"]))
    b = chunk_ordinal(str(cand["chunk_id"]))
    if a is None or b is None:
        return None

    dist = abs(a - b)
    if dist == 0 or dist > max_distance:
        return None

    same_section = same_nonempty(
        seed.get("section"), cand.get("section")
    )

    score = (6.0 if same_section else 5.0) - 0.25 * dist
    relation = (
        f"same_section_distance{dist}"
        if same_section
        else f"same_section_family_{sf}_distance{dist}"
    )
    return score, relation


def expand(
    dense_ids: Sequence[str],
    anchors: Sequence[str],
    chunk_map: Dict[str, Dict],
    chunks: Sequence[Dict],
    max_distance: int,
    max_new: int,
) -> Tuple[List[str], List[Dict]]:
    dense_set = set(dense_ids)
    best: Dict[str, Dict] = {}

    for anchor_order, seed_id in enumerate(anchors, 1):
        seed = chunk_map[seed_id]

        for cand in chunks:
            cid = str(cand["chunk_id"])
            if cid in dense_set:
                continue

            relation = structural_relation(
                seed, cand, max_distance
            )
            if relation is None:
                continue

            rel_score, rel_name = relation
            score = (
                rel_score
                + (len(anchors) - anchor_order + 1) * 0.01
            )

            rec = {
                "chunk_id": cid,
                "score": score,
                "relation": rel_name,
                "seed_chunk_id": seed_id,
                "section": cand.get("section"),
                "chapter": cand.get("chapter"),
                "source_file": cand.get("source_file"),
                "text": cand.get("text", ""),
            }

            old = best.get(cid)
            if old is None or score > old["score"]:
                best[cid] = rec

    ranked = sorted(
        best.values(),
        key=lambda x: (-x["score"], x["chunk_id"]),
    )[:max_new]

    expanded_ids = (
        list(dense_ids)
        + [x["chunk_id"] for x in ranked]
    )
    return expanded_ids, ranked


def recall(ids: Sequence[str], gold: Sequence[str]) -> float:
    g = set(gold)
    if not g:
        return 0.0
    return len(set(ids) & g) / len(g)


def main() -> None:
    load_dotenv(PROJECT_ROOT / ".env", override=False)

    ap = argparse.ArgumentParser()
    ap.add_argument("--benchmark", type=Path, default=DEFAULT_BENCHMARK)
    ap.add_argument("--pool", type=Path, default=DEFAULT_POOL)
    ap.add_argument("--knowledge", type=Path, default=DEFAULT_KNOWLEDGE)
    ap.add_argument("--decomp-cache", type=Path, default=DEFAULT_DECOMP_CACHE)
    ap.add_argument("--support-cache", type=Path, default=DEFAULT_SUPPORT_CACHE)
    ap.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    ap.add_argument("--min-support", type=float, default=2.0/3.0)
    ap.add_argument("--max-distance", type=int, default=4)
    ap.add_argument("--max-new", type=int, default=5)
    args = ap.parse_args()

    benchmark_all = {
        x["id"]: x
        for x in load_jsonl(args.benchmark)
    }

    missing = [
        qid for qid in INCOMPLETE_IDS
        if qid not in benchmark_all
    ]
    if missing:
        raise RuntimeError(
            f"benchmark missing incomplete IDs: {missing}"
        )

    judgments = load_judgments(args.pool)
    chunks = load_chunks_from_jsonl(args.knowledge)
    chunk_map = {str(x["chunk_id"]): x for x in chunks}

    dense = DenseRetriever()
    dense.prepare(chunks, use_cache=True)

    decomposer = QueryFacetDecomposer(
        GENERATION_MODEL, args.decomp_cache
    )
    scorer = LLMSupportScorer(
        GENERATION_MODEL, args.support_cache
    )

    rows = []

    for no, qid in enumerate(INCOMPLETE_IDS, 1):
        q = benchmark_all[qid]
        query = q["question"]

        print("\n" + "=" * 80)
        print(f"[{no}/{len(INCOMPLETE_IDS)}] {qid}: {query}")

        retrieved = dense.retrieve(
            query=query,
            chunks=chunks,
            top_k=5,
        )
        dense_ids = [
            str(x["chunk_id"]) for x in retrieved
        ]
        candidate_texts = [
            str(chunk_map[cid]["text"])
            for cid in dense_ids
        ]

        needs = decomposer.decompose(qid, query)
        print("needs:")
        for i, need in enumerate(needs, 1):
            print(f"  N{i}: {need}")

        support = scorer.score(
            qid,
            query,
            needs,
            dense_ids,
            candidate_texts,
        )

        print("support:")
        for i, row in enumerate(support, 1):
            print(
                f"  N{i}:",
                [round(float(v), 3) for v in row],
            )

        anchors, anchor_details = choose_need_anchors(
            dense_ids,
            needs,
            support,
            args.min_support,
        )

        print("anchors:")
        for d in anchor_details:
            print(
                f"  N{d['need_index']} -> "
                f"{d['anchor_chunk_id']} "
                f"(rank={d['dense_rank']}, "
                f"support={d['support']}, "
                f"fallback={d['fallback']})"
            )

        expanded_ids, new_candidates = expand(
            dense_ids,
            anchors,
            chunk_map,
            chunks,
            args.max_distance,
            args.max_new,
        )

        gold_ids = [
            str(x) for x in q.get("gold_chunk_ids", [])
        ]
        before = set(dense_ids) & set(gold_ids)
        after = set(expanded_ids) & set(gold_ids)
        recovered = sorted(after - before)

        annotated_new = []
        unjudged = []

        for rec in new_candidates:
            item = dict(rec)
            key = (qid, rec["chunk_id"])
            j = judgments.get(key)

            if j is None:
                item["judged"] = False
                item["relevance_label"] = None
                unjudged.append(rec["chunk_id"])
            else:
                item["judged"] = True
                item["relevance_label"] = j.get(
                    "relevance_label"
                )

            item["is_known_gold"] = (
                rec["chunk_id"] in set(gold_ids)
            )
            annotated_new.append(item)

        before_recall = recall(dense_ids, gold_ids)
        after_recall = recall(expanded_ids, gold_ids)

        print(
            "known GoldRecall:",
            round(before_recall, 4),
            "->",
            round(after_recall, 4),
        )
        print(
            "recovered known gold:",
            recovered or "[]",
        )

        print("new structural candidates:")
        if not annotated_new:
            print("  []")
        for item in annotated_new:
            print(
                " ",
                item["chunk_id"],
                f"via={item['relation']}",
                f"seed={item['seed_chunk_id']}",
                f"judged={item['judged']}",
                f"label={item['relevance_label']}",
                f"KNOWN_GOLD={item['is_known_gold']}",
            )
            print(
                "    ",
                str(item["text"])[:180],
            )

        rows.append(
            {
                "id": qid,
                "question": query,
                "needs": needs,
                "dense_ids": dense_ids,
                "anchor_ids": anchors,
                "anchor_details": anchor_details,
                "expanded_ids": expanded_ids,
                "new_candidates": annotated_new,
                "gold_ids": gold_ids,
                "dense_known_gold_recall": round(
                    before_recall, 4
                ),
                "expanded_known_gold_recall": round(
                    after_recall, 4
                ),
                "recovered_known_gold_ids": recovered,
                "unjudged_new_ids": unjudged,
            }
        )

    n = len(rows)

    dense_mean = sum(
        x["dense_known_gold_recall"]
        for x in rows
    ) / n
    expanded_mean = sum(
        x["expanded_known_gold_recall"]
        for x in rows
    ) / n

    total_new = sum(
        len(x["new_candidates"])
        for x in rows
    )
    unjudged_count = sum(
        len(x["unjudged_new_ids"])
        for x in rows
    )

    recovered_queries = [
        x["id"]
        for x in rows
        if x["recovered_known_gold_ids"]
    ]

    recovered_pairs = [
        (x["id"], cid)
        for x in rows
        for cid in x["recovered_known_gold_ids"]
    ]

    summary = {
        "queries": n,
        "target": "Dense Top5 incomplete-coverage queries",
        "generation_model": GENERATION_MODEL,
        "min_support": round(args.min_support, 4),
        "max_distance": args.max_distance,
        "max_new": args.max_new,
        "mean_unique_anchors_per_query": round(
            sum(len(x["anchor_ids"]) for x in rows) / n,
            4,
        ),
        "total_new_candidates": total_new,
        "avg_new_candidates_per_query": round(
            total_new / n, 4
        ),
        "mean_dense_known_gold_recall": round(
            dense_mean, 4
        ),
        "mean_expanded_known_gold_recall": round(
            expanded_mean, 4
        ),
        "known_gold_recall_gain": round(
            expanded_mean - dense_mean, 4
        ),
        "queries_with_recovered_known_gold": recovered_queries,
        "recovered_query_count": len(recovered_queries),
        "recovered_known_gold_pairs": recovered_pairs,
        "unjudged_new_pair_count": unjudged_count,
        "IMPORTANT": (
            "Diagnostic only. Expanded unjudged chunks must be "
            "human-adjudicated before formal comparison."
        ),
    }

    args.output.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    args.output.write_text(
        json.dumps(
            {
                "summary": summary,
                "per_query": rows,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print(
        "\n===== STRUCTURE EXPANSION "
        "DIAGNOSTIC V1.3 ====="
    )
    for k, v in summary.items():
        print(f"{k}={v}")

    print("\noutput:", args.output)


if __name__ == "__main__":
    main()
