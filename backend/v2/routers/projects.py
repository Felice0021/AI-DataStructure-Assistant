from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Response, Request
from sqlalchemy.orm import Session

from backend.v2.dependencies.auth import require_active_user
from backend.v2.dependencies.database import get_session
from backend.v2.models import User
from backend.v2.schemas.auth import ErrorResponse
from backend.v2.schemas.conversation import (ProjectCreate, ProjectUpdate, ProjectResponse,
                                             ProjectList, ProjectMemoryList, ProjectMemoryResponse)
from backend.v2.services import project_service as service

router = APIRouter(prefix='/api/v2/projects', tags=['projects'],
                   responses={code: {'model': ErrorResponse} for code in (401, 403, 404, 409, 422, 500, 503)})
CurrentUser = Annotated[User, Depends(require_active_user)]
Database = Annotated[Session, Depends(get_session)]


@router.get('', response_model=ProjectList)
def list_projects(user: CurrentUser, session: Database):
    return ProjectList(items=[ProjectResponse.model_validate(record) for record in service.list_owned(session, user)])


@router.post('', status_code=201, response_model=ProjectResponse)
def create_project(data: ProjectCreate, user: CurrentUser, session: Database):
    return ProjectResponse.model_validate(service.create(session, user, data))


@router.patch('/{project_id}', response_model=ProjectResponse)
def update_project(project_id: UUID, data: ProjectUpdate, user: CurrentUser, session: Database):
    return ProjectResponse.model_validate(service.update_owned(session, user, project_id, data))


@router.delete('/{project_id}', status_code=204)
def delete_project(project_id: UUID, user: CurrentUser, session: Database):
    service.delete_owned(session, user, project_id)
    return Response(status_code=204)


@router.get('/{project_id}/memories', response_model=ProjectMemoryList)
def list_memories(project_id: UUID, request: Request, user: CurrentUser, session: Database):
    from backend.v2.dependencies.auth import lock_current_session
    from backend.v2.services.conversation_rag import checked_result
    return ProjectMemoryList(items=[ProjectMemoryResponse.model_validate(note)
                                    for note in service.own_notes(session, user, project_id,
                                        request.app.state.settings,
                                        lambda final: lock_current_session(request, final), checked_result)])


@router.delete('/{project_id}/memories/{note_id}', status_code=204)
def forget_memory(project_id: UUID, note_id: UUID, user: CurrentUser, session: Database):
    service.forget_note(session, user, project_id, note_id)
    return Response(status_code=204)
