from fastapi import APIRouter
from backend.schemas import AskRequest, AskResponse
from backend.services.mock_service import MockAnswerService

router = APIRouter()

@router.post("/api/v1/ask")
async def ask(req: AskRequest) -> AskResponse:
    return await MockAnswerService.answer(req.question, req.top_k or 5)