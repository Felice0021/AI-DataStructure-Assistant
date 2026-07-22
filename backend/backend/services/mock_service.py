import time
import asyncio
from backend.schemas import AskResponse, SourceInfo


class MockAnswerService:

    @staticmethod
    async def answer(question: str, top_k: int = 5) -> AskResponse:
        start = time.time()

        # 模拟延迟
        await asyncio.sleep(0.3)

        # 模拟回答
        answer = f"这是关于 '{question}' 的模拟回答。当前为阶段一，后端使用模拟数据。"

        # 模拟来源（符合规范）
        sources = [
            SourceInfo(
                chunk_id="mock_001",
                chapter="第一章 绪论",
                section="数据结构基本概念",
                source_file="第一章绪论.pdf",
                page=5
            )
        ]

        latency = (time.time() - start) * 1000

        return AskResponse.ok(answer, sources, latency)