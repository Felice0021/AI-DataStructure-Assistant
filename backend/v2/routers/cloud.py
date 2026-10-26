from datetime import datetime
from typing import Literal
from uuid import UUID
from fastapi import APIRouter,Request
from pydantic import BaseModel,ConfigDict
from backend.v2.routers.documents import CurrentUser,Database
from backend.v2.services import cloud_service

router=APIRouter(prefix='/api/v2/knowledge-bases/{kb_id}/cloud-consents',tags=['cloud-consents'])


class Consent(BaseModel):
    model_config=ConfigDict(from_attributes=True)
    id:UUID
    knowledge_base_id:UUID
    purpose:Literal['embedding','reranking','generation']
    provider:str
    model:str
    service_key:str
    granted_at:datetime
    revoked_at:datetime|None


@router.get('',response_model=list[Consent])
def listing(kb_id:UUID,user:CurrentUser,session:Database):return cloud_service.list_consents(session,user,kb_id)


@router.post('/{purpose}',response_model=Consent)
def grant(kb_id:UUID,purpose:Literal['embedding','reranking','generation'],request:Request,user:CurrentUser,session:Database):
    return cloud_service.change(session,user,kb_id,purpose,request.app.state.settings)


@router.delete('/{purpose}',response_model=Consent)
def revoke(kb_id:UUID,purpose:Literal['embedding','reranking','generation'],request:Request,user:CurrentUser,session:Database):
    return cloud_service.change(session,user,kb_id,purpose,request.app.state.settings,revoke=True)


from fastapi import Query
from sqlalchemy import select,or_
from backend.v2.models import CloudAudit
from backend.v2.services import knowledge_base_service


class Audit(BaseModel):
    model_config=ConfigDict(from_attributes=True)
    id:UUID
    purpose:str
    event:str
    service_key:str
    details:dict
    created_at:datetime


@router.get('/audit',response_model=list[Audit])
def audits(kb_id:UUID,user:CurrentUser,session:Database,limit:int=Query(default=50,ge=1,le=100),offset:int=Query(default=0,ge=0,le=10000)):
    knowledge_base_service.get_readable(session,user,kb_id)
    return session.scalars(select(CloudAudit).where(CloudAudit.user_id==user.id,or_(
        CloudAudit.details['knowledge_base_id'].astext==str(kb_id),CloudAudit.details['knowledge_base_ids'].contains([str(kb_id)])))
        .order_by(CloudAudit.created_at.desc(),CloudAudit.id).limit(limit).offset(offset)).all()
