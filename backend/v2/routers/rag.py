from types import SimpleNamespace
from fastapi import APIRouter,Request
from fastapi.responses import JSONResponse
from backend.v2.dependencies.auth import lock_current_session
from backend.v2.routers.documents import CurrentUser,Database
from backend.v2.schemas.rag import AskRequest,AskResponse
from backend.v2.services.rag_service import ask

router=APIRouter(prefix='/api/v2/rag',tags=['rag'])


@router.post('/ask',response_model=AskResponse)
def answer(data:AskRequest,request:Request,user:CurrentUser,session:Database):
    identity=SimpleNamespace(id=user.id);session.rollback()
    result=AskResponse.model_validate(ask(request.app.state.session_factory,identity,data,request.app.state.settings,
        verify_session=lambda final:lock_current_session(request,final)))
    if result.status in {'generation_unavailable','validation_failed'}:
        body=result.model_dump(mode='json')
        body['error']={'code':result.reason,'message':'Generation unavailable' if result.status=='generation_unavailable' else 'Generated answer failed validation'}
        return JSONResponse(status_code=503 if result.status=='generation_unavailable' else 502,content=body)
    return result
