from datetime import datetime
from fastapi import APIRouter
from backend.schemas import HealthResponse

router = APIRouter()

@router.get("/api/v1/health")
async def health():
    return HealthResponse(
        status="healthy",
        version="1.0.0",
        timestamp=datetime.now().isoformat()
    )