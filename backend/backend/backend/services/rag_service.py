"""
RAG问答服务
"""
import time
import asyncio
import uuid
from pathlib import Path

from backend.schemas import AskResponse, SourceInfo
from backend.logging_config import get_logger
from backend.config import get_settings

logger = get_logger(__name__)
settings = get_settings()

# 记录项目根目录
project_root = Path(__file__).parent.parent.parent
logger.info(f"项目根目录: {project_root}")

# 导入RAG模块
try:
    from rag.rag_demo import main as rag_main
    prepare_knowledge_base = rag_main.prepare_knowledge_base
    answer_question = rag_main.answer_question
    RAG_AVAILABLE = True
    logger.info(f"RAG模块导入成功，文件路径: {rag_main.__file__}")
except ImportError as e:
    RAG_AVAILABLE = False
    logger.error(f"RAG模块导入失败: {e}")


class RAGService:
    """RAG问答服务"""

    _chunks = None
    _is_initialized = False
    _chunk_count = 0

    @classmethod
    async def initialize(cls):
        """初始化RAG服务"""
        if cls._is_initialized:
            return True

        if not RAG_AVAILABLE:
            logger.error("RAG模块不可用")
            return False

        try:
            logger.info("开始加载知识库...")

            cls._chunks = prepare_knowledge_base()

            cls._chunk_count = len(cls._chunks) if cls._chunks else 0
            cls._is_initialized = True

            logger.info(f"知识库加载成功，共 {cls._chunk_count} 个片段")
            return True

        except Exception as e:
            logger.error(f"知识库加载失败: {e}")
            cls._is_initialized = False
            cls._chunk_count = 0
            return False

    @classmethod
    def is_ready(cls) -> bool:
        """检查RAG是否就绪"""
        return RAG_AVAILABLE and cls._is_initialized

    @classmethod
    def get_chunk_count(cls) -> int:
        """获取知识库片段数量"""
        return cls._chunk_count

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
                message="RAG模块未正确导入，请检查 rag/rag_demo/main.py 是否存在"
            )

        # 检查是否已初始化
        if not cls._is_initialized:
            logger.warning(f"RAG服务未初始化 [{request_id}]，尝试初始化...")
            init_success = await cls.initialize()
            if not init_success:
                return AskResponse.fail(
                    request_id=request_id,
                    code="RAG_INIT_FAILED",
                    message="知识库加载失败，请检查 knowledge_base/ds_chunks.jsonl 是否存在"
                )

        try:
            logger.info(f"问答请求 [{request_id}]: {question[:30]}...")

            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                answer_question,
                question,
                cls._chunks,
                top_k
            )

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

            latency_ms = result.get("latency_ms", (time.time() - start_time) * 1000)

            logger.info(f"问答成功 [{request_id}]: {len(sources)} 个来源, {latency_ms:.0f}ms")

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