from typing import Literal
from pydantic import BaseModel, Field
from backend.v2.schemas.retrieval import SearchRequest, SearchHit


class PrepareRequest(SearchRequest):
    top_k: int = Field(default=20, ge=1, le=100, strict=True)
    rerank: Literal['off','optional','required'] = 'optional'
    allow_cloud_rerank: bool = Field(default=False, strict=True)
    max_evidence: int = Field(default=5, ge=1, le=20, strict=True)
    context_max_chars: int = Field(default=12000, ge=1, le=64000, strict=True)
    context_token_budget: int = Field(default=4000, ge=1, le=24000, strict=True)


class Evidence(SearchHit):
    citation_id: str
    original_rank: int
    rerank_score: float | None
    rerank_rank: int | None
    rerank_applied: bool
    rerank_model: str | None
    content_hash: str
    generation: int
    index_revision: int
    embedding_space_id: str
    sanitized: bool
    truncated: bool


class Excluded(BaseModel):
    # Only already-authorized candidate IDs and fixed reason codes, no cached text.
    chunk_id: str
    reason: str


class ContextResponse(BaseModel):
    requested_mode: str
    actual_mode: str
    rerank_applied: bool
    rerank_model: str | None
    rerank_reason: str | None
    context_format: Literal['json_evidence_v1']
    trust_boundary: Literal['untrusted_reference_data']
    context_text: str
    evidence: list[Evidence]
    excluded: list[Excluded]
    used_chars: int
    estimated_tokens: int
    token_estimate_method: Literal['utf8_bytes_conservative_not_tokenizer']
    elapsed_ms: float
