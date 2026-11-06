from uuid import UUID

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from backend.v2.core.errors import AuthError, unauthorized
from backend.v2.models import Conversation, Message, User
from backend.v2.schemas.conversation import (
    ConversationCreate, ConversationUpdate, MessageCreate,
)

METADATA_MAX_BYTES = 4096


def owned_scope(user: User):
    if not user.is_active:
        raise unauthorized()
    return and_(Conversation.deleted_at.is_(None), Conversation.user_id == user.id)


def get_owned(session: Session, user: User, conversation_id: UUID, *, for_update=False) -> Conversation:
    stmt = select(Conversation).where(
        Conversation.id == conversation_id, owned_scope(user)
    )
    if for_update:
        stmt = stmt.with_for_update()
    record = session.scalar(stmt)
    if record is None:
        # 不存在 / 已删 / 他人 → 统一 404
        raise AuthError(404, "conversation_not_found", "Conversation not found")
    return record


def list_owned(session: Session, user: User, *, limit: int, offset: int):
    scope = owned_scope(user)
    total = session.scalar(select(func.count()).select_from(Conversation).where(scope))
    records = session.scalars(
        select(Conversation).where(scope)
        .order_by(Conversation.updated_at.desc(), Conversation.id.desc())
        .limit(limit).offset(offset)
    ).all()
    return records, total


def create(session: Session, user: User, data: ConversationCreate) -> Conversation:
    if not user.is_active:
        raise unauthorized()
    record = Conversation(user_id=user.id, title=data.title)
    session.add(record)
    session.flush()
    session.refresh(record)
    session.commit()
    return record


def update(session: Session, user: User, conversation_id: UUID, data: ConversationUpdate) -> Conversation:
    record = get_owned(session, user, conversation_id, for_update=True)
    record.title = data.title
    record.updated_at = session.scalar(select(func.clock_timestamp()))
    session.flush()
    session.refresh(record)
    session.commit()
    return record


def delete(session: Session, user: User, conversation_id: UUID) -> None:
    record = get_owned(session, user, conversation_id, for_update=True)
    now = session.scalar(select(func.clock_timestamp()))
    record.deleted_at = now
    record.updated_at = now
    session.flush()
    session.commit()


def list_messages(session: Session, user: User, conversation_id: UUID, *, limit: int, offset: int):
    get_owned(session, user, conversation_id)
    total = session.scalar(
        select(func.count()).select_from(Message)
        .where(Message.conversation_id == conversation_id)
    )
    records = session.scalars(
        select(Message).where(Message.conversation_id == conversation_id)
        .order_by(Message.seq.asc())
        .limit(limit).offset(offset)
    ).all()
    return records, total


def append_message(session: Session, user: User, conversation_id: UUID, data: MessageCreate) -> Message:
    # 锁会话行，保证 seq 递增与 updated_at 同一事务
    conv = get_owned(session, user, conversation_id, for_update=True)

    if data.role != "user":
        raise AuthError(422, "invalid_role", "Only user messages can be appended")

    next_seq = (session.scalar(
        select(func.coalesce(func.max(Message.seq), 0))
        .where(Message.conversation_id == conv.id)
    ) or 0) + 1

    metadata = {}
    if len(str(metadata).encode("utf-8")) > METADATA_MAX_BYTES:
        raise AuthError(422, "metadata_too_large", "Metadata too large")

    msg = Message(
        conversation_id=conv.id,
        seq=next_seq,
        role=data.role,
        content=data.content,
        metadata_json=metadata,
    )
    conv.updated_at = session.scalar(select(func.clock_timestamp()))
    session.add(msg)
    session.flush()
    session.refresh(msg)
    session.commit()
    return msg
