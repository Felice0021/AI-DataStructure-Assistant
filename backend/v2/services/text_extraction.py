"""Pure text extraction. Called only inside the restricted parser subprocess."""
import re
import zipfile

from backend.v2.services.chunking import ParseFailure, TextBlock
from backend.v2.services.file_validation import detect_file, MIME


def extract_text(source, mime, limits):
    blocks, total = [], 0

    def add(text, page=None, title=None, kind="paragraph"):
        nonlocal total
        text = text.replace("\x00", "\ufffd").strip()
        total += len(text)
        if total > limits["max_text_chars"]:
            raise ParseFailure("text_limit")
        if text:
            blocks.append(TextBlock(text, page, title, kind))

    if mime == "application/pdf":
        from pypdf import PdfReader
        reader = PdfReader(source, strict=True)
        if reader.is_encrypted:
            raise ParseFailure("encrypted_pdf")
        if len(reader.pages) > limits["max_pages"]:
            raise ParseFailure("page_limit")
        for number, page in enumerate(reader.pages, 1):
            add(page.extract_text() or "", page=number)
    elif mime == MIME[".docx"]:
        # Re-run upload structure checks against actual bytes before any XML/body inflation.
        source.seek(0)
        detect_file(source, "source.docx", mime)
        source.seek(0)
        with zipfile.ZipFile(source) as archive:
            # Validate actual decompression lengths/CRC, not just directory claims.
            expanded = 0
            for entry in archive.infolist():
                actual, xml_tail = 0, b""
                with archive.open(entry) as part:
                    while chunk := part.read(65536):
                        actual += len(chunk)
                        expanded += len(chunk)
                        if entry.filename.lower().endswith((".xml", ".rels")):
                            scan = (xml_tail + chunk).replace(b"\x00", b"").upper()
                            if b"<!DOCTYPE" in scan or b"<!ENTITY" in scan:
                                raise ParseFailure("unsafe_xml")
                            xml_tail = chunk[-64:]
                        if actual > min(entry.file_size, 32 * 1024 * 1024) or expanded > 64 * 1024 * 1024:
                            raise ParseFailure("archive_limit")
                if actual != entry.file_size:
                    raise ParseFailure("invalid_format")
        source.seek(0)
        from docx import Document
        from docx.table import Table
        from docx.text.paragraph import Paragraph
        document, title = Document(source), None
        for item in document.iter_inner_content():
            if isinstance(item, Paragraph):
                text = item.text
                style = item.style.name if item.style else ""
                if style.lower().startswith(("heading", "title")) or style.startswith("标题"):
                    title = text.strip()[:300] or title
                    add(text, title=title, kind="heading")
                else:
                    # OMML math text is not included by python-docx paragraph.text.
                    math = item._p.xpath('.//m:t')
                    if math:
                        text += "\n" + " ".join(n.text or "" for n in math)
                    if item._p.xpath('./w:pPr/w:numPr') or style.lower().startswith("list"):
                        text = "- " + text
                    add(text, title=title, kind="code" if "code" in style.lower() else "paragraph")
            elif isinstance(item, Table):
                for row in item.rows:
                    add(" | ".join(cell.text for cell in row.cells), title=title, kind="table")
    elif mime == "text/plain":
        import codecs
        decoder, parts = codecs.getincrementaldecoder("utf-8-sig")("strict"), []
        length = 0
        while chunk := source.read(65536):
            text = decoder.decode(chunk)
            length += len(text)
            if length > limits["max_text_chars"]:
                raise ParseFailure("text_limit")
            parts.append(text)
        parts.append(decoder.decode(b"", final=True))
        text, title = "".join(parts), None
        # Headings form structural boundaries; fences/formulas keep blank lines intact.
        pending, fenced, math = [], False, False
        for line in text.splitlines():
            stripped = line.strip()
            heading = not fenced and not math and (re.match(r"^#{1,6}\s+", stripped) or re.match(r"^第[一二三四五六七八九十百0-9]+[章节]", stripped))
            if heading and len(stripped) <= 300:
                if pending: add("\n".join(pending), title=title)
                pending, title = [line], stripped.lstrip("# ")
            else:
                pending.append(line)
            if stripped.startswith(("```", "~~~")): fenced = not fenced
            if stripped == "$$": math = not math
        if pending: add("\n".join(pending), title=title)
    else:
        raise ParseFailure("unsupported_type")
    if not blocks or not any(b.text.strip() for b in blocks):
        raise ParseFailure("no_text")
    return blocks
