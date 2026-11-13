"""Reference HTTP checks use real isolated DB; oracle output is not AI-quality evidence."""
import json
import os
from uuid import UUID

import pytest
from sqlalchemy import select
from backend.v2.models import DocumentChunk
from backend.v2.services.generation_provider import Completion
from backend.v2.tests.test_problem_solving import CASES
from backend.v2.tests.test_ingestion import setup, upload
from backend.v2.tests.test_auth import csrf_headers
from backend.v2.worker import run_once as parse_once
from backend.v2.embedding_worker import run_once as index_once

pytestmark=[pytest.mark.integration,pytest.mark.skipif(os.getenv('DS_V2_RUN_DB_TESTS')!='1',reason='Isolated PostgreSQL')]

@pytest.mark.parametrize('case',CASES,ids=[c['id'] for c in CASES])
def test_problem_http_reference_and_refusal(setup,case,monkeypatch):
    e=setup;s=e['settings'];s.embedding_provider='deterministic';s.embedding_allow_test_provider=True
    record=upload(e,name=case['id']+'.txt',data=case['lesson'].encode())
    assert parse_once(e['factory'],s) and index_once(e['factory'],s)
    calls=[]
    class Oracle:
        model='reference-oracle-not-real-model'
        def generate(self,messages,*,before_attempt):
            before_attempt();calls.append(messages)
            blocks=json.loads(messages[2]['content'])['blocks']
            block=next(b for b in blocks if case['lesson'] in b['content'])
            return Completion(json.dumps({'status':'answered','answer':case['reference_answer']+' '+block['citation_id'],
                                          'used_source_ids':[block['citation_id']]},ensure_ascii=False))
    monkeypatch.setattr('backend.v2.services.rag_service.build_provider',lambda *a,**kw:Oracle())
    c=e['client'];response=c.post('/api/v2/rag/ask',json={'query':case['query'],'knowledge_base_ids':[e['kb']['id']],
        'retrieval_mode':'bm25','rerank':'off'},headers=csrf_headers(c))
    assert response.status_code==200,response.text
    body=response.json()
    if case['expected_reason']:
        assert body['status']=='insufficient_evidence' and body['reason']==case['expected_reason']
        assert body['sources']==[] and calls==[]
    else:
        assert body['status']=='answered'
        source=body['sources'][0]
        assert body['answer']==case['reference_answer']+' '+source['citation_id']
        assert source['document_id']==record['id'] and source['knowledge_base_id']==e['kb']['id']
        with e['factory']() as db:
            assert case['lesson'] in db.get(DocumentChunk,UUID(source['chunk_id'])).content
