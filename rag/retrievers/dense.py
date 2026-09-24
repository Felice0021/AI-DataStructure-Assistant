"""Dense retriever with batched document embedding and persistent cache."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Dict, List, Sequence
from http import HTTPStatus

import dashscope
import numpy as np

from rag.config import (
    DEFAULT_TOP_K,
    EMBEDDING_BATCH_SIZE,
    EMBEDDING_DIMENSION,
    EMBEDDING_MODEL,
    RAG_CACHE_DIR,
)
from rag.retrievers.base import BaseRetriever


class DenseRetriever(BaseRetriever):
    """Cosine-similarity dense retriever.

    Document embeddings are generated in batches and stored as a compressed
    NumPy cache keyed by corpus content + embedding configuration. Query
    embeddings are still generated online for each query.
    """

    def __init__(
        self,
        *,
        batch_size: int = EMBEDDING_BATCH_SIZE,
        cache_dir: Path = RAG_CACHE_DIR,
    ) -> None:
        if batch_size <= 0:
            raise ValueError("batch_size 必须大于 0")

        self.embedding_model = EMBEDDING_MODEL
        self.embedding_dimension = EMBEDDING_DIMENSION
        self.batch_size = int(batch_size)
        self.cache_dir = Path(cache_dir)
        self._prepared_chunks_object_id: int | None = None

    def get_name(self) -> str:
        return "dense"

    def get_config(self) -> Dict:
        return {
            "retriever": self.get_name(),
            "embedding_model": self.embedding_model,
            "embedding_dimension": self.embedding_dimension,
            "batch_size": self.batch_size,
        }

    def _ensure_api_key(self) -> None:
        if getattr(dashscope, "api_key", None):
            return
        api_key = os.getenv("DASHSCOPE_API_KEY")
        if not api_key:
            raise RuntimeError("未设置 DASHSCOPE_API_KEY")
        dashscope.api_key = api_key

    def _embed_texts(
        self,
        texts: Sequence[str],
        text_type: str = "document",
    ) -> List[List[float]]:
        if not texts:
            return []

        self._ensure_api_key()
        all_embeddings: List[List[float]] = []

        for start in range(0, len(texts), self.batch_size):
            batch = list(texts[start : start + self.batch_size])
            response = dashscope.TextEmbedding.call(
                model=self.embedding_model,
                input=batch,
                dimension=self.embedding_dimension,
                text_type=text_type,
            )

            if response.status_code != HTTPStatus.OK:
                raise RuntimeError(
                    f"Embedding调用失败：{response.code} - {response.message}"
                )

            embeddings = sorted(
                response.output["embeddings"],
                key=lambda item: item["text_index"],
            )
            all_embeddings.extend(item["embedding"] for item in embeddings)

        return all_embeddings

    def _corpus_fingerprint(self, chunks: Sequence[Dict]) -> str:
        digest = hashlib.sha256()
        digest.update(self.embedding_model.encode("utf-8"))
        digest.update(str(self.embedding_dimension).encode("ascii"))

        for chunk in chunks:
            digest.update(str(chunk.get("chunk_id", "")).encode("utf-8"))
            digest.update(b"\0")
            digest.update(str(chunk.get("text", "")).encode("utf-8"))
            digest.update(b"\0")

        return digest.hexdigest()

    def _cache_path(self, chunks: Sequence[Dict]) -> Path:
        fingerprint = self._corpus_fingerprint(chunks)
        return self.cache_dir / f"dense_{fingerprint[:24]}.npz"

    @staticmethod
    def _has_valid_embeddings(chunks: Sequence[Dict], dimension: int) -> bool:
        if not chunks:
            return True
        for chunk in chunks:
            embedding = chunk.get("embedding")
            if embedding is None or len(embedding) != dimension:
                return False
        return True

    def _load_cache(self, chunks: Sequence[Dict], cache_path: Path) -> bool:
        if not cache_path.exists():
            return False

        try:
            with np.load(cache_path, allow_pickle=False) as cached:
                embeddings = cached["embeddings"]
                chunk_ids = cached["chunk_ids"].astype(str).tolist()
                model = str(cached["model"].item())
                dimension = int(cached["dimension"].item())
        except (OSError, ValueError, KeyError):
            return False

        expected_ids = [str(chunk.get("chunk_id", "")) for chunk in chunks]
        if (
            model != self.embedding_model
            or dimension != self.embedding_dimension
            or chunk_ids != expected_ids
            or embeddings.shape != (len(chunks), self.embedding_dimension)
        ):
            return False

        for chunk, embedding in zip(chunks, embeddings):
            chunk["embedding"] = embedding.astype(np.float32, copy=False)
        return True

    def _save_cache(self, chunks: Sequence[Dict], cache_path: Path) -> None:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        embeddings = np.asarray(
            [chunk["embedding"] for chunk in chunks],
            dtype=np.float32,
        )
        chunk_ids = np.asarray(
            [str(chunk.get("chunk_id", "")) for chunk in chunks],
            dtype=str,
        )

        np.savez_compressed(
            cache_path,
            embeddings=embeddings,
            chunk_ids=chunk_ids,
            model=np.asarray(self.embedding_model),
            dimension=np.asarray(self.embedding_dimension, dtype=np.int32),
        )

    def prepare(
        self,
        chunks: Sequence[Dict],
        *,
        use_cache: bool = True,
    ) -> None:
        if not chunks:
            return
        if self._prepared_chunks_object_id == id(chunks):
            return
        if self._has_valid_embeddings(chunks, self.embedding_dimension):
            self._prepared_chunks_object_id = id(chunks)
            return

        cache_path = self._cache_path(chunks)
        if use_cache and self._load_cache(chunks, cache_path):
            self._prepared_chunks_object_id = id(chunks)
            return

        texts = [str(chunk.get("text", "")) for chunk in chunks]
        embeddings = self._embed_texts(texts, text_type="document")
        if len(embeddings) != len(chunks):
            raise RuntimeError(
                f"Embedding数量不匹配：expected={len(chunks)}, got={len(embeddings)}"
            )

        for chunk, embedding in zip(chunks, embeddings):
            if len(embedding) != self.embedding_dimension:
                raise RuntimeError(
                    f"Embedding维度不匹配：expected={self.embedding_dimension}, "
                    f"got={len(embedding)}"
                )
            chunk["embedding"] = np.asarray(embedding, dtype=np.float32)

        if use_cache:
            self._save_cache(chunks, cache_path)
        self._prepared_chunks_object_id = id(chunks)

    def retrieve_many(
        self,
        queries: Sequence[str],
        chunks: Sequence[Dict],
        top_k: int = DEFAULT_TOP_K,
    ) -> List[List[Dict]]:
        """Batch-retrieve multiple queries with one embedding API call."""
        cleaned = [(q or "").strip() for q in queries]

        if not cleaned:
            return []

        if top_k <= 0 or not chunks:
            return [[] for _ in cleaned]

        self.prepare(chunks, use_cache=True)

        nonempty_indices = [
            i for i, q in enumerate(cleaned)
            if q
        ]

        results: List[List[Dict]] = [
            [] for _ in cleaned
        ]

        if not nonempty_indices:
            return results

        active_queries = [
            cleaned[i]
            for i in nonempty_indices
        ]

        query_embeddings = np.asarray(
            self._embed_texts(
                active_queries,
                text_type="query",
            ),
            dtype=np.float32,
        )

        matrix = np.asarray(
            [chunk["embedding"] for chunk in chunks],
            dtype=np.float32,
        )

        doc_norms = np.linalg.norm(
            matrix,
            axis=1,
        )

        query_norms = np.linalg.norm(
            query_embeddings,
            axis=1,
        )

        numerators = query_embeddings @ matrix.T
        denominators = (
            query_norms[:, None]
            * doc_norms[None, :]
        )

        similarities = np.divide(
            numerators,
            denominators,
            out=np.zeros_like(
                numerators,
                dtype=np.float32,
            ),
            where=denominators != 0,
        )

        limit = min(top_k, len(chunks))

        for row_index, original_index in enumerate(
            nonempty_indices
        ):
            row = similarities[row_index]

            order = np.argsort(
                -row,
                kind="stable",
            )[:limit]

            query_results: List[Dict] = []

            for index in order:
                chunk = chunks[int(index)]

                query_results.append(
                    {
                        "score": float(row[int(index)]),
                        "chunk_id": chunk.get(
                            "chunk_id",
                            "unknown",
                        ),
                        "text": chunk.get(
                            "text",
                            "",
                        ),
                        "chapter": chunk.get(
                            "chapter",
                            "",
                        ),
                        "section": chunk.get(
                            "section",
                            "",
                        ),
                        "source_file": chunk.get(
                            "source_file",
                            "",
                        ),
                        "page": chunk.get("page"),
                        "content_type": chunk.get(
                            "content_type",
                            "other",
                        ),
                    }
                )

            results[original_index] = (
                query_results
            )

        return results

    def retrieve(
        self,
        query: str,
        chunks: Sequence[Dict],
        top_k: int = DEFAULT_TOP_K,
    ) -> List[Dict]:
        results = self.retrieve_many(
            [query],
            chunks,
            top_k=top_k,
        )
        return results[0] if results else []
