"""Application configuration and settings."""

from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parent.parent

# Substrings of Cloud Run system log lines and the platform event each means.
# Check them against real logs after the first deploy.
DEFAULT_PLATFORM_PATTERNS: tuple[tuple[str, str], ...] = (
    ("Memory limit of", "out_of_memory"),
    ("Container called exit", "container_exit"),
    ("failed to start and listen", "startup_failed"),
    ("Starting new instance", "instance_started"),
)


class Config(BaseSettings):
    """Application configuration, loaded from environment and .env."""

    source: Literal["fixture", "gcp"] = "fixture"
    fixture_dir: Path = Field(default=Path("fixtures"), validate_default=True)
    gcp_project_id: str | None = None
    api_service_name: str = "football-api"
    cache_ttl_seconds: int = Field(default=60, ge=0, le=600)
    default_window_hours: int = Field(default=24, ge=1, le=720)
    gcp_page_size: int = Field(default=1000, ge=1, le=1000)
    platform_patterns: tuple[tuple[str, str], ...] = DEFAULT_PLATFORM_PATTERNS

    model_config = SettingsConfigDict(env_prefix="", extra="ignore")

    @field_validator("fixture_dir")
    @classmethod
    def _resolve_fixture_dir(cls, value: Path) -> Path:
        """Resolve a relative fixture_dir against the repo root, not the cwd."""
        return value if value.is_absolute() else REPO_ROOT / value

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
