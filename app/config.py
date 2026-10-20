"""Application configuration and settings."""

from functools import lru_cache
from pathlib import Path
from typing import Any, Literal, Self
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parent.parent

# D9 owner sign-in. The console's own login is Google OpenID Connect with a
# server-side owner allowlist; see guide/D9-owner-login.md and
# guide/adr/001-owner-google-login.md. "fixture" is not an off switch: it is the
# explicit loopback demonstration mode, and it refuses a real source, an enabled
# invite page or a hosted revision.
SESSION_MAX_AGE_SECONDS = 3600
TRANSACTION_MAX_AGE_SECONDS = 300
DEFAULT_OWNER_EMAIL = "sumukh.aithal@gmail.com"
GOOGLE_CLIENT_ID_SUFFIX = ".apps.googleusercontent.com"

# The window choices the picker offers, in hours (7 days == 168 hours). This is
# configuration, not service logic, so Config can validate its own default.
WINDOW_HOURS: tuple[int, ...] = (1, 6, 24, 168)

# The app's own Java/Kotlin package. A stack frame whose symbol sits under it is
# the app's own code; every other frame comes from a library. See
# guide/D8-redesign.md.
DEFAULT_CRASH_APP_PACKAGE = "com.footballintelligence.app"

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

    source: Literal["fixture", "local", "gcp"] = "fixture"
    fixture_dir: Path = Field(default=Path("fixtures"), validate_default=True)
    # The backend's JSON log file, read when source is "local". Only its last
    # local_log_max_bytes are read, so a long-running log stays quick to open.
    local_log_path: Path | None = None
    local_log_max_bytes: int = Field(default=50_000_000, ge=1_000_000, le=1_000_000_000)
    gcp_project_id: str | None = None
    api_service_name: str = "football-api"
    cache_ttl_seconds: int = Field(default=60, ge=0, le=600)
    default_window_hours: int = 24
    # Per-page default windows. The data page looks back a week, because the
    # refresh and download runs it shows are daily; the access page looks back a
    # day. Both must be windows the picker offers. See guide/D6-data-and-access.md.
    data_default_window_hours: int = 168
    access_default_window_hours: int = 24
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
    # Which stack frames count as the app's own code on the crashes page.
    crash_app_package: str = Field(
        default=DEFAULT_CRASH_APP_PACKAGE,
        pattern=r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)+$",
    )

    # Which sign-in the console runs. "google" is the owner's verified Google
    # account; "fixture" is the local demonstration mode described above.
    auth_mode: Literal["google", "fixture"] = "google"
    owner_email: str = DEFAULT_OWNER_EMAIL
    # The Web application OAuth client and its secret. The secret is a
    # SecretStr, so a printed or logged configuration never shows it.
    google_client_id: str | None = None
    google_client_secret: SecretStr | None = None
    # The canonical origin and the callback derived from it. Both come from
    # configuration, never from a request's Host or forwarded headers.
    auth_public_origin: str | None = None
    auth_callback_url: str | None = None
    # Two independent random secrets. They have no default and no fallback, so
    # a console either has its own keys or does not serve.
    session_signing_key: SecretStr | None = None
    oauth_signing_key: SecretStr | None = None
    # An hour of console session and five minutes of pending sign-in, at most.
    session_max_age_seconds: int = Field(
        default=SESSION_MAX_AGE_SECONDS, ge=60, le=SESSION_MAX_AGE_SECONDS
    )
    oauth_transaction_max_age_seconds: int = Field(
        default=TRANSACTION_MAX_AGE_SECONDS, ge=30, le=TRANSACTION_MAX_AGE_SECONDS
    )

    # hide_input_in_errors keeps a rejected value (a signing key, a client
    # secret, or the whole input of a model-level error) out of the printed
    # error and the startup traceback. SecretStr alone only hides a value after
    # it has been accepted; a rejected one is echoed back unless this is set.
    model_config = SettingsConfigDict(
        env_prefix="", extra="ignore", hide_input_in_errors=True
    )

    @property
    def crashes_enabled(self) -> bool:
        """The crashes page runs on sample data, or on gcp with a Firebase project."""
        return self.source == "fixture" or self.crashlytics_project_id is not None

    def local_log_file(self) -> Path:
        """The log file a local source reads; only local runs have one.

        Validation already refuses a local source without a path, so this raises
        only for a caller that reads the path of a source that is not local.
        """
        if self.local_log_path is None:
            raise ValueError("local_log_path is required when source is 'local'")
        return self.local_log_path

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

    @field_validator("local_log_path")
    @classmethod
    def _require_local_log_path(cls, value: Path | None, info: Any) -> Path | None:
        """local_log_path is required when source is local."""
        if info.data.get("source") == "local" and not value:
            raise ValueError("local_log_path is required when source is 'local'")
        return value

    @field_validator(
        "default_window_hours",
        "data_default_window_hours",
        "access_default_window_hours",
    )
    @classmethod
    def _window_is_offered(cls, value: int, info: Any) -> int:
        """Every configured default window must be one the picker offers."""
        if value not in WINDOW_HOURS:
            raise ValueError(f"{info.field_name} must be one of {WINDOW_HOURS}")
        return value

    contract_version: str = "1.1.0"

    # The console's own version and the revision it runs as. Cloud Run sets
    # K_REVISION on every revision; locally it is absent, and the sidebar footer
    # then shows the version alone.
    app_version: str = "1.0.0"
    revision: str | None = Field(default=None, validation_alias="K_REVISION")

    @field_validator("owner_email")
    @classmethod
    def _check_owner_email(cls, value: str) -> str:
        """One plain address, lower-cased: no wildcard, list or empty domain."""
        cleaned = value.strip().lower()
        local, _, domain = cleaned.partition("@")
        malformed = (
            not local
            or not domain
            or "." not in domain
            or "@" in domain
            or "/" in cleaned
            or any(char in cleaned for char in "*;,")
            or any(char.isspace() for char in cleaned)
        )
        if malformed:
            raise ValueError(
                "owner_email must be one email address, like name@example.com"
            )
        return cleaned

    @field_validator("google_client_id")
    @classmethod
    def _check_client_id(cls, value: str | None) -> str | None:
        """The Web OAuth client, not an API key or a service-account name."""
        if value is None:
            return None
        if not value.endswith(GOOGLE_CLIENT_ID_SUFFIX) or " " in value:
            raise ValueError(
                "google_client_id must be a Web OAuth client id ending in "
                f"{GOOGLE_CLIENT_ID_SUFFIX}"
            )
        return value

    @field_validator("google_client_secret")
    @classmethod
    def _check_client_secret(cls, value: SecretStr | None) -> SecretStr | None:
        """A secret that is present must have a value."""
        if value is not None and not value.get_secret_value().strip():
            raise ValueError("google_client_secret must not be blank")
        return value

    @field_validator("auth_public_origin")
    @classmethod
    def _check_public_origin(cls, value: str | None) -> str | None:
        """The canonical scheme, host and port only, never a path or a user."""
        if value is None:
            return None
        if any(char in value for char in "\\\n\r\t "):
            raise ValueError("auth_public_origin must not carry control characters")
        parsed = urlsplit(value)
        if parsed.scheme not in {"https", "http"}:
            raise ValueError("auth_public_origin must be an https URL")
        if (
            parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError(
                "auth_public_origin must not carry userinfo, a query or a fragment"
            )
        if parsed.path not in {"", "/"}:
            raise ValueError("auth_public_origin must not carry a path")
        if not parsed.hostname or parsed.hostname.endswith("."):
            raise ValueError("auth_public_origin must name a host")
        try:
            # Reading the port is what validates it: urlsplit is lazy and only
            # raises for a malformed port when the attribute is touched.
            _port = parsed.port
        except ValueError as exc:
            raise ValueError("auth_public_origin must carry a valid port") from exc
        if parsed.scheme == "http" and parsed.hostname != "127.0.0.1":
            raise ValueError(
                "auth_public_origin may use http only for local 127.0.0.1 testing"
            )
        return f"{parsed.scheme}://{parsed.netloc}"

    @field_validator("auth_callback_url")
    @classmethod
    def _check_callback_url(cls, value: str | None) -> str | None:
        """The callback path is fixed; its origin is checked with the model."""
        if value is not None and not value.endswith("/auth/callback"):
            raise ValueError("auth_callback_url must end with /auth/callback")
        return value

    @field_validator("session_signing_key", "oauth_signing_key")
    @classmethod
    def _check_signing_key(cls, value: SecretStr | None, info: Any) -> SecretStr | None:
        """At least 32 bytes of a key that is not a repeated placeholder."""
        if value is None:
            return None
        secret = value.get_secret_value()
        if len(secret.encode()) < 32:
            raise ValueError(f"{info.field_name} must be at least 32 bytes")
        if len(set(secret)) < 8:
            raise ValueError(f"{info.field_name} looks like a placeholder key")
        return value

    @model_validator(mode="after")
    def _check_auth_combination(self) -> Self:
        """The rules that need several settings in view at once."""
        if self.auth_mode == "fixture" and (
            self.source != "fixture" or self.invites_enabled or self.revision
        ):
            raise ValueError(
                "auth_mode=fixture is the loopback demonstration mode: it needs "
                "source=fixture, invites off and no hosted revision"
            )
        if (
            self.revision is not None
            and self.auth_public_origin is not None
            and self.auth_public_origin.startswith("http://")
        ):
            # The origin validator allows http only on 127.0.0.1, so this is
            # the local-flow exception. A hosted revision would send the
            # browser to the visitor's own machine instead of the console.
            raise ValueError(
                "a hosted revision (K_REVISION) needs an https "
                "auth_public_origin: http loopback is for local testing only"
            )
        if self.auth_callback_url is not None:
            if self.auth_public_origin is None:
                raise ValueError("auth_callback_url needs auth_public_origin")
            expected = f"{self.auth_public_origin}/auth/callback"
            if self.auth_callback_url != expected:
                raise ValueError(f"auth_callback_url must be {expected}")
        if (
            self.session_signing_key is not None
            and self.oauth_signing_key is not None
            and self.session_signing_key.get_secret_value()
            == self.oauth_signing_key.get_secret_value()
        ):
            raise ValueError("session_signing_key and oauth_signing_key must differ")
        return self

    def missing_google_auth(self) -> tuple[str, ...]:
        """The Google settings a console must have before it serves.

        Empty for the fixture demonstration mode, which has no provider at all.
        """
        if self.auth_mode != "google":
            return ()
        required: tuple[tuple[str, object | None], ...] = (
            ("GOOGLE_CLIENT_ID", self.google_client_id),
            ("GOOGLE_CLIENT_SECRET", self.google_client_secret),
            ("AUTH_PUBLIC_ORIGIN", self.auth_public_origin),
            ("AUTH_CALLBACK_URL", self.auth_callback_url),
            ("SESSION_SIGNING_KEY", self.session_signing_key),
            ("OAUTH_SIGNING_KEY", self.oauth_signing_key),
        )
        return tuple(name for name, value in required if value is None)

    def validate_callback_url(self) -> None:
        \"\"\"Validate that AUTH_CALLBACK_URL matches AUTH_PUBLIC_ORIGIN.\"\"\"
        if self.auth_public_origin is not None and self.auth_callback_url is not None:
            expected = f\"{self.auth_public_origin}/auth/callback\"
            if self.auth_callback_url != expected:
                raise ValueError(
                    f\"auth_callback_url must be {expected}\"
                    f\"when auth_public_origin is {self.auth_public_origin}\"
                )

    def require_google_auth(self) -> None:
        """Refuse to serve a console whose owner sign-in is not configured.

        The server calls this as it starts, so a revision with no Google
        settings exits instead of serving real telemetry behind no gate.
        """
        missing = self.missing_google_auth()
        if missing:
            raise ValueError(
                f"auth_mode=google needs {', '.join(missing)}: set them, or run "
                "the explicit fixture demonstration mode"
            )


@lru_cache
def get_config() -> Config:
    """Return a cached Config instance."""
    return Config()
