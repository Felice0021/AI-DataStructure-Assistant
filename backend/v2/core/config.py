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

    @model_validator(mode="after")
    def validate_security(self):
        if self.allow_insecure_loopback and self.environment != "development":
            raise ValueError("Insecure cookies require explicit development mode")
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
