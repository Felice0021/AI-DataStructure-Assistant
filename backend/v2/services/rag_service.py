"""Single-turn RAG. All evidence sent to generation is fenced again before publication."""
import time
from backend.v2.core.errors import AuthError,unauthorized
from backend.v2.schemas.context import PrepareRequest
from backend.v2.schemas.rag import AnswerSource
from backend.v2.services.context_service import prepare_context,validate_evidence
from backend.v2.services.context_builder import safe_text
from backend.v2.services.prompt_builder import build_prompt
from backend.v2.services.evidence_policy import preflight,resolve_mode
from backend.v2.services.answer_validation import parse_draft,validate_answer,AnswerValidationError
from backend.v2.services.generation_provider import build_provider,RequestBudget,GenerationError,Completion
from backend.v2.services.retrieval_service import capacity

REFUSAL='根据当前授权资料无法确定。'


def ask(factory,user,data,settings,*,verify_session,provider=None,before_cloud_call=None):
    started=time.monotonic();mode=resolve_mode(data.query,data.answer_mode)
    request=PrepareRequest(query=data.query,knowledge_base_ids=data.knowledge_base_ids,mode=data.retrieval_mode,
        top_k=data.top_k,rerank=data.rerank,allow_cloud=data.allow_cloud,allow_cloud_rerank=data.allow_cloud_rerank)
    with capacity(factory.kw['bind'],settings.generation_concurrency,namespace=174928):
        context=prepare_context(factory,user,request,settings,verify_session=verify_session,before_cloud_call=before_cloud_call)
        evidence=context['evidence']
        def publish(status,reason,answer=None,citations=(),model=None):
            with factory() as session:
                # Revalidate every submitted block, even if the model omitted its citation.
                fresh=validate_evidence(session,user,data.knowledge_base_ids,evidence,settings,verify_session=verify_session)
                fresh_by_id={row['chunk_id']:row for row in fresh}
                allowed={e['citation_id']:e for e in evidence};sources=[]
                for citation in citations:
                    old=allowed[citation];row=fresh_by_id[old['chunk_id']]
                    source=AnswerSource.model_validate({**row,'citation_id':citation,
                        'source_filename':safe_text(row['source_filename']),
                        'section_title':safe_text(row['section_title']) if row['section_title'] is not None else None})
                    sources.append(source)
                verified=verify_session(session)
                if verified is None or verified.id!=user.id:raise unauthorized()
                return {'status':status,'reason':reason,'answer':answer,'sources':sources,
                    'retrieval_mode':context['actual_mode'],'answer_mode':mode,'rerank_applied':context['rerank_applied'],
                    'generation_model':model,'execution_performed':False,'latency_ms':round((time.monotonic()-started)*1000,3)}
        reason=preflight(data.query,evidence)
        if reason:return publish('insufficient_evidence',reason,REFUSAL)
        messages=build_prompt(data.query,mode,context,settings)
        # Recheck again immediately before any generator could receive evidence, then release locks.
        with factory() as session:validate_evidence(session,user,data.knowledge_base_ids,evidence,settings,verify_session=verify_session)
        budget=RequestBudget(settings.generation_max_calls)
        try:
            from backend.v2.services.cloud_service import Guard
            guard=Guard(factory,user.id,data.knowledge_base_ids,'generation',settings,verify_session=verify_session,before_call=before_cloud_call,evidence=evidence)
            chosen=provider or build_provider(settings,factory.kw['bind'],cloud_guard=guard)
            if settings.generation_provider=='qwen' and not data.allow_cloud_generation:
                raise GenerationError('generation_cloud_consent_required')
            for attempt in range(settings.generation_validation_retries+1):
                try:
                    completion=chosen.generate(messages,before_attempt=budget.reserve)
                    if not isinstance(completion,Completion) or completion.finish_reason!='stop':raise AnswerValidationError('truncated_or_invalid_completion')
                    draft=parse_draft(completion.content,settings)
                    citations=validate_answer(draft,evidence)
                    if draft.status!='answered':
                        reason='model_reported_conflict' if draft.status=='evidence_conflict' else 'scope_not_verified' if draft.status=='out_of_scope' else 'model_refusal'
                        return publish('insufficient_evidence',reason,REFUSAL,model=chosen.model)
                    return publish('answered',None,draft.answer,citations,chosen.model)
                except AnswerValidationError as error:
                    if attempt==settings.generation_validation_retries:
                        return publish('validation_failed',str(error),model=chosen.model)
                    # Do not feed unvalidated output back as control text, and do not strip bad citations.
                    messages=build_prompt(data.query,mode,context,settings,feedback=str(error))
        except GenerationError as error:
            return publish('generation_unavailable',error.code)
