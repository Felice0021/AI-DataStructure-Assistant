#!/usr/bin/env python3
"""
Validate the project's JSONL knowledge-base chunks.

Current chunk schema:
    chunk_id
    text
    chapter
    section
    source_file
    page
    content_type

Usage:
    python3 knowledge_base/validate_chunks.py
    python3 knowledge_base/validate_chunks.py knowledge_base/ds_chunks.jsonl
    python3 knowledge_base/validate_chunks.py --report knowledge_base/validation_report.json
    python3 knowledge_base/validate_chunks.py --fail-on-warning

Exit codes:
    0: validation passed
    1: validation errors exist
    2: input file cannot be read
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_INPUT = SCRIPT_DIR / "ds_chunks.jsonl"

REQUIRED_FIELDS = {
    "chunk_id",
    "text",
    "chapter",
    "section",
    "source_file",
    "page",
    "content_type",
}

STRING_FIELDS = {
    "chunk_id",
    "text",
    "chapter",
    "section",
    "source_file",
    "content_type",
}

# 这些类型是当前项目推荐类型。
# 未知类型暂时只给 warning，不直接判整个知识库无效，
# 便于后续增加新的 content_type。
RECOMMENDED_CONTENT_TYPES = {
    "concept",
    "algorithm",
    "code",
    "example",
    "exercise",
    "operation",
    "comparison",
    "complexity",
    "other",
}

CHUNK_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
WINDOWS_ABSOLUTE_PATH = re.compile(r"^[A-Za-z]:[\\/]")


@dataclass
class Issue:
    level: str
    line: int
    chunk_id: str | None
    code: str
    message: str


def add_issue(
    issues: list[Issue],
    *,
    level: str,
    line: int,
    chunk_id: str | None,
    code: str,
    message: str,
) -> None:
    """Append one validation issue."""
    issues.append(
        Issue(
            level=level,
            line=line,
            chunk_id=chunk_id,
            code=code,
            message=message,
        )
    )


def normalized_text(text: str) -> str:
    """Normalize whitespace for duplicate-text detection."""
    return " ".join(text.split())


def is_absolute_or_path_like_source(source_file: str) -> bool:
    """
    Return True when source_file looks like a local/absolute path.

    source_file should contain the original file name only, rather than
    a user's machine-specific path.
    """
    if not source_file:
        return False

    if Path(source_file).is_absolute():
        return True

    if WINDOWS_ABSOLUTE_PATH.match(source_file):
        return True

    return "/" in source_file or "\\" in source_file


def validate_chunk(
    chunk: dict[str, Any],
    *,
    line_number: int,
    issues: list[Issue],
) -> None:
    """Validate schema, types, and basic quality rules for one chunk."""

    raw_chunk_id = chunk.get("chunk_id")
    chunk_id = raw_chunk_id if isinstance(raw_chunk_id, str) else None

    actual_fields = set(chunk.keys())

    missing_fields = REQUIRED_FIELDS - actual_fields
    extra_fields = actual_fields - REQUIRED_FIELDS

    if missing_fields:
        add_issue(
            issues,
            level="ERROR",
            line=line_number,
            chunk_id=chunk_id,
            code="MISSING_FIELDS",
            message=f"缺少字段: {sorted(missing_fields)}",
        )

    if extra_fields:
        add_issue(
            issues,
            level="ERROR",
            line=line_number,
            chunk_id=chunk_id,
            code="EXTRA_FIELDS",
            message=f"存在未定义字段: {sorted(extra_fields)}",
        )

    for field in STRING_FIELDS:
        if field not in chunk:
            continue

        value = chunk[field]

        if not isinstance(value, str):
            add_issue(
                issues,
                level="ERROR",
                line=line_number,
                chunk_id=chunk_id,
                code="INVALID_TYPE",
                message=(
                    f"{field} 应为 str，"
                    f"实际为 {type(value).__name__}"
                ),
            )

    if "page" in chunk:
        page = chunk["page"]

        # bool 是 int 的子类，因此需要显式排除。
        valid_page = (
            page is None
            or (
                isinstance(page, int)
                and not isinstance(page, bool)
                and page >= 1
            )
        )

        if not valid_page:
            add_issue(
                issues,
                level="ERROR",
                line=line_number,
                chunk_id=chunk_id,
                code="INVALID_PAGE",
                message="page 必须为正整数或 null",
            )

    if isinstance(raw_chunk_id, str):
        if not raw_chunk_id.strip():
            add_issue(
                issues,
                level="ERROR",
                line=line_number,
                chunk_id=chunk_id,
                code="EMPTY_CHUNK_ID",
                message="chunk_id 不能为空",
            )

        elif raw_chunk_id != raw_chunk_id.strip():
            add_issue(
                issues,
                level="ERROR",
                line=line_number,
                chunk_id=chunk_id,
                code="CHUNK_ID_WHITESPACE",
                message="chunk_id 首尾不能包含空白字符",
            )

        elif not CHUNK_ID_PATTERN.fullmatch(raw_chunk_id):
            add_issue(
                issues,
                level="WARNING",
                line=line_number,
                chunk_id=chunk_id,
                code="CHUNK_ID_FORMAT",
                message=(
                    "chunk_id 建议只使用字母、数字、"
                    "下划线、连字符和点"
                ),
            )

    text = chunk.get("text")
    if isinstance(text, str):
        stripped_text = text.strip()

        if not stripped_text:
            add_issue(
                issues,
                level="ERROR",
                line=line_number,
                chunk_id=chunk_id,
                code="EMPTY_TEXT",
                message="text 不能为空",
            )
        else:
            if text != stripped_text:
                add_issue(
                    issues,
                    level="WARNING",
                    line=line_number,
                    chunk_id=chunk_id,
                    code="TEXT_WHITESPACE",
                    message="text 首尾存在多余空白字符",
                )

            text_length = len(stripped_text)

            if text_length < 10:
                add_issue(
                    issues,
                    level="WARNING",
                    line=line_number,
                    chunk_id=chunk_id,
                    code="TEXT_TOO_SHORT",
                    message=f"text 过短，仅 {text_length} 个字符",
                )

            if text_length > 2000:
                add_issue(
                    issues,
                    level="WARNING",
                    line=line_number,
                    chunk_id=chunk_id,
                    code="TEXT_TOO_LONG",
                    message=f"text 较长，共 {text_length} 个字符",
                )

            if "\x00" in text:
                add_issue(
                    issues,
                    level="ERROR",
                    line=line_number,
                    chunk_id=chunk_id,
                    code="NULL_BYTE",
                    message="text 中含有 NUL 控制字符",
                )

    # metadata 字段存在但为空时先作为 warning。
    # 因为某些来源可能无法精确获得 section/page。
    for field in ("chapter", "section", "source_file"):
        value = chunk.get(field)

        if isinstance(value, str) and not value.strip():
            add_issue(
                issues,
                level="WARNING",
                line=line_number,
                chunk_id=chunk_id,
                code="EMPTY_METADATA",
                message=f"{field} 为空",
            )

    source_file = chunk.get("source_file")
    if isinstance(source_file, str) and source_file.strip():
        if is_absolute_or_path_like_source(source_file):
            add_issue(
                issues,
                level="ERROR",
                line=line_number,
                chunk_id=chunk_id,
                code="SOURCE_PATH",
                message=(
                    "source_file 应只保存原始文件名，"
                    "不能包含本地绝对路径或目录"
                ),
            )

    content_type = chunk.get("content_type")
    if isinstance(content_type, str):
        content_type = content_type.strip()

        if not content_type:
            add_issue(
                issues,
                level="WARNING",
                line=line_number,
                chunk_id=chunk_id,
                code="EMPTY_CONTENT_TYPE",
                message="content_type 为空",
            )

        elif content_type not in RECOMMENDED_CONTENT_TYPES:
            add_issue(
                issues,
                level="WARNING",
                line=line_number,
                chunk_id=chunk_id,
                code="UNKNOWN_CONTENT_TYPE",
                message=f"未登记的 content_type: {content_type}",
            )


def load_and_validate(
    input_path: Path,
) -> tuple[list[dict[str, Any]], list[Issue]]:
    """
    Load and validate a JSONL knowledge base.

    JSON syntax errors are recorded per line so that one bad line does
    not prevent the remaining file from being inspected.
    """

    chunks: list[dict[str, Any]] = []
    issues: list[Issue] = []

    try:
        text = input_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise RuntimeError(f"无法读取文件: {exc}") from exc

    if not text.strip():
        add_issue(
            issues,
            level="ERROR",
            line=0,
            chunk_id=None,
            code="EMPTY_FILE",
            message="JSONL 文件为空",
        )
        return chunks, issues

    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()

        if not line:
            add_issue(
                issues,
                level="WARNING",
                line=line_number,
                chunk_id=None,
                code="BLANK_LINE",
                message="存在空行",
            )
            continue

        try:
            item = json.loads(line)
        except json.JSONDecodeError as exc:
            add_issue(
                issues,
                level="ERROR",
                line=line_number,
                chunk_id=None,
                code="INVALID_JSON",
                message=(
                    f"JSON 解析失败: {exc.msg} "
                    f"(column {exc.colno})"
                ),
            )
            continue

        if not isinstance(item, dict):
            add_issue(
                issues,
                level="ERROR",
                line=line_number,
                chunk_id=None,
                code="NOT_OBJECT",
                message="每一行必须是一个 JSON object",
            )
            continue

        chunks.append(item)

        validate_chunk(
            item,
            line_number=line_number,
            issues=issues,
        )

    validate_cross_chunk_rules(chunks, issues)

    return chunks, issues


def validate_cross_chunk_rules(
    chunks: list[dict[str, Any]],
    issues: list[Issue],
) -> None:
    """Validate duplicate IDs and duplicate text across chunks."""

    id_locations: dict[str, list[int]] = defaultdict(list)
    text_locations: dict[str, list[tuple[int, str | None]]] = defaultdict(list)

    for index, chunk in enumerate(chunks, start=1):
        chunk_id = chunk.get("chunk_id")
        text = chunk.get("text")

        if isinstance(chunk_id, str) and chunk_id.strip():
            id_locations[chunk_id].append(index)

        if isinstance(text, str) and text.strip():
            key = normalized_text(text)
            text_locations[key].append(
                (
                    index,
                    chunk_id if isinstance(chunk_id, str) else None,
                )
            )

    for chunk_id, lines in id_locations.items():
        if len(lines) > 1:
            for line_number in lines:
                add_issue(
                    issues,
                    level="ERROR",
                    line=line_number,
                    chunk_id=chunk_id,
                    code="DUPLICATE_CHUNK_ID",
                    message=(
                        f"chunk_id 重复，共出现 {len(lines)} 次；"
                        f"位置: {lines}"
                    ),
                )

    for locations in text_locations.values():
        if len(locations) <= 1:
            continue

        display_locations = [line for line, _ in locations]

        for line_number, chunk_id in locations:
            add_issue(
                issues,
                level="WARNING",
                line=line_number,
                chunk_id=chunk_id,
                code="DUPLICATE_TEXT",
                message=(
                    "存在完全重复或仅空白不同的 text；"
                    f"位置: {display_locations}"
                ),
            )


def build_statistics(
    chunks: list[dict[str, Any]],
    issues: list[Issue],
) -> dict[str, Any]:
    """Build human-readable validation statistics."""

    error_count = sum(issue.level == "ERROR" for issue in issues)
    warning_count = sum(issue.level == "WARNING" for issue in issues)

    chapters: Counter[str] = Counter()
    content_types: Counter[str] = Counter()
    source_files: Counter[str] = Counter()
    text_lengths: list[int] = []

    for chunk in chunks:
        chapter = chunk.get("chapter")
        content_type = chunk.get("content_type")
        source_file = chunk.get("source_file")
        text = chunk.get("text")

        if isinstance(chapter, str):
            chapters[chapter] += 1

        if isinstance(content_type, str):
            content_types[content_type] += 1

        if isinstance(source_file, str):
            source_files[source_file] += 1

        if isinstance(text, str):
            text_lengths.append(len(text.strip()))

    if text_lengths:
        avg_length = round(statistics.mean(text_lengths), 2)
        median_length = round(statistics.median(text_lengths), 2)
        min_length = min(text_lengths)
        max_length = max(text_lengths)
    else:
        avg_length = 0
        median_length = 0
        min_length = 0
        max_length = 0

    return {
        "chunk_count": len(chunks),
        "error_count": error_count,
        "warning_count": warning_count,
        "valid": error_count == 0,
        "unique_chapter_count": len(chapters),
        "unique_source_count": len(source_files),
        "average_text_length": avg_length,
        "median_text_length": median_length,
        "min_text_length": min_length,
        "max_text_length": max_length,
        "chapter_distribution": dict(
            sorted(chapters.items(), key=lambda item: item[0])
        ),
        "content_type_distribution": dict(
            sorted(content_types.items(), key=lambda item: item[0])
        ),
        "source_distribution": dict(
            sorted(
                source_files.items(),
                key=lambda item: (-item[1], item[0]),
            )
        ),
    }


def print_report(
    input_path: Path,
    statistics_data: dict[str, Any],
    issues: list[Issue],
) -> None:
    """Print validation results to stdout."""

    print("=" * 72)
    print("知识库 JSONL Chunk 校验")
    print("=" * 72)
    print(f"文件: {input_path}")
    print(f"Chunk 数量: {statistics_data['chunk_count']}")
    print(f"错误: {statistics_data['error_count']}")
    print(f"警告: {statistics_data['warning_count']}")
    print(f"来源文件数: {statistics_data['unique_source_count']}")
    print(f"章节数: {statistics_data['unique_chapter_count']}")
    print(
        "文本长度: "
        f"avg={statistics_data['average_text_length']}, "
        f"median={statistics_data['median_text_length']}, "
        f"min={statistics_data['min_text_length']}, "
        f"max={statistics_data['max_text_length']}"
    )

    print()
    print("章节分布:")
    if statistics_data["chapter_distribution"]:
        for chapter, count in statistics_data["chapter_distribution"].items():
            label = chapter if chapter else "<empty>"
            print(f"  {label}: {count}")
    else:
        print("  无")

    print()
    print("content_type 分布:")
    if statistics_data["content_type_distribution"]:
        for content_type, count in (
            statistics_data["content_type_distribution"].items()
        ):
            label = content_type if content_type else "<empty>"
            print(f"  {label}: {count}")
    else:
        print("  无")

    if issues:
        print()
        print("问题明细:")
        for issue in issues:
            chunk_info = (
                f" chunk_id={issue.chunk_id}"
                if issue.chunk_id
                else ""
            )
            print(
                f"  [{issue.level}] "
                f"line={issue.line}{chunk_info} "
                f"{issue.code}: {issue.message}"
            )

    print()
    print("=" * 72)

    if statistics_data["valid"]:
        print("校验结果: PASS（无 ERROR）")
    else:
        print("校验结果: FAIL（存在 ERROR）")

    print("=" * 72)


def save_json_report(
    report_path: Path,
    *,
    input_path: Path,
    statistics_data: dict[str, Any],
    issues: list[Issue],
) -> None:
    """Save validation result as UTF-8 JSON."""

    report = {
        "input_file": str(input_path),
        "statistics": statistics_data,
        "issues": [asdict(issue) for issue in issues],
    }

    report_path.parent.mkdir(parents=True, exist_ok=True)

    report_path.write_text(
        json.dumps(
            report,
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="校验数据结构智能助教知识库 JSONL Chunk"
    )

    parser.add_argument(
        "input",
        nargs="?",
        type=Path,
        default=DEFAULT_INPUT,
        help=(
            "待校验 JSONL 文件。"
            "默认: knowledge_base/ds_chunks.jsonl"
        ),
    )

    parser.add_argument(
        "--report",
        type=Path,
        default=None,
        help="可选：将完整校验结果保存为 JSON",
    )

    parser.add_argument(
        "--fail-on-warning",
        action="store_true",
        help="存在 WARNING 时也返回非 0 状态码",
    )

    return parser.parse_args()


def main() -> int:
    args = parse_args()
    input_path: Path = args.input

    if not input_path.is_absolute():
        input_path = Path.cwd() / input_path

    input_path = input_path.resolve()

    if not input_path.exists():
        print(
            f"ERROR: 文件不存在: {input_path}",
            file=sys.stderr,
        )
        return 2

    if not input_path.is_file():
        print(
            f"ERROR: 输入路径不是文件: {input_path}",
            file=sys.stderr,
        )
        return 2

    try:
        chunks, issues = load_and_validate(input_path)
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    statistics_data = build_statistics(chunks, issues)

    print_report(
        input_path,
        statistics_data,
        issues,
    )

    if args.report is not None:
        report_path: Path = args.report

        if not report_path.is_absolute():
            report_path = Path.cwd() / report_path

        save_json_report(
            report_path.resolve(),
            input_path=input_path,
            statistics_data=statistics_data,
            issues=issues,
        )

        print(f"JSON 报告已保存: {report_path.resolve()}")

    if statistics_data["error_count"] > 0:
        return 1

    if args.fail_on_warning and statistics_data["warning_count"] > 0:
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
