"""Ownership checks shared by CRUD and future document/index services.

Access helpers do not commit. CRUD functions own their transaction boundaries.
"""
from uuid import UUID

from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.v2.core.errors import AuthError, unauthorized
from backend.v2.models import KnowledgeBase, User
from backend.v2.schemas.knowledge_base import KnowledgeBaseCreate, KnowledgeBaseUpdate


def require_public_manager(user: User) -> None:
    if not user.is_active:
        raise unauthorized()
    if user.role != "admin":
        raise AuthError(403, "forbidden", "Insufficient permissions")


def readable_scope(user: User):
    if not user.is_active:
        raise unauthorized()
    return and_(
        KnowledgeBase.deleted_at.is_(None),
        or_(KnowledgeBase.visibility == "public", and_(
            KnowledgeBase.visibility == "private", KnowledgeBase.owner_id == user.id,
        )),
    )


def get_readable(session: Session, user: User, knowledge_base_id: UUID, *, for_update=False) -> KnowledgeBase:
    statement = select(KnowledgeBase).where(KnowledgeBase.id == knowledge_base_id, readable_scope(user))
    if for_update:
        statement = statement.with_for_update()
    record = session.scalar(statement)
    if record is None:
        # Same response for absent, deleted and another user's private resource.
        raise AuthError(404, "knowledge_base_not_found", "Knowledge base not found")
    return record


def get_writable(session: Session, user: User, knowledge_base_id: UUID) -> KnowledgeBase:
    record = get_readable(session, user, knowledge_base_id, for_update=True)
    if record.visibility == "public":
        require_public_manager(user)
    return record


def list_readable(session: Session, user: User, *, limit: int, offset: int):
    scope = readable_scope(user)
    total = session.scalar(select(func.count()).select_from(KnowledgeBase).where(scope))
    records = session.scalars(select(KnowledgeBase).where(scope).order_by(
        KnowledgeBase.created_at.desc(), KnowledgeBase.id.desc(),
    ).limit(limit).offset(offset)).all()
    return records, total


def _commit(session: Session, record: KnowledgeBase) -> KnowledgeBase:
    try:
        session.flush()
        session.refresh(record)
        session.commit()
    except IntegrityError as error:
        session.rollback()
        constraint = getattr(getattr(error.orig, "diag", None), "constraint_name", None)
        if constraint in {"uq_knowledge_bases_private_name", "uq_knowledge_bases_public_name"}:
            raise AuthError(409, "knowledge_base_name_exists", "Knowledge base name already exists") from None
        raise
    return record


def create_private(session: Session, user: User, data: KnowledgeBaseCreate) -> KnowledgeBase:
    if not user.is_active:
        raise unauthorized()
    record = KnowledgeBase(owner_id=user.id, visibility="private", **data.model_dump())
    session.add(record)
    return _commit(session, record)


def create_public(session: Session, user: User, data: KnowledgeBaseCreate) -> KnowledgeBase:
    require_public_manager(user)
    record = KnowledgeBase(owner_id=None, visibility="public", **data.model_dump())
    session.add(record)
    return _commit(session, record)


def update(session: Session, user: User, knowledge_base_id: UUID, data: KnowledgeBaseUpdate) -> KnowledgeBase:
    record = get_writable(session, user, knowledge_base_id)
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(record, field, value)
    record.updated_at = session.scalar(select(func.clock_timestamp()))
    return _commit(session, record)


def delete(session: Session, user: User, knowledge_base_id: UUID) -> None:
    record = get_writable(session, user, knowledge_base_id)
    now = session.scalar(select(func.clock_timestamp()))
    record.deleted_at, record.updated_at = now, now
    _commit(session, record)
