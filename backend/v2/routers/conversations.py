from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from backend.v2.dependencies.auth import require_active_user
from backend.v2.dependencies.database import get_session
from backend.v2.models import User
from backend.v2.schemas.auth import ErrorResponse
from backend.v2.schemas.conversation import (
    ConversationCreate, ConversationEnvelope, ConversationList,
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
    conversation_id: UUID, user: CurrentUser, session: Database,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    records, total = service.list_messages(session, user, conversation_id, limit=limit, offset=offset)
    return MessageList(
        items=[MessageResponse.model_validate(r) for r in records],
        total=total, limit=limit, offset=offset,
    )


@router.post("/{conversation_id}/messages", status_code=201, response_model=MessageResponse)
def append_message(
    conversation_id: UUID, data: MessageCreate, user: CurrentUser, session: Database
):
    return MessageResponse.model_validate(
        service.append_message(session, user, conversation_id, data)
    )
