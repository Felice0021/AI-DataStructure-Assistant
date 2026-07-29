from typing import List, Optional
from pydantic import BaseModel, Field


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1)
    top_k: Optional[int] = Field(5, ge=1, le=20)


class SourceInfo(BaseModel):
    chunk_id: str
    chapter: str = ""
    section: str = ""
    source_file: str = ""
    page: Optional[int] = None


class AskData(BaseModel):
    answer: str
    sources: List[SourceInfo]
    latency_ms: float


class ErrorInfo(BaseModel):
    code: str
    message: str


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


class HealthResponse(BaseModel):
    status: str
    version: str
    timestamp: str