from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Sequence

from rag.config import KNOWLEDGE_BASE_PATH
from rag.retrievers.base import BaseRetriever


Tokenizer = Callable[[str], List[str]]
_TOKEN_RE = re.compile(r"[\u4e00-\u9fff]+|[a-zA-Z_][a-zA-Z0-9_]*|\d+(?:\.\d+)?")


def jieba_tokenize(text: str) -> List[str]:
    """Tokenize Chinese/English mixed text for BM25."""
    try:
        import jieba
    except ImportError as exc:
        raise RuntimeError("BM25 中文分词需要 jieba。请先执行：pip install jieba") from exc

    tokens: List[str] = []
    for raw_token in jieba.lcut(text or "", cut_all=False):
        raw_token = raw_token.strip().lower()
        if raw_token:
            tokens.extend(piece.lower() for piece in _TOKEN_RE.findall(raw_token))
    return tokens


def load_chunks_from_jsonl(file_path: Path = KNOWLEDGE_BASE_PATH) -> List[Dict]:
    """Load the shared seven-field JSONL chunk schema."""
    required_fields = {
        "chunk_id", "text", "chapter", "section",
        "source_file", "page", "content_type",
    }
    path = Path(file_path)
    if not path.exists():
        raise RuntimeError(f"知识库文件不存在：{path}")

    chunks: List[Dict] = []
    seen_chunk_ids = set()
    with path.open("r", encoding="utf-8") as file:
        for line_number, raw_line in enumerate(file, start=1):
            line = raw_line.strip()
            if not line:
                continue
            try:
                chunk = json.loads(line)
            except json.JSONDecodeError as exc:
                raise RuntimeError(f"JSONL 第 {line_number} 行格式错误：{exc}") from exc

            missing = required_fields - chunk.keys()
            if missing:
                raise RuntimeError(
                    f"JSONL 第 {line_number} 行缺少字段：{', '.join(sorted(missing))}"
                )
            chunk_id = chunk["chunk_id"]
            if chunk_id in seen_chunk_ids:
                raise RuntimeError(f"发现重复 chunk_id：{chunk_id}")
            if not str(chunk["text"]).strip():
                raise RuntimeError(f"chunk {chunk_id} 的 text 不能为空")
            seen_chunk_ids.add(chunk_id)
            chunks.append(chunk)

    if not chunks:
        raise RuntimeError(f"知识库为空：{path}")
    return chunks


class BM25Retriever(BaseRetriever):
    """Okapi BM25 lexical retrieval baseline.

    The constructor still accepts ``chunks`` for backward compatibility, while
    the common experiment interface is ``retrieve(query, chunks, top_k)``.
    """

    def __init__(
        self,
        chunks: Sequence[Dict] | None = None,
        *,
        k1: float = 1.5,
        b: float = 0.75,
        tokenizer: Tokenizer = jieba_tokenize,
    ) -> None:
        if k1 <= 0:
            raise ValueError("k1 必须大于 0")
        if not 0 <= b <= 1:
            raise ValueError("b 必须位于 [0, 1]")

        self.k1 = float(k1)
        self.b = float(b)
        self.tokenizer = tokenizer
        self.chunks: List[Dict] = []
        self._term_freqs: List[Counter[str]] = []
        self._doc_lengths: List[int] = []
        self._idf: Dict[str, float] = {}
        self.document_count = 0
        self.avg_doc_length = 0.0
        self._index_fingerprint: str | None = None
        self._prepared_chunks_object_id: int | None = None

        if chunks is not None:
            self.prepare(chunks)

    def get_name(self) -> str:
        return "bm25"

    @staticmethod
    def _fingerprint(chunks: Sequence[Dict]) -> str:
        digest = hashlib.sha256()
        for chunk in chunks:
            digest.update(str(chunk.get("chunk_id", "")).encode("utf-8"))
            digest.update(b"\0")
            digest.update(str(chunk.get("text", "")).encode("utf-8"))
            digest.update(b"\0")
        return digest.hexdigest()

    def prepare(self, chunks: Sequence[Dict], **_: object) -> None:
        if not chunks:
            raise ValueError("chunks 不能为空")
        if self._prepared_chunks_object_id == id(chunks):
            return

        fingerprint = self._fingerprint(chunks)
        if fingerprint == self._index_fingerprint:
            self._prepared_chunks_object_id = id(chunks)
            return

        self.chunks = [dict(chunk) for chunk in chunks]
        self._term_freqs = []
        self._doc_lengths = []
        document_frequency: Counter[str] = Counter()

        for chunk in self.chunks:
            tokens = self.tokenizer(str(chunk.get("text", "")))
            term_freq = Counter(tokens)
            self._term_freqs.append(term_freq)
            self._doc_lengths.append(len(tokens))
            document_frequency.update(term_freq.keys())

        self.document_count = len(self.chunks)
        self.avg_doc_length = sum(self._doc_lengths) / self.document_count
        self._idf = {
            term: math.log(
                1.0 + (self.document_count - doc_freq + 0.5) / (doc_freq + 0.5)
            )
            for term, doc_freq in document_frequency.items()
        }
        self._index_fingerprint = fingerprint
        self._prepared_chunks_object_id = id(chunks)

    @classmethod
    def from_jsonl(
        cls,
        file_path: Path = KNOWLEDGE_BASE_PATH,
        *,
        k1: float = 1.5,
        b: float = 0.75,
        tokenizer: Tokenizer = jieba_tokenize,
    ) -> "BM25Retriever":
        return cls(
            load_chunks_from_jsonl(file_path),
            k1=k1,
            b=b,
            tokenizer=tokenizer,
        )

    def _score_document(self, query_tokens: Iterable[str], doc_index: int) -> float:
        term_freq = self._term_freqs[doc_index]
        doc_length = self._doc_lengths[doc_index]
        if self.avg_doc_length == 0:
            return 0.0

        length_norm = self.k1 * (
            1.0 - self.b + self.b * doc_length / self.avg_doc_length
        )
        score = 0.0
        for term in query_tokens:
            tf = term_freq.get(term, 0)
            if tf == 0:
                continue
            idf = self._idf.get(term)
            if idf is not None:
                score += idf * (tf * (self.k1 + 1.0) / (tf + length_norm))
        return score

    def retrieve(
        self,
        query: str,
        chunks: Sequence[Dict] | None = None,
        top_k: int = 3,
    ) -> List[Dict]:
        query = (query or "").strip()
        if not query or top_k <= 0:
            return []

        if chunks is not None:
            self.prepare(chunks)
        elif not self.chunks:
            raise ValueError("BM25 尚未建立索引，请传入 chunks 或在构造时提供 chunks")

        query_tokens = self.tokenizer(query)
        if not query_tokens:
            return []

        scored = [
            (self._score_document(query_tokens, index), index)
            for index in range(self.document_count)
        ]
        scored.sort(key=lambda item: (-item[0], item[1]))

        results: List[Dict] = []
        for score, index in scored[: min(top_k, self.document_count)]:
            item = dict(self.chunks[index])
            item.pop("embedding", None)
            item["score"] = float(score)
            results.append(item)
        return results

    def get_config(self) -> Dict[str, float | str]:
        return {
            "retriever": self.get_name(),
            "tokenizer": getattr(self.tokenizer, "__name__", "custom"),
            "k1": self.k1,
            "b": self.b,
        }
