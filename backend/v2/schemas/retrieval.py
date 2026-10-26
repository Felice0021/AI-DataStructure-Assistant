from typing import Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, field_validator


class SearchRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    query: str = Field(max_length=2000)
    knowledge_base_ids: list[UUID] = Field(min_length=1, max_length=20)
    mode: Literal['bm25', 'dense', 'hybrid'] = 'hybrid'
    top_k: int = Field(default=5, ge=1, le=100, strict=True)
    allow_cloud: bool = False

    @field_validator('knowledge_base_ids')
    @classmethod
    def unique_scope(cls, value):
        if len(set(value)) != len(value):
            raise ValueError('Duplicate knowledge base')
        return value


class SearchHit(BaseModel):
    chunk_id: UUID
    document_id: UUID
    knowledge_base_id: UUID
    content: str
    page_number: int | None
    section_title: str | None
    source_filename: str
    chunk_index: int
    fused_score: float | None
    dense_score: float | None
    bm25_score: float | None
    dense_rank: int | None
    bm25_rank: int | None


class SearchResponse(BaseModel):
    requested_mode: Literal['bm25', 'dense', 'hybrid']
    actual_mode: Literal['bm25', 'dense', 'hybrid']
    degradation_reason: str | None = None
    results: list[SearchHit]
    elapsed_ms: float
    candidate_k: int
    eligible_chunks: int
