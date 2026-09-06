"""Export all comparison questions for gold/obligation audit v2.6.

No API calls. No data modification.

Purpose
-------
Before further method tuning, inspect whether:
1. each gold facet is actually required by the question;
2. each v2.5 structured obligation is query-faithful;
3. any obligation was created only by forced symmetry or unsupported expansion;
4. FullFacet failures are genuine method failures rather than benchmark-scope
   mismatch.

Output
------
tests/annotations/comparison_audit_v26.md
tests/annotations/comparison_audit_v26.json

Run
---
python3 tests/export_comparison_audit_v26.py
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Dict, List

PROJECT_ROOT = Path(__file__).resolve().parents[1]

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
DEFAULT_STRUCT = (
    PROJECT_ROOT
    / "tests"
    / "results"
    / "structured_contrastive_v25.json"
)
DEFAULT_MD = (
    PROJECT_ROOT
    / "tests"
    / "annotations"
    / "comparison_audit_v26.md"
)
DEFAULT_JSON = (
    PROJECT_ROOT
    / "tests"
    / "annotations"
    / "comparison_audit_v26.json"
)


def load_jsonl(path: Path) -> Dict[str, Dict]:
    out = {}
    with path.open("r", encoding="utf-8") as f:
        for raw in f:
            if raw.strip():
                obj = json.loads(raw)
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


def dense_rank(row: Dict):
    raw = str(row.get("dense_rank", "")).strip()
    if not raw:
        return None
    try:
        return int(float(raw))
    except ValueError:
        return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--benchmark", type=Path, default=DEFAULT_BENCHMARK)
    ap.add_argument("--pool", type=Path, default=DEFAULT_POOL)
    ap.add_argument("--facets", type=Path, default=DEFAULT_FACETS)
    ap.add_argument("--setr", type=Path, default=DEFAULT_SETR)
    ap.add_argument("--diag", type=Path, default=DEFAULT_DIAG)
    ap.add_argument("--structured", type=Path, default=DEFAULT_STRUCT)
    ap.add_argument("--output", type=Path, default=DEFAULT_MD)
    ap.add_argument("--json-output", type=Path, default=DEFAULT_JSON)
    args = ap.parse_args()

    benchmark = load_jsonl(args.benchmark)
    facets = load_jsonl(args.facets)
    pool = load_pool(args.pool)

    setr_raw = json.loads(args.setr.read_text(encoding="utf-8"))
    diag_raw = json.loads(args.diag.read_text(encoding="utf-8"))
    struct_raw = json.loads(args.structured.read_text(encoding="utf-8"))

    setr = {x["id"]: x for x in setr_raw["per_query"]}
    diag = {x["id"]: x for x in diag_raw["per_query"]}
    struct = {x["id"]: x for x in struct_raw["per_query"]}

    qids = [
        qid
        for qid, q in benchmark.items()
        if not q.get("is_out_of_scope", False)
        and str(q.get("type", "")).lower() == "comparison"
    ]

    lines: List[str] = []
    payload = {"question_ids": qids, "per_question": {}}

    lines.append("# Comparison Gold / Obligation Audit v2.6")
    lines.append("")
    lines.append(
        "Goal: distinguish genuine method failures from benchmark-scope "
        "or structured-obligation overgeneration."
    )
    lines.append("")
    lines.append(
        "Audit principle: a CORE facet must be explicitly requested by the "
        "question or logically necessary to answer it. Useful extra facts "
        "should not be core FullFacet requirements."
    )
    lines.append("")

    for qid in qids:
        q = benchmark[qid]
        f = facets[qid]
        s = setr[qid]
        d = diag[qid]
        st = struct[qid]

        lines.append("---")
        lines.append("")
        lines.append(f"## {qid}")
        lines.append("")
        lines.append(f"**Question:** {q['question']}")
        lines.append("")
        lines.append(
            f"**Reference answer:** {q.get('reference_answer', '')}"
        )
        lines.append("")
        lines.append(
            f"**v2.1 gold class:** `{d['classification']}`"
        )
        lines.append(
            f"**v2.5 predicted class:** `{st['predicted_class']}`"
        )
        lines.append("")

        lines.append("### A. Gold facets")
        lines.append("")
        for i, facet in enumerate(f.get("facets", []), 1):
            if isinstance(facet, str):
                fid = f"f{i}"
                desc = facet.strip()
            elif isinstance(facet, dict):
                fid = str(facet.get("facet_id") or f"f{i}").strip()
                desc = str(
                    facet.get("description")
                    or facet.get("text")
                    or facet.get("facet")
                    or facet.get("content")
                    or ""
                ).strip()
            else:
                fid = f"f{i}"
                desc = str(facet).strip()

            if not desc:
                desc = "<EMPTY_FACET_DESCRIPTION>"

            lines.append(f"- `{fid}` {desc}")
            lines.append(
                "  - [ ] CORE_REQUIRED — explicitly asked or necessary"
            )
            lines.append(
                "  - [ ] AUXILIARY — useful but should not count toward FullFacet"
            )
            lines.append(
                "  - [ ] INVALID / needs rewrite"
            )
            lines.append("  - Notes:")
        lines.append("")

        lines.append("### B. SetR requirements")
        lines.append("")
        for req in s.get("requirements", []):
            lines.append(f"- {req}")
        lines.append("")
        lines.append(
            f"**SetR selected:** `{s['setr_selected_ids']}`"
        )
        lines.append("")

        lines.append("### C. v2.5 structured obligations")
        lines.append("")
        lines.append("**Entities:**")
        for e in st["structure"]["entities"]:
            lines.append(
                f"- `{e['entity_id']}` {e['name']}"
            )
        lines.append("")
        lines.append("**Aspects:**")
        for a in st["structure"]["aspects"]:
            lines.append(
                f"- `{a['aspect_id']}` {a['description']}"
            )
        lines.append("")
        lines.append("**Obligations:**")
        for o in st["structure"]["obligations"]:
            lines.append(
                f"- `{o['obligation_id']}` "
                f"({o['entity_id']} × {o['aspect_id']}) "
                f"{o['description']}"
            )
            lines.append(
                "  - [ ] QUERY_FAITHFUL"
            )
            lines.append(
                "  - [ ] FORCED_SYMMETRY — mirrored fact not actually requested"
            )
            lines.append(
                "  - [ ] OVEREXPANDED — invented a comparison dimension"
            )
            lines.append(
                "  - [ ] TOO_COARSE / needs split"
            )
            lines.append("  - Notes:")
        lines.append("")
        lines.append(
            f"**Structured selected:** `{st['structured_selected_ids']}`"
        )
        lines.append("")

        lines.append("### D. Dense Top-5")
        lines.append("")

        dense_rows = []
        for cid, prow in pool[qid].items():
            r = dense_rank(prow)
            if r is not None and 1 <= r <= 5:
                dense_rows.append((r, cid, prow))
        dense_rows.sort()

        for r, cid, prow in dense_rows:
            label = str(prow.get("relevance_label", "")).strip()
            mapped = f.get("chunk_support", {}).get(cid, [])
            lines.append(
                f"#### rank={r} `{cid}` "
                f"label={label or 'unjudged'} mapped={mapped}"
            )
            lines.append("")
            lines.append(prow.get("chunk_text", "").strip())
            lines.append("")

        lines.append("### E. Known relevant outside Top-5")
        lines.append("")

        outside = []
        for cid, prow in pool[qid].items():
            label = str(prow.get("relevance_label", "")).strip()
            r = dense_rank(prow)
            if label not in {"1", "2"}:
                continue
            if r is not None and 1 <= r <= 5:
                continue
            outside.append((cid, prow))

        if outside:
            for cid, prow in outside:
                lines.append(
                    f"- `{cid}` label={prow['relevance_label']} "
                    f"mapped={f.get('chunk_support', {}).get(cid, [])}"
                )
                lines.append(
                    f"  - {prow.get('chunk_text', '').strip()}"
                )
        else:
            lines.append("- none")
        lines.append("")

        lines.append("### F. Final human decision")
        lines.append("")
        lines.append(
            "- [ ] Gold facets are query-faithful as-is"
        )
        lines.append(
            "- [ ] Gold facet set must be revised"
        )
        lines.append(
            "- [ ] v2.5 structured obligations are query-faithful"
        )
        lines.append(
            "- [ ] v2.5 contains forced symmetry / overexpansion"
        )
        lines.append(
            "- [ ] Original SetR failure remains a genuine failure after audit"
        )
        lines.append(
            "- [ ] Original SetR failure should be reclassified after audit"
        )
        lines.append("- Notes:")
        lines.append("")

        payload["per_question"][qid] = {
            "question": q["question"],
            "reference_answer": q.get("reference_answer", ""),
            "gold_class": d["classification"],
            "v25_predicted_class": st["predicted_class"],
            "facets": f.get("facets", []),
            "chunk_support": f.get("chunk_support", {}),
            "setr_requirements": s.get("requirements", []),
            "setr_selected_ids": s["setr_selected_ids"],
            "structured": st["structure"],
            "structured_selected_ids": st["structured_selected_ids"],
            "dense_top5": [
                {
                    "rank": r,
                    "chunk_id": cid,
                    "label": prow.get("relevance_label", ""),
                    "mapped_facets": f.get("chunk_support", {}).get(cid, []),
                    "text": prow.get("chunk_text", ""),
                }
                for r, cid, prow in dense_rows
            ],
            "relevant_outside_top5": [
                {
                    "chunk_id": cid,
                    "label": prow.get("relevance_label", ""),
                    "mapped_facets": f.get("chunk_support", {}).get(cid, []),
                    "text": prow.get("chunk_text", ""),
                }
                for cid, prow in outside
            ],
        }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("\n".join(lines), encoding="utf-8")
    args.json_output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print("===== COMPARISON AUDIT EXPORT V2.6 =====")
    print("comparison_questions =", len(qids))
    print("question_ids =", qids)
    print("markdown =", args.output)
    print("json =", args.json_output)


if __name__ == "__main__":
    main()
