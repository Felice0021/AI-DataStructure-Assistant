from types import SimpleNamespace
from fastapi import APIRouter, Request
from backend.v2.dependencies.auth import get_current_user
from backend.v2.routers.documents import CurrentUser, Database
from backend.v2.schemas.retrieval import SearchRequest, SearchResponse
from backend.v2.services.retrieval_service import search

router = APIRouter(prefix='/api/v2/retrieval', tags=['retrieval'])


@router.post('/search', response_model=SearchResponse)
def retrieve(data: SearchRequest, request: Request, user: CurrentUser, session: Database):
    # Finish dependency transaction before any remote call. Recheck cookie afterward.
    identity = SimpleNamespace(id=user.id)
    session.rollback()
    return search(request.app.state.session_factory, identity, data, request.app.state.settings,
                  verify_session=lambda final: get_current_user(request, final))


from backend.v2.dependencies.auth import lock_current_session
from backend.v2.schemas.context import PrepareRequest, ContextResponse
from backend.v2.services.context_service import prepare_context


@router.post('/prepare-context', response_model=ContextResponse)
def context(data: PrepareRequest, request: Request, user: CurrentUser, session: Database):
    identity = SimpleNamespace(id=user.id)
    session.rollback()
    return prepare_context(request.app.state.session_factory,identity,data,request.app.state.settings,
        verify_session=lambda final: lock_current_session(request,final))
