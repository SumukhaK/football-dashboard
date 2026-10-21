"""Google sign-in settings: required values, secret handling, origins, keys and lifetimes."""

from __future__ import annotations

import traceback
from pathlib import Path
from typing import Any

import pytest
from pydantic import SecretStr, ValidationError

from app.config import Config

# Placeholder signing keys for the Google settings below: 32+ bytes, and not a
# repeated character, so they pass the same checks a real key would.
AUTH_SESSION_KEY = "session-8f14e45fceea167a0b1c2d3e4f5a6b7c8d9e0f1a"


AUTH_OAUTH_KEY = "oauth-3f6a1c37b90d2e5847a9c0b1d2e3f4a5b6c7d8e9"


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

    rendered = repr(settings) + str(settings)

    assert "GOCSPX" not in rendered
    assert AUTH_SESSION_KEY not in rendered
    assert AUTH_OAUTH_KEY not in rendered
    assert settings.google_client_secret is not None
    assert settings.google_client_secret.get_secret_value().startswith("GOCSPX")


def _every_printed_form(error: ValidationError) -> str:
    """What an operator or a crash reporter would normally get to see."""
    return str(error) + repr(error) + "".join(traceback.format_exception(error))


@pytest.mark.parametrize("field", ["session_signing_key", "oauth_signing_key"])
def test_a_rejected_key_never_echoes_the_supplied_value(field: str) -> None:
    """A short key is named and explained, but the value is not repeated."""
    sentinel = "short-key-SENTINEL"

    with pytest.raises(ValidationError) as caught:
        Config.model_validate({field: sentinel})

    rendered = _every_printed_form(caught.value)

    assert "SENTINEL" not in rendered
    assert field in rendered
    assert "32 bytes" in rendered


def test_a_model_error_never_echoes_the_supplied_secrets() -> None:
    """A model-level error echoes its whole input unless the input is hidden."""
    # Plain strings, as an environment variable would arrive: wrapping them in
    # SecretStr here would mask them even without the fix and hide the problem.
    client_secret = "GOCSPX-MODEL_SENTINEL"
    session_key = "demo-only-long-key-PRIVATE_SENTINEL"
    oauth_key = "demo-only-long-key-OAUTH_SENTINEL"

    with pytest.raises(ValidationError) as caught:
        Config.model_validate(
            {
                "auth_callback_url": "/auth/callback",
                "google_client_secret": client_secret,
                "session_signing_key": session_key,
                "oauth_signing_key": oauth_key,
            }
        )

    rendered = _every_printed_form(caught.value)

    for fragment in ("MODEL_SENTINEL", "PRIVATE_SENTINEL", "OAUTH_SENTINEL"):
        assert fragment not in rendered
    assert "auth_callback_url needs auth_public_origin" in rendered


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
        "https://@console.example",
        "https://:@console.example",
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


def test_a_hosted_revision_cannot_use_the_loopback_origin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cloud Run sets K_REVISION; http://127.0.0.1 is a local flow only.

    Accepting it would send a hosted console's browser to the visitor's own
    machine, so it is invalid configuration rather than a later provider error.
    """
    monkeypatch.setenv("K_REVISION", "console-00042-review")

    with pytest.raises(ValidationError, match="K_REVISION"):
        _google_config(
            source="gcp",
            gcp_project_id="example-project",
            auth_public_origin="http://127.0.0.1:8080",
            auth_callback_url="http://127.0.0.1:8080/auth/callback",
        )


def test_a_hosted_revision_passes_over_https(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The same configuration is fine once the origin is a hosted https one."""
    monkeypatch.setenv("K_REVISION", "console-00042-review")

    settings = _google_config(source="gcp", gcp_project_id="example-project")

    settings.require_google_auth()


def test_a_local_google_flow_may_use_loopback() -> None:
    """Without a hosted revision a developer may test the flow on 127.0.0.1."""
    settings = _google_config(
        source="gcp",
        gcp_project_id="example-project",
        auth_public_origin="http://127.0.0.1:8080",
        auth_callback_url="http://127.0.0.1:8080/auth/callback",
    )

    assert settings.auth_public_origin == "http://127.0.0.1:8080"
    settings.require_google_auth()


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
