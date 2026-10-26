from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from uuid import UUID, uuid4
import math
import os

import pytest
from sqlalchemy import select, text
from backend.v2.core.errors import AuthError
from backend.v2.embedding_worker import run_once as index_once
from backend.v2.models import User, Document
from backend.v2.schemas.retrieval import SearchRequest
from backend.v2.services.lexical_search import tokenize, bm25
from backend.v2.services.retrieval_service import search, fuse, capacity
from backend.v2.tests.test_auth import client_for, register, post, csrf_headers
from backend.v2.tests.test_ingestion import setup, upload
from backend.v2.worker import run_once as parse_once


def test_mixed_terms():
    words=tokenize('B 树 红黑树 AVL Dijkstra insert_node 1024')
    assert {'btree','红黑树','avl','dijkstra','insert_node','1024'}<=set(words)
    assert tokenize('的 和 与 the and')==[]


def test_bm25_formula_and_no_match():
    settings=SimpleNamespace(retrieval_bm25_k1=1.5,retrieval_bm25_b=.75,retrieval_max_corpus_tokens=100)
    rows=[{'chunk_id':'a','content':'AVL AVL'},{'chunk_id':'b','content':'graph'}]
    actual=bm25(['avl'],rows,settings)
    expected=math.log(1+(2-1+.5)/(1+.5))*2*2.5/(2+1.5*(.25+.75*2/1.5))
    assert actual==[('a',pytest.approx(expected))]
    assert bm25(['absent'],rows,settings)==[]


def test_rrf_numbers_dedup_ties():
    s=SimpleNamespace(retrieval_dense_weight=1,retrieval_bm25_weight=1,retrieval_rrf_k=60)
    result=fuse([('a',.8),('b',.7)],[('b',3),('a',2)],s)
    assert [r['chunk_id'] for r in result]==['a','b']
    assert all(r['fused_score']==pytest.approx(1/61+1/62) for r in result)
    assert result[0]['dense_score']==.8 and result[0]['bm25_rank']==2


integration=[pytest.mark.integration,pytest.mark.skipif(os.environ.get('DS_V2_RUN_DB_TESTS')!='1',reason='Isolated PostgreSQL')]

@pytest.fixture
def env(setup):
    s=setup['settings'];s.embedding_provider='deterministic';s.embedding_allow_test_provider=True
    record=upload(setup,data='# AVL\nAVL 红黑树 insert_node 算法。\n\n# 图\nDijkstra 最短路径 graph 1024。'.encode())
    parse_once(setup['factory'],s);index_once(setup['factory'],s)
    setup['record']=record
    return setup


def request(env,query='AVL',mode='hybrid',**kw):
    return SearchRequest(query=query,mode=mode,knowledge_base_ids=[UUID(env['kb']['id'])],**kw)


def run(env,**kw):
    return search(env['factory'],SimpleNamespace(id=UUID(env['user']['id'])),request(env,**kw),env['settings'])


@pytest.mark.parametrize('mode',['bm25','dense','hybrid'])
@pytest.mark.integration
@pytest.mark.skipif(os.environ.get('DS_V2_RUN_DB_TESTS')!='1',reason='Isolated PostgreSQL')
def test_real_modes(env,mode):
    result=run(env,mode=mode)
    assert result['actual_mode']==mode and result['degradation_reason'] is None and result['results']
    assert all(r['knowledge_base_id']==UUID(env['kb']['id']) for r in result['results'])
    assert run(env,mode=mode)['results']==result['results']
    if mode=='bm25':assert all(r['bm25_score']>0 and r['dense_score'] is None for r in result['results'])
    if mode=='dense':assert all(-1.0001<=r['dense_score']<=1.0001 for r in result['results'])
    if mode=='hybrid':assert all(r['fused_score']>0 for r in result['results'])


@pytest.mark.parametrize('query',['','  ','的 和 the','zzzznotpresent'])
@pytest.mark.integration
@pytest.mark.skipif(os.environ.get('DS_V2_RUN_DB_TESTS')!='1',reason='Isolated PostgreSQL')
def test_empty_stop_and_no_keyword(env,query):
    assert run(env,query=query,mode='bm25')['results']==[]


@pytest.mark.parametrize('limit,value',[('retrieval_max_query_chars',1),('retrieval_top_k',1),('retrieval_max_corpus_chunks',1),('retrieval_max_corpus_bytes',1),('retrieval_max_corpus_tokens',1)])
@pytest.mark.integration
@pytest.mark.skipif(os.environ.get('DS_V2_RUN_DB_TESTS')!='1',reason='Isolated PostgreSQL')
def test_limits(env,limit,value):
    setattr(env['settings'],limit,value)
    with pytest.raises(AuthError) as error:run(env,mode='bm25',top_k=2)
    assert error.value.status in {413,422}


@pytest.mark.parametrize('change',["UPDATE documents SET deleted_at=now()", "UPDATE documents SET status='processing',ingestion_version=ingestion_version+1,parsed_version=NULL,indexed_version=NULL", "UPDATE documents SET status='indexing'", "UPDATE documents SET status='index_failed'"])
@pytest.mark.integration
@pytest.mark.skipif(os.environ.get('DS_V2_RUN_DB_TESTS')!='1',reason='Isolated PostgreSQL')
def test_unpublished_and_deleted_hidden(env,change):
    with env['engine'].begin() as c:c.execute(text(change))
    for mode in ('bm25','dense','hybrid'):assert run(env,mode=mode)['results']==[]


