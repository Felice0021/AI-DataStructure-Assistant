from io import BytesIO
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace

import pytest

from backend.v2.core.config import Settings
from backend.v2.services.chunking import ParseFailure, TextBlock, chunk_blocks
from backend.v2.services.file_storage import LocalFileStorage
from backend.v2.services.parser_runner import parse_source, run_restricted
from backend.v2.services.text_extraction import extract_text
from backend.v2.tests.document_samples import PDF, DOCX_MIME, docx
from backend.v2.tests.ingestion_samples import text_pdf, course_docx

LIMITS={"max_pages":300,"max_text_chars":10000}


def test_pdf_pages():
    blocks=extract_text(BytesIO(text_pdf()),"application/pdf",LIMITS)
    assert [b.page_number for b in blocks]==[1,2]
    assert "Course Alpha" in blocks[0].text and "Course Beta" in blocks[1].text


def test_docx_order_headings_table():
    blocks=extract_text(BytesIO(course_docx()),DOCX_MIME,LIMITS)
    text="\n".join(b.text for b in blocks)
    assert text.index("课程标题")<text.index("段落内容")<text.index("算法")<text.index("查找")
    assert any(b.kind=="table" and "O(log n)" in b.text for b in blocks)
    assert all(b.section_title=="课程标题" for b in blocks)


@pytest.mark.parametrize("prefix",[b"",b"\xef\xbb\xbf"])
def test_txt_chinese_bom(prefix):
    blocks=extract_text(BytesIO(prefix+"# 章节\n\n中文 α ∑\n\n- 项目".encode()),"text/plain",LIMITS)
    assert blocks[0].section_title=="章节" and "中文 α ∑" in blocks[0].text


@pytest.mark.parametrize("mime,data,code",[("text/plain",b"", "no_text"),("application/pdf",PDF,"no_text"),("text/plain",b"x"*20,"text_limit")])
def test_empty_scan_and_limits(mime,data,code):
    limits={**LIMITS,"max_text_chars":10} if code=="text_limit" else LIMITS
    with pytest.raises(ParseFailure) as error:extract_text(BytesIO(data),mime,limits)
    assert error.value.code==code


def test_pdf_page_limit():
    with pytest.raises(ParseFailure) as error:extract_text(BytesIO(text_pdf()),"application/pdf",{**LIMITS,"max_pages":1})
    assert error.value.code=="page_limit"


def test_chunk_boundaries_overlap_and_metadata():
    blocks=[TextBlock("a"*120,page_number=1,section_title="甲"),TextBlock("b"*20,page_number=2,section_title="乙")]
    chunks=chunk_blocks(blocks,size=50,overlap=10)
    assert [c["chunk_index"] for c in chunks]==list(range(len(chunks)))
    assert chunks[0]["content"][-10:]==chunks[1]["content"][:10]
    assert all(len(c["content"])<=50 for c in chunks)
    assert chunks[-1]["page_number"]==2 and chunks[-1]["section_title"]=="乙"
    assert chunks==chunk_blocks(blocks,size=50,overlap=10)


def test_code_and_formula_kept_whole_when_fit():
    code="```python\nprint(1)\n\nprint(2)\n```"
    formula="$$\nx + y = z\n\n\\sum x\n$$"
    chunks=chunk_blocks([TextBlock("a"*40+"\n\n"+code+"\n\n"+formula)],size=60,overlap=10)
    assert any(code in c["content"] for c in chunks)
    assert any(formula in c["content"] for c in chunks)


@pytest.mark.parametrize("text",["汉字"*1000,"α∑🙂"*400,"a"*1000])
def test_long_unicode_stable(text):
    result=chunk_blocks([TextBlock(text)],size=64,overlap=8,max_chunks=100)
    rebuilt=result[0]["content"]+"".join(c["content"][8:] for c in result[1:])
    assert rebuilt==text


def test_chunk_limits_and_empty():
    with pytest.raises(ParseFailure):chunk_blocks([TextBlock(" ")])
    with pytest.raises(ParseFailure):chunk_blocks([TextBlock("x"*1000)],size=20,overlap=2,max_chunks=1)


@pytest.mark.parametrize("name,data,mime",[("x.pdf",text_pdf(),"application/pdf"),("x.docx",course_docx(),DOCX_MIME),("x.txt",b"\xef\xbb\xbf"+"中文测试".encode(),"text/plain")])
def test_real_restricted_parser(tmp_path,name,data,mime):
    settings=Settings(file_storage_root=tmp_path.resolve()/"objects")
    storage=LocalFileStorage(settings.file_storage_root)
    saved=storage.save(BytesIO(data),100000,name,mime)
    claim=SimpleNamespace(mime_type=mime,sha256=saved.sha256,storage_key=saved.key)
    with storage.open(saved.key,saved.size) as source: result=parse_source(source,claim,settings)
    assert result and all(c["content"] for c in result)


def restricted_probe(tmp_path, code, *, timeout=3,memory=256):
    base=tmp_path.resolve()
    input_path=base/"input";input_path.write_bytes(b"synthetic")
    path=base/"result"
    with input_path.open("rb") as source,path.open("w+b") as output:
        run_restricted([sys.executable,"-I","-B","-c",code],source=source,input_path=input_path,output=output,output_path=path,
                       timeout=timeout,memory_mb=memory,output_limit=100000)
        output.seek(0)
        return output.read()


def test_real_sandbox_denies_network_secret_read_write_and_spawn(tmp_path):
    canary=tmp_path.resolve()/"private-canary";canary.write_bytes(b"test-only-value")
    code='''import json,os,socket,subprocess
checks={}
try: open(%s).read(); checks['read']=False
except OSError as error: checks['read']=error.errno in {1,13}
try: open(%s,'w').write('bad'); checks['write']=False
except OSError as error: checks['write']=error.errno in {1,13}
try:
 s=socket.socket();s.connect(('127.0.0.1',9));checks['network']=False
except OSError as error:checks['network']=error.errno in {1,13}
try:subprocess.run(['/usr/bin/true'],check=True);checks['spawn']=False
except OSError as error:checks['spawn']=error.errno in {1,13}
checks['input']=os.read(0,9)==b'synthetic'
checks['env']=not any(k.startswith('DS_V2_') for k in os.environ)
print(json.dumps(checks))
'''%(repr(str(canary)),repr(str(canary)))
    result=json.loads(restricted_probe(tmp_path,code))
    assert all(result.values()),result
    assert canary.read_bytes()==b"test-only-value"


def test_actual_timeout_kills_process(tmp_path):
    with pytest.raises(ParseFailure) as error:restricted_probe(tmp_path,"import time;time.sleep(10)",timeout=0.2)
    assert error.value.code=="parse_timeout"


def test_actual_rss_limit_kills_process(tmp_path):
    with pytest.raises(ParseFailure) as error:restricted_probe(tmp_path,"import time;data=bytearray(128*1024*1024);time.sleep(10)",memory=32)
    assert error.value.code=="memory_limit"
