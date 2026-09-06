"""Structured contrastive requirements diagnostic v2.5.

Purpose
-------
Test whether comparison questions benefit from a structured representation of
answer obligations rather than free-form requirements.

Only benchmark questions with type == "comparison" are used.

Prediction input:
    question
    Dense Top-5 passages

Never shown to the method:
    reference answer
    relevance labels
    gold chunks
    evaluation facets
    v2.1 gold failure class

Pipeline
--------
1. Query-only structured decomposition:
      entities
      comparison aspects
      atomic obligations

   Important constraints:
   - for a comparative aspect involving multiple entities, create one
     obligation per entity;
   - complexity/value "change" questions must preserve BOTH old/new values;
   - broad "特点 / 区别 / 变化 / 优缺点" must be decomposed into atomic
     contrastive dimensions instead of one vague requirement;
   - do not merge multiple independent facts into one obligation.

2. Score obligation x Dense-Top5 support on 0..3.

3. Diagnose the ORIGINAL SetR-style selection:
      solved
      selector_limited
      retrieval_limited

4. Build a structured minimal-cover selection from Dense Top-5 using only the
   predicted obligation-support matrix.

5. Evaluate both the diagnosis and the structured selection with human facets
   after prediction.

This is a Dev diagnostic, not a final method claim.

Run
---
python3 tests/diagnose_structured_contrastive_v25.py

First run: ~20 Qwen Flash calls for 10 comparison questions.
"""
from __future__ import annotations

import argparse
import csv
import itertools
import json
import os
import re
import sys
from pathlib import Path
from typing import Dict, List, Sequence, Set, Tuple

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
    / "structured_contrastive_v25.json"
)
DEFAULT_OUTPUT = (
    PROJECT_ROOT
    / "tests"
    / "results"
    / "structured_contrastive_v25.json"
)

VERSION = "structured_contrastive_v25"
SUPPORT_THRESHOLD = 2


def strip_json_fence(text: str) -> str:
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, count=1)
        text = re.sub(r"\s*```$", "", text, count=1)
    return text.strip()


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


def load_pool(path: Path) -> Dict[str, Dict[str, Dict]]:
    out: Dict[str, Dict[str, Dict]] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            out.setdefault(row["question_id"], {})[
                row["chunk_id"]
            ] = row
    return out


def dense5_ids(pool_q: Dict[str, Dict]) -> List[str]:
    ranked = []
    for cid, row in pool_q.items():
        raw = str(row.get("dense_rank", "")).strip()
        if not raw:
            continue
        try:
            rank = int(float(raw))
        except ValueError:
            continue
        if 1 <= rank <= 5:
            ranked.append((rank, cid))
    ranked.sort()
    return [cid for _, cid in ranked]


def normalize_matrix(raw, n_obl: int, n_cand: int) -> List[List[int]]:
    if isinstance(raw, dict):
        for key in ("support_matrix", "matrix", "scores", "support"):
            if key in raw:
                raw = raw[key]
                break

    if isinstance(raw, dict):
        vals = list(raw.values())
        if all(isinstance(x, list) for x in vals):
            raw = vals

    if not isinstance(raw, list):
        raise ValueError("support matrix is not a list")

    matrix = []
    for row in raw:
        if isinstance(row, dict):
            row = list(row.values())
        if not isinstance(row, list):
            raise ValueError("support matrix row is not a list")

        vals = []
        for x in row:
            if isinstance(x, bool):
                x = int(x)
            if isinstance(x, str):
                x = x.strip()
                if not re.fullmatch(r"-?\d+(?:\.\d+)?", x):
                    raise ValueError(f"non-numeric score {x!r}")
                x = float(x)
            if not isinstance(x, (int, float)):
                raise ValueError(f"bad score type {type(x).__name__}")
            v = int(round(float(x)))
            if not 0 <= v <= 3:
                raise ValueError(f"support score outside 0..3: {v}")
            vals.append(v)
        matrix.append(vals)

    if len(matrix) == n_obl and all(len(r) == n_cand for r in matrix):
        return matrix

    if len(matrix) == n_cand and all(len(r) == n_obl for r in matrix):
        return [
            [matrix[c][r] for c in range(n_cand)]
            for r in range(n_obl)
        ]

    raise ValueError(
        f"shape mismatch: got {len(matrix)} rows "
        f"with widths {[len(r) for r in matrix]}, "
        f"expected {n_obl}x{n_cand}"
    )


