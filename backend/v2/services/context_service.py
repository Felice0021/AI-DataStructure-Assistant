"""Retrieve -> rerank without row locks -> revalidate versions -> build authorized evidence."""
import time
from sqlalchemy import select
from backend.v2.core.errors import AuthError, unauthorized
from backend.v2.models import KnowledgeBase, User
from backend.v2.schemas.retrieval import SearchRequest
from backend.v2.services import rerank_provider
from backend.v2.services.context_builder import build_context
from backend.v2.services.embedding_provider import space_for
from backend.v2.services.retrieval_service import capacity, search
from backend.v2.services.vector_search import authorize_scope, eligible_chunks


def order_candidates(candidates,rows,model):
    # Stable original input ranks, not ranks derived from arbitrary provider output order.
    scores=rerank_provider.validate_scores(rows,len(candidates))
    indices=sorted(range(len(candidates)),key=lambda i:(-scores[i],i,str(candidates[i]['chunk_id'])))
    return [{**candidates[i],'original_rank':i+1,'rerank_score':scores[i],'rerank_rank':rank,
             'rerank_applied':True,'rerank_model':model} for rank,i in enumerate(indices,1)]


def prepare_context(factory,user,data,settings,*,verify_session,provider=None,before_cloud_call=None):
    start=time.monotonic()
    if (data.top_k>settings.rerank_max_candidates or data.top_k>settings.rerank_batch_size
        or data.max_evidence>settings.context_max_evidence or data.context_max_chars>settings.context_max_chars
        or data.context_token_budget>settings.context_token_budget):
        raise AuthError(422,'context_limit','Context or candidate limit exceeded')
    def authenticated(session):
        verified=verify_session(session)
        if verified is None or verified.id!=user.id:
            raise unauthorized()
        return verified
    with factory() as session:
        authorize_scope(session,user,data.knowledge_base_ids)
        authenticated(session)
    try:
        from backend.v2.services.cloud_service import Guard
        guard=Guard(factory,user.id,data.knowledge_base_ids,'reranking',settings,verify_session=verify_session,before_call=before_cloud_call)
        chosen=rerank_provider.DisabledProvider() if data.rerank=='off' else provider or rerank_provider.build_provider(settings,factory.kw['bind'],cloud_guard=guard)
        disabled=isinstance(chosen,rerank_provider.DisabledProvider)
        if data.rerank=='required' and disabled:raise rerank_provider.RerankError('rerank_disabled')
        if data.rerank!='off' and settings.rerank_provider=='qwen' and not data.allow_cloud_rerank:
            raise AuthError(403,'rerank_cloud_consent_required','Explicit cloud reranking consent required')
        request=SearchRequest.model_validate(data.model_dump(include=set(SearchRequest.model_fields)))
        with capacity(factory.kw['bind'],settings.rerank_concurrency,namespace=174927):
            retrieved=search(factory,user,request,settings,verify_session=authenticated,include_snapshot=True,before_cloud_call=before_cloud_call)
            unique={}
            for candidate in retrieved['results']:unique.setdefault(candidate['chunk_id'],candidate)
            candidates=list(unique.values())
            applied=False;reason='requested_off' if data.rerank=='off' else 'provider_disabled' if disabled else 'empty_candidates'
            guard.evidence=candidates
            if candidates and data.rerank!='off' and not disabled:
                rows=chosen.rerank(data.query,[c['content'] for c in candidates])
                candidates=order_candidates(candidates,rows,chosen.model)
                applied=True;reason=None
            else:
                candidates=[{**c,'original_rank':i,'rerank_score':None,'rerank_rank':None,'rerank_applied':False,'rerank_model':None} for i,c in enumerate(candidates,1)]
            # No cached candidate body is used to construct the response.
            with factory() as session:
                fresh=validate_evidence(session,user,data.knowledge_base_ids,candidates,settings,verify_session=authenticated)
                validated=[]
                for candidate,row in zip(candidates,fresh):
                    scores={k:candidate[k] for k in ('fused_score','dense_score','bm25_score','dense_rank','bm25_rank',
                        'original_rank','rerank_score','rerank_rank','rerank_applied','rerank_model')}
                    validated.append({**row,**scores})
                result=build_context(validated,settings,max_evidence=data.max_evidence,max_chars=data.context_max_chars,token_budget=data.context_token_budget)
                authenticated(session)  # Check actual expiry again after local construction.
                return {**result,'requested_mode':data.mode,'actual_mode':retrieved['actual_mode'],
                        'rerank_applied':applied,'rerank_model':chosen.model if applied else None,'rerank_reason':reason,
                        'elapsed_ms':round((time.monotonic()-start)*1000,3)}
    except rerank_provider.RerankError as error:
        raise AuthError(413 if error.code=='rerank_input_limit' else 503,error.code,'Reranking unavailable') from None


def validate_evidence(session,user,kb_ids,candidates,settings,*,verify_session):
    """Hold User/session/KB share locks until caller materializes its final response."""
    current=session.scalar(select(User).where(User.id==user.id).with_for_update(read=True))
    if current is None or not current.is_active:raise unauthorized()
    verified=verify_session(session)
    if verified is None or verified.id!=user.id:raise unauthorized()
    for kb_id in sorted(kb_ids,key=str):
        session.scalar(select(KnowledgeBase).where(KnowledgeBase.id==kb_id).with_for_update(read=True))
    authorize_scope(session,current,kb_ids)
    eligible=eligible_chunks(current,kb_ids,space_for(settings).id,settings,chunk_ids=[c['chunk_id'] for c in candidates])
    rows=session.execute(select(*[c for c in eligible.c if c.name!='embedding'])).mappings().all() if candidates else []
    rows={r['chunk_id']:dict(r) for r in rows};result=[]
    for candidate in candidates:
        row=rows.get(candidate['chunk_id'])
        snapshot=candidate.get('snapshot') or {k:candidate[k] for k in ('content_hash','generation','index_revision','embedding_space_id')}
        if (row is None or any(row[k]!=snapshot[k] for k in snapshot)
            or row['document_id']!=candidate['document_id'] or row['knowledge_base_id']!=candidate['knowledge_base_id']):
            raise AuthError(409,'context_stale','Evidence changed; retry retrieval')
        result.append(row)
    return result
