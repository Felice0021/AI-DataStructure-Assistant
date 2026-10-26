"""Optional real container sandbox checks; never cloud."""
import hashlib,os
from io import BytesIO
from types import SimpleNamespace
import pytest
from backend.v2.core.config import Settings
from backend.v2.services.parser_runner import parse_source
from backend.v2.tests.ingestion_samples import text_pdf,course_docx
from backend.v2.tests.document_samples import DOCX_MIME

pytestmark=pytest.mark.skipif(os.environ.get('DS_V2_RUN_DOCKER_TESTS')!='1',reason='Explicit prebuilt parser image test')


@pytest.mark.parametrize('data,mime,needle',[(b'synthetic container text','text/plain','synthetic'),(text_pdf(),'application/pdf','Course Alpha'),(course_docx(),DOCX_MIME,'课程标题')])
def test_real_container_formats(tmp_path,data,mime,needle):
    s=Settings(_env_file=None,db_password='unit-only-not-real-password',file_storage_root=tmp_path/'objects',parser_backend='docker')
    claim=SimpleNamespace(mime_type=mime,sha256=hashlib.sha256(data).hexdigest(),storage_key='a'*64)
    chunks=parse_source(BytesIO(data),claim,s)
    assert needle in '\n'.join(c['content'] for c in chunks)
