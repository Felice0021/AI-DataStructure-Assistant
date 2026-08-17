from pydantic_settings import BaseSettings
from pathlib import Path


class Settings(BaseSettings):
    host: str = "127.0.0.1"
    port: int = 8000
    version: str = "1.0.0"

    # 知识库配置
    knowledge_file: str = "knowledge_base/ds_chunks.jsonl"

    # RAG 配置
    rag_top_k: int = 3
    rag_use_cache: bool = True

    class Config:
        extra = "ignore"


def get_settings():
    return Settings()