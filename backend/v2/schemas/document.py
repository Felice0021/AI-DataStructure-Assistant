from datetime import datetime
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict


class DocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    knowledge_base_id: UUID
    uploaded_by: UUID
    original_filename: str
    mime_type: str
    size_bytes: int
    sha256: str
    status: Literal["uploaded", "processing", "parsed", "indexing", "index_failed", "ready", "failed"]
    created_at: datetime
    updated_at: datetime


class DocumentEnvelope(BaseModel):
    document: DocumentResponse


class DocumentList(BaseModel):
    items: list[DocumentResponse]
    total: int
    limit: int
    offset: int
