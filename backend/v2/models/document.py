from datetime import datetime
from uuid import UUID

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Uuid, func, text
from sqlalchemy.orm import Mapped, mapped_column

from backend.v2.db.base import Base


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (
        CheckConstraint("size_bytes > 0", name="positive_size"),
        CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name="sha256"),
        CheckConstraint("storage_key ~ '^[0-9a-f]{64}$'", name="storage_key"),
        CheckConstraint("length(original_filename) BETWEEN 1 AND 255", name="filename"),
        CheckConstraint("mime_type IN ('application/pdf', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document', 'text/plain')", name="mime_type"),
        CheckConstraint("status IN ('uploaded', 'processing', 'parsed', 'indexing', 'index_failed', 'ready', 'failed')", name="status"),
        CheckConstraint("storage_deleted_at IS NULL OR deleted_at IS NOT NULL", name="cleanup_after_delete"),
        CheckConstraint("index_revision >= 0", name="index_revision"),
        CheckConstraint("indexed_version IS NULL OR indexed_version = ingestion_version", name="indexed_version"),
        CheckConstraint("ingestion_version > 0", name="ingestion_version"),
        CheckConstraint("parsed_version IS NULL OR parsed_version = ingestion_version", name="parsed_version"),
        Index("ix_documents_ingestion_pending", "status", "created_at", postgresql_where=text("deleted_at IS NULL")),
        Index("ix_documents_kb_active", "knowledge_base_id", "created_at", "id", postgresql_where=text("deleted_at IS NULL")),
        Index("ix_documents_kb_storage", "knowledge_base_id", postgresql_where=text("storage_deleted_at IS NULL")),
        Index("ix_documents_uploaded_by", "uploaded_by"),
        Index("ix_documents_cleanup_pending", "deleted_at", postgresql_where=text("deleted_at IS NOT NULL AND storage_deleted_at IS NULL")),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, server_default=text("gen_random_uuid()"))
    knowledge_base_id: Mapped[UUID] = mapped_column(ForeignKey("knowledge_bases.id", ondelete="RESTRICT"))
    uploaded_by: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    original_filename: Mapped[str] = mapped_column(String(255))
    storage_key: Mapped[str] = mapped_column(String(64), unique=True)
    mime_type: Mapped[str] = mapped_column(String(100))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    sha256: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), server_default="uploaded")
    ingestion_version: Mapped[int] = mapped_column(Integer, server_default=text("1"))
    parsed_version: Mapped[int | None] = mapped_column(Integer)
    embedding_space_id: Mapped[str | None] = mapped_column(ForeignKey("embedding_spaces.id", ondelete="RESTRICT"))
    indexed_version: Mapped[int | None] = mapped_column(Integer)
    index_revision: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    cloud_embedding_generation: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    storage_deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
