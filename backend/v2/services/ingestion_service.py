"""Leased jobs. All mutation lock order is knowledge base -> document -> job."""
from dataclasses import dataclass
from datetime import timedelta
import hashlib
from uuid import UUID, uuid4

from sqlalchemy import and_, delete, exists, func, or_, select
from sqlalchemy.dialects.postgresql import insert

from backend.v2.core.errors import AuthError
from backend.v2.models import Document, DocumentChunk, IngestionJob, KnowledgeBase, User
from backend.v2.services import knowledge_base_service as knowledge
from backend.v2.services.chunking import ParseFailure
from backend.v2.services import task_leases as leases
from backend.v2.services.file_storage import LocalFileStorage


@dataclass(frozen=True)
class Claim:
    job_id: UUID
    document_id: UUID
    knowledge_base_id: UUID
    token: UUID
    generation: int
    storage_key: str
    size_bytes: int
    sha256: str
    mime_type: str


def enqueue(session, document, actor_id, settings):
    session.add(IngestionJob(document_id=document.id, requested_by=actor_id,
                             generation=document.ingestion_version, max_attempts=settings.ingestion_max_attempts))


def reconcile(session, settings, batch=100):
    # One batch per poll; repairs legacy uploads/missing job rows without touching parsed data.
    documents = session.scalars(select(Document).join(KnowledgeBase).where(
        Document.deleted_at.is_(None), KnowledgeBase.deleted_at.is_(None),
        Document.status.in_(["uploaded", "processing"]),
        ~exists(select(IngestionJob.id).where(IngestionJob.document_id == Document.id)),
    ).order_by(Document.created_at, Document.id).limit(batch)).all()
    for document in documents:
        session.execute(insert(IngestionJob).values(document_id=document.id, requested_by=document.uploaded_by,
            generation=document.ingestion_version, max_attempts=settings.ingestion_max_attempts).on_conflict_do_nothing(index_elements=["document_id"]))
    session.commit()


def _locked(session, document_id, kb_id):
    return leases.lock_resources(session, document_id, kb_id, IngestionJob)


def _authorized(session, document, job):
    return leases.authorize(session, document, job)


_end = leases.end


def claim_next(session, settings):
    now = session.scalar(select(func.clock_timestamp()))
    candidate = leases.candidate(session, IngestionJob, now)
    if candidate is None:
        session.rollback()
        return None
    document, job = _locked(session, candidate[0], candidate[1])
    now = session.scalar(select(func.clock_timestamp()))
    if job is None or not ((job.status == "queued" and job.next_retry_at <= now) or
                           (job.status == "running" and job.lease_expires_at <= now)):
        session.rollback()
        return None
    try:
        _authorized(session, document, job)
    except AuthError:
        _end(job, "cancelled", now, "resource_unavailable")
        document.status, document.parsed_version, document.updated_at = "failed", None, now
        session.commit()
        return None
    if job.generation != document.ingestion_version:
        _end(job, "cancelled", now, "stale_generation")
        session.commit()
        return None
    if job.attempts >= job.max_attempts:
        _end(job, "failed", now, "attempts_exhausted")
        document.status, document.parsed_version = "failed", None
        session.commit()
        return None
    job.status, job.started_at, job.finished_at, job.error_code = "running", now, None, None
    job.attempts += 1
    job.lease_token, job.lease_expires_at = uuid4(), now + timedelta(seconds=settings.ingestion_lease_seconds)
    document.status, document.parsed_version, document.updated_at = "processing", None, now
    claim = Claim(job.id, document.id, document.knowledge_base_id, job.lease_token, job.generation,
                  document.storage_key, document.size_bytes, document.sha256, document.mime_type)
    session.commit()
    return claim


def _current(session, claim):
    document, job = _locked(session, claim.document_id, claim.knowledge_base_id)
    now = session.scalar(select(func.clock_timestamp()))
    valid = (document is not None and job is not None and job.id == claim.job_id and job.status == "running"
             and job.lease_token == claim.token and job.generation == claim.generation
             and document.ingestion_version == claim.generation and job.lease_expires_at > now)
    if not valid:
        return None
    try:
        _authorized(session, document, job)
    except AuthError:
        _end(job, "cancelled", now, "resource_unavailable")
        document.status, document.parsed_version, document.updated_at = "failed", None, now
        session.commit()
        return None
    return document, job, now


def open_claim_source(session, claim, settings):
    current = _current(session, claim)
    if current is None:
        session.rollback()
        return None
    document, _, _ = current
    source = LocalFileStorage(settings.file_storage_root).open(document.storage_key, document.size_bytes)
    try:
        session.rollback()
    except BaseException:
        source.close()
        raise
    return source