@pytest.mark.integration
@pytest.mark.skipif(os.environ.get('DS_V2_RUN_DB_TESTS')!='1',reason='Isolated PostgreSQL')
def test_model_change_and_cloud_off(env):
    env['settings'].embedding_model_revision='new'
    assert run(env,mode='bm25')['results']==[]
    assert run(env,mode='dense')['results']==[]
    env['settings'].embedding_provider='disabled'
    with pytest.raises(AuthError) as err:run(env)
    assert err.value.code=='dense_unavailable'


@pytest.mark.integration
@pytest.mark.skipif(os.environ.get('DS_V2_RUN_DB_TESTS')!='1',reason='Isolated PostgreSQL')
def test_http_permissions_csrf_extra_and_limits(env):
    url='/api/v2/retrieval/search';data=request(env).model_dump(mode='json')
    client=env['client']
    r=client.post(url,json=data,headers=csrf_headers(client));assert r.status_code==200
    assert r.headers['cache-control']=='no-store'
    assert not {'storage_key','embedding','token_hash'} & r.json().keys()
    assert client.post(url,json=data).status_code==403
    assert client.post(url,json={**data,'user_id':env['user']['id']},headers=csrf_headers(client)).status_code==422
    assert client.post(url,json={**data,'top_k':101},headers=csrf_headers(client)).status_code==422
    with client_for(env['settings']) as other:
        credentials,_=register(other);assert post(other,'login',credentials).status_code==200
        assert other.post(url,json=data,headers=csrf_headers(other)).status_code==404
        data['knowledge_base_ids'].append(str(uuid4()))
        assert client.post(url,json=data,headers=csrf_headers(client)).status_code==404


@pytest.mark.integration
@pytest.mark.skipif(os.environ.get('DS_V2_RUN_DB_TESTS')!='1',reason='Isolated PostgreSQL')
def test_cross_process_capacity(env):
    with capacity(env['engine'],1):
        with pytest.raises(AuthError) as e:
            with capacity(env['engine'],1):pass
        assert e.value.code=='retrieval_busy'
    with capacity(env['engine'],1):pass


@pytest.mark.integration
@pytest.mark.skipif(os.environ.get('DS_V2_RUN_DB_TESTS')!='1',reason='Isolated PostgreSQL')
def test_final_recheck_after_query_embedding(env,monkeypatch):
    from backend.v2.services import retrieval_service as service
    actual=service.embed_query
    def changed(*a,**kw):
        result=actual(*a,**kw)
        with env['engine'].begin() as c:c.execute(text('UPDATE knowledge_bases SET deleted_at=now()'))
        return result
    monkeypatch.setattr(service,'embed_query',changed)
    with pytest.raises(AuthError) as e:run(env)
    assert e.value.status==404


@pytest.mark.integration
@pytest.mark.skipif(os.environ.get('DS_V2_RUN_DB_TESTS')!='1',reason='Isolated PostgreSQL')
def test_user_deactivated_after_embedding(env,monkeypatch):
    from backend.v2.services import retrieval_service as service
    actual=service.embed_query
    def changed(*a,**kw):
        result=actual(*a,**kw)
        with env['engine'].begin() as c:c.execute(text('UPDATE users SET is_active=false'))
        return result
    monkeypatch.setattr(service,'embed_query',changed)
    with pytest.raises(AuthError) as e:run(env)
    assert e.value.status==401


@pytest.mark.integration
@pytest.mark.skipif(os.environ.get('DS_V2_RUN_DB_TESTS')!='1',reason='Isolated PostgreSQL')
def test_deleted_kb_and_unknown_scope_even_empty_query(env):
    with env['engine'].begin() as c:c.execute(text('UPDATE knowledge_bases SET deleted_at=now()'))
    with pytest.raises(AuthError) as e:run(env,query='',mode='bm25')
    assert e.value.status==404


@pytest.mark.integration
@pytest.mark.skipif(os.environ.get('DS_V2_RUN_DB_TESTS')!='1',reason='Isolated PostgreSQL')
def test_database_connection_failure_safe_http(env):
    from backend.v2.main import create_app
    from fastapi.testclient import TestClient
    broken=env['settings'].model_copy(update={'db_port':1})
    with TestClient(create_app(broken),base_url='http://127.0.0.1:8001',client=('127.0.0.1',45000)) as client:
        client.cookies.update(env['client'].cookies)
        # Obtain CSRF before failure from the healthy app, not the broken database.
        r=client.post('/api/v2/retrieval/search',json=request(env).model_dump(mode='json'),headers=csrf_headers(env['client']))
        assert r.status_code==503 and r.json()['error']['code']=='service_unavailable'
        assert not any(x in r.text for x in ('password','psycopg','SELECT','Traceback'))


@pytest.mark.integration
@pytest.mark.skipif(os.environ.get('DS_V2_RUN_DB_TESTS')!='1',reason='Isolated PostgreSQL')
def test_scope_lock_blocks_deletion_until_snapshot_return(env,monkeypatch):
    from threading import Event
    from backend.v2.services import retrieval_service as service
    entered,attempted,finished=Event(),Event(),Event()
    actual=service.bm25
    def guarded(*a,**kw):
        entered.set();assert attempted.wait(5)
        assert not finished.wait(.1)
        return actual(*a,**kw)
    monkeypatch.setattr(service,'bm25',guarded)
    def deleting():
        assert entered.wait(5)
        with env['engine'].begin() as c:
            attempted.set()
            c.execute(text('SELECT id FROM knowledge_bases FOR UPDATE'))
            c.execute(text('UPDATE documents SET deleted_at=now()'))
        finished.set()
    with ThreadPoolExecutor(max_workers=2) as pool:
        pending=pool.submit(deleting)
        assert run(env,mode='bm25')['results']
        pending.result(timeout=5)
    monkeypatch.setattr(service,'bm25',actual)
    assert run(env,mode='bm25')['results']==[]
