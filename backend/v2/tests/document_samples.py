"""Synthetic in-memory fixtures only; never real user uploads."""
from io import BytesIO
from zipfile import ZipFile, ZIP_DEFLATED

def _pdf():
    objects = [b"<< /Type /Catalog /Pages 2 0 R >>",
               b"<< /Type /Pages /Count 1 /Kids [3 0 R] >>",
               b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R >>",
               b"<< /Length 0 >>\nstream\n\nendstream"]
    output = bytearray(b"%PDF-1.7\n")
    offsets = [0]
    for index, data in enumerate(objects, 1):
        offsets.append(len(output))
        output.extend(f"{index} 0 obj\n".encode() + data + b"\nendobj\n")
    xref = len(output)
    output.extend(b"xref\n0 5\n0000000000 65535 f \n")
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode())
    output.extend(f"trailer\n<< /Size 5 /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    return bytes(output)


PDF = _pdf()
TXT = "数据结构 UTF-8\n".encode()
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def docx(entries=None):
    output = BytesIO()
    default = {
        "[Content_Types].xml": b'<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>',
        "_rels/.rels": b'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>',
        "word/document.xml": b'<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p/></w:body></w:document>',
    }
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        for name, data in (default if entries is None else entries).items():
            archive.writestr(name, data)
    return output.getvalue()
