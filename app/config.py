"""Application configuration and settings."""

from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parent.parent

# The window choices the picker offers, in hours (7 days == 168 hours). This is
# configuration, not service logic, so Config can validate its own default.
WINDOW_HOURS: tuple[int, ...] = (1, 6, 24, 168)

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
    default_window_hours: int = 24
    gcp_page_size: int = Field(default=1000, ge=1, le=1000)
    platform_patterns: tuple[tuple[str, str], ...] = DEFAULT_PLATFORM_PATTERNS

    # Data-freshness tile thresholds, in hours: green below warn, amber up to
    # error, red above. See guide/D3-overview.md.
    freshness_warn_hours: int = Field(default=36, ge=1)
    freshness_error_hours: int = Field(default=72, ge=1)

    # How far back a component tile looks for the last load / refresh /
    # freshness reading, so a short window is not all grey. See guide/D3-overview.md.
    tile_lookback_hours: int = Field(default=168, ge=1)

    # The opt-in invite page, the one place the console writes to Google Cloud:
    # one Firestore document per invite, in the platform's invite collection.
    invites_enabled: bool = False
    invite_collection_prefix: str = "staging_"
    invite_lifetime_days: int = Field(default=7, ge=1)

    # The opt-in crashes page reads the Firebase Crashlytics BigQuery export,
    # which lives in the Firebase project, not the API's project. Identifiers
    # are pasted into the SQL (BigQuery cannot parameterise them), hence the
    # patterns.
    crashlytics_project_id: str | None = Field(
        default=None, pattern=r"^[a-z][a-z0-9-]{4,61}[a-z0-9]$"
    )
    crashlytics_dataset: str = Field(default="firebase_crashlytics", pattern=r"^\w+$")
    crashlytics_table: str = Field(
        default="com_footballintelligence_app_stg_ANDROID", pattern=r"^\w+$"
    )
    crashlytics_location: str = "US"
    # Cost guard: BigQuery refuses any crash query that would bill more.
    crashlytics_max_bytes_billed: int = Field(default=1_000_000_000, ge=1)

    model_config = SettingsConfigDict(env_prefix="", extra="ignore")

    @property
    def crashes_enabled(self) -> bool:
        """The crashes page runs on sample data, or on gcp with a Firebase project."""
        return self.source == "fixture" or self.crashlytics_project_id is not None

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

    @field_validator("default_window_hours")
    @classmethod
    def _default_window_is_offered(cls, value: int) -> int:
        """The default window must be one the picker offers."""
        if value not in WINDOW_HOURS:
            raise ValueError(f"default_window_hours must be one of {WINDOW_HOURS}")
        return value

    contract_version: str = "1.0.0"


@lru_cache
def get_config() -> Config:
    """Return a cached Config instance."""
    return Config()
