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
from backend.v2.services.course_source_labels import read_mapping,source_label
from backend.v2.services.verified_trees import calculate,TreeError,tree_family,unverified_tree_prose
from backend.v2.services.tree_rule_evidence import rule_supported

REFUSAL='根据当前授权资料无法确定。'


def ask(factory,user,data,settings,*,verify_session,provider=None,before_cloud_call=None,retrieval_query=None,conversation_history=(),project_memories=(),stream=None):
    from backend.v2.services.verified_partition import prepare as prepare_partition
    if stream:
        original_before_call=before_cloud_call
        def before_cloud_call(purpose):
            stream.check()
            if original_before_call:original_before_call(purpose)
    started=time.monotonic();mode=resolve_mode(data.query,data.answer_mode)
    effective_query=retrieval_query or data.query
    partition=None
    request=PrepareRequest(query=effective_query,knowledge_base_ids=data.knowledge_base_ids,mode=data.retrieval_mode,
        top_k=data.top_k,rerank=data.rerank,allow_cloud=data.allow_cloud,allow_cloud_rerank=data.allow_cloud_rerank)
    with capacity(factory.kw['bind'],settings.generation_concurrency,namespace=174928):
        if stream:stream.stage('retrieving')
        context=prepare_context(factory,user,request,settings,verify_session=verify_session,before_cloud_call=before_cloud_call)
        if stream:stream.check()
        evidence=context['evidence']
        partition_reason=None
        if mode!='code':partition,partition_reason=prepare_partition(effective_query,evidence,user_query=data.query)
        def publish(status,reason,answer=None,citations=(),model=None,tree=None):
            if stream:stream.stage('validating')
            if status=='insufficient_evidence' and reason and reason.startswith('partition_'):
                answer='当前分区题的变体、输入、基准、下标约定或课程依据不满足已校验条件。仅支持明确末元素基准、下标从0开始的Lomuto单次分区；请核对条件，不会改用其他算法或伪造引用。'
            if status=='answered' and partition:
                answer=partition.finish(answer,citations)
                if len(answer.encode())>settings.generation_max_output_bytes:
                    raise AnswerValidationError('partition_output_limit')
            with factory() as session:
                # Revalidate every submitted block, even if the model omitted its citation.
                fresh=validate_evidence(session,user,data.knowledge_base_ids,evidence,settings,verify_session=verify_session)
                fresh_by_id={row['chunk_id']:row for row in fresh}
                allowed={e['citation_id']:e for e in evidence};sources=[]
                labels=read_mapping(settings.course_source_mapping_path)
                for citation in citations:
                    old=allowed[citation];row=fresh_by_id[old['chunk_id']]
                    label=source_label(row,labels)
                    name=label.get('source_filename',row['source_filename'])
                    title=label.get('section_title',row['section_title'])
                    source=AnswerSource.model_validate({**row,**label,'citation_id':citation,
                        'source_filename':safe_text(name),
                        'section_title':safe_text(title) if title is not None else None})
                    sources.append(source)
                verified=verify_session(session)
                if verified is None or verified.id!=user.id:raise unauthorized()
                return {'status':status,'reason':reason,'answer':answer,'sources':sources,
                    'retrieval_mode':context['actual_mode'],'answer_mode':mode,'rerank_applied':context['rerank_applied'],
                    'generation_model':model,'execution_performed':False,'latency_ms':round((time.monotonic()-started)*1000,3),
                    'tree_visualization':tree}
        reason=preflight(effective_query,evidence) or partition_reason
        if reason:return publish('insufficient_evidence',reason,REFUSAL)
        calculation=None
        if mode!='code':
            try:calculation,reason=calculate(effective_query)
            except TreeError:return publish('validation_failed','tree_invariant_failed')
            if reason:return publish('insufficient_evidence',reason,'当前构造不在已校验范围内。请提供从空树开始的整数插入序列及明确规则；不会猜测或替换原题条件。')
            if calculation:
                rule_support={e['citation_id']:rule_supported(calculation,e['content']) for e in evidence}
                if any(s.kind=='conflict' for s in rule_support.values()):
                    return publish('insufficient_evidence','tree_rule_conflict','课程资料中识别到的构造约定与本题条件冲突。请确认采用哪套规则；未修改输入或生成构造结果。')
                if any(s.kind=='unrecognized' for s in rule_support.values()):
                    return publish('insufficient_evidence','tree_rule_unverified','课程资料的具体约定超出当前可核对范围，请明确规则依据；不会将其当作一致约定。')
                if not any(s.usable for s in rule_support.values()):
                    return publish('insufficient_evidence','tree_rule_evidence_required','本轮未检索到足够的树操作规则，无法为构造结果提供可靠课程引用。')
        rule_citations=tuple(c for c,s in rule_support.items() if s.usable) if calculation and calculation.family=='AVL' and calculation.rotations else ()
        messages=build_prompt(data.query,mode,context,settings,history=conversation_history,project_memories=project_memories,resolved_query=effective_query,rule_citations=rule_citations)
        if partition:partition.instruct(messages,settings.generation_max_input_bytes)
        # Recheck again immediately before any generator could receive evidence, then release locks.
        with factory() as session:validate_evidence(session,user,data.knowledge_base_ids,evidence,settings,verify_session=verify_session)
        budget=RequestBudget(settings.generation_max_calls)
        try:
            from backend.v2.services.cloud_service import Guard
            guard=Guard(factory,user.id,data.knowledge_base_ids,'generation',settings,verify_session=verify_session,before_call=before_cloud_call,evidence=evidence)
            chosen=provider or build_provider(settings,factory.kw['bind'],cloud_guard=guard)
            if settings.generation_provider=='qwen' and not data.allow_cloud_generation:
                raise GenerationError('generation_cloud_consent_required')
            if stream:
                from contextlib import contextmanager
                @contextmanager
                def preview_check():
                    stream.check()
                    with factory() as session:
                        validate_evidence(session,user,data.knowledge_base_ids,evidence,settings,verify_session=verify_session)
                        if settings.generation_provider=='qwen':
                            from backend.v2.services.cloud_service import require
                            current=verify_session(session)
                            if current is None or current.id!=user.id:raise unauthorized()
                            require(session,current,data.knowledge_base_ids,'generation',settings)
                        yield
                stream.preview_check=preview_check
            preview_allowed=not (calculation or partition or tree_family(effective_query))
            for attempt in range(settings.generation_validation_retries+1):
                try:
                    if stream:
                        def before_attempt():
                            stream.check();budget.reserve();stream.reset()
                            stream.stage('generating',preview=preview_allowed and hasattr(chosen,'generate_stream'))
                        if hasattr(chosen,'generate_stream'):
                            completion=chosen.generate_stream(messages,before_attempt=before_attempt,
                                on_delta=stream.draft if preview_allowed else lambda _text:stream.check(),check_cancel=stream.check)
                            stream.flush()
                        else:
                            completion=chosen.generate(messages,before_attempt=before_attempt)
                        stream.stage('validating')
                    else:completion=chosen.generate(messages,before_attempt=budget.reserve)
                    if not isinstance(completion,Completion) or completion.finish_reason!='stop':raise AnswerValidationError('truncated_or_invalid_completion')
                    draft=parse_draft(completion.content,settings)
                    citations=validate_answer(draft,evidence)
                    if draft.status!='answered':
                        reason='model_reported_conflict' if draft.status=='evidence_conflict' else 'scope_not_verified' if draft.status=='out_of_scope' else 'model_refusal'
                        return publish('insufficient_evidence',reason,REFUSAL,model=chosen.model)
                    answer=draft.answer
                    tree=None
                    if calculation:
                        if any(not rule_support[c].usable for c in citations):
                            raise AnswerValidationError('tree_rule_citation_required')
                        # Numerical structures never come from unchecked model prose. Keep the
                        # original strict citation checks; render only the verified calculation.
                        answer=calculation.render(' '.join(citations),supports={c:rule_support[c] for c in citations})
                        if len(answer.encode())>settings.generation_max_output_bytes:raise AnswerValidationError('tree_output_limit')
                        from backend.v2.services.tree_visualization import build
                        from pydantic import ValidationError
                        try:tree=build(calculation,citations,{c:rule_support[c] for c in citations}).model_dump(mode='json')
                        except (TreeError,ValidationError):raise AnswerValidationError('tree_display_invalid') from None
                    elif mode!='code' and tree_family(effective_query) and unverified_tree_prose(answer):
                        raise AnswerValidationError('unverified_tree_prose')
                    return publish('answered',None,answer,citations,chosen.model,tree)
                except AnswerValidationError as error:
                    if attempt==settings.generation_validation_retries:
                        return publish('validation_failed',str(error),model=chosen.model)
                    # Do not feed unvalidated output back as control text, and do not strip bad citations.
                    messages=build_prompt(data.query,mode,context,settings,feedback=str(error),history=conversation_history,project_memories=project_memories,resolved_query=effective_query,rule_citations=rule_citations)
                    if partition:partition.instruct(messages,settings.generation_max_input_bytes)
        except GenerationError as error:
            return publish('generation_unavailable',error.code)
