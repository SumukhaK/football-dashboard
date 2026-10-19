"""Tests for configuration settings."""

from pathlib import Path
from typing import Any

import pytest
from pydantic import SecretStr, ValidationError

from app.config import REPO_ROOT, Config

# Placeholder signing keys for the Google settings below: 32+ bytes, and not a
# repeated character, so they pass the same checks a real key would.
AUTH_SESSION_KEY = "session-8f14e45fceea167a0b1c2d3e4f5a6b7c8d9e0f1a"
AUTH_OAUTH_KEY = "oauth-3f6a1c37b90d2e5847a9c0b1d2e3f4a5b6c7d8e9"


def test_default_source_is_fixture() -> None:
    """Default source should be 'fixture'."""
    config = Config()
    assert config.source == "fixture"


def test_fixture_dir_resolves_against_repo_root() -> None:
    """A relative fixture_dir is resolved against the repo, not the cwd."""
    assert Config().fixture_dir == REPO_ROOT / "fixtures"


def test_absolute_fixture_dir_is_kept(tmp_path: Path) -> None:
    """An absolute fixture_dir is used as given."""
    assert Config(fixture_dir=tmp_path).fixture_dir == tmp_path


def test_gcp_defaults() -> None:
    """Page size and platform patterns have the documented defaults."""
    config = Config()
    assert config.gcp_page_size == 1000
    assert ("Memory limit of", "out_of_memory") in config.platform_patterns


def test_gcp_requires_project_id() -> None:
    """source='gcp' without gcp_project_id should fail validation."""
    with pytest.raises(ValidationError):
        Config(source="gcp")


def test_gcp_with_project_id() -> None:
    """source='gcp' with gcp_project_id should succeed."""
    config = Config(source="gcp", gcp_project_id="test-project")
    assert config.source == "gcp"
    assert config.gcp_project_id == "test-project"


def test_local_requires_a_log_path() -> None:
    """source='local' without local_log_path should fail validation."""
    with pytest.raises(ValidationError):
        Config(source="local")


def test_local_with_a_log_path() -> None:
    """source='local' with a path is accepted, with the documented tail limit."""
    config = Config(source="local", local_log_path=Path("api.jsonl"))
    assert config.source == "local"
    assert config.local_log_path == Path("api.jsonl")
    assert config.local_log_max_bytes == 50_000_000


def test_local_log_file_is_only_there_for_a_local_source() -> None:
    """The path a local source reads is absent when the source reads no file."""
    with pytest.raises(ValueError):
        Config().local_log_file()
    local = Config(source="local", local_log_path=Path("api.jsonl"))
    assert local.local_log_file() == Path("api.jsonl")


def test_cache_ttl_in_valid_range() -> None:
    """cache_ttl_seconds should be between 0 and 600."""
    # Valid values
    Config(cache_ttl_seconds=0)
    Config(cache_ttl_seconds=300)
    Config(cache_ttl_seconds=600)


def test_default_window_in_valid_range() -> None:
    """default_window_hours should be between 1 and 720."""
    config = Config()
    assert 1 <= config.default_window_hours <= 720


def test_default_window_must_be_a_picker_window() -> None:
    """default_window_hours must be one of the windows the picker offers."""
    with pytest.raises(ValidationError):
        Config(default_window_hours=12)


def test_tile_lookback_default() -> None:
    """The tile lookback defaults to a week."""
    assert Config().tile_lookback_hours == 168


def test_contract_version() -> None:
    """Config should have access to contract_version."""
    config = Config()
    assert config.contract_version == "1.1.0"


def test_version_and_revision_defaults() -> None:
    """The footer's version has a default and the revision is unset locally."""
    config = Config()
    assert config.app_version == "1.0.0"
    assert config.revision is None


def test_revision_is_read_from_the_cloud_run_variable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cloud Run's K_REVISION names the revision the console runs as."""
    monkeypatch.setenv("K_REVISION", "football-dashboard-00007-abc")
    assert Config().revision == "football-dashboard-00007-abc"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("cache_ttl_seconds", -1),
        ("cache_ttl_seconds", 601),
        ("default_window_hours", 0),
        ("default_window_hours", 721),
        ("gcp_page_size", 0),
        ("gcp_page_size", 1001),
        ("local_log_max_bytes", 999_999),
        ("local_log_max_bytes", 1_000_000_001),
    ],
)
def test_out_of_range_settings_are_rejected(field: str, value: int) -> None:
    """Range-limited settings reject values outside their bounds."""
    with pytest.raises(ValidationError):
        Config.model_validate({field: value})


