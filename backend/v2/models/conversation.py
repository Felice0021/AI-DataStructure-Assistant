from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text,
    UniqueConstraint, Uuid, func, text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from backend.v2.db.base import Base


class Conversation(Base):
    __tablename__ = "conversations"
    __table_args__ = (
        CheckConstraint("length(btrim(title)) > 0", name="title_not_blank"),
        CheckConstraint("length(title) <= 200", name="title_length"),
        Index(
            "ix_conversations_user_active_updated", "user_id", "updated_at",
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()")
    )
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(200), server_default="新会话")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (
        CheckConstraint("role IN ('user', 'assistant')", name="role"),
        CheckConstraint("length(btrim(content)) > 0", name="content_not_blank"),
        CheckConstraint("length(content) <= 20000", name="content_length"),
        CheckConstraint("seq >= 1", name="seq_positive"),
        UniqueConstraint("conversation_id", "seq", name="uq_messages_conversation_seq"),
        Index("ix_messages_conversation_seq", "conversation_id", "seq"),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()")
    )
    conversation_id: Mapped[UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE")
    )
    seq: Mapped[int] = mapped_column(Integer)
    role: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text)
    metadata_json: Mapped[dict] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
