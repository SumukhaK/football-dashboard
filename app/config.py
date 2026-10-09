"""Application configuration and settings."""

from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Config(BaseSettings):
    """Application configuration, loaded from environment and .env."""

    source: Literal["fixture", "gcp"] = "fixture"
    fixture_path: Path = Path("fixtures/events.jsonl")
    gcp_project_id: str | None = None
    api_service_name: str = "football-api"
    cache_ttl_seconds: int = Field(default=60, ge=0, le=600)
    default_window_hours: int = Field(default=24, ge=1, le=720)

    model_config = SettingsConfigDict(env_prefix="", extra="ignore")

    @field_validator("gcp_project_id")
    @classmethod
    def _require_gcp_project_id(cls, value: str | None, info: Any) -> str | None:
        """gcp_project_id is required when source is gcp."""
        # info.data contains the other fields already validated
        if info.data.get("source") == "gcp" and not value:
            raise ValueError("gcp_project_id is required when source is 'gcp'")
        return value

    contract_version: str = "1.0.0"


@lru_cache
def get_config() -> Config:
    """Return a cached Config instance."""
    return Config()
