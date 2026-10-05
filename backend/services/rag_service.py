"""
RAG问答服务 - 接入新版 rag.main.run()
"""
import time
import asyncio
import uuid
from pathlib import Path
from typing import Any, Dict, List

from backend.schemas import AskResponse, SourceInfo, LatencyInfo
from backend.logging_config import get_logger
from backend.config import get_settings

logger = get_logger(__name__)
settings = get_settings()

project_root = Path(__file__).parent.parent.parent
logger.info(f"项目根目录: {project_root}")

try:
    import rag.main as rag_main
    RAG_AVAILABLE = True
    logger.info(f"RAG模块导入成功: {rag_main.__file__}")
except ImportError as e:
    RAG_AVAILABLE = False
    logger.error(f"RAG模块导入失败: {e}")


def _normalize_sources(raw_sources: List[Dict]) -> List[SourceInfo]:
    return [
        SourceInfo(
            chunk_id=s.get("chunk_id", "unknown"),
            chapter=s.get("chapter", ""),
            section=s.get("section", ""),
            source_file=s.get("source_file", ""),
            page=s.get("page"),
        )
        for s in (raw_sources or [])
    ]


def _normalize_latency(raw: Any) -> LatencyInfo:
    if isinstance(raw, dict):
        return LatencyInfo(
            retrieval=int(raw.get("retrieval", 0) or 0),
            rerank=int(raw.get("rerank", 0) or 0),
            generation=int(raw.get("generation", 0) or 0),
            total=int(raw.get("total", 0) or 0),
        )
    if isinstance(raw, (int, float)):
        return LatencyInfo(total=int(raw))
    return LatencyInfo()


class RAGService:
    _is_initialized = False
    _chunk_count = 0
    _chunks = None

    @classmethod
    async def initialize(cls) -> bool:
        if cls._is_initialized:
            return True
        if not RAG_AVAILABLE:
            return False

        try:
            logger.info("开始加载知识库...")
            loop = asyncio.get_event_loop()
            cls._chunks = await loop.run_in_executor(
                None,
                lambda: rag_main.prepare_knowledge_base(
                    file_path=Path(settings.knowledge_file),
                    use_cache=settings.rag_use_cache,
                ),
            )
            cls._chunk_count = len(cls._chunks) if cls._chunks else 0
            cls._is_initialized = True
            logger.info(f"知识库加载成功: {cls._chunk_count} 个片段")
            return True
        except Exception as e:
            logger.error(f"知识库加载失败: {e}")
            cls._is_initialized = False
            cls._chunk_count = 0
            return False

    @classmethod
    def is_ready(cls) -> bool:
        return RAG_AVAILABLE and cls._is_initialized

    @classmethod
    def get_chunk_count(cls) -> int:
        return cls._chunk_count

    @classmethod
    async def answer(cls, question: str, top_k: int = None) -> AskResponse:
        request_id = str(uuid.uuid4())[:8]
        start = time.time()

        if top_k is None:
            top_k = settings.rag_top_k

        if not RAG_AVAILABLE:
            return AskResponse.fail(
                request_id, "RAG_UNAVAILABLE", "RAG模块未正确导入"
            )

        if not cls._is_initialized:
            ok = await cls.initialize()
            if not ok:
                return AskResponse.fail(
                    request_id, "RAG_INIT_FAILED",
                    f"知识库加载失败，请检查 {settings.knowledge_file}"
                )

        try:
            logger.info(f"问答请求 [{request_id}]: {question[:30]}...")

            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                lambda: rag_main.run(
                    query=question,
                    chunks=cls._chunks,
                    top_k=top_k,
                    mode="auto",
                ),
            )

            # RAG 内部错误
            if result.get("error"):
                err = result["error"]
                if isinstance(err, dict):
                    code = err.get("code", "RAG_ERROR")
                    message = err.get("message", str(err))
                else:
                    code = "RAG_ERROR"
                    message = str(err)
                logger.warning(f"RAG错误 [{request_id}]: {code} - {message}")
                return AskResponse.fail(request_id, code, message)

            fallback_ms = (time.time() - start) * 1000
            latency = _normalize_latency(result.get("latency_ms"))
            if latency.total == 0:
                latency.total = int(fallback_ms)

            resp = AskResponse.ok(
                request_id=request_id,
                answer=result.get("answer", ""),
                sources=_normalize_sources(result.get("sources", [])),
                mode=result.get("mode", ""),
                out_of_scope=bool(result.get("out_of_scope", False)),
                latency_ms=latency,
            )

            logger.info(
                f"问答完成 [{request_id}]: mode={resp.data.mode}, "
                f"out_of_scope={resp.data.out_of_scope}, "
                f"sources={len(resp.data.sources)}, "
                f"retrieval={latency.retrieval}ms, "
                f"rerank={latency.rerank}ms, "
                f"generation={latency.generation}ms, "
                f"total={latency.total}ms"
            )
            return resp

        except Exception as e:
            logger.error(f"问答异常 [{request_id}]: {e}")
            return AskResponse.fail(
                request_id, "RAG_EXCEPTION",
                f"问答过程发生异常: {str(e)}"
            )