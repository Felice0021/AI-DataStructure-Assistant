from uuid import UUID
from fastapi import APIRouter, Request
from backend.v2.routers.documents import CurrentUser, Database
from backend.v2.schemas.embedding import IndexJobEnvelope, IndexJobResponse, IndexRequest
from backend.v2.services import embedding_service as service

router=APIRouter(prefix='/api/v2/knowledge-bases/{kb_id}/documents/{doc_id}/embedding',tags=['embedding'])


@router.get('',response_model=IndexJobEnvelope)
def status(kb_id:UUID,doc_id:UUID,request:Request,user:CurrentUser,session:Database):
    return IndexJobEnvelope(job=IndexJobResponse.model_validate(service.get_job(session,user,kb_id,doc_id,request.app.state.settings)))


@router.post('',status_code=202,response_model=IndexJobEnvelope)
def enqueue(kb_id:UUID,doc_id:UUID,request:Request,user:CurrentUser,session:Database,data:IndexRequest=IndexRequest()):
    return IndexJobEnvelope(job=IndexJobResponse.model_validate(service.request_indexing(session,user,kb_id,doc_id,request.app.state.settings,data.allow_cloud)))
