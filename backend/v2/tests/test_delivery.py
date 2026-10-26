import json,os
from pathlib import Path
from uuid import UUID
import pytest
from sqlalchemy import select
from backend.v2.models import User,Document,DocumentChunk
from backend.v2.tools.import_course import prepare,apply
from backend.v2.evaluation.score import evaluate
from backend.v2.tests.test_ingestion import setup
from backend.v2.tests.test_retrieval import env
from backend.v2.tests.test_auth import csrf_headers
from backend.v2.worker import run_once


def test_no_unreviewed_quality_numbers():
    assert evaluate([{'id':'x','annotation_status':'pending'}],[{'id':'x'}])['quality_metrics']=={}


def test_reviewed_metric_formula():
    case={'id':'x','annotation_status':'human_approved','reviewer':'synthetic-unit-review','reviewed_at':'2026-10-26',
          'evidence_sufficient':True,'relevance':{'a':2,'b':1}}
    result=evaluate([case],[{'id':'x','retrieved_chunk_ids':['z','a','b'],'refused':False}])
    assert result['quality_metrics']['recall_at_5']==1 and result['quality_metrics']['mrr_at_10']==.5


@pytest.mark.skipif(os.environ.get('DS_V2_RUN_DB_TESTS')!='1',reason='Isolated DB')
def test_import_admin_idempotent_and_genuine_parsed_text(env,tmp_path):
    source=tmp_path/'synthetic.jsonl'
    source.write_text(json.dumps({'chunk_id':'synthetic_001','text':'AVL树是平衡二叉搜索树。','chapter':'合成章','section':'合成节','source_file':'synthetic.pdf','page':3,'content_type':'concept'},ensure_ascii=False)+'\n')
    original=source.read_bytes();data,manifest=prepare(source);assert manifest['source_records']==1
    with env['factory']() as db:
        user=db.get(User,UUID(env['user']['id']));user.role='admin';db.commit()
    response=env['client'].post('/api/v2/admin/knowledge-bases',json={'name':'synthetic-import'},headers=csrf_headers(env['client']))
    assert response.status_code==201;kb=UUID(response.json()['knowledge_base']['id'])
    s=env['settings'].model_copy(update={'embedding_provider':'disabled'})
    with env['factory']() as db:
        record,created,_=apply(db,db.get(User,UUID(env['user']['id'])),kb,source,s);identifier=record.id
        assert created and record.mime_type=='text/plain' and record.status=='uploaded'
    with env['factory']() as db:
        second,created,_=apply(db,db.get(User,UUID(env['user']['id'])),kb,source,s)
        assert second.id==identifier and not created
    # Existing parsed fixture has no pending parse job, so the import job is claimed next.
    run_once(env['factory'],s)
    with env['factory']() as db:
        assert db.get(Document,identifier).status=='parsed'
        chunks=db.scalars(select(DocumentChunk).where(DocumentChunk.document_id==identifier)).all()
        assert chunks and chunks[0].section_title=='V1:synthetic_001'
        assert 'synthetic.pdf' in chunks[0].content and 'AVL树' in chunks[0].content
    assert source.read_bytes()==original


def test_deterministic_outputs_never_become_quality_metrics():
    case={'id':'x','annotation_status':'human_approved','reviewer':'synthetic-unit-review',
          'reviewed_at':'2026-10-26','evidence_sufficient':True,'relevance':{'a':1}}
    result=evaluate([case],[{'id':'x','provider_kind':'deterministic','retrieved_chunk_ids':['a'],'refused':False}])
    assert result['quality_metrics']=={} and result['evaluated_cases']==0


def test_frozen_openapi_matches_runtime_and_safe_default():
    from backend.v2.tools.export_openapi import schema
    from backend.v2.core.config import REPOSITORY_ROOT,Settings
    assert json.loads((REPOSITORY_ROOT/'docs/v2/openapi.json').read_text())==schema()
    settings=Settings(_env_file=None,db_password='synthetic-only-password')
    assert settings.generation_model=='qwen3.8-flash'
    assert not any((settings.embedding_cloud_enabled,settings.rerank_cloud_enabled,settings.generation_cloud_enabled))
