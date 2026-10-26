from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import UUID,uuid4
import math
import os

import pytest
from sqlalchemy import func,select,text
from sqlalchemy.exc import IntegrityError,OperationalError
from sqlalchemy.orm import Session

from backend.v2.embedding_worker import run_once
from backend.v2.models import ChunkEmbedding,Document,DocumentChunk,EmbeddingJob,User
from backend.v2.services import embedding_service as jobs
from backend.v2.services.embedding_provider import DeterministicProvider,EmbeddingError,normalize,space_for
from backend.v2.services.vector_search import QueryEmbedding,exact_search
from backend.v2.tests.test_embedding_provider import axis
from backend.v2.tests.test_ingestion import setup,upload
from backend.v2.tests.test_auth import client_for,csrf_headers,post,register
from backend.v2.manage import create_admin
from backend.v2.core.security import new_token
from backend.v2.core.errors import AuthError
from backend.v2.worker import run_once as parse_once

pytestmark=[pytest.mark.integration,pytest.mark.skipif(os.environ.get('DS_V2_RUN_DB_TESTS')!='1',reason='Opt in to isolated database tests')]


@pytest.fixture
def env(setup):
    s=setup['settings'];s.embedding_provider='deterministic';s.embedding_allow_test_provider=True;s.embedding_batch_size=1
    record=upload(setup,data='# 甲\n\n链表与算法。\n\n# 乙\n\n树与遍历。\n\n# 丙\n\n图与路径。'.encode())
    parse_once(setup['factory'],s)
    setup['record']=record;setup['path']=setup['base']+'/'+record['id'];return setup


def rows(env):
    with env['factory']() as s:
        return s.scalar(select(Document)),s.scalar(select(EmbeddingJob)),s.scalars(select(ChunkEmbedding)).all()


def claim(env):
    with env['factory']() as s:return jobs.claim_next(s,env['settings'])


def query(env,user=None,kb=None,vector=None,settings=None):
    settings=settings or env['settings']
    with env['factory']() as session:
        actor=user or session.get(User,UUID(env['user']['id']))
        return exact_search(session,actor,[kb or UUID(env['kb']['id'])],QueryEmbedding(space_for(settings).id,vector or axis()),settings)


def test_normal_indexing_and_no_open_transaction_during_provider(env):
    class Checking(DeterministicProvider):
        def embed(self,*args,**kwargs):
            with env['engine'].connect() as c:
                assert c.scalar(text("SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() AND state='idle in transaction'"))==0
            return super().embed(*args,**kwargs)
    assert run_once(env['factory'],env['settings'],provider=Checking(env['settings']))
    doc,job,vectors=rows(env)
    assert doc.status=='ready' and doc.indexed_version==doc.ingestion_version
    assert job.status=='succeeded' and len(vectors)==job.expected_chunks==3
    assert all(len(v.embedding.to_list() if hasattr(v.embedding,'to_list') else v.embedding)==1024 for v in vectors)
    assert not run_once(env['factory'],env['settings'])
    assert len(query(env))==3


def test_partial_failure_is_hidden_and_cached_batches_reused(env):
    class Failing(DeterministicProvider):
        calls=0
        def embed(self,*args,**kwargs):
            self.calls+=1
            if self.calls==2:raise EmbeddingError('permanent_provider_error')
            return super().embed(*args,**kwargs)
    run_once(env['factory'],env['settings'],provider=Failing(env['settings']))
    assert rows(env)[0].status=='index_failed' and len(rows(env)[2])==1
    assert query(env)==[]
    assert env['client'].post(env['path']+'/embedding',json={},headers=csrf_headers(env['client'])).status_code==202
    class Counting(DeterministicProvider):
        calls=0
        def embed(self,*args,**kwargs):self.calls+=1;return super().embed(*args,**kwargs)
    provider=Counting(env['settings']);run_once(env['factory'],env['settings'],provider=provider)
    assert provider.calls==2 and rows(env)[0].status=='ready' and len(rows(env)[2])==3


def test_retryable_failure_is_queued(env):
    class Timeout(DeterministicProvider):
        def embed(self,*a,**kw):kw['before_attempt']();raise EmbeddingError('embedding_timeout',True)
    run_once(env['factory'],env['settings'],provider=Timeout(env['settings']))
    assert rows(env)[1].status=='queued' and query(env)==[]
    with env['engine'].begin() as c:c.execute(text("UPDATE embedding_jobs SET next_retry_at=clock_timestamp()-interval '1 second'"))
    run_once(env['factory'],env['settings']);assert rows(env)[0].status=='ready'


