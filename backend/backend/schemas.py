from typing import List, Optional
from pydantic import BaseModel, Field


# 请求
class AskRequest(BaseModel):
    question: str = Field(..., min_length=1)
    top_k: Optional[int] = Field(5, ge=1, le=20)


# 来源
class SourceInfo(BaseModel):
    chunk_id: str
    chapter: str = ""
    section: str = ""
    source_file: str = ""
    page: Optional[int] = None


# 响应数据
class AskData(BaseModel):
    answer: str
    sources: List[SourceInfo]
    latency_ms: float


# 错误
class ErrorInfo(BaseModel):
    code: str
    message: str


# 统一响应（符合规范）
class AskResponse(BaseModel):
    success: bool
    data: Optional[AskData] = None
    error: Optional[ErrorInfo] = None

    @classmethod
    def ok(cls, answer: str, sources: List[SourceInfo], latency_ms: float):
        return cls(
            success=True,
            data=AskData(answer=answer, sources=sources, latency_ms=latency_ms),
            error=None
        )

    @classmethod
    def fail(cls, code: str, message: str):
        return cls(
            success=False,
            data=None,
            error=ErrorInfo(code=code, message=message)
        )


# 健康检查
class HealthResponse(BaseModel):
    status: str
    version: str
    timestamp: str