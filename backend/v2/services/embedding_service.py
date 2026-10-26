"""Resumable indexing using the same fenced lease primitives as ingestion."""
from dataclasses import dataclass
from datetime import timedelta
import hashlib
from uuid import UUID, uuid4

from sqlalchemy import exists, func, select, text
from sqlalchemy.dialects.postgresql import insert

from backend.v2.core.errors import AuthError
from backend.v2.models import ChunkEmbedding, Document, DocumentChunk, EmbeddingJob, EmbeddingSpace, KnowledgeBase
from backend.v2.services import task_leases as leases
from backend.v2.services.embedding_provider import EmbeddingError, enabled, normalize, space_for


@dataclass(frozen=True)
class IndexClaim:
    job_id: UUID
    document_id: UUID
    knowledge_base_id: UUID
    token: UUID
    generation: int
    index_revision: int
    space_id: str


def ensure_space(session,settings):
    space=space_for(settings)
    session.execute(insert(EmbeddingSpace).values(id=space.id,provider=space.provider,model=space.model,
        revision=space.revision,dimension=space.dimension).on_conflict_do_nothing(index_elements=['id']))
    return space


def manifest(session,document):
    rows=session.execute(select(DocumentChunk.id,DocumentChunk.chunk_index,DocumentChunk.generation,DocumentChunk.content_hash)
        .where(DocumentChunk.document_id==document.id,DocumentChunk.generation==document.ingestion_version).order_by(DocumentChunk.chunk_index)).all()
    data=''.join(f'{row.id}:{row.chunk_index}:{row.generation}:{row.content_hash}\n' for row in rows)
    return hashlib.sha256(data.encode()).hexdigest(),len(rows)


def eligible(document,settings):
    return enabled(settings) and (settings.embedding_provider!='dashscope' or document.cloud_embedding_generation==document.ingestion_version)


def enqueue_if_enabled(session,document,actor_id,settings,*,explicit=False):
    if not eligible(document,settings):
        if explicit:raise AuthError(409,'cloud_consent_required','Explicit cloud processing consent and configuration required')
        return None
    if document.parsed_version!=document.ingestion_version or document.status not in {'parsed','indexing','index_failed','ready'}:
        if explicit:raise AuthError(409,'document_not_parsed','Document is not parsed')
        return None
    space=ensure_space(session,settings)
    job=session.scalar(select(EmbeddingJob).where(EmbeddingJob.document_id==document.id,EmbeddingJob.space_id==space.id).with_for_update())
    if job and job.generation==document.ingestion_version and job.index_revision==document.index_revision:
        if job.status in {'queued','running','succeeded'} or not explicit:return job
    # Serialize capacity checks across worker processes without holding a lock over API calls.
    session.execute(text('SELECT pg_advisory_xact_lock(174924,100)'))
    now=session.scalar(select(func.clock_timestamp()))
    for old in session.scalars(select(EmbeddingJob).where(EmbeddingJob.document_id==document.id,EmbeddingJob.space_id!=space.id,EmbeddingJob.status.in_(['queued','running']))):
        leases.end(old,'cancelled',now,'model_replaced')
    if document.embedding_space_id not in {None,space.id}:
        document.embedding_space_id=space.id;document.indexed_version=None;document.status='parsed'
    pending=session.scalar(select(func.count()).select_from(EmbeddingJob).where(EmbeddingJob.status.in_(['queued','running'])))
    if pending>=settings.embedding_queue_capacity:
        if explicit:raise AuthError(429,'embedding_queue_full','Embedding queue is full')
        return None  # Reconciliation can enqueue later; parsing publication must still succeed.
    digest,count=manifest(session,document)
    if not count:return None
    document.index_revision+=1
    document.embedding_space_id,document.indexed_version=space.id,None
    document.status='parsed'
    now=session.scalar(select(func.clock_timestamp()))
    values=dict(requested_by=actor_id,generation=document.ingestion_version,index_revision=document.index_revision,
                manifest_hash=digest,expected_chunks=count,status='queued',attempts=0,max_attempts=settings.embedding_max_attempts,
                api_calls=0,max_api_calls=settings.embedding_max_api_calls,next_retry_at=now,started_at=None,finished_at=None,
                deadline_at=None,lease_token=None,lease_expires_at=None,error_code=None)
    if job is None:
        job=EmbeddingJob(document_id=document.id,space_id=space.id,**values);session.add(job)
    else:
        for key,value in values.items():setattr(job,key,value)
    return job


