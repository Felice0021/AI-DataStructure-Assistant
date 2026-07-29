from fastapi import APIRouter
from backend.schemas import AskRequest, AskResponse
from backend.services.rag_service import RAGService  # 改为RAGService

router = APIRouter()


@router.post(
    "/api/v1/ask",
    response_model=AskResponse,
    summary="问答接口"
)
async def ask(req: AskRequest) -> AskResponse:
    """
    问答接口 - 使用真实RAG

    请求体:
        question: 用户问题
        top_k: 检索返回数量 (默认5)

    返回:
        success: 是否成功
        data: 回答和来源
        error: 错误信息
    """
    return await RAGService.answer(req.question, req.top_k or 5)