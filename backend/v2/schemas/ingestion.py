from datetime import datetime
from uuid import UUID
from typing import Literal
from pydantic import BaseModel, ConfigDict


class IngestionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reprocess: bool = False


class JobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    document_id: UUID
    generation: int
    status: Literal["queued", "running", "succeeded", "failed", "cancelled"]
    attempts: int
    max_attempts: int
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    next_retry_at: datetime
    error_code: str | None


class JobEnvelope(BaseModel):
    job: JobResponse


class ChunkResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    document_id: UUID
    generation: int
    chunk_index: int
    content: str
    content_hash: str
    page_number: int | None
    section_title: str | None
    source_metadata: dict[str, int]


class ChunkList(BaseModel):
    items: list[ChunkResponse]
    total: int
    limit: int
    offset: int
