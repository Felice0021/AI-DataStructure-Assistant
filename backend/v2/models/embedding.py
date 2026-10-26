from datetime import datetime
from uuid import UUID

from pgvector.sqlalchemy import Vector
from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, ForeignKeyConstraint, Index, Integer, String, UniqueConstraint, Uuid, func, text
from sqlalchemy.orm import Mapped, mapped_column
from backend.v2.db.base import Base


class EmbeddingSpace(Base):
    __tablename__ = "embedding_spaces"
    __table_args__ = (CheckConstraint("dimension = 1024", name="dimension"),)
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    provider: Mapped[str] = mapped_column(String(32))
    model: Mapped[str] = mapped_column(String(128))
    revision: Mapped[str] = mapped_column(String(64))
    dimension: Mapped[int] = mapped_column(Integer)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ChunkEmbedding(Base):
    __tablename__ = "chunk_embeddings"
    __table_args__ = (
        ForeignKeyConstraint(["chunk_id", "document_id", "generation", "chunk_content_hash"],
            ["document_chunks.id", "document_chunks.document_id", "document_chunks.generation", "document_chunks.content_hash"], ondelete="CASCADE"),
        UniqueConstraint("chunk_id", "space_id"),
        CheckConstraint("embedding_dimension = 1024 AND vector_dims(embedding) = 1024", name="dimension"),
        CheckConstraint("abs(vector_norm(embedding) - 1) < 0.001", name="unit_norm"),
        Index("ix_chunk_embeddings_document_space", "document_id", "space_id", "generation"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, server_default=text("gen_random_uuid()"))
    chunk_id: Mapped[UUID] = mapped_column(Uuid)
    document_id: Mapped[UUID] = mapped_column(Uuid)
    generation: Mapped[int] = mapped_column(Integer)
    chunk_content_hash: Mapped[str] = mapped_column(String(64))
    space_id: Mapped[str] = mapped_column(ForeignKey("embedding_spaces.id", ondelete="RESTRICT"))
    embedding_dimension: Mapped[int] = mapped_column(Integer, server_default=text("1024"))
    embedding: Mapped[list[float]] = mapped_column(Vector(1024))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class EmbeddingJob(Base):
    __tablename__ = "embedding_jobs"
    __table_args__ = (
        UniqueConstraint("document_id", "space_id"),
        CheckConstraint("status IN ('queued','running','succeeded','failed','cancelled')", name="status"),
        CheckConstraint("generation > 0 AND index_revision > 0", name="versions"),
        CheckConstraint("attempts >= 0 AND attempts <= max_attempts AND max_attempts BETWEEN 1 AND 10", name="attempts"),
        CheckConstraint("api_calls >= 0 AND api_calls <= max_api_calls AND max_api_calls > 0", name="api_calls"),
        CheckConstraint("expected_chunks > 0", name="expected_chunks"),
        CheckConstraint("(status = 'running' AND lease_token IS NOT NULL AND lease_expires_at IS NOT NULL) OR (status <> 'running' AND lease_token IS NULL AND lease_expires_at IS NULL)", name="lease"),
        CheckConstraint("error_code IS NULL OR error_code ~ '^[a-z_]{1,64}$'", name="error_code"),
        Index("ix_embedding_jobs_due", "status", "next_retry_at", "lease_expires_at"),
        Index("ix_embedding_jobs_requested_by", "requested_by"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, server_default=text("gen_random_uuid()"))
    document_id: Mapped[UUID] = mapped_column(ForeignKey("documents.id", ondelete="RESTRICT"))
    requested_by: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    space_id: Mapped[str] = mapped_column(ForeignKey("embedding_spaces.id", ondelete="RESTRICT"))
    generation: Mapped[int] = mapped_column(Integer)
    index_revision: Mapped[int] = mapped_column(Integer)
    manifest_hash: Mapped[str] = mapped_column(String(64))
    expected_chunks: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), server_default="queued")
    attempts: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    max_attempts: Mapped[int] = mapped_column(Integer)
    api_calls: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    max_api_calls: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deadline_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_retry_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_token: Mapped[UUID | None] = mapped_column(Uuid)
    error_code: Mapped[str | None] = mapped_column(String(64))
