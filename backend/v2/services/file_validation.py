"""Bounded structural checks, not document parsing or malware scanning."""
import codecs
from pathlib import PurePosixPath
import re
import struct
import zlib
import unicodedata
import zipfile
from xml.etree import ElementTree

from backend.v2.core.errors import AuthError

MIME = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".txt": "text/plain",
}


def invalid():
    return AuthError(422, "invalid_file", "Invalid or unsupported file")


def validate_filename(name: str) -> str:
    if (not name or len(name) > 255 or name in {".", ".."}
        or name != name.strip() or any(c in name for c in '/\\:')
        or any(unicodedata.category(c).startswith("C") for c in name)
        or len(name.encode("utf-8")) > 255
        or PurePosixPath(name).suffix.lower() not in MIME):
        raise invalid()
    return name


def _xml(data):
    # No DTD/entity expansion; metadata is capped before reading.
    if b"<!DOCTYPE" in data.upper() or b"<!ENTITY" in data.upper() or b"\x00" in data:
        raise invalid()
    return ElementTree.fromstring(data)


def _docx(source):
    # Check the bounded central-directory budget before ZipFile allocates ZipInfo objects.
    source.seek(0, 2)
    length = source.tell()
    source.seek(max(0, length - 65557))
    tail = source.read(65557)
    end = tail.rfind(b"PK\x05\x06")
    if end < 0 or len(tail) - end < 22:
        raise invalid()
    _, disk, directory_disk, disk_count, count, directory_size, directory_offset, comment = struct.unpack("<4s4H2LH", tail[end:end+22])
    if (disk or directory_disk or disk_count != count or not 3 <= count <= 256
        or directory_size > 256 * 1024 or directory_offset + directory_size != length - len(tail) + end
        or end + 22 + comment != len(tail)):
        raise invalid()
    source.seek(0)
    with zipfile.ZipFile(source) as archive:
        entries = archive.infolist()
        if not 3 <= len(entries) <= 256:
            raise invalid()
        names, total = set(), 0
        for entry in entries:
            name = entry.filename
            if (name in names or name.startswith("/") or "\\" in name
                or any(part in {".", ".."} for part in name.split("/"))
                or entry.flag_bits & 1 or (entry.external_attr >> 16) & 0o170000 == 0o120000
                or entry.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}
                or entry.file_size > 32 * 1024 * 1024
                or entry.file_size > max(1, entry.compress_size) * 200):
                raise invalid()
            names.add(name)
            total += entry.file_size
        if total > 64 * 1024 * 1024 or not {"[Content_Types].xml", "_rels/.rels", "word/document.xml"} <= names:
            raise invalid()
        if any(n.lower().endswith(("vbaproject.bin", ".exe", ".dll")) or n.lower().startswith(("word/embeddings/", "word/activex/")) for n in names):
            raise invalid()
        # Opening validates local headers and overlap boundaries without inflating payloads.
        # Only package metadata is decompressed below; document body stays opaque in 3B-1.
        for entry in entries:
            with archive.open(entry):
                pass
        if archive.getinfo("word/document.xml").file_size == 0:
            raise invalid()
        for name in ("[Content_Types].xml", "_rels/.rels"):
            if archive.getinfo(name).file_size > 256 * 1024:
                raise invalid()
        types = _xml(archive.read("[Content_Types].xml"))
        if types.tag != "{http://schemas.openxmlformats.org/package/2006/content-types}Types" or not any(
            e.attrib.get("PartName") == "/word/document.xml" and e.attrib.get("ContentType") == "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"
            for e in types
        ):
            raise invalid()
        rels = _xml(archive.read("_rels/.rels"))
        if rels.tag != "{http://schemas.openxmlformats.org/package/2006/relationships}Relationships" or not any(
            e.attrib.get("Type") == "http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument"
            and e.attrib.get("Target") in {"word/document.xml", "/word/document.xml"}
            and e.attrib.get("TargetMode", "Internal") == "Internal" for e in rels
        ):
            raise invalid()


def detect_file(source, filename: str, declared_type: str) -> str:
    validate_filename(filename)
    extension = PurePosixPath(filename).suffix.lower()
    mime = MIME[extension]
    declared = declared_type.split(";", 1)[0].strip().lower()
    if declared not in {mime, "application/octet-stream", ""}:
        raise invalid()
    try:
        if extension == ".pdf":
            header = source.read(16)
            source.seek(0, 2)
            length = source.tell()
            source.seek(max(0, length - 2048))
            tail = source.read(2048)
            if not re.match(rb"%PDF-(?:1\.[0-7]|2\.0)(?:\r|\n)", header) or not tail.rstrip().endswith(b"%%EOF"):
                raise invalid()
        elif extension == ".docx":
            if source.read(4) != b"PK\x03\x04":
                raise invalid()
            source.seek(0)
            _docx(source)
        else:
            prefix = source.read(8)
            if prefix.startswith((b"%PDF-", b"PK\x03\x04", b"MZ")):
                raise invalid()
            source.seek(0)
            decoder = codecs.getincrementaldecoder("utf-8-sig")("strict")
            has_text = False
            while chunk := source.read(64 * 1024):
                value = decoder.decode(chunk)
                if any(unicodedata.category(c) == "Cc" and c not in "\t\n\r" for c in value):
                    raise invalid()
                has_text |= bool(value.strip())
            decoder.decode(b"", final=True)
            if not has_text:
                raise invalid()
    except (zipfile.BadZipFile, zipfile.LargeZipFile, UnicodeError, ElementTree.ParseError, RuntimeError, NotImplementedError, ValueError, EOFError, zlib.error, struct.error):
        raise invalid() from None
    return mime