def test_two_workers_and_expired_fencing(env):
    barrier=Barrier(2)
    def attempt(_):barrier.wait(timeout=10);return claim(env)
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(attempt,range(2)))
    assert sum(x is not None for x in results)==1
    old=next(x for x in results if x)
    with env['engine'].begin() as c:c.execute(text("UPDATE embedding_jobs SET lease_expires_at=clock_timestamp()-interval '1 second'"))
    current=claim(env);assert current.token!=old.token
    with env['factory']() as s:assert not jobs.complete(s,old,env['settings'])
    with env['factory']() as s:batch=jobs.load_batch(s,current,env['settings'])
    with env['factory']() as s:assert jobs.save_batch(s,current,batch,[axis()],env['settings'])
    assert len(rows(env)[2])==1 and query(env)==[]


def test_call_budget_is_bounded(env):
    with env['engine'].begin() as c:c.execute(text('UPDATE embedding_jobs SET max_api_calls=1'))
    run_once(env['factory'],env['settings'])
    doc,job,vectors=rows(env)
    assert doc.status=='index_failed' and job.api_calls==1 and job.error_code=='embedding_budget_exhausted'
    assert len(vectors)==1 and query(env)==[]


def test_bad_provider_vectors_never_enter_db(env):
    class Invalid(DeterministicProvider):
        def embed(self,*args,**kwargs):kwargs['before_attempt']();return [[0.]*1024]
    run_once(env['factory'],env['settings'],provider=Invalid(env['settings']))
    assert rows(env)[1].error_code=='invalid_vector_norm' and not rows(env)[2]


@pytest.mark.parametrize('target',['document','knowledge_base'])
def test_soft_delete_hides_vectors_and_blocks_publish(env,target):
    current=claim(env)
    path=env['path'] if target=='document' else '/api/v2/knowledge-bases/'+env['kb']['id']
    assert env['client'].delete(path,headers=csrf_headers(env['client'])).status_code==204
    with env['factory']() as s:assert not jobs.complete(s,current,env['settings'])
    if target=='document':assert query(env)==[]
    else:
        with pytest.raises(AuthError):query(env)


def test_reparse_invalidates_old_vectors_immediately(env):
    run_once(env['factory'],env['settings']);assert query(env)
    assert env['client'].post(env['path']+'/ingestion',json={'reprocess':True},headers=csrf_headers(env['client'])).status_code==202
    assert query(env)==[]
    parse_once(env['factory'],env['settings'])
    assert rows(env)[2]==[]  # Chunk FK physically cascades old cache on replacement.
    run_once(env['factory'],env['settings'])
    assert rows(env)[0].status=='ready' and {v.generation for v in rows(env)[2]}=={2}


def test_model_change_isolates_spaces_and_rebuilds(env):
    run_once(env['factory'],env['settings']);assert query(env)
    old_space=space_for(env['settings']).id
    env['settings'].embedding_model_revision='fixture-v2'
    assert query(env)==[]
    run_once(env['factory'],env['settings'])
    assert rows(env)[0].embedding_space_id!=old_space and len(query(env))==3


def test_exact_cosine_numeric_order_and_limits(env):
    run_once(env['factory'],env['settings'])
    with env['factory']() as s:
        values=s.scalars(select(ChunkEmbedding).join(DocumentChunk,ChunkEmbedding.chunk_id==DocumentChunk.id).order_by(DocumentChunk.chunk_index)).all()
        values[0].embedding=axis();values[1].embedding=axis(1);values[2].embedding=normalize([-1.]+[0.]*1023);s.commit()
        user=s.get(User,UUID(env['user']['id']))
        hits=exact_search(s,user,[UUID(env['kb']['id'])],QueryEmbedding(space_for(env['settings']).id,axis()),env['settings'],top_k=2)
        assert [round(x['distance'],5) for x in hits]==[0,1]
        assert [round(x['similarity'],5) for x in hits]==[1,0]
        last=exact_search(s,user,[UUID(env['kb']['id'])],QueryEmbedding(space_for(env['settings']).id,axis()),env['settings'],top_k=1,offset=2)
        assert round(last[0]['distance'])==2 and round(last[0]['similarity'])==-1
        for top in (0,101):
            with pytest.raises(ValueError):exact_search(s,user,[UUID(env['kb']['id'])],QueryEmbedding(space_for(env['settings']).id,axis()),env['settings'],top_k=top)


