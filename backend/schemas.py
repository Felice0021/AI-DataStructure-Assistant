from typing import List, Optional
from pydantic import BaseModel, Field


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1)
    top_k: Optional[int] = Field(3, ge=1, le=20)


class SourceInfo(BaseModel):
    chunk_id: str
    chapter: str = ""
    section: str = ""
    source_file: str = ""
    page: Optional[int] = None


class LatencyInfo(BaseModel):
    retrieval: int = 0
    rerank: int = 0
    generation: int = 0
    total: int = 0


class AskData(BaseModel):
    answer: str
    sources: List[SourceInfo]
    mode: str = ""
    out_of_scope: bool = False
    latency_ms: LatencyInfo


class ErrorInfo(BaseModel):
    code: str
    message: str


class AskResponse(BaseModel):
    request_id: str
    success: bool
    data: Optional[AskData] = None
    error: Optional[ErrorInfo] = None

    @classmethod
    def ok(cls, request_id, answer, sources, mode, out_of_scope, latency_ms):
        return cls(
            request_id=request_id,
            success=True,
            data=AskData(
                answer=answer,
                sources=sources,
                mode=mode,
                out_of_scope=out_of_scope,
                latency_ms=latency_ms,
            ),
            error=None,
        )

    @classmethod
    def fail(cls, request_id, code, message):
        return cls(
            request_id=request_id,
            success=False,
            data=None,
            error=ErrorInfo(code=code, message=message),
        )


class HealthResponse(BaseModel):
    status: str
    version: str
    rag_ready: bool
    chunk_count: int
    knowledge_file: str
    timestamp: str