def reconcile(session,settings):
    if not enabled(settings):return
    space=space_for(settings)
    documents=session.scalars(select(Document).join(KnowledgeBase).where(Document.deleted_at.is_(None),KnowledgeBase.deleted_at.is_(None),
        Document.status.in_(['parsed','ready']),Document.parsed_version==Document.ingestion_version,
        ~exists(select(EmbeddingJob.id).where(EmbeddingJob.document_id==Document.id,EmbeddingJob.space_id==space.id,
            EmbeddingJob.generation==Document.ingestion_version,EmbeddingJob.index_revision==Document.index_revision)))
        .order_by(Document.created_at).with_for_update(of=KnowledgeBase,skip_locked=True).limit(100)).all()
    for document in documents:
        enqueue_if_enabled(session,document,document.uploaded_by,settings)
    session.commit()


def _locked(session,claim):
    return leases.lock_resources(session,claim.document_id,claim.knowledge_base_id,EmbeddingJob,EmbeddingJob.space_id==claim.space_id)


def _versions(document,job,settings):
    return (document.ingestion_version==document.parsed_version==job.generation
        and document.embedding_space_id==job.space_id==space_for(settings).id and document.index_revision==job.index_revision
        and document.status in {'parsed','indexing','index_failed','ready'} and eligible(document,settings))


def current(session,claim,settings):
    document,job=_locked(session,claim)
    now=session.scalar(select(func.clock_timestamp()))
    if not (job and job.id==claim.job_id and job.status=='running' and job.lease_token==claim.token
        and job.generation==claim.generation and job.index_revision==claim.index_revision and job.lease_expires_at>now):return None
    try:leases.authorize(session,document,job)
    except AuthError:
        leases.end(job,'cancelled',now,'resource_unavailable')
        if document.index_revision==job.index_revision and document.embedding_space_id==job.space_id:
            document.status='index_failed';document.indexed_version=None
        session.commit();return None
    if not _versions(document,job,settings):
        leases.end(job,'cancelled',now,'stale_generation');session.commit();return None
    if manifest(session,document)!=(job.manifest_hash,job.expected_chunks):
        leases.end(job,'failed',now,'chunk_content_changed');document.status='index_failed';session.commit();return None
    return document,job,now


def claim_next(session,settings):
    if not enabled(settings):return None
    now=session.scalar(select(func.clock_timestamp()))
    row=leases.candidate(session,EmbeddingJob,now,EmbeddingJob.space_id==space_for(settings).id)
    if row is None:session.rollback();return None
    document,job=leases.lock_resources(session,row[0],row[1],EmbeddingJob,EmbeddingJob.space_id==space_for(settings).id)
    now=session.scalar(select(func.clock_timestamp()))
    if not job or not ((job.status=='queued' and job.next_retry_at<=now) or (job.status=='running' and job.lease_expires_at<=now)):
        session.rollback();return None
    try:leases.authorize(session,document,job)
    except AuthError:
        leases.end(job,'cancelled',now,'resource_unavailable')
        if document.index_revision==job.index_revision and document.embedding_space_id==job.space_id:
            document.status='index_failed';document.indexed_version=None
        session.commit();return None
    if not _versions(document,job,settings):leases.end(job,'cancelled',now,'stale_generation');session.commit();return None
    if job.attempts>=job.max_attempts or (job.deadline_at and job.deadline_at<=now):
        leases.end(job,'failed',now,'embedding_budget_exhausted');document.status='index_failed';session.commit();return None
    if job.expected_chunks>settings.embedding_max_chunks:
        leases.end(job,'failed',now,'embedding_chunk_limit');document.status='index_failed';session.commit();return None
    if job.deadline_at is None:job.deadline_at=now+timedelta(seconds=settings.embedding_job_timeout_seconds)
    job.attempts+=1
    job.status,job.started_at,job.finished_at,job.error_code='running',now,None,None
    job.lease_token=uuid4();job.lease_expires_at=min(job.deadline_at,now+timedelta(seconds=settings.embedding_lease_seconds))
    document.status='indexing';document.indexed_version=None
    result=IndexClaim(job.id,document.id,document.knowledge_base_id,job.lease_token,job.generation,job.index_revision,job.space_id)
    session.commit();return result


def reserve_attempt(session,claim,settings):
    state=current(session,claim,settings)
    if state is None:session.rollback();raise EmbeddingError('stale_embedding_lease')
    _,job,now=state
    if job.api_calls>=job.max_api_calls or now+timedelta(seconds=settings.embedding_timeout_seconds)>=job.deadline_at:
        session.rollback();raise EmbeddingError('embedding_budget_exhausted')
    job.api_calls+=1
    job.lease_expires_at=min(job.deadline_at,now+timedelta(seconds=settings.embedding_lease_seconds))
    session.commit()


