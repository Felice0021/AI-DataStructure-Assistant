"""Qwen text reranker backed by Alibaba Cloud Model Studio."""

from __future__ import annotations

import os
from http import HTTPStatus
from typing import Dict, List, Sequence

import dashscope
from dotenv import load_dotenv

from rag.config import PROJECT_ROOT, RERANK_MODEL


DEFAULT_RERANK_INSTRUCT = (
    "Given a search query, retrieve passages that best answer the query."
)


class QwenReranker:
    def __init__(
        self,
        *,
        model: str = RERANK_MODEL,
        instruct: str = DEFAULT_RERANK_INSTRUCT,
    ) -> None:
        self.model = model
        self.instruct = instruct

    def get_config(self) -> Dict:
        return {
            "reranker": "qwen",
            "model": self.model,
            "instruct": self.instruct,
        }

    def _configure_dashscope(self) -> None:
        load_dotenv(PROJECT_ROOT / ".env", override=True)

        api_key = os.getenv("DASHSCOPE_API_KEY")
        workspace_id = os.getenv("DASHSCOPE_WORKSPACE_ID")
        region = os.getenv("DASHSCOPE_REGION")

        if not api_key:
            raise RuntimeError("未设置 DASHSCOPE_API_KEY")
        if not workspace_id:
            raise RuntimeError("未设置 DASHSCOPE_WORKSPACE_ID")
        if not region:
            raise RuntimeError("未设置 DASHSCOPE_REGION")

        dashscope.api_key = api_key
        dashscope.base_http_api_url = (
            f"https://{workspace_id}.{region}.maas.aliyuncs.com/api/v1"
        )

    def rerank(
        self,
        query: str,
        candidates: Sequence[Dict],
        *,
        top_n: int,
    ) -> List[Dict]:
        query = (query or "").strip()

        if not query or not candidates or top_n <= 0:
            return []

        self._configure_dashscope()

        documents = [
            str(item.get("text", ""))
            for item in candidates
        ]

        response = dashscope.TextReRank.call(
            model=self.model,
            query=query,
            documents=documents,
            top_n=min(top_n, len(documents)),
            instruct=self.instruct,
        )

        if response.status_code != HTTPStatus.OK:
            raise RuntimeError(
                "Rerank调用失败："
                f"{getattr(response, 'code', '')} - "
                f"{getattr(response, 'message', '')}"
            )

        results = response.output["results"]
        reranked: List[Dict] = []

        for result in results:
            index = int(result["index"])

            if index < 0 or index >= len(candidates):
                raise RuntimeError(
                    f"Rerank返回非法候选索引：{index}"
                )

            source = candidates[index]
            item = dict(source)

            dense_score = float(source.get("score", 0.0))
            rerank_score = float(result["relevance_score"])

            item["dense_rank"] = index + 1
            item["dense_score"] = dense_score
            item["rerank_score"] = rerank_score
            item["score"] = rerank_score

            reranked.append(item)

        return reranked
