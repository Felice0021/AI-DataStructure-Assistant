"""No text, prompts, endpoint secrets or keys are persisted by this module."""
from contextlib import contextmanager
import hashlib,json,time
from uuid import uuid4
from sqlalchemy import select,func
from sqlalchemy.dialects.postgresql import insert
from backend.v2.models import CloudConsent,CloudAudit,User,Document
from backend.v2.core.errors import AuthError,unauthorized
from backend.v2.services import knowledge_base_service as knowledge


def target(settings,purpose):
    prefix={'embedding':'embedding','reranking':'rerank','generation':'generation'}[purpose]
    model=getattr(settings,prefix+'_model');endpoint=getattr(settings,prefix+'_endpoint')
    revision=settings.embedding_model_revision if purpose=='embedding' else ''
    digest=hashlib.sha256(json.dumps([purpose,'dashscope',model,endpoint,revision],separators=(',',':')).encode()).hexdigest()
    return model,digest


def audit(session,user_id,purpose,key,event,details):
    record=CloudAudit(user_id=user_id,purpose=purpose,service_key=key,event=event,details=details)
    session.add(record);return record


def change(session,user,kb_id,purpose,settings,*,revoke=False):
    # KB shared parent serialization also protects grant/revoke identity and ownership checks.
    knowledge.get_readable(session,user,kb_id,for_update=True)
    model,key=target(settings,purpose)
    session.execute(insert(CloudConsent).values(user_id=user.id,knowledge_base_id=kb_id,purpose=purpose,model=model,
        provider='dashscope',service_key=key).on_conflict_do_nothing())
    record=session.scalar(select(CloudConsent).where(CloudConsent.user_id==user.id,CloudConsent.knowledge_base_id==kb_id,
        CloudConsent.purpose==purpose,CloudConsent.service_key==key).with_for_update())
    now=session.scalar(select(func.clock_timestamp()))
    if revoke:record.revoked_at=now
    else:record.granted_at=now;record.revoked_at=None
    audit(session,user.id,purpose,key,'revoked' if revoke else 'granted',{'knowledge_base_id':str(kb_id),'scope':'all_current_and_future_versions'})
    session.commit();return record


def list_consents(session,user,kb_id):
    knowledge.get_readable(session,user,kb_id)
    return session.scalars(select(CloudConsent).where(CloudConsent.user_id==user.id,CloudConsent.knowledge_base_id==kb_id).order_by(CloudConsent.purpose,CloudConsent.granted_at)).all()


def require(session,user,kb_ids,purpose,settings):
    model,key=target(settings,purpose)
    for kb_id in sorted(kb_ids,key=str):
        knowledge.get_readable(session,user,kb_id,for_update=True)
        record=session.scalar(select(CloudConsent).where(CloudConsent.user_id==user.id,CloudConsent.knowledge_base_id==kb_id,
            CloudConsent.purpose==purpose,CloudConsent.service_key==key,CloudConsent.revoked_at.is_(None)).with_for_update(read=True))
        if record is None:raise AuthError(403,'cloud_consent_required','Purpose-specific cloud consent required')
    return model,key


class Guard:
    def __init__(self,factory,user_id,kb_ids,purpose,settings,*,verify_session=None,document_id=None,before_call=None,evidence=None,expected_generation=None,expected_index_revision=None):
        self.factory,self.user_id,self.kb_ids,self.purpose,self.settings=factory,user_id,kb_ids,purpose,settings
        self.verify_session,self.document_id,self.before_call=verify_session,document_id,before_call
        self.evidence,self.expected_generation,self.expected_index_revision=evidence,expected_generation,expected_index_revision

    @contextmanager
    def __call__(self):
        with self.factory() as session:
            user=session.scalar(select(User).where(User.id==self.user_id).with_for_update(read=True))
            if user is None or not user.is_active:raise unauthorized()
            if self.verify_session:
                verified=self.verify_session(session)
                if verified is None or verified.id!=user.id:raise unauthorized()
            model,key=require(session,user,self.kb_ids,self.purpose,self.settings)
            if self.evidence is not None:
                from backend.v2.services.context_service import validate_evidence
                validate_evidence(session,user,self.kb_ids,self.evidence,self.settings,verify_session=self.verify_session)
            if self.document_id:
                doc=session.get(Document,self.document_id)
                if doc is None or doc.deleted_at is not None or doc.knowledge_base_id not in self.kb_ids:
                    raise AuthError(409,'context_stale','Cloud source changed')
                if (self.expected_generation is not None and doc.ingestion_version!=self.expected_generation) or (self.expected_index_revision is not None and doc.index_revision!=self.expected_index_revision):
                    raise AuthError(409,'context_stale','Cloud source changed')
                if doc.cloud_embedding_generation!=doc.ingestion_version:raise AuthError(403,'cloud_consent_required','Current parsing generation consent required')
            if self.before_call:self.before_call(self.purpose)
            call_id=str(uuid4());details={'call_id':call_id,'knowledge_base_ids':[str(k) for k in self.kb_ids],'model':model}
            if self.evidence is not None:
                details['evidence']=[{'chunk_id':str(c['chunk_id']),'generation':(c.get('snapshot') or c)['generation'],'content_hash':(c.get('snapshot') or c)['content_hash']} for c in self.evidence]
            if self.document_id:details.update(document_id=str(doc.id),generation=doc.ingestion_version)
            audit(session,user.id,self.purpose,key,'attempt',details);session.commit()
        ticket=Ticket();start=time.monotonic()
        try:
            yield ticket
        except BaseException:
            with self.factory() as session:
                audit(session,self.user_id,self.purpose,key,'failed',{'call_id':call_id,'knowledge_base_ids':[str(k) for k in self.kb_ids],'elapsed_ms':round((time.monotonic()-start)*1000)});session.commit()
            raise
        else:
            with self.factory() as session:
                audit(session,self.user_id,self.purpose,key,'succeeded',{'call_id':call_id,'knowledge_base_ids':[str(k) for k in self.kb_ids],'elapsed_ms':round((time.monotonic()-start)*1000),'usage':ticket.usage});session.commit()


class Ticket:
    def __init__(self):self.usage={}
    def record(self,payload):
        value=payload.get('usage',{}) if isinstance(payload,dict) else {}
        self.usage={k:v for k,v in value.items() if k in {'input_tokens','output_tokens','prompt_tokens','completion_tokens','total_tokens'} and type(v) is int and 0<=v<=10000000} if isinstance(value,dict) else {}
