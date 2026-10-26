"""Document authorization always starts at the parent knowledge base."""
import logging

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError

from backend.v2.core.errors import AuthError
from backend.v2.models import Document
from backend.v2.services import knowledge_base_service as knowledge
from backend.v2.services.file_storage import LocalFileStorage, storage_unavailable

logger = logging.getLogger(__name__)


def not_found():
    return AuthError(404, "document_not_found", "Document not found")


def get_document(session, user, kb_id, doc_id, *, writable=False, include_deleted=False):
    if writable:
        knowledge.get_writable(session, user, kb_id)
    else:
        knowledge.get_readable(session, user, kb_id, for_update=True)
    query = select(Document).where(Document.id == doc_id, Document.knowledge_base_id == kb_id)
    if not include_deleted:
        query = query.where(Document.deleted_at.is_(None))
    record = session.scalar(query)
    if record is None:
        raise not_found()
    return record


def list_documents(session, user, kb_id, *, limit, offset):
    knowledge.get_readable(session, user, kb_id, for_update=True)
    scope = (Document.knowledge_base_id == kb_id, Document.deleted_at.is_(None))
    total = session.scalar(select(func.count()).select_from(Document).where(*scope))
    items = session.scalars(select(Document).where(*scope).order_by(
        Document.created_at.desc(), Document.id.desc(),
    ).limit(limit).offset(offset)).all()
    return items, total


def prepare_upload(session, user, kb_id, settings):
    knowledge.get_writable(session, user, kb_id)
    # One in-flight upload across all processes for this local filesystem deployment.
    # Transaction-scoped lock also serializes global byte quota checks with publication.
    if not session.scalar(text("SELECT pg_try_advisory_xact_lock(174923, 3101)")):
        raise AuthError(429, "upload_busy", "Another upload is in progress", headers={"Retry-After": "2"})
    count, used = session.execute(select(func.count(), func.coalesce(func.sum(Document.size_bytes), 0)).where(
        Document.knowledge_base_id == kb_id, Document.storage_deleted_at.is_(None),
    )).one()
    total = session.scalar(select(func.coalesce(func.sum(Document.size_bytes), 0)).where(Document.storage_deleted_at.is_(None)))
    if count >= settings.documents_per_kb or used >= settings.storage_bytes_per_kb or total >= settings.storage_total_bytes:
        raise AuthError(409, "storage_quota_exceeded", "Document storage quota exceeded")
    return min(settings.upload_max_bytes, settings.storage_bytes_per_kb - used, settings.storage_total_bytes - total)


def upload(session, user, kb_id, file, settings, limit):
    storage = LocalFileStorage(settings.file_storage_root)
    saved = None
    try:
        limit = min(limit, prepare_upload(session, user, kb_id, settings))
        saved = storage.save(file.file, limit, file.filename, file.content_type or "")
        record = Document(knowledge_base_id=kb_id, uploaded_by=user.id, original_filename=file.filename,
                          storage_key=saved.key, mime_type=saved.mime, size_bytes=saved.size,
                          sha256=saved.sha256, status="uploaded")
        session.add(record)
        session.flush()
        from backend.v2.services.ingestion_service import enqueue
        enqueue(session, record, user.id, settings)
        session.flush()
        session.refresh(record)
        session.commit()
        return record
    except BaseException as error:
        try:
            session.rollback()
        except SQLAlchemyError:
            logger.warning("Upload transaction rollback failed")
        if saved is not None:
            try:
                storage.remove(saved.key)
            except OSError:
                # A crash/failed compensating cleanup can leave an unreachable orphan.
                logger.warning("Upload compensation requires local storage reconciliation")
        if isinstance(error, OSError):
            raise storage_unavailable() from None
        raise


def open_download(session, user, kb_id, doc_id, settings):
    # Serialize authorization + opening with tombstoning/upload/delete on the parent.
    record = get_document(session, user, kb_id, doc_id)
    try:
        stream = LocalFileStorage(settings.file_storage_root).open(record.storage_key, record.size_bytes)
    except OSError:
        raise storage_unavailable() from None
    # Capture immutable response metadata before releasing the authorization lock.
    metadata = (record.original_filename, record.mime_type, record.size_bytes)
    try:
        session.rollback()
    except BaseException:
        stream.close()
        raise
    return metadata, stream


def delete(session: Session, user, kb_id, doc_id, settings):
    record = get_document(session, user, kb_id, doc_id, writable=True, include_deleted=True)
    if record.deleted_at is None:
        now = session.scalar(select(func.clock_timestamp()))
        record.deleted_at = record.updated_at = now
    key, document_id = record.storage_key, record.id
    already_cleaned = record.storage_deleted_at is not None
    session.commit()  # Durable denial of new reads comes before any filesystem change.
    if already_cleaned:
        return
    try:
        LocalFileStorage(settings.file_storage_root).remove(key)
    except OSError:
        logger.warning("Document physical cleanup pending")
        return  # Tombstone remains authoritative. Same DELETE can safely retry cleanup.
    try:
        record = session.get(Document, document_id)
        record.storage_deleted_at = record.updated_at = session.scalar(select(func.clock_timestamp()))
        session.commit()
    except Exception:
        session.rollback()
        # Missing object remains safe; repeated DELETE retries the cleanup marker.
        logger.warning("Document cleanup marker pending")
