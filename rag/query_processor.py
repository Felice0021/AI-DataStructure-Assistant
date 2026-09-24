"""Query processing for production RAG."""

from __future__ import annotations

import json
import logging
import os
import re
from typing import List

from dotenv import load_dotenv
from openai import OpenAI

from rag.config import (
    PROJECT_ROOT,
    QUERY_EXPANSION_ENABLED,
    QUERY_EXPANSION_MODEL,
    QUERY_EXPANSION_MAX_SUBQUERIES,
)

logger = logging.getLogger(__name__)


_COMPLEX_HINTS = (
    "比较",
    "区别",
    "异同",
    "分别",
    "各自",
    "优缺点",
    "适用场景",
    "并说明",
    "并分析",
    "并比较",
    "同时",
    "以及",
)


def needs_expansion(query: str, mode: str = "qa") -> bool:
    """判断 Query 是否需要拆成多个检索子查询。"""
    query = (query or "").strip()
    mode = (mode or "qa").strip().lower()

    if not QUERY_EXPANSION_ENABLED or not query:
        return False

    # 代码本身不能被 LLM 任意改写。
    if mode == "code":
        return False

    if any(hint in query for hint in _COMPLEX_HINTS):
        return True

    # 例如：
    # “构造二叉排序树，并写出中序遍历结果”
    if re.search(
        r"(?:并|然后|再).{0,12}(?:写出|说明|分析|计算|求|比较)",
        query,
    ):
        return True

    return False


def _strip_json_fence(text: str) -> str:
    text = (text or "").strip()

    if text.startswith("```"):
        text = re.sub(
            r"^```(?:json)?\s*",
            "",
            text,
            count=1,
        )
        text = re.sub(
            r"\s*```$",
            "",
            text,
            count=1,
        )

    return text.strip()


class QueryProcessor:
    """复杂 Query 拆解器。

    返回结果中永远保留用户原始 Query：
        [original_query, subquery1, ...]
    """

    def __init__(self) -> None:
        self._client = None

    def _get_client(self) -> OpenAI:
        if self._client is not None:
            return self._client

        load_dotenv(PROJECT_ROOT / ".env", override=True)

        api_key = os.getenv("DASHSCOPE_API_KEY")
        if not api_key:
            raise RuntimeError("未设置 DASHSCOPE_API_KEY")

        self._client = OpenAI(
            api_key=api_key,
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        )
        return self._client

    def process(
        self,
        query: str,
        *,
        mode: str = "qa",
    ) -> List[str]:

        query = (query or "").strip()

        if not query:
            return []

        if not needs_expansion(query, mode):
            return [query]

        prompt = f"""
只根据下面的用户问题，将其拆成最多
{QUERY_EXPANSION_MAX_SUBQUERIES} 个用于知识库检索的子查询。

要求：
1. 只拆解查询，不回答问题。
2. 不得增加原问题没有要求的信息。
3. 每个子查询表示一个完整的信息需求。
4. 保留数据结构、算法和关键术语名称。
5. 不要过度拆分。
6. 只输出 JSON：
{{"queries": ["子查询1", "子查询2"]}}

用户问题：
{query}
""".strip()

        try:
            completion = self._get_client().chat.completions.create(
                model=QUERY_EXPANSION_MODEL,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "你是数据结构课程的信息检索查询分析器。"
                            "只分析和拆解查询，不回答问题。"
                        ),
                    },
                    {
                        "role": "user",
                        "content": prompt,
                    },
                ],
                temperature=0.0,
                extra_body={"enable_thinking": False},
            )

            payload = json.loads(
                _strip_json_fence(
                    completion.choices[0].message.content
                )
            )

            raw_queries = payload.get("queries", [])

            if not isinstance(raw_queries, list):
                raise ValueError("queries 不是列表")

            result = [query]
            seen = {query}

            for item in raw_queries:
                subquery = str(item).strip()

                if not subquery or subquery in seen:
                    continue

                result.append(subquery)
                seen.add(subquery)

                if len(result) >= (
                    1 + QUERY_EXPANSION_MAX_SUBQUERIES
                ):
                    break

            return result

        except Exception as exc:
            # Query expansion 失败不能影响主 RAG。
            logger.warning(
                "Query expansion failed; fallback to raw query: %s",
                exc,
            )
            return [query]