@pytest.mark.parametrize('role',['student','admin'])
def test_other_users_cannot_query_private_scope(env,role):
    run_once(env['factory'],env['settings'])
    with client_for(env['settings']) as outsider:
        if role=='student':credentials,user=register(outsider)
        else:
            credentials={'email':uuid4().hex+'@example.com','password':new_token()};create_admin(**credentials,settings=env['settings'])
        assert post(outsider,'login',credentials).status_code==200
        assert outsider.get(env['path']+'/embedding').status_code==404
        assert outsider.post(env['path']+'/embedding',json={},headers=csrf_headers(outsider)).status_code==404
        with env['factory']() as s:
            actor=s.scalar(select(User).where(User.email==credentials['email']))
            with pytest.raises(AuthError):exact_search(s,actor,[UUID(env['kb']['id'])],QueryEmbedding(space_for(env['settings']).id,axis()),env['settings'])


def test_chunk_hash_and_fk_constraints_prevent_stale_vectors(env):
    run_once(env['factory'],env['settings'])
    with env['engine'].connect() as c:
        with pytest.raises(IntegrityError):c.execute(text("UPDATE document_chunks SET content='changed'"))
        c.rollback()
        with pytest.raises(IntegrityError):c.execute(text("UPDATE document_chunks SET content='changed',content_hash=encode(sha256(convert_to('changed','UTF8')),'hex')"))
        c.rollback()
        c.execute(text('DELETE FROM chunk_embeddings WHERE id=(SELECT id FROM chunk_embeddings LIMIT 1)'));c.commit()
    assert query(env)==[]  # Even a forged ready status cannot publish a partial set.


def test_db_failure_rolls_back_staging(env,monkeypatch):
    current=claim(env)
    with env['factory']() as s:batch=jobs.load_batch(s,current,env['settings'])
    def broken(self):raise OperationalError('hidden',{},RuntimeError('private-test-detail'))
    with monkeypatch.context() as patch:
        patch.setattr(Session,'commit',broken)
        with env['factory']() as s:
            with pytest.raises(OperationalError):jobs.save_batch(s,current,batch,[axis()],env['settings'])
    assert not rows(env)[2]


def test_disabled_cloud_and_per_document_consent(env):
    env['settings'].embedding_provider='dashscope'
    assert not run_once(env['factory'],env['settings'])
    assert env['client'].post(env['path']+'/embedding',json={'allow_cloud':True},headers=csrf_headers(env['client'])).status_code==503
    from pydantic import SecretStr
    env['settings'].embedding_cloud_enabled=True;env['settings'].embedding_api_key=SecretStr('test-only-not-real-key');env['settings'].embedding_model_revision='fixture-cloud'
    with env['factory']() as s:
        doc=s.get(Document,UUID(env['record']['id']))
        assert jobs.enqueue_if_enabled(s,doc,UUID(env['user']['id']),env['settings']) is None
    assert env['client'].post(env['path']+'/embedding',json={},headers=csrf_headers(env['client'])).status_code==409
    response=env['client'].post(env['path']+'/embedding',json={'allow_cloud':True},headers=csrf_headers(env['client']))
    assert response.status_code==202 and 'lease_token' not in response.text
    # No cloud Worker is run and no network provider is invoked in this test.


def test_max_attempts_and_deadline_recovery(env):
    current=claim(env)
    with env['engine'].begin() as c:c.execute(text("UPDATE embedding_jobs SET max_attempts=attempts,lease_expires_at=clock_timestamp()-interval '1 second'"))
    assert claim(env) is None and rows(env)[0].status=='index_failed'


def test_csrf_and_extra_fields(env):
    assert env['client'].post(env['path']+'/embedding',json={}).status_code==403
    assert env['client'].post(env['path']+'/embedding',json={'space_id':'forged'},headers=csrf_headers(env['client'])).status_code==422


