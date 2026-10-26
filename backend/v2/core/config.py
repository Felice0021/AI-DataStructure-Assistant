from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="DS_V2_",
        env_file=REPOSITORY_ROOT / "deploy/v2/.env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    db_host: str = "127.0.0.1"
    db_port: int = Field(default=5433, ge=1, le=65535)
    db_name: str = "ds_assistant_v2"
    db_user: str = "ds_assistant_v2"
    db_password: SecretStr = Field(min_length=16)
    environment: Literal["production", "development"] = "production"
    allow_insecure_loopback: bool = False
    allowed_origins: list[str] = []
    session_ttl_seconds: int = Field(default=28800, ge=60, le=604800)
    login_max_failures: int = Field(default=5, ge=1, le=100)
    login_ip_max_failures: int = Field(default=20, ge=1, le=1000)
    login_window_seconds: int = Field(default=900, ge=1, le=86400)

    file_storage_root: Path = Field(default_factory=lambda: Path.home() / "Library/Application Support/AI-DataStructure-Assistant/v2/files")
    upload_max_bytes: int = Field(default=20 * 1024 * 1024, ge=1, le=100 * 1024 * 1024)
    documents_per_kb: int = Field(default=100, ge=1, le=10000)
    storage_bytes_per_kb: int = Field(default=1024 * 1024 * 1024, ge=1)
    storage_total_bytes: int = Field(default=10 * 1024 * 1024 * 1024, ge=1)
    upload_timeout_seconds: int = Field(default=120, ge=1, le=600)

    parse_max_pages: int = Field(default=300, ge=1, le=2000)
    parse_max_text_chars: int = Field(default=2_000_000, ge=1, le=10_000_000)
    parse_timeout_seconds: int = Field(default=30, ge=1, le=300)
    parse_memory_mb: int = Field(default=256, ge=64, le=2048)
    chunk_size: int = Field(default=1200, ge=32, le=8000)
    chunk_overlap: int = Field(default=150, ge=0)
    parse_max_chunks: int = Field(default=2000, ge=1, le=10000)
    ingestion_lease_seconds: int = Field(default=90, ge=20, le=1800)
    ingestion_max_attempts: int = Field(default=3, ge=1, le=10)
    ingestion_retry_seconds: int = Field(default=5, ge=1, le=3600)
    worker_poll_seconds: float = Field(default=1, ge=0.1, le=60)

    embedding_provider: Literal["disabled", "dashscope", "deterministic"] = "disabled"
    embedding_cloud_enabled: bool = False
    embedding_allow_test_provider: bool = False
    embedding_api_key: SecretStr | None = None
    embedding_endpoint: str = "https://dashscope.aliyuncs.com/api/v1/services/embeddings/text-embedding/text-embedding"
    embedding_model: str = "qwen3.7-text-embedding-flash"
    embedding_model_revision: str = "unverified"
    embedding_dimension: int = 1024
    embedding_batch_size: int = Field(default=10, ge=1, le=10)
    embedding_timeout_seconds: float = Field(default=15, ge=0.1, le=60)
    embedding_request_retries: int = Field(default=2, ge=0, le=3)
    embedding_backoff_seconds: float = Field(default=1, ge=0.1, le=10)
    embedding_concurrency: int = Field(default=1, ge=1, le=8)
    embedding_max_input_chars: int = Field(default=2000, ge=1, le=8000)
    embedding_max_input_bytes: int = Field(default=8192, ge=1, le=8192)
    embedding_max_chunks: int = Field(default=500, ge=1, le=2000)
    embedding_max_api_calls: int = Field(default=150, ge=1, le=1000)
    embedding_job_timeout_seconds: int = Field(default=180, ge=10, le=7200)
    embedding_lease_seconds: int = Field(default=90, ge=20, le=600)
    embedding_max_attempts: int = Field(default=3, ge=1, le=10)
    embedding_queue_capacity: int = Field(default=1000, ge=1, le=10000)

    retrieval_candidate_k: int = Field(default=20, ge=1, le=100)
    retrieval_top_k: int = Field(default=20, ge=1, le=100)
    retrieval_rrf_k: int = Field(default=60, ge=1, le=1000)
    retrieval_dense_weight: float = Field(default=1.0, gt=0, le=10, allow_inf_nan=False)
    retrieval_bm25_weight: float = Field(default=1.0, gt=0, le=10, allow_inf_nan=False)
    retrieval_bm25_k1: float = Field(default=1.5, gt=0, le=10, allow_inf_nan=False)
    retrieval_bm25_b: float = Field(default=0.75, ge=0, le=1, allow_inf_nan=False)
    retrieval_max_query_chars: int = Field(default=512, ge=1, le=2000)
    retrieval_max_corpus_chunks: int = Field(default=2000, ge=1, le=10000)
    retrieval_max_corpus_bytes: int = Field(default=4*1024*1024, ge=1, le=32*1024*1024)
    retrieval_max_corpus_tokens: int = Field(default=200000, ge=1, le=1000000)
    retrieval_concurrency: int = Field(default=2, ge=1, le=8)

    @model_validator(mode="after")
    def validate_security(self):
        if self.allow_insecure_loopback and self.environment != "development":
            raise ValueError("Insecure cookies require explicit development mode")
        root = self.file_storage_root.expanduser()
        if not root.is_absolute() or root.resolve().is_relative_to(REPOSITORY_ROOT):
            raise ValueError("File storage must be an absolute private path outside the repository")
        self.file_storage_root = root
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError("Chunk overlap must be smaller than chunk size")
        if self.ingestion_lease_seconds < self.parse_timeout_seconds + 15:
            raise ValueError("Task lease must exceed parser timeout by at least 15 seconds")
        if self.embedding_dimension != 1024:
            raise ValueError("This schema supports vector(1024); other dimensions require a new migration")
        if self.embedding_provider == "deterministic" and not (self.environment == "development" and self.embedding_allow_test_provider):
            raise ValueError("Deterministic embeddings require explicit development test mode")
        endpoint = urlsplit(self.embedding_endpoint)
        if (endpoint.scheme != "https" or endpoint.username or endpoint.password or endpoint.query or endpoint.fragment
            or endpoint.port not in {None, 443} or not endpoint.hostname
            or not (endpoint.hostname == "dashscope.aliyuncs.com" or endpoint.hostname.endswith(".maas.aliyuncs.com"))
            or endpoint.path != "/api/v1/services/embeddings/text-embedding/text-embedding"):
            raise ValueError("Embedding endpoint must be an official HTTPS DashScope endpoint")
        if not 1 <= len(self.embedding_model) <= 128 or not 1 <= len(self.embedding_model_revision) <= 64:
            raise ValueError("Invalid embedding model identity")
        maximum_backoff = self.embedding_backoff_seconds * 2**(self.embedding_request_retries-1) if self.embedding_request_retries else 0
        if self.embedding_lease_seconds < self.embedding_timeout_seconds + maximum_backoff + 15:
            raise ValueError("Embedding lease must cover HTTP timeout, retry backoff and a 15 second margin")
        if self.embedding_job_timeout_seconds <= self.embedding_timeout_seconds:
            raise ValueError("Embedding job deadline must exceed a request timeout")
        origins = []
        for origin in self.allowed_origins:
            parts = urlsplit(origin)
            if (parts.scheme not in {"http", "https"} or not parts.hostname
                or parts.username or parts.password or parts.path not in {"", "/"}
                or parts.query or parts.fragment or "*" in origin):
                raise ValueError("Origins must be explicit HTTP(S) origins without paths")
            _ = parts.port  # Validate malformed port numbers as well.
            if parts.scheme != "https":
                if not self.allow_insecure_loopback or parts.hostname not in {"127.0.0.1", "localhost", "::1"}:
                    raise ValueError("HTTP origins require explicit loopback development mode")
            if self.allow_insecure_loopback and parts.hostname not in {"127.0.0.1", "localhost", "::1"}:
                raise ValueError("Insecure development origins must be loopback")
            origins.append(origin.lower().rstrip("/"))
        self.allowed_origins = list(dict.fromkeys(origins))
        return self

    @property
    def cookie_secure(self) -> bool:
        return not self.allow_insecure_loopback

    @property
    def session_cookie(self) -> str:
        return "__Host-ds_v2_session" if self.cookie_secure else "ds_v2_session"

    @property
    def csrf_cookie(self) -> str:
        return "__Host-ds_v2_preauth" if self.cookie_secure else "ds_v2_preauth"

    @property
    def database_url(self) -> URL:
        # URL.create safely handles reserved characters in credentials.
        return URL.create(
            "postgresql+psycopg",
            username=self.db_user,
            password=self.db_password.get_secret_value(),
            host=self.db_host,
            port=self.db_port,
            database=self.db_name,
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