def normalize_structure(obj: Dict) -> Dict:
    entities = obj.get("entities", [])
    aspects = obj.get("aspects", [])
    obligations = obj.get("obligations", [])

    if not isinstance(entities, list) or len(entities) < 2:
        raise ValueError("need at least 2 entities")
    if not isinstance(aspects, list) or not aspects:
        raise ValueError("aspects missing")
    if not isinstance(obligations, list) or len(obligations) < 2:
        raise ValueError("need at least 2 obligations")

    entity_map = {}
    clean_entities = []
    for i, e in enumerate(entities, 1):
        if isinstance(e, str):
            eid = f"e{i}"
            name = e.strip()
        elif isinstance(e, dict):
            eid = str(e.get("entity_id") or f"e{i}").strip()
            name = str(e.get("name") or e.get("entity") or "").strip()
        else:
            continue
        if not name:
            continue
        entity_map[eid] = eid
        clean_entities.append({"entity_id": eid, "name": name})

    if len(clean_entities) < 2:
        raise ValueError("fewer than 2 valid entities")

    aspect_map = {}
    clean_aspects = []
    for i, a in enumerate(aspects, 1):
        if isinstance(a, str):
            aid = f"a{i}"
            desc = a.strip()
        elif isinstance(a, dict):
            aid = str(a.get("aspect_id") or f"a{i}").strip()
            desc = str(
                a.get("description") or a.get("aspect") or ""
            ).strip()
        else:
            continue
        if not desc:
            continue
        aspect_map[aid] = aid
        clean_aspects.append({"aspect_id": aid, "description": desc})

    if not clean_aspects:
        raise ValueError("no valid aspects")

    valid_eids = {x["entity_id"] for x in clean_entities}
    valid_aids = {x["aspect_id"] for x in clean_aspects}

    clean_obligations = []
    for i, o in enumerate(obligations, 1):
        if not isinstance(o, dict):
            continue
        oid = str(o.get("obligation_id") or f"o{i}").strip()
        eid = str(o.get("entity_id") or "").strip()
        aid = str(o.get("aspect_id") or "").strip()
        desc = str(
            o.get("description") or o.get("requirement") or ""
        ).strip()

        if eid not in valid_eids:
            raise ValueError(f"obligation {oid}: invalid entity_id={eid!r}")
        if aid not in valid_aids:
            raise ValueError(f"obligation {oid}: invalid aspect_id={aid!r}")
        if not desc:
            raise ValueError(f"obligation {oid}: empty description")

        clean_obligations.append(
            {
                "obligation_id": oid,
                "entity_id": eid,
                "aspect_id": aid,
                "description": desc,
            }
        )

    if len(clean_obligations) < 2:
        raise ValueError("too few valid obligations")

    # Canonical IDs make later inspection easier.
    e_old_to_new = {
        x["entity_id"]: f"e{i}"
        for i, x in enumerate(clean_entities, 1)
    }
    a_old_to_new = {
        x["aspect_id"]: f"a{i}"
        for i, x in enumerate(clean_aspects, 1)
    }

    canonical_entities = [
        {"entity_id": e_old_to_new[x["entity_id"]], "name": x["name"]}
        for x in clean_entities
    ]
    canonical_aspects = [
        {
            "aspect_id": a_old_to_new[x["aspect_id"]],
            "description": x["description"],
        }
        for x in clean_aspects
    ]
    canonical_obligations = []
    for i, x in enumerate(clean_obligations, 1):
        canonical_obligations.append(
            {
                "obligation_id": f"o{i}",
                "entity_id": e_old_to_new[x["entity_id"]],
                "aspect_id": a_old_to_new[x["aspect_id"]],
                "description": x["description"],
            }
        )

    return {
        "entities": canonical_entities,
        "aspects": canonical_aspects,
        "obligations": canonical_obligations,
    }


