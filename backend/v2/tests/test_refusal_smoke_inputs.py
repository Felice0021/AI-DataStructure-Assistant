"""Read-only source selection must not quietly substitute fabricated course material."""
import hashlib
import json
from pathlib import Path
import pytest
from backend.v2.tools.refusal_context_smoke import documents


def test_course_selection_preserves_real_ids_prose_and_metadata_and_checks_sha(tmp_path):
    path=tmp_path/'course.jsonl'
    records=[{'chunk_id':'self_authored_avl','text':'AVL高度平衡。','chapter':'chapter-a','section':'section-a','source_file':'own-notes.txt','page':None,'content_type':'text'},
             {'chunk_id':'self_authored_other','text':'数组的存储。','chapter':'chapter-b','section':'section-b','source_file':'own-notes.txt','page':None,'content_type':'text'}]
    path.write_text('\n'.join(json.dumps(x,ensure_ascii=False) for x in records))
    before=path.read_bytes();digest=hashlib.sha256(before).hexdigest()
    files,manifest=documents('course',path,digest)
    assert manifest['source_records']==2 and manifest['selected_v1_ids']==['self_authored_avl']
    assert files[0][0]=='v1-course-chapter-01.txt'
    assert '# V1:self_authored_avl\n' in files[0][1].decode() and 'AVL高度平衡。' in files[0][1].decode()
    assert path.read_bytes()==before
    with pytest.raises(ValueError,match='course_source_hash_mismatch'):documents('course',path,'0'*64)
    path.write_text(json.dumps(records[1],ensure_ascii=False))
    with pytest.raises(ValueError,match='course_subset_empty'):documents('course',path,hashlib.sha256(path.read_bytes()).hexdigest())


def test_control_source_is_explicitly_labeled_not_course_data():
    files,manifest=documents('control',None,None)
    assert manifest['kind']=='self_authored_control'
    assert files[0][0]=='self-authored-rules.txt'
    assert 'Lomuto' in files[0][1].decode() and '红黑树' in files[0][1].decode()
