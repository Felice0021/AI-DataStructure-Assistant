import json
from uuid import uuid4
from backend.v2.services.course_source_labels import read_mapping, source_label


def test_mapping_requires_exact_authorized_chunk_and_hash(tmp_path):
    row={'chunk_id':uuid4(),'document_id':uuid4(),'knowledge_base_id':uuid4(),'content_hash':'a'*64}
    entry={k:str(row[k]) for k in ('document_id','knowledge_base_id','content_hash')}
    entry.update(source_file='课程资料.pdf',chapter='第三章 栈和队列',section='栈',page=None)
    path=tmp_path/'mapping.json';path.write_text(json.dumps({str(row['chunk_id']):entry},ensure_ascii=False))
    labels=read_mapping(path)
    assert source_label(row,labels)=={'source_filename':'课程资料.pdf','section_title':'第三章 栈和队列 · 栈','page_number':None}
    assert source_label({**row,'content_hash':'b'*64},labels)=={}
    assert source_label({**row,'knowledge_base_id':uuid4()},labels)=={}
    assert source_label({**row,'document_id':uuid4()},labels)=={}
    assert source_label({**row,'chunk_id':uuid4()},labels)=={}


def test_unreadable_invalid_or_unsafe_mapping_falls_back(tmp_path):
    assert read_mapping(tmp_path/'missing')=={}
    path=tmp_path/'invalid';path.write_text('{')
    assert read_mapping(path)=={}
    row={'chunk_id':uuid4(),'document_id':uuid4(),'knowledge_base_id':uuid4(),'content_hash':'a'*64}
    entry={k:str(row[k]) for k in ('document_id','knowledge_base_id','content_hash')}
    entry.update(source_file='bad\nname',chapter='',section='',page=3)
    assert source_label(row,{str(row['chunk_id']):entry})=={}
