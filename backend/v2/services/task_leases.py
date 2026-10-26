"""Shared short-transaction lease/authorization primitives for both worker stages."""
from sqlalchemy import and_, or_, select
from backend.v2.core.errors import AuthError
from backend.v2.models import Document, KnowledgeBase, User
from backend.v2.services import knowledge_base_service as knowledge


def due(model, now):
    return or_(and_(model.status == "queued", model.next_retry_at <= now),
               and_(model.status == "running", model.lease_expires_at <= now))


def candidate(session, model, now, *conditions):
    return session.execute(select(Document.id, KnowledgeBase.id).join(KnowledgeBase, Document.knowledge_base_id == KnowledgeBase.id)
        .join(model, model.document_id == Document.id).where(due(model, now), *conditions)
        .order_by(model.next_retry_at, model.id).with_for_update(of=KnowledgeBase, skip_locked=True).limit(1)).first()


def lock_resources(session, doc_id, kb_id, model, *conditions):
    session.scalar(select(KnowledgeBase).where(KnowledgeBase.id == kb_id).with_for_update())
    document = session.scalar(select(Document).where(Document.id == doc_id, Document.knowledge_base_id == kb_id).with_for_update())
    job = session.scalar(select(model).where(model.document_id == doc_id, *conditions).with_for_update())
    return document, job


def authorize(session, document, job):
    actor = session.get(User, job.requested_by)
    if document.deleted_at is not None or actor is None:
        raise AuthError(404, "document_not_found", "Document not found")
    knowledge.get_writable(session, actor, document.knowledge_base_id)


def end(job, status, now, code=None):
    job.status, job.finished_at, job.error_code = status, now, code
    job.lease_token = job.lease_expires_at = None
