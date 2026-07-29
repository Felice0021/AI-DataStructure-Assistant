from fastapi import APIRouter
from backend.schemas import AskRequest, AskResponse
from backend.services.rag_service import RAGService

router = APIRouter()

@router.post("/api/v1/ask", response_model=AskResponse)
async def ask(req: AskRequest) -> AskResponse:
    """问答接口"""
    # 默认 top_k 为 3
    top_k = req.top_k if req.top_k is not None else 3
    return await RAGService.answer(req.question, top_k)