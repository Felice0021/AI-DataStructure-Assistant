import json,os
from types import SimpleNamespace
from uuid import UUID
import pytest
from sqlalchemy import select,text,func
from backend.v2.models import User,CloudConsent,CloudAudit
from backend.v2.services.cloud_service import change,Guard,target
from backend.v2.services.generation_provider import QwenProvider,Completion,GenerationError
from backend.v2.tests.test_ingestion import setup
from backend.v2.tests.test_retrieval import env
from backend.v2.tests.test_auth import csrf_headers,client_for,register,post
from backend.v2.core.errors import AuthError

pytestmark=pytest.mark.skipif(os.environ.get('DS_V2_RUN_DB_TESTS')!='1',reason='Isolated DB')


def actor(env,session):return session.get(User,UUID(env['user']['id']))


def test_purpose_grant_revoke_and_audit(env):
    kb=UUID(env['kb']['id']);s=env['settings']
    with env['factory']() as db:change(db,actor(env,db),kb,'generation',s)
    guard=Guard(env['factory'],UUID(env['user']['id']),[kb],'generation',s)
    with guard() as ticket:ticket.record({'usage':{'prompt_tokens':12,'completion_tokens':4,'private_text':'must-not-persist'}})
    with env['factory']() as db:
        assert db.scalar(select(func.count()).select_from(CloudAudit))==3
        values=db.scalars(select(CloudAudit)).all()
        assert 'must-not-persist' not in json.dumps([r.details for r in values])
        change(db,actor(env,db),kb,'generation',s,revoke=True)
    with pytest.raises(AuthError):
        with guard():pass
    with pytest.raises(AuthError):
        with Guard(env['factory'],UUID(env['user']['id']),[kb],'embedding',s)():pass


def test_http_consent_scope_and_csrf(env):
    path='/api/v2/knowledge-bases/'+env['kb']['id']+'/cloud-consents';a=env['client']
    assert a.post(path+'/generation',headers=csrf_headers(a)).status_code==200
    assert a.get(path).json()[0]['purpose']=='generation'
    assert a.delete(path+'/generation').status_code==403
    assert a.delete(path+'/generation',headers=csrf_headers(a)).status_code==200
    with client_for(env['settings']) as b:
        cred,_=register(b);post(b,'login',cred)
        assert b.get(path).status_code==404
        assert b.post(path+'/generation',headers=csrf_headers(b)).status_code==404


def test_model_change_requires_new_grant(env):
    kb=UUID(env['kb']['id']);s=env['settings']
    with env['factory']() as db:change(db,actor(env,db),kb,'generation',s)
    s.generation_model='new-model'
    with pytest.raises(AuthError):
        with Guard(env['factory'],UUID(env['user']['id']),[kb],'generation',s)():pass


def test_key_aliases_are_only_from_selected_v2_file(tmp_path):
    from backend.v2.core.config import Settings
    p=tmp_path/'local.env';p.write_text('DS_V2_DB_PASSWORD=synthetic-test-password\nDASHSCOPE_API_KEY=synthetic-only\nDASHSCOPE_WORKSPACE_ID=synthetic\nDASHSCOPE_REGION=cn-beijing\n')
    s=Settings(_env_file=p);assert s.generation_api_key.get_secret_value()=='synthetic-only'
    assert 'synthetic.cn-beijing.maas.aliyuncs.com' in s.generation_endpoint
    assert Settings(_env_file=None,db_password='synthetic-test-password').generation_api_key is None


def test_unexpected_500_cors_and_patch_schema(env):
    from fastapi.testclient import TestClient
    from backend.v2.main import create_app
    from backend.v2.dependencies.database import get_session
    def fail():raise RuntimeError('private-not-for-output')
    app=create_app(env['settings']);app.dependency_overrides[get_session]=fail
    with TestClient(app,raise_server_exceptions=False) as c:
        r=c.get('/api/v2/health/db',headers={'Origin':'http://127.0.0.1:5173'})
        assert r.status_code==500 and r.headers['access-control-allow-origin']=='http://127.0.0.1:5173'
    from backend.v2.schemas.knowledge_base import KnowledgeBaseUpdate
    schema=KnowledgeBaseUpdate.model_json_schema()
    assert 'null' not in json.dumps(schema['properties']['name'])
    with pytest.raises(ValueError):KnowledgeBaseUpdate(name=None)


def test_guard_rechecks_worker_generation_before_audited_outbound(env):
    from backend.v2.models import Document
    kb=UUID(env['kb']['id']);doc_id=UUID(env['record']['id']);s=env['settings']
    with env['factory']() as db:
        change(db,actor(env,db),kb,'embedding',s)
        document=db.get(Document,doc_id)
        document.cloud_embedding_generation=document.ingestion_version
        generation=document.ingestion_version;revision=document.index_revision
        db.commit()
    with pytest.raises(AuthError) as error:
        with Guard(env['factory'],UUID(env['user']['id']),[kb],'embedding',s,
                   document_id=doc_id,expected_generation=generation+1,expected_index_revision=revision)():
            pytest.fail('Stale source must not reach outbound transport')
    assert error.value.code=='context_stale'
    with env['factory']() as db:
        assert db.scalar(select(func.count()).select_from(CloudAudit).where(CloudAudit.event=='attempt'))==0


def test_guard_rechecks_session_and_releases_transaction(env):
    kb=UUID(env['kb']['id']);s=env['settings'];user_id=UUID(env['user']['id'])
    with env['factory']() as db:change(db,actor(env,db),kb,'generation',s)
    with pytest.raises(AuthError):
        with Guard(env['factory'],user_id,[kb],'generation',s,verify_session=lambda db:None)():
            pytest.fail('Revoked session must not reach transport')
    with Guard(env['factory'],user_id,[kb],'generation',s)():
        # Actual server view: no held source transaction across the remote-call interval.
        with env['engine'].connect() as connection:
            count=connection.scalar(text("SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() AND state='idle in transaction' AND pid<>pg_backend_pid()"))
            assert count==0


def test_audit_http_is_scoped_to_current_user(env):
    path='/api/v2/knowledge-bases/'+env['kb']['id']+'/cloud-consents'
    a=env['client']
    assert a.post(path+'/generation',headers=csrf_headers(a)).status_code==200
    with Guard(env['factory'],UUID(env['user']['id']),[UUID(env['kb']['id'])],'generation',env['settings'])() as ticket:
        ticket.record({'usage':{'prompt_tokens':7}})
    records=a.get(path+'/audit').json()
    assert {r['event'] for r in records}=={'granted','attempt','succeeded'}
    assert next(r for r in records if r['event']=='succeeded')['details']['usage']=={'prompt_tokens':7}
    with client_for(env['settings']) as b:
        credentials,_=register(b);post(b,'login',credentials)
        assert b.get(path+'/audit').status_code==404