class StructuredContrastive:
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

    def decompose(self, qid: str, question: str) -> Dict:
        ck = f"{qid}:decomposition"
        cached = self.cache.get(ck)
        if (
            isinstance(cached, dict)
            and cached.get("version") == VERSION
            and cached.get("model") == self.model
            and cached.get("question") == question
            and cached.get("structure")
        ):
            return cached["structure"]

        prompt = f"""
你正在为“比较类问题”的RAG检索构造结构化回答义务。
只分析用户问题本身，不回答问题，不查看任何参考答案或检索证据。

问题：
{question}

任务：
1. 找出被比较的实体/方法/结构，至少2个。
2. 找出问题要求比较的原子维度（aspect）。
3. 将答案要求拆成“实体 × 比较维度”的原子 obligation。
4. 一个obligation只能表达一个独立事实，不要把多个事实压在一起。
5. 如果问题问“复杂度如何变化”“从A到B如何变化”，必须分别保留A和B的值/性质，不能只写最终值。
6. 如果问题使用“特点、区别、优缺点、有什么不同”等宽泛表达，不要保留一个含糊的“特点”维度：
   - 应拆成能真正区分这些实体的最少原子比较维度；
   - 对可以对称比较的维度，每个实体都建立对应obligation；
   - 不要把“机制 + 优点 + 缺点”塞进同一个obligation。
7. 如果问题还单独询问数值、复杂度、适用条件、原因等，必须作为独立aspect。
8. 总obligation通常2~8个，避免无关扩展。

只输出JSON：
{{
  "entities": [
    {{"entity_id":"e1","name":"实体1"}},
    {{"entity_id":"e2","name":"实体2"}}
  ],
  "aspects": [
    {{"aspect_id":"a1","description":"比较维度1"}},
    {{"aspect_id":"a2","description":"比较维度2"}}
  ],
  "obligations": [
    {{
      "obligation_id":"o1",
      "entity_id":"e1",
      "aspect_id":"a1",
      "description":"回答中必须明确给出的一个原子事实"
    }}
  ]
}}
""".strip()

        last_error = None
        for attempt in range(3):
            extra = ""
            if attempt:
                extra = (
                    "\n\n格式纠正：必须至少2个实体、1个aspect、2个obligations；"
                    "每个obligation必须引用有效的entity_id和aspect_id。"
                )

            rsp = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "你是严格的比较式问答需求结构化器。"
                            "只做query understanding，不回答问题。"
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
                structure = normalize_structure(obj)

                self.cache[ck] = {
                    "version": VERSION,
                    "model": self.model,
                    "question": question,
                    "structure": structure,
                }
                self._save()
                return structure
            except Exception as exc:
                last_error = exc
                print(
                    f"  WARNING {qid} decomposition attempt "
                    f"{attempt+1}/3: {exc}"
                )

        raise RuntimeError(
            f"{qid}: structured decomposition failed: {last_error}"
        )

    def support(
        self,
        qid: str,
        question: str,
        structure: Dict,
        candidate_ids: Sequence[str],
        candidate_texts: Sequence[str],
    ) -> List[List[int]]:
        ck = f"{qid}:support"
        obligations = structure["obligations"]
        obligation_texts = [x["description"] for x in obligations]

        cached = self.cache.get(ck)
        if (
            isinstance(cached, dict)
            and cached.get("version") == VERSION
            and cached.get("model") == self.model
            and cached.get("question") == question
            and cached.get("obligations") == obligation_texts
            and cached.get("candidate_ids") == list(candidate_ids)
            and cached.get("matrix")
        ):
            return cached["matrix"]

        obl_text = "\n".join(
            f"O{i+1}: {x['description']}"
            for i, x in enumerate(obligations)
        )
        cand_text = "\n\n".join(
            f"C{i+1} [{cid}]\n{text}"
            for i, (cid, text) in enumerate(
                zip(candidate_ids, candidate_texts)
            )
        )

        prompt = f"""
你正在评估Dense Top-5证据对“原子比较回答义务”的支撑程度。

问题：
{question}

原子回答义务：
{obl_text}

候选证据：
{cand_text}

逐一判断 obligation × candidate：

0 = 不支持或只有主题相关
1 = 弱背景，不能实际满足该原子义务
2 = 能支持该义务主要内容；或结合问题+证据做一步直接推导/简单计算即可
3 = 完整、明确、直接支持

严格规则：
- 每个obligation独立判断，不能因为同一证据支持另一个相邻obligation就顺带给高分。
- 如果obligation要求“A的值/性质”，只出现“B的值/性质”不能算支持。
- 如果obligation要求某个优点/缺点/特性，只描述一般机制不能自动算支持。
- 允许一步直接计算和直接阅读代码。
- 不允许依赖外部知识补全。
- 不回答问题。

只输出JSON：
{{
  "support_matrix": [
    [O1-C1, O1-C2, O1-C3, O1-C4, O1-C5],
    ...
  ]
}}
必须严格为 {len(obligations)} 行 × 5列，值只允许0/1/2/3。
""".strip()

        last_error = None
        for attempt in range(3):
            extra = ""
            if attempt:
                extra = (
                    f"\n\n格式纠正：输出严格 "
                    f"{len(obligations)}x5 的0/1/2/3整数矩阵。"
                )

            rsp = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "你是严格的原子证据支撑评分器。"
                            "不得把相邻义务合并判断。"
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
                    len(obligations),
                    len(candidate_ids),
                )

                self.cache[ck] = {
                    "version": VERSION,
                    "model": self.model,
                    "question": question,
                    "obligations": obligation_texts,
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
            f"{qid}: structured support failed: {last_error}"
        )


