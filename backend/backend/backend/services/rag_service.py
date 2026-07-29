"""
真实RAG问答服务
"""
import time
import asyncio
import uuid
from pathlib import Path

from backend.schemas import AskResponse, SourceInfo
from backend.logging_config import get_logger

logger = get_logger(__name__)

# 导入RAG模块
try:
    from rag.rag_demo.main import prepare_knowledge_base, answer_question
    RAG_AVAILABLE = True
    logger.info("RAG模块导入成功")
except ImportError as e:
    RAG_AVAILABLE = False
    logger.warning(f"RAG模块导入失败: {e}")


class RAGService:
    """真实RAG问答服务"""

    _chunks = None
    _is_initialized = False

    @classmethod
    async def initialize(cls):
        """初始化RAG服务，加载知识库（只执行一次）"""
        if cls._is_initialized:
            logger.info("RAG服务已初始化，复用已有知识库")
            return True

        if not RAG_AVAILABLE:
            logger.error("RAG模块不可用")
            return False

        try:
            logger.info("开始加载知识库...")

            # 调用 prepare_knowledge_base
            cls._chunks = prepare_knowledge_base()

            cls._is_initialized = True
            chunk_count = len(cls._chunks) if cls._chunks else 0
            logger.info(f"知识库加载成功，共 {chunk_count} 个片段")
            return True

        except Exception as e:
            logger.error(f"知识库加载失败: {e}")
            return False

    @classmethod
    async def answer(cls, question: str, top_k: int = 3) -> AskResponse:
        """问答接口"""
        request_id = str(uuid.uuid4())[:8]
        start_time = time.time()

        # 检查RAG是否可用
        if not RAG_AVAILABLE:
            return AskResponse.fail(
                request_id=request_id,
                code="RAG_UNAVAILABLE",
                message="RAG模块未正确导入"
            )

        # 检查是否已初始化
        if not cls._is_initialized:
            logger.warning("RAG服务未初始化，尝试初始化...")
            init_success = await cls.initialize()
            if not init_success:
                return AskResponse.fail(
                    request_id=request_id,
                    code="RAG_INIT_FAILED",
                    message="知识库加载失败"
                )

        try:
            logger.info(f"问答请求 [{request_id}]: {question[:30]}...")

            # 在线程池中执行
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                answer_question,
                question,
                cls._chunks,
                top_k
            )

            # 【调试】打印第一个检索到的chunk文本
            retrieved = result.get("retrieved_chunks", [])
            if retrieved:
                logger.info(f"[调试] 第一个检索到的chunk文本: {retrieved[0].get('text', '')[:100]}...")
            else:
                logger.warning(f"[调试] 没有检索到任何chunk")

            # 检查RAG返回是否有错误
            if result.get("error"):
                error_msg = result["error"].get("message", str(result["error"]))
                logger.warning(f"RAG返回错误 [{request_id}]: {error_msg}")
                return AskResponse.fail(
                    request_id=request_id,
                    code=result["error"].get("code", "RAG_ERROR"),
                    message=error_msg
                )

            # 构建来源列表
            sources = []
            for source in result.get("sources", []):
                sources.append(SourceInfo(
                    chunk_id=source.get("chunk_id", "unknown"),
                    chapter=source.get("chapter", ""),
                    section=source.get("section", ""),
                    source_file=source.get("source_file", ""),
                    page=source.get("page")
                ))

            # 计算耗时
            latency_ms = result.get("latency_ms", (time.time() - start_time) * 1000)

            logger.info(f"问答成功 [{request_id}]: {len(sources)} 个来源, {latency_ms:.0f}ms")
            logger.info(f"[调试] 回答内容: {result.get('answer', '')[:200]}...")

            return AskResponse.ok(
                request_id=request_id,
                answer=result.get("answer", ""),
                sources=sources,
                latency_ms=latency_ms
            )

        except Exception as e:
            logger.error(f"问答异常 [{request_id}]: {e}")
            return AskResponse.fail(
                request_id=request_id,
                code="RAG_EXCEPTION",
                message=f"问答过程发生异常: {str(e)}"
            )