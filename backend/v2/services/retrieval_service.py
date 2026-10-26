"""Authenticated bounded retrieval. Remote embedding precedes final resource locks."""
from contextlib import contextmanager
import time
from sqlalchemy import func, select, text

from backend.v2.core.errors import AuthError, unauthorized
from backend.v2.models import KnowledgeBase, User
from backend.v2.services.embedding_provider import EmbeddingError, space_for
from backend.v2.services.lexical_search import bm25, tokenize
from backend.v2.services.vector_search import authorize_scope, eligible_chunks, embed_query, exact_search


@contextmanager
def capacity(engine, limit, *, namespace=174925):
    # Session-level advisory slots bound memory/CPU across API processes.
    with engine.connect().execution_options(isolation_level='AUTOCOMMIT') as connection:
        slot = None
        try:
            for i in range(limit):
                if connection.scalar(text('SELECT pg_try_advisory_lock(:namespace,:slot)'), {'slot': i, 'namespace':namespace}):
                    slot = i
                    break
            if slot is None:
                raise AuthError(429, 'retrieval_busy', 'Retrieval capacity reached')
            yield
        finally:
            if slot is not None:
                connection.execute(text('SELECT pg_advisory_unlock(:namespace,:slot)'), {'slot': slot, 'namespace':namespace})


def fuse(dense, lexical, settings):
    scores = {}
    for label, values, weight in [('dense', dense, settings.retrieval_dense_weight), ('bm25', lexical, settings.retrieval_bm25_weight)]:
        for rank, (chunk_id, score) in enumerate(values, 1):
            item = scores.setdefault(chunk_id, {'chunk_id': chunk_id, 'fused_score': 0.0,
                'dense_score': None, 'bm25_score': None, 'dense_rank': None, 'bm25_rank': None})
            item['fused_score'] += weight/(settings.retrieval_rrf_k+rank)
            item[label+'_score'], item[label+'_rank'] = score, rank
    return sorted(scores.values(), key=lambda x: (-x['fused_score'], str(x['chunk_id'])))


def search(factory, user, data, settings, *, verify_session=None, include_snapshot=False,before_cloud_call=None):
    start = time.monotonic()
    if len(data.query) > settings.retrieval_max_query_chars or data.top_k > settings.retrieval_top_k:
        raise AuthError(422, 'retrieval_limit', 'Query or result limit exceeded')
    candidate_k = max(data.top_k, settings.retrieval_candidate_k)
    with capacity(factory.kw['bind'], settings.retrieval_concurrency):
        with factory() as session:
            authorize_scope(session, user, data.knowledge_base_ids)
        terms = tokenize(data.query)
        query = None
        if terms and data.mode != 'bm25':
            try:
                query = embed_query(factory, user, data.knowledge_base_ids, data.query, settings, allow_cloud=data.allow_cloud,verify_session=verify_session,before_cloud_call=before_cloud_call)
            except EmbeddingError as error:
                code = 'cloud_consent_required' if error.code == 'cloud_consent_required' else 'dense_unavailable'
                raise AuthError(403 if code == 'cloud_consent_required' else 503, code, 'Dense retrieval unavailable') from None
        with factory() as session:
            # Linearization boundary: mutations use KB FOR UPDATE before touching docs/chunks.
            # Reload and lock the user and all requested parents, even for empty queries.
            current = session.scalar(select(User).where(User.id == user.id).with_for_update(read=True))
            if current is None or not current.is_active:
                raise unauthorized()
            if verify_session is not None:
                verify_session(session)
            for kb_id in sorted(data.knowledge_base_ids, key=str):
                session.scalar(select(KnowledgeBase).where(KnowledgeBase.id == kb_id).with_for_update(read=True))
            authorize_scope(session, current, data.knowledge_base_ids)
            eligible = eligible_chunks(current, data.knowledge_base_ids, space_for(settings).id, settings, limit=settings.retrieval_max_corpus_chunks+1)
            count, size = session.execute(select(func.count(), func.coalesce(func.sum(func.octet_length(eligible.c.content)),0))).one()
            if count > settings.retrieval_max_corpus_chunks or size > settings.retrieval_max_corpus_bytes:
                raise AuthError(413, 'retrieval_corpus_limit', 'Select a smaller knowledge base scope')
            if not terms:
                ranked, rows = [], []
            else:
                # Finite corpus snapshot; never select vector arrays into Python.
                cols = [c for c in eligible.c if c.name != 'embedding']
                rows = session.execute(select(*cols).order_by(eligible.c.chunk_id).limit(settings.retrieval_max_corpus_chunks+1)).mappings().all()
                lexical = bm25(terms, rows, settings)[:candidate_k] if data.mode != 'dense' else []
                dense = []
                if query is not None:
                    hits = exact_search(session, current, data.knowledge_base_ids, query, settings, top_k=candidate_k)
                    dense = [(x['chunk_id'], x['similarity']) for x in hits]
                ranked = fuse(dense, lexical, settings)
                if data.mode != 'hybrid':
                    # Single-route rank follows its raw score; fused score has no meaning here.
                    for item in ranked:
                        item['fused_score'] = None
            sources = {row['chunk_id']: dict(row) for row in rows}
            results = []
            for item in ranked[:data.top_k]:
                source = sources[item['chunk_id']]
                snapshot = {k:source.pop(k) for k in ('content_hash','generation','index_revision','embedding_space_id')}
                if include_snapshot:
                    source['snapshot'] = snapshot
                results.append({**source, **item})
            return {'requested_mode': data.mode, 'actual_mode': data.mode, 'degradation_reason': None,
                'results': results, 'elapsed_ms': round((time.monotonic()-start)*1000,3),
                'candidate_k': candidate_k, 'eligible_chunks': count}
