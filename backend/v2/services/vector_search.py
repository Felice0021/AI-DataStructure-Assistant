"""Internal exact cosine search. No HTTP/chat endpoint; authorization precedes ranking."""
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import func, select
from backend.v2.models import ChunkEmbedding, Document, DocumentChunk, EmbeddingJob, EmbeddingSpace, KnowledgeBase, User
from backend.v2.core.errors import unauthorized
from backend.v2.services import knowledge_base_service as knowledge
from backend.v2.services.embedding_provider import EmbeddingError, build_provider, enabled, normalize, space_for


@dataclass(frozen=True)
class QueryEmbedding:
    space_id: str
    vector: list[float]


def authorize_scope(session,user,kb_ids):
    if not 1<=len(kb_ids)<=20 or len(set(kb_ids))!=len(kb_ids) or any(not isinstance(x,UUID) for x in kb_ids):
        raise ValueError('Provide 1-20 distinct knowledge base UUIDs')
    current=session.scalar(select(User).where(User.id==user.id).execution_options(populate_existing=True))
    if current is None or not current.is_active:raise unauthorized()
    for kb_id in kb_ids:knowledge.get_readable(session,current,kb_id)
    return current


def embed_query(factory,user,kb_ids,text,settings,*,allow_cloud=False,verify_session=None,before_cloud_call=None):
    with factory() as session:
        authorize_scope(session,user,kb_ids)
        if settings.embedding_provider=='dashscope':
            space=session.get(EmbeddingSpace,space_for(settings).id)
            if not allow_cloud:raise EmbeddingError('cloud_consent_required')
            if space is None or space.verified_at is None:raise EmbeddingError('embedding_space_unverified')
    from backend.v2.services.cloud_service import Guard
    guard=Guard(factory,user.id,kb_ids,'embedding',settings,verify_session=verify_session,before_call=before_cloud_call)
    provider=build_provider(settings,factory.kw['bind'],cloud_guard=guard)
    calls=0
    def reserve():
        nonlocal calls
        calls+=1
        if calls>settings.embedding_request_retries+1:raise EmbeddingError('embedding_budget_exhausted')
    return QueryEmbedding(provider.space.id,provider.embed([text],text_type='query',before_attempt=reserve)[0])


def exact_search(session,user,kb_ids,query,settings,*,top_k=10,offset=0):
    user=authorize_scope(session,user,kb_ids)
    if not enabled(settings) or query.space_id!=space_for(settings).id:raise EmbeddingError('embedding_model_mismatch')
    if type(top_k) is not int or not 1<=top_k<=100 or type(offset) is not int or not 0<=offset<=10000:
        raise ValueError('Invalid retrieval limit')
    vector=normalize(query.vector,settings.embedding_dimension)
    eligible=eligible_chunks(user,kb_ids,query.space_id,settings)
    distance=eligible.c.embedding.cosine_distance(vector).label('distance')
    rows=session.execute(select(eligible.c.chunk_id,eligible.c.document_id,eligible.c.knowledge_base_id,eligible.c.page_number,
        eligible.c.section_title,eligible.c.chunk_index,eligible.c.content_hash,distance)
        .order_by(distance,eligible.c.chunk_id).limit(top_k).offset(offset)).mappings().all()
    return [{**row,'distance':float(row['distance']),'similarity':1-float(row['distance'])} for row in rows]


def eligible_chunks(user,kb_ids,space_id,settings,*,limit=None,chunk_ids=None):
    """Single published/current/authorized corpus for Dense and lexical retrieval."""
    valid_count=select(func.count()).select_from(ChunkEmbedding).join(DocumentChunk,ChunkEmbedding.chunk_id==DocumentChunk.id).where(
        ChunkEmbedding.document_id==Document.id,ChunkEmbedding.space_id==space_id,ChunkEmbedding.generation==Document.parsed_version,
        DocumentChunk.generation==Document.parsed_version,DocumentChunk.content_hash==ChunkEmbedding.chunk_content_hash).correlate(Document).scalar_subquery()
    chunk_count=select(func.count()).select_from(DocumentChunk).where(DocumentChunk.document_id==Document.id,
        DocumentChunk.generation==Document.parsed_version).correlate(Document).scalar_subquery()
    conditions=[knowledge.readable_scope(user),KnowledgeBase.id.in_(kb_ids),Document.deleted_at.is_(None),Document.status=='ready',
        Document.parsed_version==Document.ingestion_version,Document.indexed_version==Document.ingestion_version,
        Document.embedding_space_id==space_id,EmbeddingSpace.id==space_id,EmbeddingSpace.dimension==1024,
        EmbeddingJob.status=='succeeded',EmbeddingJob.generation==Document.ingestion_version,
        EmbeddingJob.index_revision==Document.index_revision,EmbeddingJob.expected_chunks==valid_count,EmbeddingJob.expected_chunks==chunk_count,
        DocumentChunk.generation==Document.ingestion_version,ChunkEmbedding.generation==Document.ingestion_version,
        DocumentChunk.content_hash==ChunkEmbedding.chunk_content_hash,ChunkEmbedding.space_id==space_id]
    if chunk_ids is not None:
        conditions.append(DocumentChunk.id.in_(chunk_ids))
    if settings.embedding_provider=='dashscope':conditions.append(Document.cloud_embedding_generation==Document.ingestion_version)
    # A materialized authorized CTE ensures unauthorized candidates are excluded before vector ordering.
    eligible=select(ChunkEmbedding.embedding,DocumentChunk.id.label('chunk_id'),Document.id.label('document_id'),
        KnowledgeBase.id.label('knowledge_base_id'),DocumentChunk.page_number,DocumentChunk.section_title,
        DocumentChunk.chunk_index,DocumentChunk.content_hash,DocumentChunk.generation,Document.index_revision,
        Document.embedding_space_id,DocumentChunk.content,Document.original_filename.label('source_filename')).select_from(ChunkEmbedding)
    eligible=eligible.join(DocumentChunk,ChunkEmbedding.chunk_id==DocumentChunk.id).join(Document,Document.id==DocumentChunk.document_id)
    eligible=eligible.join(KnowledgeBase,KnowledgeBase.id==Document.knowledge_base_id).join(EmbeddingSpace,EmbeddingSpace.id==ChunkEmbedding.space_id)
    eligible=eligible.join(EmbeddingJob,(EmbeddingJob.document_id==Document.id)&(EmbeddingJob.space_id==EmbeddingSpace.id))
    eligible=eligible.where(*conditions)
    if limit is not None:
        eligible=eligible.limit(limit)
    eligible=eligible.cte('authorized_embeddings').prefix_with('MATERIALIZED')
    return eligible