def test_invites_are_off_by_default() -> None:
    """The invite page is opt-in and writes to the staging collections."""
    config = Config()
    assert config.invites_enabled is False
    assert config.invite_collection_prefix == "staging_"
    assert config.invite_lifetime_days == 7


def test_crashlytics_defaults() -> None:
    """The crashes settings default to the staging app's export table."""
    config = Config()
    assert config.crashlytics_project_id is None
    assert config.crashlytics_dataset == "firebase_crashlytics"
    assert config.crashlytics_table == "com_footballintelligence_app_stg_ANDROID"
    assert config.crashlytics_location == "US"
    assert config.crashlytics_max_bytes_billed == 1_000_000_000
    assert config.crash_app_package == "com.footballintelligence.app"


def test_the_crash_app_package_must_be_a_package() -> None:
    """The app's own package is a dotted Java or Kotlin package name."""
    assert (
        Config(crash_app_package="com.example.app").crash_app_package
        == "com.example.app"
    )
    for value in ("App", "com.example.app!", "com..app"):
        with pytest.raises(ValidationError):
            Config(crash_app_package=value)


def test_crashes_enabled_on_fixture_or_with_a_firebase_project() -> None:
    """Sample data always has crashes; gcp needs crashlytics_project_id."""
    assert Config().crashes_enabled
    gcp = Config(source="gcp", gcp_project_id="demo-project")
    assert not gcp.crashes_enabled
    with_project = gcp.model_copy(update={"crashlytics_project_id": "proj-123"})
    assert with_project.crashes_enabled


def test_crashlytics_identifiers_are_checked() -> None:
    """Identifiers pasted into the SQL must be plain names."""
    with pytest.raises(ValidationError):
        Config(crashlytics_table="t`; DROP TABLE x")
    with pytest.raises(ValidationError):
        Config(crashlytics_project_id="Bad Project")


# --- D9: the console's own sign-in -----------------------------------------


def _google_config(**overrides: Any) -> Config:
    """A console configured for Google sign-in, with placeholder credentials."""
    fields: dict[str, Any] = {
        "google_client_id": "114958444175-abcdefghijklmnop.apps.googleusercontent.com",
        "google_client_secret": "GOCSPX-not-a-real-secret",
        "auth_public_origin": "https://console.example",
        "auth_callback_url": "https://console.example/auth/callback",
        "session_signing_key": AUTH_SESSION_KEY,
        "oauth_signing_key": AUTH_OAUTH_KEY,
    }
    fields.update(overrides)
    return Config(**fields)


def test_auth_defaults_are_the_secure_ones() -> None:
    """The console defaults to Google sign-in, and carries no secret yet."""
    config = Config()

    assert config.auth_mode == "google"
    assert config.owner_email == "sumukh.aithal@gmail.com"
    assert config.google_client_id is None
    assert config.google_client_secret is None
    assert config.auth_public_origin is None
    assert config.auth_callback_url is None
    assert config.session_signing_key is None
    assert config.oauth_signing_key is None
    assert config.session_max_age_seconds == 3600
    assert config.oauth_transaction_max_age_seconds == 300


def test_the_settings_a_google_console_needs_are_listed() -> None:
    """The names to set, in order, so an operator is never left guessing."""
    assert Config().missing_google_auth() == (
        "GOOGLE_CLIENT_ID",
        "GOOGLE_CLIENT_SECRET",
        "AUTH_PUBLIC_ORIGIN",
        "AUTH_CALLBACK_URL",
        "SESSION_SIGNING_KEY",
        "OAUTH_SIGNING_KEY",
    )
    assert _google_config().missing_google_auth() == ()
    assert Config(auth_mode="fixture").missing_google_auth() == ()


def test_serving_without_the_google_settings_is_refused() -> None:
    """require_google_auth is what the server calls as it starts."""
    with pytest.raises(ValueError, match="GOOGLE_CLIENT_ID"):
        Config().require_google_auth()

    _google_config().require_google_auth()
    Config(auth_mode="fixture").require_google_auth()


def test_the_client_secret_never_appears_in_a_rendering() -> None:
    """A secret is a SecretStr, so a logged or printed config hides it."""
    settings = _google_config()

    assert "GOCSPX" not in repr(settings)
    assert settings.google_client_secret is not None
    assert settings.google_client_secret.get_secret_value().startswith("GOCSPX")


def test_the_owner_email_must_be_one_plain_address() -> None:
    """No wildcard, no list and no malformed address is accepted."""
    for value in (
        "",
        "   ",
        "no-at-sign",
        "a@b",
        "a@@b.com",
        "two@a.com, three@b.com",
        "*@example.com",
        "a b@c.com",
        "a@b/c.com",
    ):
        with pytest.raises(ValidationError):
            Config(owner_email=value)


