import json
import pytest

from backend.v2.services.prompt_builder import model_evidence


@pytest.mark.parametrize('filename',['v1-course-01.txt','v1-course-chapter-03.txt'])
def test_v1_import_wrapper_is_not_sent_to_model(filename):
    metadata={'chunk_id':'v1-1','chapter':'1','section':'1.1','source_file':'course.pdf','page':None,'content_type':'concept'}
    content='# V1:v1-1\n'+json.dumps(metadata,ensure_ascii=False)+'\n原创示例：栈后进先出。\n'
    block={'citation_id':'[S1]','source':{'source_filename':filename,'chunk_id':'private-id'},'content':content}
    context={'context_text':json.dumps([block],ensure_ascii=False)}
    result=model_evidence(context)
    assert result==[{'citation_id':'[S1]','content':'原创示例：栈后进先出。\n'}]
    assert json.loads(context['context_text'])[0]==block


def test_other_documents_and_ordinary_json_are_preserved():
    content='# V1:example\n{"chunk_id":"code"}\n正文'
    blocks=[{'citation_id':'[S1]','source':{'source_filename':'other.txt'},'content':content},
            {'citation_id':'[S2]','source':{'source_filename':'v1-course-01.txt'},'content':'{"chunk_id":"code"}\n正文'}]
    assert model_evidence({'context_text':json.dumps(blocks)})==[
        {'citation_id':'[S1]','content':content},
        {'citation_id':'[S2]','content':'{"chunk_id":"code"}\n正文'}]


def test_metadata_only_block_is_not_sent():
    assert model_evidence({'context_text':json.dumps([{'citation_id':'[S1]','source':{'source_filename':'v1-course-01.txt'},'content':'# V1:abc\n'}])})==[]
