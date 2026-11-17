"""Offline V1 course replay for the two tree questions reported failing online.

This checks the BM25/context path only; it does not claim to replay live Hybrid
embeddings, Qwen generation, or the production database.
"""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.v2.services.context_builder import build_context
from backend.v2.services.evidence_policy import preflight
from backend.v2.services.lexical_search import bm25, tokenize
from backend.v2.services.tree_rule_evidence import rule_supported,focused_rule_query
from backend.v2.services.verified_trees import calculate


@pytest.mark.parametrize('query',[
    '空AVL树，依次插入30,10,20，画出最终树。',
    '从一棵空 AVL 树开始，依次插入 30、10、20。请根据课程知识库中的 AVL 树规则，画出最终树形图，并说明是否发生旋转、旋转类型及过程。',
    '构造空BST树，依次插入40,20,30,70,60，画出最终树。',
])
def test_course_tree_rule_survives_bm25_and_context_limits(query):
    source=Path(__file__).resolve().parents[3]/'knowledge_base'/'ds_chunks.jsonl'
    original=[json.loads(line) for line in source.read_text().splitlines()]
    rows=[]
    for index,row in enumerate(original):
        metadata={key:row[key] for key in ('chunk_id','chapter','section','source_file','page','content_type')}
        rows.append({'chunk_id':row['chunk_id'], 'document_id':row['chapter'], 'knowledge_base_id':'course',
                     'source_filename':'v1-course-chapter.txt', 'page_number':row['page'],
                     'section_title':row['section'], 'chunk_index':index,
                     'content':'# V1:'+row['chunk_id']+'\n'+json.dumps(metadata,ensure_ascii=False)+'\n'+row['text']})
    settings=SimpleNamespace(retrieval_max_corpus_tokens=200000,retrieval_bm25_k1=1.5,
                             retrieval_bm25_b=.75,context_per_document=3,context_max_chunk_chars=8000)
    by_id={row['chunk_id']:row for row in rows}
    result,reason=calculate(query)
    assert reason is None and result is not None
    ranked=bm25(tokenize(focused_rule_query(query,result)),rows,settings)[:20]
    context=build_context([by_id[chunk_id] for chunk_id,_ in ranked],settings,
                          max_evidence=5,max_chars=12000,token_budget=4000)
    assert preflight(query,context['evidence']) is None
    assert any(rule_supported(result,row['content']).usable for row in context['evidence'])
    assert not any(rule_supported(result,row['content']).kind in {'conflict','unrecognized'}
                   for row in context['evidence'])
