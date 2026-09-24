"""Lightweight query-mode router for the production RAG pipeline."""

from __future__ import annotations

import re

VALID_MODES = {"auto", "qa", "exercise", "code"}

_CODE_PATTERNS = (
    r"#include\s*[<\"]",
    r"\b(?:int|void|char|float|double)\s+\w+\s*\(",
    r"```(?:c|cpp|c\+\+)?",
    r"\b(?:segmentation fault|null pointer|runtime error|compile error)\b",
)
_CODE_KEYWORDS = (
    "代码", "程序", "编译", "报错", "段错误", "越界",
    "指针", "bug", "debug",
)
_EXERCISE_KEYWORDS = (
    "给定", "求出", "计算", "构造", "画出", "写出",
    "执行过程", "结果是什么", "排序过程", "遍历序列",
    "建立", "求时间复杂度", "求空间复杂度",
)


def resolve_mode(query: str, mode: str = "auto") -> str:
    """Resolve the answer mode without doing scope classification.

    Scope is decided by retrieval evidence in the RAG pipeline. Keeping the
    two concerns separate avoids classifying unfamiliar but valid course
    questions as out-of-scope before retrieval.
    """
    normalized = (mode or "auto").strip().lower()
    if normalized not in VALID_MODES:
        raise ValueError(
            f"未知 mode：{mode}；可选值为 auto/qa/exercise/code"
        )
    if normalized != "auto":
        return normalized

    text = (query or "").strip()
    lower = text.lower()

    if any(keyword in lower for keyword in _CODE_KEYWORDS):
        return "code"
    if any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in _CODE_PATTERNS):
        return "code"
    if any(keyword in text for keyword in _EXERCISE_KEYWORDS):
        return "exercise"
    return "qa"
