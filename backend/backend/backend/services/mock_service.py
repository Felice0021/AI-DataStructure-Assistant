"""
真实RAG问答服务
"""
import time
import random
import asyncio
from backend.schemas import AskResponse, SourceInfo


class MockAnswerService:

    @classmethod
    async def answer(cls, question: str, top_k: int = 5) -> AskResponse:
        start_time = time.time()
        print(f"[模拟问答] 问题: {question[:30]}...")

        try:
            await asyncio.sleep(random.uniform(0.2, 0.8))
            answer = f"这是关于 '{question}' 的模拟回答。阶段一使用模拟数据支持前端开发。"
            sources = [
                SourceInfo(
                    chunk_id="mock_001",
                    chapter="第一章 绪论",
                    section="基本概念",
                    source_file="第一章绪论.pdf",
                    page=5
                )
            ]
            latency_ms = (time.time() - start_time) * 1000
            print(f"[模拟问答] 完成, 耗时: {latency_ms:.2f}ms")
            return AskResponse.ok(answer, sources, latency_ms)
        except Exception as e:
            return AskResponse.fail(code="MOCK_ERROR", message=str(e))