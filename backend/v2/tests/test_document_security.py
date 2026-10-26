from io import BytesIO
import os
from pathlib import Path
import stat
import pytest

from backend.v2.core.config import REPOSITORY_ROOT, Settings
from backend.v2.core.errors import AuthError
from backend.v2.services.file_storage import LocalFileStorage
from backend.v2.services.file_validation import detect_file, validate_filename
from backend.v2.tests.document_samples import PDF, TXT, DOCX_MIME, docx


@pytest.mark.parametrize("name", ["../a.txt", "/etc/passwd.txt", "a/b.txt", "a\\b.txt", "C:a.txt", "a\r\n.txt", "a\x00.txt", "a\u202e.txt", "a\ud800.txt", " a.txt", "a.txt ", "a.exe", "x"*252+".txt", ""])
def test_unsafe_filename(name):
    with pytest.raises(AuthError): validate_filename(name)


@pytest.mark.parametrize("name,data,mime", [("ok.pdf",PDF,"application/pdf"), ("ok.docx",docx(),DOCX_MIME), ("ok.txt",TXT,"text/plain"), ("BOM.TXT",b"\xef\xbb\xbf"+TXT,"application/octet-stream")])
def test_format_acceptance(name, data, mime):
    assert detect_file(BytesIO(data), name, mime) in {"application/pdf", DOCX_MIME, "text/plain"}


@pytest.mark.parametrize("name,data,mime", [
    ("bad.pdf",TXT,"application/pdf"), ("bad.pdf",PDF,"text/plain"),
    ("bad.pdf",b"%PDF-1.7\ntruncated","application/pdf"),
    ("bad.docx",b"PK\x03\x04broken",DOCX_MIME),
    ("bad.docx",docx({"word/document.xml":b"invalid"}),DOCX_MIME),
    ("bad.docx",docx({"../evil":b"x", "word/document.xml":b"x", "[Content_Types].xml":b"x"}),DOCX_MIME),
    ("bad.txt",b"\xff\xfeinvalid","text/plain"), ("bad.txt",b"a\x00b","text/plain"),
    ("bad.txt",b"\xef\xbb\xbf","text/plain"),
])
def test_invalid_formats(name, data, mime):
    with pytest.raises(AuthError): detect_file(BytesIO(data), name, mime)


def test_zip_bomb_is_rejected():
    with pytest.raises(AuthError):
        detect_file(BytesIO(docx({"x":b"0"*1000000,"[Content_Types].xml":b"x","_rels/.rels":b"x"})),"x.docx",DOCX_MIME)


def test_storage_permissions_streaming_and_atomic_cleanup(tmp_path):
    root = tmp_path.resolve()/"private"
    storage = LocalFileStorage(root)
    class BoundedRead(BytesIO):
        def read(self, size=-1):
            assert 0 < size <= 65536
            return super().read(size)
    saved = storage.save(BoundedRead(TXT), 1000, "ok.txt", "text/plain")
    assert stat.S_IMODE(root.stat().st_mode) == 0o700
    assert stat.S_IMODE((root/saved.key).stat().st_mode) == 0o600
    with storage.open(saved.key, saved.size) as f: assert f.read() == TXT
    for data, limit in [(b"", 100), (TXT, 1), (b"invalid pdf", 100)]:
        with pytest.raises(AuthError): storage.save(BoundedRead(data), limit, "bad.pdf", "application/pdf")
    assert [p.name for p in root.iterdir()] == [saved.key]
    storage.remove(saved.key)
    assert not list(root.iterdir())


@pytest.mark.parametrize("component", ["root", "ancestor", "object"])
def test_symlink_escape_is_rejected(tmp_path, component):
    base = tmp_path.resolve()
    outside = base/"outside"; outside.mkdir(mode=0o700)
    (outside/"secret").write_bytes(b"untouched")
    if component == "root":
        root = base/"link"; root.symlink_to(outside, target_is_directory=True)
    elif component == "ancestor":
        (base/"link").symlink_to(outside, target_is_directory=True)
        root = base/"link"/"child"
    else:
        root=base/"private"; root.mkdir(mode=0o700)
        (root/("a"*64)).symlink_to(outside/"secret")
    with pytest.raises(OSError):
        if component=="object": LocalFileStorage(root).open("a"*64,9)
        else: LocalFileStorage(root).save(BytesIO(TXT),1000,"x.txt","text/plain")
    assert (outside/"secret").read_bytes()==b"untouched"
    assert not (outside/"child").exists()


def test_storage_root_must_be_outside_repo():
    with pytest.raises(ValueError): Settings(_env_file=None,db_password="not-a-real-test-password",file_storage_root=REPOSITORY_ROOT/"uploads")


def test_storage_rejects_forged_key(tmp_path):
    with pytest.raises(OSError): LocalFileStorage(tmp_path.resolve()).remove("../../secret")


def test_atomic_publish_failure_removes_temporary_file(tmp_path, monkeypatch):
    root = tmp_path.resolve()/"private"
    def broken(*args, **kwargs): raise OSError("simulated rename failure")
    monkeypatch.setattr("backend.v2.services.file_storage.os.rename", broken)
    with pytest.raises(OSError):
        LocalFileStorage(root).save(BytesIO(TXT), 1000, "x.txt", "text/plain")
    assert not list(root.iterdir())


@pytest.mark.parametrize("data", [PDF, docx()])
def test_text_extension_cannot_disguise_other_supported_types(data):
    with pytest.raises(AuthError): detect_file(BytesIO(data), "fake.txt", "text/plain")


def test_zip_central_directory_budget():
    data=docx({str(i):b"x" for i in range(257)})
    with pytest.raises(AuthError): detect_file(BytesIO(data),"many.docx",DOCX_MIME)


def test_corrupt_zip_crc_is_rejected():
    from zipfile import ZipFile, ZIP_STORED
    output=BytesIO()
    with ZipFile(BytesIO(docx())) as source, ZipFile(output,"w",ZIP_STORED) as target:
        for name in source.namelist(): target.writestr(name,source.read(name))
    data=output.getvalue().replace(b'<Types',b'<Xypes',1)
    with pytest.raises(AuthError): detect_file(BytesIO(data),"broken.docx",DOCX_MIME)


def test_docx_body_is_not_decompressed(monkeypatch):
    import zipfile
    original=zipfile.ZipExtFile.read
    def checked(self, *args, **kwargs):
        assert self.name != "word/document.xml"
        return original(self, *args, **kwargs)
    monkeypatch.setattr(zipfile.ZipExtFile,"read",checked)
    assert detect_file(BytesIO(docx()),"opaque.docx",DOCX_MIME)==DOCX_MIME
