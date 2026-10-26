from typing import Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, field_validator


class AskRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    query: str = Field(min_length=1,max_length=2000)
    knowledge_base_ids: list[UUID] = Field(min_length=1,max_length=20)
    retrieval_mode: Literal['bm25','dense','hybrid'] = 'hybrid'
    answer_mode: Literal['auto','qa','exercise','code'] = 'auto'
    top_k: int = Field(default=20,ge=1,le=100,strict=True)
    rerank: Literal['off','optional','required'] = 'optional'
    allow_cloud: bool = Field(default=False,strict=True)
    allow_cloud_rerank: bool = Field(default=False,strict=True)
    allow_cloud_generation: bool = Field(default=False,strict=True)

    @field_validator('query')
    @classmethod
    def valid_query(cls,value):
        if not value.strip():raise ValueError('Empty query')
        try:value.encode('utf8')
        except UnicodeError:raise ValueError('Invalid Unicode') from None
        return value

    @field_validator('knowledge_base_ids')
    @classmethod
    def unique_ids(cls,value):
        if len(set(value))!=len(value):raise ValueError('Duplicate knowledge base')
        return value


class AnswerDraft(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    status: Literal['answered','insufficient_evidence','out_of_scope','evidence_conflict']
    answer: str = Field(max_length=32000)
    used_source_ids: list[str] = Field(max_length=20)


class AnswerSource(BaseModel):
    citation_id: str
    chunk_id: UUID
    document_id: UUID
    knowledge_base_id: UUID
    source_filename: str
    page_number: int | None
    section_title: str | None
    chunk_index: int
    content_hash: str
    generation: int
    index_revision: int
    embedding_space_id: str


class AskResponse(BaseModel):
    status: Literal['answered','insufficient_evidence','out_of_scope','generation_unavailable','validation_failed']
    reason: str | None
    answer: str | None
    sources: list[AnswerSource]
    retrieval_mode: Literal['bm25','dense','hybrid']
    answer_mode: Literal['qa','exercise','code']
    rerank_applied: bool
    generation_model: str | None
    execution_performed: Literal[False] = False
    latency_ms: float