def load_batch(session,claim,settings):
    state=current(session,claim,settings)
    if state is None:session.rollback();raise EmbeddingError('stale_embedding_lease')
    rows=session.scalars(select(DocumentChunk).where(DocumentChunk.document_id==claim.document_id,DocumentChunk.generation==claim.generation,
        ~exists(select(ChunkEmbedding.id).where(ChunkEmbedding.chunk_id==DocumentChunk.id,ChunkEmbedding.space_id==claim.space_id,
            ChunkEmbedding.chunk_content_hash==DocumentChunk.content_hash,ChunkEmbedding.generation==DocumentChunk.generation)))
        .order_by(DocumentChunk.chunk_index).limit(settings.embedding_batch_size)).all()
    result=[(row.id,row.content_hash,row.content) for row in rows]
    session.rollback();return result


def save_batch(session,claim,batch,vectors,settings):
    if not isinstance(vectors,(list,tuple)) or len(vectors)!=len(batch):raise EmbeddingError('invalid_embedding_count')
    vectors=[normalize(vector,settings.embedding_dimension) for vector in vectors]
    state=current(session,claim,settings)
    if state is None:session.rollback();return False
    for (chunk_id,digest,_),vector in zip(batch,vectors):
        chunk=session.get(DocumentChunk,chunk_id)
        if chunk is None or chunk.content_hash!=digest or chunk.generation!=claim.generation or chunk.document_id!=claim.document_id:
            session.rollback();return False
        session.execute(insert(ChunkEmbedding).values(chunk_id=chunk_id,document_id=claim.document_id,generation=claim.generation,
            chunk_content_hash=digest,space_id=claim.space_id,embedding_dimension=1024,embedding=vector)
            .on_conflict_do_nothing(index_elements=['chunk_id','space_id']))
    session.flush()
    if session.scalar(select(func.clock_timestamp()))>=state[1].lease_expires_at:session.rollback();return False
    session.commit();return True


def complete(session,claim,settings):
    state=current(session,claim,settings)
    if state is None:session.rollback();return False
    document,job,now=state
    count=session.scalar(select(func.count()).select_from(ChunkEmbedding).join(DocumentChunk,ChunkEmbedding.chunk_id==DocumentChunk.id)
        .where(ChunkEmbedding.document_id==document.id,ChunkEmbedding.space_id==claim.space_id,ChunkEmbedding.generation==claim.generation,
            DocumentChunk.generation==claim.generation,DocumentChunk.content_hash==ChunkEmbedding.chunk_content_hash))
    if count!=job.expected_chunks:session.rollback();raise EmbeddingError('embedding_incomplete')
    if session.scalar(select(func.clock_timestamp()))>=job.lease_expires_at:session.rollback();return False
    document.status,document.indexed_version,document.updated_at='ready',claim.generation,now
    leases.end(job,'succeeded',now)
    session.commit();return True


def fail(session,claim,error,settings):
    state=current(session,claim,settings)
    if state is None:session.rollback();return False
    document,job,now=state
    if error.retryable and job.attempts<job.max_attempts and job.api_calls<job.max_api_calls and now<job.deadline_at:
        job.status,job.error_code='queued',error.code
        job.lease_token=job.lease_expires_at=None
        job.next_retry_at=now+timedelta(seconds=settings.embedding_backoff_seconds*2**job.attempts)
        document.status='parsed'
    else:
        leases.end(job,'failed',now,error.code);document.status='index_failed'
    document.indexed_version=None;session.commit();return True


def request_indexing(session,user,kb_id,doc_id,settings,allow_cloud=False):
    from backend.v2.services.document_service import get_document
    document=get_document(session,user,kb_id,doc_id,writable=True)
    if not enabled(settings):raise AuthError(503,'embedding_not_configured','Embedding is not enabled')
    if settings.embedding_provider=='dashscope':
        if not allow_cloud:raise AuthError(409,'cloud_consent_required','Explicit cloud processing consent required')
        document.cloud_embedding_generation=document.ingestion_version
    job=enqueue_if_enabled(session,document,user.id,settings,explicit=True)
    session.commit();return job


def get_job(session,user,kb_id,doc_id,settings):
    from backend.v2.services.document_service import get_document
    get_document(session,user,kb_id,doc_id)
    job=session.scalar(select(EmbeddingJob).where(EmbeddingJob.document_id==doc_id,EmbeddingJob.space_id==space_for(settings).id))
    if job is None:raise AuthError(404,'embedding_job_not_found','Embedding job not found')
    return job