def test_public_and_two_private_scopes_are_filtered_before_ranking(env):
    run_once(env['factory'],env['settings'])
    with client_for(env['settings']) as second,client_for(env['settings']) as admin:
        credentials,b=register(second);assert post(second,'login',credentials).status_code==200
        ac={'email':uuid4().hex+'@example.com','password':new_token()};create_admin(**ac,settings=env['settings'])
        assert post(admin,'login',ac).status_code==200
        kb_b=second.post('/api/v2/knowledge-bases',json={'name':uuid4().hex},headers=csrf_headers(second)).json()['knowledge_base']
        kb_public=admin.post('/api/v2/admin/knowledge-bases',json={'name':uuid4().hex},headers=csrf_headers(admin)).json()['knowledge_base']
        for client,kb in ((second,kb_b),(admin,kb_public)):
            base='/api/v2/knowledge-bases/'+kb['id']+'/documents'
            assert client.post(base,files={'file':('course.txt','合成课程'.encode(),'text/plain')},headers=csrf_headers(client)).status_code==201
            parse_once(env['factory'],env['settings']);run_once(env['factory'],env['settings'])
        with env['factory']() as s:
            for actor,kb in ((s.get(User,UUID(env['user']['id'])),env['kb']),(s.get(User,UUID(b['id'])),kb_b)):
                hits=exact_search(s,actor,[UUID(kb['id']),UUID(kb_public['id'])],QueryEmbedding(space_for(env['settings']).id,axis()),env['settings'])
                assert {h['knowledge_base_id'] for h in hits}=={UUID(kb['id']),UUID(kb_public['id'])}
            actor=s.scalar(select(User).where(User.email==ac['email']))
            hits=exact_search(s,actor,[UUID(kb_public['id'])],QueryEmbedding(space_for(env['settings']).id,axis()),env['settings'])
            assert {h['knowledge_base_id'] for h in hits}=={UUID(kb_public['id'])}


@pytest.mark.parametrize('values',[[0.]*1024,[1.]*1023,[float('nan')]*1024])
def test_database_vector_constraints(env,values):
    run_once(env['factory'],env['settings'])
    with env['engine'].connect() as c:
        from sqlalchemy.exc import DBAPIError
        with pytest.raises((DBAPIError,ValueError)):
            c.execute(text('UPDATE chunk_embeddings SET embedding=CAST(:vector AS vector)'),{'vector':'['+','.join(str(x) for x in values)+']'})
        c.rollback()


def test_global_api_concurrency_slot_is_cross_connection(env):
    from pydantic import SecretStr
    from backend.v2.services.embedding_provider import build_provider
    settings=env['settings'].model_copy(update={'embedding_provider':'dashscope','embedding_cloud_enabled':True,
        'embedding_api_key':SecretStr('test-only-key'),'embedding_model_revision':'fixture','embedding_request_retries':0})
    provider=build_provider(settings,env['engine'])
    called=[]
    provider.transport=lambda *_:called.append(1)
    with env['engine'].connect().execution_options(isolation_level='AUTOCOMMIT') as c:
        c.execute(text('SELECT pg_advisory_lock(174924,0)'))
        try:
            with pytest.raises(EmbeddingError) as error:provider.embed(['synthetic'],text_type='document',before_attempt=lambda:None)
            assert error.value.code=='embedding_busy' and not called
        finally:c.execute(text('SELECT pg_advisory_unlock(174924,0)'))


def test_queue_capacity_and_idempotent_reconciliation(env):
    env['settings'].embedding_queue_capacity=1
    other=upload(env,data='新增合成课程'.encode());parse_once(env['factory'],env['settings'])
    with env['factory']() as s:assert s.scalar(select(func.count()).select_from(EmbeddingJob))==1
    run_once(env['factory'],env['settings']);run_once(env['factory'],env['settings'])
    with env['factory']() as s:
        assert s.get(Document,UUID(other['id'])).status=='ready'
        assert s.scalar(select(func.count()).select_from(EmbeddingJob))==2


def test_retrieval_rechecks_user_activation(env):
    run_once(env['factory'],env['settings'])
    with env['factory']() as s:
        actor=s.get(User,UUID(env['user']['id']))
    with env['engine'].begin() as c:c.execute(text('UPDATE users SET is_active=false'))
    with pytest.raises(AuthError) as error:query(env,user=actor)
    assert error.value.status==401


def test_retrieval_refuses_a_mismatched_query_space(env):
    run_once(env['factory'],env['settings'])
    with env['factory']() as s:
        actor=s.get(User,UUID(env['user']['id']))
        with pytest.raises(EmbeddingError):exact_search(s,actor,[UUID(env['kb']['id'])],QueryEmbedding('other-space',axis()),env['settings'])