def validate_chunks(chunks, settings):
    if not isinstance(chunks, list) or not 1 <= len(chunks) <= settings.parse_max_chunks:
        raise ParseFailure("invalid_parser_output")
    total = 0
    for index, chunk in enumerate(chunks):
        if not isinstance(chunk, dict) or set(chunk) != {"chunk_index", "content", "content_hash", "page_number", "section_title", "source_metadata"}:
            raise ParseFailure("invalid_parser_output")
        content, title, page, metadata = chunk["content"], chunk["section_title"], chunk["page_number"], chunk["source_metadata"]
        if (chunk["chunk_index"] != index or not isinstance(content, str) or not 1 <= len(content) <= settings.chunk_size
            or "\x00" in content or any(0xD800 <= ord(c) <= 0xDFFF for c in content)
            or title is not None and (not isinstance(title, str) or len(title) > 300 or "\x00" in title)
            or page is not None and (type(page) is not int or not 1 <= page <= settings.parse_max_pages)
            or not isinstance(metadata, dict) or set(metadata) != {"block_start", "block_end"}
            or any(type(v) is not int or v < 0 for v in metadata.values())
            or metadata["block_start"] > metadata["block_end"]):
            raise ParseFailure("invalid_parser_output")
        if chunk["content_hash"] != hashlib.sha256(content.encode()).hexdigest():
            raise ParseFailure("invalid_parser_output")
        total += len(content)
    if total > settings.parse_max_text_chars + settings.parse_max_chunks * settings.chunk_overlap:
        raise ParseFailure("text_limit")


def complete(session, claim, chunks, settings):
    validate_chunks(chunks, settings)
    current = _current(session, claim)
    if current is None:
        session.rollback()
        return False
    document, job, now = current
    session.execute(delete(DocumentChunk).where(DocumentChunk.document_id == document.id))
    session.add_all(DocumentChunk(document_id=document.id, generation=claim.generation, **chunk) for chunk in chunks)
    # Check lease against fresh DB time after inserts/flush, not a transaction-start timestamp.
    session.flush()
    if session.scalar(select(func.clock_timestamp())) >= job.lease_expires_at:
        session.rollback()
        return False
    document.status, document.parsed_version, document.updated_at = "parsed", claim.generation, now
    document.indexed_version = None
    from backend.v2.services.embedding_service import enqueue_if_enabled
    enqueue_if_enabled(session, document, job.requested_by, settings)
    _end(job, "succeeded", now)
    session.commit()
    return True


def fail(session, claim, code, retryable, settings):
    current = _current(session, claim)
    if current is None:
        session.rollback()
        return False
    document, job, now = current
    if retryable and job.attempts < job.max_attempts:
        job.status, job.error_code = "queued", code
        job.lease_token = job.lease_expires_at = None
        job.next_retry_at = now + timedelta(seconds=settings.ingestion_retry_seconds * 2 ** (job.attempts-1))
        document.status = "uploaded"
    else:
        _end(job, "failed", now, code)
        document.status = "failed"
    document.parsed_version, document.updated_at = None, now
    session.commit()
    return True


def request_processing(session, user, kb_id, doc_id, settings, reprocess=False):
    from backend.v2.services.document_service import get_document
    document = get_document(session, user, kb_id, doc_id, writable=True)
    job = session.scalar(select(IngestionJob).where(IngestionJob.document_id == doc_id).with_for_update())
    if job is not None and job.status in {"queued", "running"}:
        return job  # Duplicate requests never reset an in-flight lease or retry budget.
    if document.status in {"parsed", "indexing", "index_failed", "ready"} and not reprocess:
        raise AuthError(409, "already_parsed", "Explicit reprocess is required")
    if job is None:
        enqueue(session, document, user.id, settings)
        session.flush()
        job = session.scalar(select(IngestionJob).where(IngestionJob.document_id == doc_id))
    else:
        document.ingestion_version += 1
        job.generation, job.requested_by, job.attempts = document.ingestion_version, user.id, 0
        job.max_attempts = settings.ingestion_max_attempts
        job.status, job.error_code, job.started_at, job.finished_at = "queued", None, None, None
        job.lease_token = job.lease_expires_at = None
        job.next_retry_at = session.scalar(select(func.clock_timestamp()))
    document.status, document.parsed_version, document.indexed_version = "uploaded", None, None
    # Hide previous generation immediately; replace rows atomically when the new run succeeds.
    session.commit()
    return job


def get_job(session, user, kb_id, doc_id):
    from backend.v2.services.document_service import get_document
    get_document(session, user, kb_id, doc_id)
    job = session.scalar(select(IngestionJob).where(IngestionJob.document_id == doc_id))
    if job is None:
        raise AuthError(404, "ingestion_not_found", "Ingestion job not found")
    return job


def list_chunks(session, user, kb_id, doc_id, limit, offset):
    from backend.v2.services.document_service import get_document
    document = get_document(session, user, kb_id, doc_id)
    if document.status not in {"parsed", "indexing", "index_failed", "ready"} or document.parsed_version != document.ingestion_version:
        return [], 0
    scope = (DocumentChunk.document_id == doc_id, DocumentChunk.generation == document.parsed_version)
    total = session.scalar(select(func.count()).select_from(DocumentChunk).where(*scope))
    chunks = session.scalars(select(DocumentChunk).where(*scope).order_by(DocumentChunk.chunk_index).limit(limit).offset(offset)).all()
    return chunks, total
