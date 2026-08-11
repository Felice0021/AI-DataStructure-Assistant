from __future__ import annotations

import json
import math
import re
from collections import Counter
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Sequence

from rag.config import KNOWLEDGE_BASE_PATH


Tokenizer = Callable[[str], List[str]]
_TOKEN_RE = re.compile(r"[\u4e00-\u9fff]+|[a-zA-Z_][a-zA-Z0-9_]*|\d+(?:\.\d+)?")


def jieba_tokenize(text: str) -> List[str]:
    """Tokenize Chinese/English mixed text for BM25."""
    try:
        import jieba
    except ImportError as exc:
        raise RuntimeError(
            "BM25 中文分词需要 jieba。请先执行：pip install jieba"
        ) from exc

    tokens: List[str] = []

    for raw_token in jieba.lcut(text or "", cut_all=False):
        raw_token = raw_token.strip().lower()
        if not raw_token:
            continue

        tokens.extend(
            piece.lower()
            for piece in _TOKEN_RE.findall(raw_token)
        )

    return tokens


def load_chunks_from_jsonl(
    file_path: Path = KNOWLEDGE_BASE_PATH,
) -> List[Dict]:
    """Load shared RAG chunks without initializing embedding/LLM APIs."""
    required_fields = {
        "chunk_id",
        "text",
        "chapter",
        "section",
        "source_file",
        "page",
        "content_type",
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
                raise RuntimeError(
                    f"JSONL 第 {line_number} 行格式错误：{exc}"
                ) from exc

            missing = required_fields - chunk.keys()
            if missing:
                raise RuntimeError(
                    f"JSONL 第 {line_number} 行缺少字段："
                    f"{', '.join(sorted(missing))}"
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


class BM25Retriever:
    """Okapi BM25 retriever over the existing chunk schema.

    IDF:
        log(1 + (N - df + 0.5) / (df + 0.5))

    BM25:
        sum_t idf(t) * tf(t,D)*(k1+1) /
        (tf(t,D) + k1*(1-b+b*|D|/avgdl))

    Only chunk['text'] is indexed. Metadata is returned unchanged, making this
    a lexical retrieval baseline against the current dense retriever.
    """

    def __init__(
        self,
        chunks: Sequence[Dict],
        *,
        k1: float = 1.5,
        b: float = 0.75,
        tokenizer: Tokenizer = jieba_tokenize,
    ) -> None:
        if k1 <= 0:
            raise ValueError("k1 必须大于 0")
        if not 0 <= b <= 1:
            raise ValueError("b 必须位于 [0, 1]")
        if not chunks:
            raise ValueError("chunks 不能为空")

        self.k1 = float(k1)
        self.b = float(b)
        self.tokenizer = tokenizer
        self.chunks = [dict(chunk) for chunk in chunks]

        self._term_freqs: List[Counter[str]] = []
        self._doc_lengths: List[int] = []
        document_frequency: Counter[str] = Counter()

        for chunk in self.chunks:
            tokens = self.tokenizer(str(chunk.get("text", "")))
            term_freq = Counter(tokens)

            self._term_freqs.append(term_freq)
            self._doc_lengths.append(len(tokens))
            document_frequency.update(term_freq.keys())

        self.document_count = len(self.chunks)
        total_length = sum(self._doc_lengths)
        self.avg_doc_length = total_length / self.document_count

        self._idf = {
            term: math.log(
                1.0
                + (self.document_count - doc_freq + 0.5)
                / (doc_freq + 0.5)
            )
            for term, doc_freq in document_frequency.items()
        }

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

    def _score_document(
        self,
        query_tokens: Iterable[str],
        doc_index: int,
    ) -> float:
        term_freq = self._term_freqs[doc_index]
        doc_length = self._doc_lengths[doc_index]

        if self.avg_doc_length == 0:
            return 0.0

        length_norm = self.k1 * (
            1.0 - self.b
            + self.b * doc_length / self.avg_doc_length
        )

        score = 0.0

        for term in query_tokens:
            tf = term_freq.get(term, 0)
            if tf == 0:
                continue

            idf = self._idf.get(term)
            if idf is None:
                continue

            score += idf * (
                tf * (self.k1 + 1.0)
                / (tf + length_norm)
            )

        return score

    def retrieve(
        self,
        query: str,
        top_k: int = 3,
    ) -> List[Dict]:
        query = (query or "").strip()

        if not query or top_k <= 0:
            return []

        query_tokens = self.tokenizer(query)
        if not query_tokens:
            return []

        scored = [
            (
                self._score_document(query_tokens, index),
                index,
            )
            for index in range(self.document_count)
        ]

        scored.sort(key=lambda item: (-item[0], item[1]))

        results: List[Dict] = []

        for score, index in scored[: min(top_k, self.document_count)]:
            item = dict(self.chunks[index])
            item["score"] = float(score)
            results.append(item)

        return results

    def get_config(self) -> Dict[str, float | str]:
        return {
            "retriever": "bm25",
            "tokenizer": "jieba",
            "k1": self.k1,
            "b": self.b,
        }
