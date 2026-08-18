import json
import statistics
from pathlib import Path

from rag.config import DEFAULT_TOP_K
from rag.main import (
    prepare_knowledge_base,
    retrieve,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]

TEST_FILE = (
    PROJECT_ROOT
    / "tests"
    / "test_questions.jsonl"
)

OUTPUT_FILE = (
    PROJECT_ROOT
    / "rag"
    / "threshold_calibration.json"
)


def load_questions():
    questions = []

    with TEST_FILE.open(
        "r",
        encoding="utf-8",
    ) as file:
        for line in file:
            line = line.strip()

            if line:
                questions.append(
                    json.loads(line)
                )

    return questions


def main():
    print("正在初始化正式知识库...")
    chunks = prepare_knowledge_base()

    print(f"知识片段数量：{len(chunks)}")
    print()

    questions = load_questions()

    records = []

    for item in questions:
        retrieved = retrieve(
            query=item["question"],
            chunks=chunks,
            top_k=DEFAULT_TOP_K,
        )

        scores = [
            round(chunk["score"], 6)
            for chunk in retrieved
        ]

        record = {
            "id": item["id"],
            "question": item["question"],
            "is_out_of_scope": item.get(
                "is_out_of_scope",
                False,
            ),
            "scores": scores,
            "top1_score": (
                scores[0]
                if scores
                else None
            ),
            "retrieved_chunk_ids": [
                chunk["chunk_id"]
                for chunk in retrieved
            ],
        }

        records.append(record)

        scope = (
            "OUT"
            if record["is_out_of_scope"]
            else "IN "
        )

        print(
            f'{item["id"]} [{scope}] '
            f'{item["question"]}'
        )

        print(
            "scores:",
            scores,
        )

        if retrieved:
            print(
                "top1:",
                retrieved[0]["chunk_id"],
                "|",
                retrieved[0]["chapter"],
                "|",
                retrieved[0]["section"],
            )

        print("-" * 70)


    in_scores = [
        record["top1_score"]
        for record in records
        if (
            not record["is_out_of_scope"]
            and record["top1_score"] is not None
        )
    ]

    out_scores = [
        record["top1_score"]
        for record in records
        if (
            record["is_out_of_scope"]
            and record["top1_score"] is not None
        )
    ]


    summary = {
        "in_scope_count": len(in_scores),
        "out_of_scope_count": len(out_scores),
        "in_scope_top1_min": (
            min(in_scores)
            if in_scores
            else None
        ),
        "in_scope_top1_max": (
            max(in_scores)
            if in_scores
            else None
        ),
        "in_scope_top1_mean": (
            statistics.mean(in_scores)
            if in_scores
            else None
        ),
        "out_of_scope_top1_min": (
            min(out_scores)
            if out_scores
            else None
        ),
        "out_of_scope_top1_max": (
            max(out_scores)
            if out_scores
            else None
        ),
        "out_of_scope_top1_mean": (
            statistics.mean(out_scores)
            if out_scores
            else None
        ),
        "separable": False,
        "candidate_threshold": None,
    }


    if in_scores and out_scores:
        min_in = min(in_scores)
        max_out = max(out_scores)

        if min_in > max_out:
            summary["separable"] = True
            summary["candidate_threshold"] = (
                min_in + max_out
            ) / 2


    output = {
        "summary": summary,
        "records": records,
    }

    with OUTPUT_FILE.open(
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(
            output,
            file,
            ensure_ascii=False,
            indent=2,
        )


    print()
    print("=" * 70)
    print("阈值标定汇总")
    print("=" * 70)

    print(
        json.dumps(
            summary,
            ensure_ascii=False,
            indent=2,
        )
    )

    print()
    print(
        f"完整结果已保存到：{OUTPUT_FILE}"
    )


if __name__ == "__main__":
    main()
