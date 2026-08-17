from datetime import datetime
from fastapi import APIRouter
from backend.schemas import HealthResponse
from backend.config import get_settings
from backend.services.rag_service import RAGService

router = APIRouter()
settings = get_settings()


@router.get("/api/v1/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """健康检查"""
    rag_ready = RAGService.is_ready()

    # rag_ready=false 时返回 degraded
    status = "degraded" if not rag_ready else "healthy"

    return HealthResponse(
        status=status,
        version=settings.version,
        rag_ready=rag_ready,
        chunk_count=RAGService.get_chunk_count(),
        knowledge_file=settings.knowledge_file,
        timestamp=datetime.now().isoformat()
    )