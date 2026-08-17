"""
Dense Retriever - 基于向量相似度检索
"""
import numpy as np
from typing import List, Dict
from http import HTTPStatus

import dashscope

from rag.retrievers.base import BaseRetriever
from rag.config import (
    EMBEDDING_MODEL,
    EMBEDDING_DIMENSION,
    DEFAULT_TOP_K,
)


class DenseRetriever(BaseRetriever):
    """Dense Retriever"""

    def __init__(self):
        self.embedding_model = EMBEDDING_MODEL
        self.embedding_dimension = EMBEDDING_DIMENSION
        self.batch_size = 10

    def get_name(self) -> str:
        return "dense"

    def _embed_texts(self, texts: List[str], text_type: str = "document") -> List[List[float]]:
        all_embeddings = []

        for i in range(0, len(texts), self.batch_size):
            batch = texts[i:i + self.batch_size]

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

            embeddings = response.output["embeddings"]
            embeddings = sorted(embeddings, key=lambda x: x["text_index"])

            for item in embeddings:
                all_embeddings.append(item["embedding"])

        return all_embeddings

    def _cosine_similarity(self, a: List[float], b: List[float]) -> float:
        vec_a = np.array(a)
        vec_b = np.array(b)
        norm_a = np.linalg.norm(vec_a)
        norm_b = np.linalg.norm(vec_b)
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return float(np.dot(vec_a, vec_b) / (norm_a * norm_b))

    def retrieve(
            self,
            query: str,
            chunks: List[Dict],
            top_k: int = DEFAULT_TOP_K
    ) -> List[Dict]:
        if not chunks:
            return []

        query_embedding = self._embed_texts([query], text_type="query")[0]

        scored_chunks = []
        for chunk in chunks:
            if "embedding" not in chunk:
                chunk["embedding"] = self._embed_texts(
                    [chunk["text"]],
                    text_type="document"
                )[0]

            score = self._cosine_similarity(query_embedding, chunk["embedding"])

            scored_chunks.append({
                "score": score,
                "chunk_id": chunk.get("chunk_id", "unknown"),
                "text": chunk.get("text", ""),
                "chapter": chunk.get("chapter", ""),
                "section": chunk.get("section", ""),
                "source_file": chunk.get("source_file", ""),
                "page": chunk.get("page"),
                "content_type": chunk.get("content_type", "other"),
            })

        scored_chunks.sort(key=lambda x: x["score"], reverse=True)
        return scored_chunks[:top_k]