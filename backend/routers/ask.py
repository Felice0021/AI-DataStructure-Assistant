from fastapi import APIRouter
from backend.schemas import AskRequest, AskResponse
from backend.services.rag_service import RAGService

router = APIRouter()

@router.post("/api/v1/ask", response_model=AskResponse)
async def ask(req: AskRequest) -> AskResponse:
    """问答接口"""
    return await RAGService.answer(req.question, req.top_k)