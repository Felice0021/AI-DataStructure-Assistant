from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, Uuid, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from backend.v2.db.base import Base


class DocumentChunk(Base):
    __tablename__ = "document_chunks"
    __table_args__ = (
        UniqueConstraint("document_id", "chunk_index"),
        UniqueConstraint("id", "document_id", "generation", "content_hash", name="uq_document_chunks_embedding_ref"),
        CheckConstraint("content_hash = encode(sha256(convert_to(content, 'UTF8')), 'hex')", name="hash_matches_content"),
        CheckConstraint("chunk_index >= 0", name="chunk_index"),
        CheckConstraint("generation > 0", name="generation"),
        CheckConstraint("length(content) > 0", name="content"),
        CheckConstraint("content_hash ~ '^[0-9a-f]{64}$'", name="content_hash"),
        CheckConstraint("page_number IS NULL OR page_number > 0", name="page_number"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, server_default=text("gen_random_uuid()"))
    document_id: Mapped[UUID] = mapped_column(ForeignKey("documents.id", ondelete="RESTRICT"))
    generation: Mapped[int] = mapped_column(Integer)
    chunk_index: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64))
    page_number: Mapped[int | None] = mapped_column(Integer)
    section_title: Mapped[str | None] = mapped_column(String(300))
    source_metadata: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class IngestionJob(Base):
    __tablename__ = "ingestion_jobs"
    __table_args__ = (
        CheckConstraint("status IN ('queued','running','succeeded','failed','cancelled')", name="status"),
        CheckConstraint("generation > 0", name="generation"),
        CheckConstraint("attempts >= 0 AND attempts <= max_attempts AND max_attempts BETWEEN 1 AND 10", name="attempts"),
        CheckConstraint("(status = 'running' AND lease_token IS NOT NULL AND lease_expires_at IS NOT NULL) OR (status <> 'running' AND lease_token IS NULL AND lease_expires_at IS NULL)", name="lease"),
        CheckConstraint("error_code IS NULL OR error_code ~ '^[a-z_]{1,64}$'", name="error_code"),
        Index("ix_ingestion_jobs_due", "status", "next_retry_at", "lease_expires_at"),
        Index("ix_ingestion_jobs_requested_by", "requested_by"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, server_default=text("gen_random_uuid()"))
    document_id: Mapped[UUID] = mapped_column(ForeignKey("documents.id", ondelete="RESTRICT"), unique=True)
    requested_by: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    generation: Mapped[int] = mapped_column(Integer, server_default=text("1"))
    status: Mapped[str] = mapped_column(String(16), server_default="queued")
    attempts: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    max_attempts: Mapped[int] = mapped_column(Integer, server_default=text("3"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_retry_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_token: Mapped[UUID | None] = mapped_column(Uuid)
    error_code: Mapped[str | None] = mapped_column(String(64))
