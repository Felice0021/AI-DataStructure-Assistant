from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from backend.v2.dependencies.auth import require_active_user, require_role
from backend.v2.dependencies.database import get_session
from backend.v2.models import User
from backend.v2.schemas.auth import ErrorResponse
from backend.v2.schemas.knowledge_base import KnowledgeBaseCreate, KnowledgeBaseEnvelope, KnowledgeBaseList, KnowledgeBaseResponse, KnowledgeBaseUpdate
from backend.v2.services import knowledge_base_service as service

errors = {code: {"model": ErrorResponse} for code in (401, 403, 404, 409, 422, 500, 503)}
router = APIRouter(prefix="/api/v2/knowledge-bases", tags=["knowledge-bases"], responses=errors)
admin_router = APIRouter(prefix="/api/v2/admin/knowledge-bases", tags=["knowledge-bases-admin"], responses=errors)
CurrentUser = Annotated[User, Depends(require_active_user)]
Database = Annotated[Session, Depends(get_session)]


def envelope(record):
    return KnowledgeBaseEnvelope(knowledge_base=KnowledgeBaseResponse.model_validate(record))


@router.get("", response_model=KnowledgeBaseList)
def list_knowledge_bases(
    user: CurrentUser, session: Database,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    records, total = service.list_readable(session, user, limit=limit, offset=offset)
    return KnowledgeBaseList(items=[KnowledgeBaseResponse.model_validate(r) for r in records], total=total, limit=limit, offset=offset)


@router.post("", status_code=201, response_model=KnowledgeBaseEnvelope)
def create_knowledge_base(data: KnowledgeBaseCreate, user: CurrentUser, session: Database):
    return envelope(service.create_private(session, user, data))


@admin_router.post("", status_code=201, response_model=KnowledgeBaseEnvelope)
def create_public_knowledge_base(
    data: KnowledgeBaseCreate, user: Annotated[User, Depends(require_role("admin"))], session: Database,
):
    return envelope(service.create_public(session, user, data))


@router.get("/{knowledge_base_id}", response_model=KnowledgeBaseEnvelope)
def get_knowledge_base(knowledge_base_id: UUID, user: CurrentUser, session: Database):
    return envelope(service.get_readable(session, user, knowledge_base_id))


@router.patch("/{knowledge_base_id}", response_model=KnowledgeBaseEnvelope)
def update_knowledge_base(knowledge_base_id: UUID, data: KnowledgeBaseUpdate, user: CurrentUser, session: Database):
    return envelope(service.update(session, user, knowledge_base_id, data))


@router.delete("/{knowledge_base_id}", status_code=204)
def delete_knowledge_base(knowledge_base_id: UUID, user: CurrentUser, session: Database):
    service.delete(session, user, knowledge_base_id)
    return Response(status_code=204)