def test_the_owner_email_is_only_trimmed_and_lower_cased() -> None:
    """Dots and plus-addresses are not folded away at configuration time."""
    settings = Config(owner_email=" Sumukh.Aithal@Gmail.COM ")

    assert settings.owner_email == "sumukh.aithal@gmail.com"


def test_the_public_origin_is_a_scheme_and_a_host_only() -> None:
    """Everything the callback URL needs, and nothing a request could steer."""
    assert (
        Config(auth_public_origin="https://console.example").auth_public_origin
        == "https://console.example"
    )
    assert (
        Config(auth_public_origin="https://console.example:8443/").auth_public_origin
        == "https://console.example:8443"
    )
    assert (
        Config(auth_public_origin="http://127.0.0.1:8080").auth_public_origin
        == "http://127.0.0.1:8080"
    )

    for value in (
        "http://console.example",
        "https://user:secret@console.example",
        "https://console.example/path",
        "https://console.example?x=1",
        "https://console.example#fragment",
        "ftp://console.example",
        "console.example",
        "https://console.example:notaport",
        "https://console.example\\@evil.example",
        "https://console.example\n.example",
    ):
        with pytest.raises(ValidationError):
            Config(auth_public_origin=value)


def test_the_callback_url_is_the_origin_plus_the_callback_path() -> None:
    """The registered redirect is derived from configuration, never a request."""
    settings = _google_config()

    assert settings.auth_callback_url == (
        f"{settings.auth_public_origin}/auth/callback"
    )

    with pytest.raises(ValidationError):
        _google_config(auth_callback_url="https://console.example/auth/other")
    with pytest.raises(ValidationError):
        _google_config(auth_callback_url="https://other.example/auth/callback")
    with pytest.raises(ValidationError):
        _google_config(auth_callback_url="https://console.example/auth/callback/")
    with pytest.raises(ValidationError):
        Config(auth_callback_url="https://console.example/auth/callback")


def test_the_signing_keys_are_long_random_and_independent() -> None:
    """Two different secrets, each at least 32 bytes, with no fallback key."""
    settings = _google_config()

    assert settings.session_signing_key is not None
    assert settings.oauth_signing_key is not None
    assert len(settings.session_signing_key.get_secret_value().encode()) >= 32
    assert len(settings.oauth_signing_key.get_secret_value().encode()) >= 32

    for value in ("short", "", "   ", "a" * 64):
        with pytest.raises(ValidationError):
            Config(session_signing_key=SecretStr(value))

    with pytest.raises(ValidationError):
        _google_config(oauth_signing_key=AUTH_SESSION_KEY)


def test_the_lifetimes_are_capped_at_the_documented_maximum() -> None:
    """An hour of console session, five minutes of pending sign-in, at most."""
    assert Config(session_max_age_seconds=60).session_max_age_seconds == 60
    assert Config(session_max_age_seconds=3600).session_max_age_seconds == 3600
    assert (
        Config(oauth_transaction_max_age_seconds=30).oauth_transaction_max_age_seconds
        == 30
    )
    assert (
        Config(oauth_transaction_max_age_seconds=300).oauth_transaction_max_age_seconds
        == 300
    )

    for field, value in (
        ("session_max_age_seconds", 59),
        ("session_max_age_seconds", 3601),
        ("oauth_transaction_max_age_seconds", 29),
        ("oauth_transaction_max_age_seconds", 301),
    ):
        with pytest.raises(ValidationError):
            Config.model_validate({field: value})


def test_the_client_id_must_be_a_web_oauth_client() -> None:
    """Not an API key, not a service account, not another host's lookalike."""
    assert _google_config().google_client_id is not None

    for value in (
        "AIzaSyD-abcdefghijklmnopqrstuvwxyz",
        "114958444175-abcdef.apps.googleusercontent.com.evil.example",
        "console-reader@demo.iam.gserviceaccount.com",
    ):
        with pytest.raises(ValidationError):
            Config(google_client_id=value)


def test_the_fixture_mode_is_only_a_local_demonstration() -> None:
    """No real telemetry and no writes behind a console with no sign-in."""
    assert Config(auth_mode="fixture").auth_mode == "fixture"

    with pytest.raises(ValidationError):
        Config(auth_mode="fixture", source="local", local_log_path=Path("api.jsonl"))
    with pytest.raises(ValidationError):
        Config(auth_mode="fixture", invites_enabled=True)


def test_the_fixture_mode_is_refused_on_a_hosted_revision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cloud Run sets K_REVISION, and that is never a demonstration."""
    monkeypatch.setenv("K_REVISION", "football-dashboard-00042-xyz")

    with pytest.raises(ValidationError):
        Config(auth_mode="fixture")
