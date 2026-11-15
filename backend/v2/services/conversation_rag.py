"""Persist only validated server RAG turns. History is bounded and independently revalidated."""
import hashlib
import json
from types import SimpleNamespace
from uuid import UUID

from sqlalchemy import func, select, text

from backend.v2.core.errors import AuthError, unauthorized
from backend.v2.models import Message
from backend.v2.schemas.rag import AskRequest, AskResponse
from backend.v2.services import conversation_service as conversations
from backend.v2.services.context_service import validate_evidence
from backend.v2.services.rag_service import ask
from backend.v2.services import conversation_context as history
from backend.v2.services import project_service as projects


def checked_result(session, user, result, settings, verify_session, kb_ids=None):
    result = AskResponse.model_validate(result)
    candidates = [s.model_dump() for s in result.sources]
    validate_evidence(session, user, [UUID(str(k)) for k in kb_ids] if kb_ids else sorted({s.knowledge_base_id for s in result.sources}, key=str),
                      candidates, settings, verify_session=verify_session)
    return result


def run(factory, user_id, conversation_id, data, settings, verify_session, *, stream=None):
    engine = factory.kw['bind']
    if stream:stream.check()
    # Session advisory lock has no row locks/transaction during remote generation.
    # All API workers share it; disconnect/crash releases it. Never reuse a locked pooled connection.
    key = int.from_bytes(hashlib.sha256(str(conversation_id).encode()).digest()[:8], 'big', signed=True)
    with engine.connect().execution_options(isolation_level='AUTOCOMMIT') as lock:
        if not lock.scalar(text('SELECT pg_try_advisory_lock(:key)'), {'key': key}):
            raise AuthError(409, 'conversation_busy', 'A turn is already running; retry later')
        try:
            fingerprint = hashlib.sha256(json.dumps(data.model_dump(mode='json', exclude={'request_id'}), sort_keys=True).encode()).hexdigest()
            with factory() as session:
                user = verify_session(session)
                if user is None or user.id != user_id:
                    raise unauthorized()
                conversations.get_owned(session, user, conversation_id)
                old = session.scalar(select(Message).where(Message.conversation_id == conversation_id,
                    Message.role == 'assistant', Message.metadata_json['request_id'].astext == str(data.request_id)))
                if old is not None:
                    if old.metadata_json.get('fingerprint') != fingerprint:
                        raise AuthError(409, 'request_id_conflict', 'Request id already used')
                    if stream:stream.stage('validating')
                    return checked_result(session, user, old.metadata_json['result'], settings, verify_session, old.metadata_json.get('knowledge_base_ids'))
                recent = history.load_recent(session, user, conversation_id, data.knowledge_base_ids,
                                             settings, verify_session, checked_result)
                memories = projects.load_notes(session, user, conversation_id, data.knowledge_base_ids,
                                               settings, verify_session, checked_result)
            plan = history.plan(data.query, recent, min(2000, settings.retrieval_max_query_chars))
            def verified_with_history(session):
                current = verify_session(session)
                if current is None or current.id != user_id:
                    raise unauthorized()
                if stream:conversations.get_owned(session,current,conversation_id)
                history.revalidate(session, current, conversation_id, plan.turns, settings, verify_session, checked_result)
                projects.revalidate_notes(session, current, conversation_id, memories, data.knowledge_base_ids,
                                          settings, verify_session, checked_result)
                return current
            payload = AskRequest.model_validate(data.model_dump(exclude={'request_id'}))
            if plan.reason:
                # A normal, persisted clarification/refusal, with no model or embedding calls.
                result = AskResponse(status='insufficient_evidence', reason=plan.reason,
                    answer='请明确本次问题所指的数据结构或算法。', sources=[], retrieval_mode=data.retrieval_mode,
                    answer_mode='qa', rerank_applied=False, generation_model=None, latency_ms=0)
            else:
                stream_options={'stream':stream} if stream else {}
                result = AskResponse.model_validate(ask(factory, SimpleNamespace(id=user_id), payload, settings,
                    verify_session=verified_with_history, retrieval_query=plan.query,
                    conversation_history=plan.prompt_history(), project_memories=memories, **stream_options))
            if result.status not in {'answered', 'insufficient_evidence', 'out_of_scope'}:
                return result  # Never save unvalidated drafts or invent assistant output on failure.
            with factory() as session:
                if stream:
                    stream.stage('saving')
                    stream.authorize_commit()
                user = verify_session(session)
                if user is None or user.id != user_id:
                    raise unauthorized()
                conv = conversations.get_owned(session, user, conversation_id, for_update=True)
                # Defense in depth if the advisory-lock connection died during generation:
                # the conversation row serializes the final idempotency check and insert.
                existing = session.scalar(select(Message).where(
                    Message.conversation_id == conversation_id, Message.role == 'assistant',
                    Message.metadata_json['request_id'].astext == str(data.request_id)))
                if existing is not None:
                    if existing.metadata_json.get('fingerprint') != fingerprint:
                        raise AuthError(409, 'request_id_conflict', 'Request id already used')
                    return checked_result(session, user, existing.metadata_json['result'], settings,
                                          verify_session, existing.metadata_json.get('knowledge_base_ids'))
                history.revalidate(session, user, conversation_id, plan.turns, settings, verify_session, checked_result)
                projects.revalidate_notes(session, user, conversation_id, memories, data.knowledge_base_ids,
                                          settings, verify_session, checked_result)
                checked_result(session, user, result, settings, verify_session, data.knowledge_base_ids)
                if len(result.answer or '') > 20000:
                    raise AuthError(422, 'answer_too_long', 'Answer exceeds history limit')
                seq = session.scalar(select(func.coalesce(func.max(Message.seq), 0)).where(Message.conversation_id == conversation_id)) + 1
                question_message = Message(conversation_id=conversation_id, seq=seq, role='user', content=data.query,
                                           metadata_json={'request_id': str(data.request_id)})
                answer_message = Message(conversation_id=conversation_id, seq=seq+1, role='assistant',
                                         content=result.answer or '根据当前授权资料无法确定。',
                                         metadata_json={'request_id': str(data.request_id), 'fingerprint': fingerprint,
                                                        'knowledge_base_ids': [str(k) for k in data.knowledge_base_ids],
                                                        'context': {**plan.audit(), 'project_memory_candidate_ids': [m['id'] for m in memories]},
                                                        'result': result.model_dump(mode='json')})
                session.add_all([question_message, answer_message])
                session.flush()
                projects.remember(session, conv, data.query, answer_message)
                conv.updated_at = session.scalar(select(func.clock_timestamp()))
                if stream:stream.check()
                session.commit()
            return result
        finally:
            try:
                lock.execute(text('SELECT pg_advisory_unlock(:key)'), {'key': key})
            except Exception:
                lock.invalidate()
                raise
