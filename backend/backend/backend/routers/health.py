from datetime import datetime
from fastapi import APIRouter
from backend.schemas import HealthResponse

router = APIRouter()

@router.get(
    "/api/v1/health",
    response_model=HealthResponse,
    summary="健康检查"
)
async def health_check() -> HealthResponse:
    """检查服务状态"""
    return HealthResponse(
        status="healthy",
        version="1.0.0",
        timestamp=datetime.now().isoformat()
    )