def covered_obligations(
    selected_ids: Sequence[str],
    candidate_ids: Sequence[str],
    matrix: Sequence[Sequence[int]],
) -> Set[int]:
    idx = {
        cid: i for i, cid in enumerate(candidate_ids)
    }
    selected_indices = [
        idx[cid] for cid in selected_ids if cid in idx
    ]

    covered = set()
    for o, row in enumerate(matrix):
        best = max(
            (row[i] for i in selected_indices),
            default=0,
        )
        if best >= SUPPORT_THRESHOLD:
            covered.add(o)
    return covered


def minimal_cover(
    candidate_ids: Sequence[str],
    matrix: Sequence[Sequence[int]],
) -> List[str] | None:
    all_obl = set(range(len(matrix)))

    for k in range(1, len(candidate_ids) + 1):
        combos = list(itertools.combinations(candidate_ids, k))
        # Stable tie break: lower total Dense rank first.
        combos.sort(
            key=lambda combo: sum(candidate_ids.index(cid) for cid in combo)
        )
        for combo in combos:
            if covered_obligations(combo, candidate_ids, matrix) == all_obl:
                return list(combo)
    return None


def best_partial_cover(
    candidate_ids: Sequence[str],
    matrix: Sequence[Sequence[int]],
) -> List[str]:
    all_obl = set(range(len(matrix)))
    best = None

    for k in range(1, len(candidate_ids) + 1):
        for combo in itertools.combinations(candidate_ids, k):
            cov = covered_obligations(combo, candidate_ids, matrix)
            score = (
                len(cov),
                -k,
                -sum(candidate_ids.index(cid) for cid in combo),
            )
            if best is None or score > best[0]:
                best = (score, list(combo), cov)

    return best[1] if best else [candidate_ids[0]]


def facet_eval(
    selected_ids: Sequence[str],
    facet_row: Dict,
) -> Dict:
    facets = {
        str(x["facet_id"])
        for x in facet_row.get("facets", [])
    }
    support = facet_row.get("chunk_support", {})

    covered = set()
    for cid in selected_ids:
        covered.update(support.get(cid, []))
    covered &= facets

    recall = len(covered) / len(facets) if facets else 0.0

    return {
        "k": len(selected_ids),
        "facet_recall": recall,
        "full_facet": abs(recall - 1.0) < 1e-9,
        "covered_facets": sorted(covered),
    }


def aggregate(rows: List[Dict], key: str) -> Dict:
    vals = [x[key] for x in rows]
    return {
        "mean_k": round(
            sum(x["k"] for x in vals) / len(vals), 4
        ),
        "mean_facet_recall": round(
            sum(x["facet_recall"] for x in vals) / len(vals), 4
        ),
        "full_facet_rate": round(
            sum(x["full_facet"] for x in vals) / len(vals), 4
        ),
    }


