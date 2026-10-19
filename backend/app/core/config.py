from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Typed runtime settings loaded from environment and an optional .env file."""

    app_env: str = "local"
    log_level: str = "INFO"

    openai_api_key: str | None = Field(
        default=None,
        repr=False,
        validation_alias=AliasChoices("OPENAI_API_KEY", "LOGIC_OPENAI_API_KEY"),
    )
    openai_model: str | None = None
    openai_reasoning_effort: Literal[
        "none", "minimal", "low", "medium", "high", "xhigh", "max"
    ] | None = None
    openai_embedding_model: str = "text-embedding-3-small"
    openai_timeout_seconds: float = Field(default=30.0, gt=0)
    openai_chat_max_output_tokens: int = Field(default=400, ge=64, le=2000)

    logic_api_base_url: str | None = None
    logic_map_url: str | None = None
    logic_official_website_url: str | None = None
    logic_escape_room_explainer_url: str | None = None
    logic_cafeteria_menu_url: str | None = None
    logic_typical_deposit_per_room_cop: int | None = Field(default=None, ge=0)
    logic_payment_method_for_deposits: str | None = Field(default=None, repr=False)
    logic_bre_b_key: str | None = Field(default=None, repr=False)
    logic_operational_values_verified: bool = False
    logic_api_timeout_seconds: float = Field(default=10.0, gt=0)
    logic_reference_cache_ttl_seconds: int = Field(default=43_200, ge=0)

    chroma_persist_directory: Path = Path(".data/chroma")
    chroma_collection_name: str = "logic_knowledge_v1"
    rag_max_distance: float = Field(default=0.55, ge=0, le=2)

    model_config = SettingsConfigDict(
        env_file=str(Path(__file__).resolve().parents[3] / ".env"),
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        extra="ignore",
        case_sensitive=False,
    )


@lru_cache
def get_settings() -> Settings:
    """Return the process settings, cached so configuration stays consistent."""
    return Settings()
