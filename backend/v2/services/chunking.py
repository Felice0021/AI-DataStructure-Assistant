"""Deterministic paragraph-first chunking; no model or tokenizer dependency."""
from dataclasses import dataclass
import hashlib
import re


class ParseFailure(Exception):
    def __init__(self, code, retryable=False):
        super().__init__(code)
        self.code, self.retryable = code, retryable


@dataclass(frozen=True)
class TextBlock:
    text: str
    page_number: int | None = None
    section_title: str | None = None
    kind: str = "paragraph"


def _units(text):
    lines, fenced, math = [], False, False
    for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        marker = line.strip()
        if marker.startswith("```") or marker.startswith("~~~"):
            fenced = not fenced
        if marker == "$$":
            math = not math
        if not marker and not fenced and not math:
            if lines:
                yield "\n".join(lines).strip()
                lines = []
        else:
            lines.append(line)
    if lines:
        yield "\n".join(lines).strip()


def chunk_blocks(blocks, *, size=1200, overlap=150, max_chunks=2000):
    if size < 1 or overlap < 0 or overlap >= size or max_chunks < 1:
        raise ValueError("Invalid chunk configuration")
    result, current, current_key, first, last = [], "", None, 0, 0

    def emit(content, key, begin, end):
        if not content.strip():
            return
        if len(result) >= max_chunks:
            raise ParseFailure("chunk_limit")
        result.append({"chunk_index": len(result), "content": content,
                       "content_hash": hashlib.sha256(content.encode("utf-8")).hexdigest(),
                       "page_number": key[0], "section_title": key[1],
                       "source_metadata": {"block_start": begin, "block_end": end}})

    for index, block in enumerate(blocks):
        text = block.text.replace("\x00", "\ufffd")
        if any(0xD800 <= ord(c) <= 0xDFFF for c in text):
            raise ParseFailure("invalid_text")
        key = (block.page_number, (block.section_title or "")[:300] or None)
        if current and key != current_key:
            emit(current, current_key, first, last)
            current = ""
        current_key = key
        for unit in _units(text):
            if not unit:
                continue
            if current and len(current) + 2 + len(unit) > size:
                emit(current, key, first, last)
                tail = current[-overlap:] if overlap else ""
                # Keep short code/formula blocks whole instead of splitting them to fit overlap.
                current = tail if len(tail) + 2 + len(unit) <= size and block.kind not in {"code", "formula"} and not unit.startswith(("```", "~~~", "$$")) else ""
                first = last
            while len(unit) > size:
                emit(unit[:size], key, index, index)
                unit = unit[size-overlap:]
            if not current:
                first = index
            current = (current + "\n\n" + unit) if current else unit
            last = index
    if current:
        emit(current, current_key, first, last)
    if not result:
        raise ParseFailure("no_text")
    return result
