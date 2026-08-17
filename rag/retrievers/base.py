"""
统一Retriever接口
"""
from abc import ABC, abstractmethod
from typing import List, Dict, Any


class BaseRetriever(ABC):
    """所有Retriever的基类"""

    @abstractmethod
    def retrieve(
            self,
            query: str,
            chunks: List[Dict],
            top_k: int = 3
    ) -> List[Dict]:
        """
        检索最相关的top_k个片段

        Returns:
            每个结果包含: chunk_id, text, chapter, section,
            source_file, page, content_type, score
        """
        pass

    @abstractmethod
    def get_name(self) -> str:
        """返回检索器名称"""
        pass