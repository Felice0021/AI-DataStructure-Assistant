from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    host: str = "127.0.0.1"
    port: int = 8000

    class Config:
        extra = "ignore"


def get_settings():
    return Settings()