def main() -> None:
    load_dotenv(PROJECT_ROOT / ".env", override=False)

    ap = argparse.ArgumentParser()
    ap.add_argument("--benchmark", type=Path, default=DEFAULT_BENCHMARK)
    ap.add_argument("--pool", type=Path, default=DEFAULT_POOL)
    ap.add_argument("--facets", type=Path, default=DEFAULT_FACETS)
    ap.add_argument("--setr", type=Path, default=DEFAULT_SETR)
    ap.add_argument("--diag", type=Path, default=DEFAULT_DIAG)
    ap.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    ap.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = ap.parse_args()

    benchmark = load_jsonl(args.benchmark)
    pool = load_pool(args.pool)
    facets = load_jsonl(args.facets)

    setr = json.loads(args.setr.read_text(encoding="utf-8"))
    diag = json.loads(args.diag.read_text(encoding="utf-8"))

    setr_by_id = {x["id"]: x for x in setr["per_query"]}
    diag_by_id = {x["id"]: x for x in diag["per_query"]}

    method = StructuredContrastive(
        GENERATION_MODEL,
        args.cache,
    )

    comparison_qids = [
        qid
        for qid, q in benchmark.items()
        if not q.get("is_out_of_scope", False)
        and str(q.get("type", "")).lower() == "comparison"
    ]

    rows = []
    diag_correct = 0
    failure_detect_tp = 0
    failure_detect_fp = 0
    failure_detect_tn = 0
    failure_detect_fn = 0

    for pos, qid in enumerate(comparison_qids, 1):
        q = benchmark[qid]
        s = setr_by_id[qid]
        gold_class = diag_by_id[qid]["classification"]

        candidate_ids = dense5_ids(pool[qid])
        if len(candidate_ids) != 5:
            raise RuntimeError(
                f"{qid}: expected Dense Top5, got {len(candidate_ids)}"
            )

        candidate_texts = [
            pool[qid][cid]["chunk_text"]
            for cid in candidate_ids
        ]

        structure = method.decompose(
            qid,
            q["question"],
        )
        matrix = method.support(
            qid,
            q["question"],
            structure,
            candidate_ids,
            candidate_texts,
        )

        all_obl = set(range(len(structure["obligations"])))
        setr_selected = [
            str(x) for x in s["setr_selected_ids"]
        ]

        setr_cov = covered_obligations(
            setr_selected,
            candidate_ids,
            matrix,
        )
        top5_cov = covered_obligations(
            candidate_ids,
            candidate_ids,
            matrix,
        )

        missing_from_setr = sorted(all_obl - setr_cov)
        missing_from_top5 = sorted(all_obl - top5_cov)

        if not missing_from_setr:
            pred_class = "solved"
        elif not missing_from_top5:
            pred_class = "selector_limited"
        else:
            pred_class = "retrieval_limited"

        if pred_class == gold_class:
            diag_correct += 1

        gold_fail = gold_class != "solved"
        pred_fail = pred_class != "solved"

        if gold_fail and pred_fail:
            failure_detect_tp += 1
        elif not gold_fail and pred_fail:
            failure_detect_fp += 1
        elif not gold_fail and not pred_fail:
            failure_detect_tn += 1
        else:
            failure_detect_fn += 1

        cover = minimal_cover(candidate_ids, matrix)
        if cover is None:
            structured_selected = best_partial_cover(
                candidate_ids,
                matrix,
            )
        else:
            structured_selected = cover

        setr_eval = facet_eval(
            setr_selected,
            facets[qid],
        )
        structured_eval = facet_eval(
            structured_selected,
            facets[qid],
        )

        missing_obligation_texts = [
            structure["obligations"][i]["description"]
            for i in missing_from_setr
        ]
        top5_missing_texts = [
            structure["obligations"][i]["description"]
            for i in missing_from_top5
        ]

        row = {
            "id": qid,
            "question": q["question"],
            "gold_class": gold_class,
            "predicted_class": pred_class,
            "structure": structure,
            "candidate_ids": candidate_ids,
            "support_matrix": matrix,
            "setr_selected_ids": setr_selected,
            "structured_selected_ids": structured_selected,
            "missing_obligation_indices_from_setr": missing_from_setr,
            "missing_obligations_from_setr": missing_obligation_texts,
            "missing_obligation_indices_from_top5": missing_from_top5,
            "missing_obligations_from_top5": top5_missing_texts,
            "setr": setr_eval,
            "structured": structured_eval,
        }
        rows.append(row)

        print(
            f"[{pos}/{len(comparison_qids)}] {qid} "
            f"gold={gold_class} pred={pred_class} "
            f"| SetR K={setr_eval['k']} "
            f"Facet={setr_eval['facet_recall']:.4f} "
            f"| Struct K={structured_eval['k']} "
            f"Facet={structured_eval['facet_recall']:.4f}"
        )
        if missing_obligation_texts:
            print("  missing from SetR:")
            for text in missing_obligation_texts:
                print("   -", text)
        if top5_missing_texts:
            print("  missing from Top5:")
            for text in top5_missing_texts:
                print("   -", text)

    precision = (
        failure_detect_tp / (failure_detect_tp + failure_detect_fp)
        if (failure_detect_tp + failure_detect_fp)
        else 0.0
    )
    recall = (
        failure_detect_tp / (failure_detect_tp + failure_detect_fn)
        if (failure_detect_tp + failure_detect_fn)
        else 0.0
    )

    setr_summary = aggregate(rows, "setr")
    structured_summary = aggregate(rows, "structured")

    summary = {
        "comparison_query_count": len(rows),
        "diagnostic_class_accuracy": round(diag_correct / len(rows), 4),
        "failure_detection": {
            "tp": failure_detect_tp,
            "fp": failure_detect_fp,
            "tn": failure_detect_tn,
            "fn": failure_detect_fn,
            "precision": round(precision, 4),
            "recall": round(recall, 4),
        },
        "setr_on_comparison": setr_summary,
        "structured_on_comparison": structured_summary,
        "predicted_classes": {
            x["id"]: x["predicted_class"]
            for x in rows
        },
        "gold_classes": {
            x["id"]: x["gold_class"]
            for x in rows
        },
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(
            {
                "config": {
                    "model": GENERATION_MODEL,
                    "version": VERSION,
                    "support_threshold": SUPPORT_THRESHOLD,
                    "query_type": "comparison",
                    "uses_gold_for_prediction": False,
                    "uses_reference_for_prediction": False,
                    "uses_eval_facets_for_prediction": False,
                    "note": (
                        "Exploratory Dev diagnostic. Structured selection "
                        "uses only query-derived obligations and Dense Top5."
                    ),
                },
                "summary": summary,
                "per_query": rows,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print("\n===== STRUCTURED CONTRASTIVE V2.5 =====")
    print("comparison_query_count =", len(rows))
    print("diagnostic_class_accuracy =", summary["diagnostic_class_accuracy"])
    print("failure_detection =", summary["failure_detection"])
    print("setr_on_comparison =", setr_summary)
    print("structured_on_comparison =", structured_summary)
    print("predicted_classes =", summary["predicted_classes"])
    print("gold_classes =", summary["gold_classes"])

    print("\n===== FAILURE / REPAIR DETAILS =====")
    for x in rows:
        if x["gold_class"] == "solved" and x["predicted_class"] == "solved":
            continue
        print(
            "\n",
            x["id"],
            "gold=", x["gold_class"],
            "pred=", x["predicted_class"],
        )
        print(" entities=", x["structure"]["entities"])
        print(" aspects=", x["structure"]["aspects"])
        print(" obligations=")
        for o in x["structure"]["obligations"]:
            print("  ", o)
        print(" SetR=", x["setr_selected_ids"])
        print(" structured=", x["structured_selected_ids"])
        print(" missing_from_setr=", x["missing_obligations_from_setr"])
        print(" missing_from_top5=", x["missing_obligations_from_top5"])
        print(
            " facet:",
            "SetR=", x["setr"]["facet_recall"],
            "Structured=", x["structured"]["facet_recall"],
        )

    print("\noutput:", args.output)


if __name__ == "__main__":
    main()
