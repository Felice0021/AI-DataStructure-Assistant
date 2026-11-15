from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, Request
from sqlalchemy.orm import Session
from fastapi.responses import StreamingResponse

from backend.v2.dependencies.auth import require_active_user
from backend.v2.dependencies.database import get_session
from backend.v2.models import User
from backend.v2.schemas.auth import ErrorResponse
from backend.v2.schemas.conversation import (
    ConversationAskError, ConversationAskRequest, ConversationCreate, ConversationEnvelope, ConversationList,
    ConversationResponse, ConversationUpdate, MessageCreate, MessageList,
    MessageResponse,
)
from backend.v2.services import conversation_service as service

errors = {code: {"model": ErrorResponse} for code in (401, 403, 404, 409, 422, 500, 503)}
router = APIRouter(prefix="/api/v2/conversations", tags=["conversations"], responses=errors)
CurrentUser = Annotated[User, Depends(require_active_user)]
Database = Annotated[Session, Depends(get_session)]


def envelope(record):
    return ConversationEnvelope(conversation=ConversationResponse.model_validate(record))


@router.get("", response_model=ConversationList)
def list_conversations(
    user: CurrentUser, session: Database,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    records, total = service.list_owned(session, user, limit=limit, offset=offset)
    return ConversationList(
        items=[ConversationResponse.model_validate(r) for r in records],
        total=total, limit=limit, offset=offset,
    )


@router.post("", status_code=201, response_model=ConversationEnvelope)
def create_conversation(data: ConversationCreate, user: CurrentUser, session: Database):
    return envelope(service.create(session, user, data))


@router.get("/{conversation_id}", response_model=ConversationEnvelope)
def get_conversation(conversation_id: UUID, user: CurrentUser, session: Database):
    return envelope(service.get_owned(session, user, conversation_id))


@router.patch("/{conversation_id}", response_model=ConversationEnvelope)
def update_conversation(
    conversation_id: UUID, data: ConversationUpdate, user: CurrentUser, session: Database
):
    return envelope(service.update(session, user, conversation_id, data))


@router.delete("/{conversation_id}", status_code=204)
def delete_conversation(conversation_id: UUID, user: CurrentUser, session: Database):
    service.delete(session, user, conversation_id)
    return Response(status_code=204)


@router.get("/{conversation_id}/messages", response_model=MessageList)
def list_messages(
    request: Request, conversation_id: UUID, user: CurrentUser, session: Database,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    records, total = service.list_messages(session, user, conversation_id, limit=limit, offset=offset)
    from backend.v2.services.conversation_rag import checked_result
    from backend.v2.dependencies.auth import lock_current_session
    from backend.v2.core.errors import AuthError
    items = []
    for record in records:
        item = MessageResponse.model_validate(record)
        if record.role == 'assistant':
            try:
                if 'result' not in record.metadata_json:
                    raise AuthError(409, 'history_unavailable', 'History unavailable')
                checked_result(session, user, record.metadata_json['result'], request.app.state.settings,
                               lambda final: lock_current_session(request, final), record.metadata_json.get('knowledge_base_ids'))
            except AuthError as error:
                if error.status == 401:
                    raise
                item = item.model_copy(update={'content': '该回答的来源已变更或不可访问，请重新提问。', 'metadata_json': {}})
        items.append(item)
    return MessageList(
        items=items,
        total=total, limit=limit, offset=offset,
    )


@router.post("/{conversation_id}/messages", status_code=201, response_model=MessageResponse)
def append_message(
    conversation_id: UUID, data: MessageCreate, user: CurrentUser, session: Database
):
    return MessageResponse.model_validate(
        service.append_message(session, user, conversation_id, data)
    )


from backend.v2.schemas.rag import AskResponse


@router.post('/{conversation_id}/ask', response_model=AskResponse, responses={
    502: {'model': ConversationAskError}, 503: {'model': ConversationAskError},
})
def ask_in_conversation(conversation_id: UUID, data: ConversationAskRequest,
                        request: Request, user: CurrentUser, session: Database):
    from backend.v2.dependencies.auth import lock_current_session
    from backend.v2.services.conversation_rag import run
    from fastapi.responses import JSONResponse
    user_id = user.id
    # The generation service owns its short transactions and final authorization locks.
    service.get_owned(session, user, conversation_id)
    session.rollback()
    result = run(request.app.state.session_factory, user_id, conversation_id, data,
                 request.app.state.settings, lambda final: lock_current_session(request, final))
    if result.status in {'generation_unavailable', 'validation_failed'}:
        return JSONResponse(status_code=503 if result.status == 'generation_unavailable' else 502,
                            content={**result.model_dump(mode='json'), 'error': {
                                'code': result.reason, 'message': 'Answer unavailable'}})
    return result


@router.post('/{conversation_id}/ask-stream', response_model=None, response_class=StreamingResponse, responses={
    200: {'description': 'Authenticated POST SSE: status/reset/draft followed by one result or error. Drafts are unverified and never persisted.',
          'content': {'text/event-stream': {'schema': {'type': 'string'},
              'example': 'event: status\nid: 1\ndata: {"type":"status","seq":1,"request_id":"00000000-0000-4000-8000-000000000001","payload":{"stage":"accepted","preview":false}}\n\n'}}},
})
async def stream_in_conversation(conversation_id: UUID, data: ConversationAskRequest,
                                 request: Request, user: CurrentUser, session: Database):
    import asyncio
    from starlette.concurrency import run_in_threadpool
    from backend.v2.core.errors import AuthError
    from backend.v2.dependencies.auth import lock_current_session
    from backend.v2.services.conversation_rag import run
    from backend.v2.services.conversation_stream import StreamControl,ConversationStreamResponse
    from backend.v2.services import knowledge_base_service as knowledge
    user_id=user.id
    def preflight():
        service.get_owned(session,user,conversation_id)
        for kb_id in sorted(data.knowledge_base_ids,key=str):knowledge.get_readable(session,user,kb_id)
        session.rollback()
    await run_in_threadpool(preflight)
    slots=request.app.state.rag_stream_slots
    if not slots.acquire(blocking=False):raise AuthError(503,'service_busy','Service temporarily busy')
    control=StreamControl(asyncio.get_running_loop(),data.request_id,request.app.state.settings.conversation_stream_timeout_seconds)
    def produce(stream):
        factory=request.app.state.session_factory
        verify=lambda final:lock_current_session(request,final)
        result=run(factory,user_id,conversation_id,data,request.app.state.settings,verify,stream=stream)
        if result.status in {'answered','insufficient_evidence','out_of_scope'}:
            from backend.v2.services.conversation_rag import checked_result
            stream.check()
            with factory() as final:
                current=verify(final)
                if current is None or current.id!=user_id:
                    from backend.v2.core.errors import unauthorized
                    raise unauthorized()
                service.get_owned(final,current,conversation_id)
                checked_result(final,current,result,request.app.state.settings,verify,data.knowledge_base_ids)
        return result
    return ConversationStreamResponse(control,produce,slots)
