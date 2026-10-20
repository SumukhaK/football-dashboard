"""Tests for the signed five-minute login transaction."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from itsdangerous import URLSafeTimedSerializer

from app.auth.transactions import TransactionCookie
from app.services.auth import AuthFailure, AuthPolicy
from tests.auth.support import AUTH_OAUTH_KEY, AUTH_SESSION_KEY, NOW, google_config


def _policy() -> AuthPolicy:
    return AuthPolicy.from_config(google_config())


def _transaction(**overrides: Any) -> Any:
    fields: dict[str, Any] = {
        "state": "state-abc",
        "nonce": "nonce-abc",
        "code_verifier": "verifier-abc",
        "return_path": "/requests?window=24",
    }
    fields.update(overrides)
    return _policy().new_transaction(clock=lambda: NOW, **fields)


def _codec(clock: Any = None, max_age: int = 300) -> TransactionCookie:
    return TransactionCookie(AUTH_OAUTH_KEY, max_age, clock or (lambda: NOW))


def test_a_transaction_survives_a_round_trip() -> None:
    """Every bound value comes back exactly as it went in."""
    transaction = _transaction()

    loaded = _codec().loads(_codec().dumps(transaction))

    assert loaded == transaction
    assert loaded.is_valid_at(NOW)


def test_a_tampered_cookie_is_rejected() -> None:
    """Changing one character of the signature or payload fails closed."""
    value = _codec().dumps(_transaction())
    payload, _, signature = value.rpartition(".")
    changed_signature = ("A" if signature[0] != "A" else "B") + signature[1:]
    changed_payload = ("A" if payload[0] != "A" else "B") + payload[1:]

    for tampered in (
        f"{payload}.{changed_signature}",
        f"{changed_payload}.{signature}",
    ):
        with pytest.raises(AuthFailure) as caught:
            _codec().loads(tampered)

        assert caught.value.kind == "transaction"


def test_a_cookie_from_another_purpose_is_rejected() -> None:
    """The session and transaction cookies share a shape but not a key."""
    other_key = _codec_with_key(AUTH_SESSION_KEY).dumps(_transaction())
    with pytest.raises(AuthFailure):
        _codec().loads(other_key)

    session_purpose = URLSafeTimedSerializer(
        AUTH_OAUTH_KEY, salt="dashboard-session"
    ).dumps({"state": "state-abc"})
    with pytest.raises(AuthFailure):
        _codec().loads(session_purpose)


def test_a_transaction_older_than_five_minutes_is_rejected() -> None:
    """Age is measured against the injected clock, not the payload's claim."""
    value = _codec().dumps(_transaction())

    later = _codec(clock=lambda: NOW + timedelta(seconds=301))
    with pytest.raises(AuthFailure) as caught:
        later.loads(value)

    assert caught.value.kind == "transaction"


def test_a_transaction_from_the_future_is_rejected() -> None:
    """A clock far behind the signer is a skew worth refusing, not trusting."""
    value = _codec().dumps(_transaction())

    earlier = _codec(clock=lambda: NOW - timedelta(minutes=5))
    with pytest.raises(AuthFailure):
        earlier.loads(value)


def test_a_payload_that_does_not_match_the_schema_is_rejected() -> None:
    """A valid signature over the wrong shape is still not a transaction."""
    serializer = URLSafeTimedSerializer(
        AUTH_OAUTH_KEY, salt="dashboard-oauth-transaction"
    )
    bad_payloads = (
        {"state": "s"},  # missing fields
        {
            "state": "s",
            "nonce": "n",
            "code_verifier": "v",
            "return_path": "/",
            "issued_at": "not-a-time",
            "expires_at": "not-a-time",
        },
        {
            "state": "s",
            "nonce": "n",
            "code_verifier": "v",
            "return_path": "/",
            "issued_at": NOW.isoformat(),
            "expires_at": (NOW - timedelta(seconds=1)).isoformat(),
        },
        {
            "state": "",
            "nonce": "n",
            "code_verifier": "v",
            "return_path": "/",
            "issued_at": NOW.isoformat(),
            "expires_at": (NOW + timedelta(minutes=5)).isoformat(),
        },
    )

    for payload in bad_payloads:
        with pytest.raises(AuthFailure):
            _codec().loads(serializer.dumps(payload))


def test_a_payload_may_not_outlive_the_configured_window() -> None:
    """Even a correctly signed payload is bounded by the configuration."""
    serializer = URLSafeTimedSerializer(
        AUTH_OAUTH_KEY, salt="dashboard-oauth-transaction"
    )
    payload = {
        "state": "s",
        "nonce": "n",
        "code_verifier": "v",
        "return_path": "/",
        "issued_at": NOW.isoformat(),
        "expires_at": (NOW + timedelta(minutes=6)).isoformat(),
    }

    with pytest.raises(AuthFailure):
        _codec(max_age=300).loads(serializer.dumps(payload))


def test_the_codec_from_config_uses_the_oauth_key_and_window() -> None:
    """Nothing is hard-coded in a router: both come from the settings."""
    settings = google_config()

    def clock() -> datetime:
        return NOW

    codec = TransactionCookie.from_config(settings, clock)
    transaction = _policy().new_transaction(
        state="s", nonce="n", code_verifier="v", return_path="/", clock=clock
    )

    assert codec.loads(codec.dumps(transaction)) == transaction
    assert codec.max_age_seconds == settings.oauth_transaction_max_age_seconds


def _codec_with_key(key: str) -> TransactionCookie:
    return TransactionCookie(key, 300, lambda: datetime.now(UTC))
