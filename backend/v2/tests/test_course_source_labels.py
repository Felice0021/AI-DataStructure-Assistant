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


def test_v1_import_legacy_pages_are_not_verified_locations():
    row = {'chunk_id': uuid4(), 'document_id': uuid4(), 'knowledge_base_id': uuid4(),
           'content_hash': 'a' * 64, 'source_filename': 'v1-course-chapter-09.txt',
           'section_title': 'V1:ds_ch09_0038', 'page_number': 1}
    entry = {k: str(row[k]) for k in ('document_id', 'knowledge_base_id', 'content_hash')}
    entry.update(source_file='教材.pdf', chapter='第九章 查找', section='B+树叶子链表', page=240)
    assert source_label(row, {}) == {'section_title': None, 'page_number': None}
    mapping = {str(row['chunk_id']): entry}
    assert source_label(row, mapping)['page_number'] is None
    entry.update(verified_printed_page=246, verified_section_title='9.2.2 B-树和B+树')
    assert source_label(row, mapping)['page_number'] == 246
    assert source_label(row, mapping)['section_title'] == '第九章 查找 · 9.2.2 B-树和B+树'
