from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Typed runtime settings loaded from environment and an optional .env file."""

    app_env: str = "local"
    log_level: str = "INFO"

    openai_api_key: str | None = Field(default=None, repr=False)
    openai_model: str | None = None
    openai_embedding_model: str = "text-embedding-3-small"

    logic_api_base_url: str | None = None
    logic_reference_cache_ttl_seconds: int = Field(default=43_200, ge=0)

    chroma_persist_directory: Path = Path(".data/chroma")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )


@lru_cache
def get_settings() -> Settings:
    """Return the process settings, cached so configuration stays consistent."""
    return Settings()
