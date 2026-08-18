"""Common retrieval interface used by all experiment baselines."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Sequence


class BaseRetriever(ABC):
    """Base class for retrievers used by the RAG system and experiments."""

    def prepare(self, chunks: Sequence[Dict], **kwargs: Any) -> None:
        """Optionally build/load an index before retrieval.

        Stateless retrievers may keep the default no-op implementation.
        """

    @abstractmethod
    def retrieve(
        self,
        query: str,
        chunks: Sequence[Dict],
        top_k: int = 3,
    ) -> List[Dict]:
        """Return ranked chunks with a numeric ``score`` field."""
        raise NotImplementedError

    @abstractmethod
    def get_name(self) -> str:
        """Return a stable retriever identifier used in experiment configs."""
        raise NotImplementedError

    def get_config(self) -> Dict[str, Any]:
        return {"retriever": self.get_name()}
