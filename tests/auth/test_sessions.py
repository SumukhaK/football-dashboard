"""Tests for the signed console session cookie.

A session carries only who, until when and its random identifier. These tests
check the exact serialized fields, the absolute expiry (a later read never
renews it), and that a forged, stale, over-long or cross-purpose value fails.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from itsdangerous import URLSafeTimedSerializer

from app.auth.sessions import (
    SESSION_SALT,
    SessionCookie,
    cookie_security,
    local_auth,
    oauth_cookie_name,
    session_cookie_name,
)
from app.auth.transactions import TransactionCookie
from app.config import Config
from app.domain.auth import (
    OAUTH_COOKIE,
    OAUTH_COOKIE_LOCAL,
    SESSION_COOKIE,
    SESSION_COOKIE_LOCAL,
    ConsoleSession,
    LoginTransaction,
)
from app.services.auth import AuthFailure
from tests.auth.support import AUTH_OAUTH_KEY, AUTH_SESSION_KEY, NOW, google_config


def _cookie(**overrides: object) -> SessionCookie:
    return SessionCookie.from_config(google_config(**overrides), lambda: NOW)


def _session(**overrides: object) -> ConsoleSession:
    fields: dict[str, object] = {
        "subject": "google-sub-1",
        "email": "sumukh.aithal@gmail.com",
        "issued_at": NOW,
        "expires_at": NOW + timedelta(hours=1),
        "session_id": "session-id-1",
    }
    fields.update(overrides)
    return ConsoleSession(**fields)  # type: ignore[arg-type]


def _signed(payload: dict[str, object]) -> str:
    """A correctly signed payload, as if our code had written a bad value."""
    serializer = URLSafeTimedSerializer(AUTH_SESSION_KEY, salt=SESSION_SALT)
    return str(serializer.dumps(payload))


def test_a_session_round_trips() -> None:
    """What is written is what is read back, with the same absolute expiry."""
    cookie = _cookie()
    session = _session()

    assert cookie.loads(cookie.dumps(session)) == session


def test_the_payload_holds_only_the_session_fields() -> None:
    """No token, name, picture or whole userinfo is ever serialized."""
    cookie = _cookie()
    payload = cookie.serializer.loads(cookie.dumps(_session()))

    assert set(payload) == {
        "subject",
        "email",
        "issued_at",
        "expires_at",
        "session_id",
    }
    text = cookie.dumps(_session())
    for forbidden in ("access_token", "refresh_token", "id_token", "picture"):
        assert forbidden not in text


def test_a_later_read_does_not_renew_the_expiry() -> None:
    """Half an hour of paging still leaves the original one-hour expiry."""
    cookie = _cookie()
    value = cookie.dumps(_session())

    later = SessionCookie(
        signing_key=cookie.signing_key,
        max_age_seconds=cookie.max_age_seconds,
        clock=lambda: NOW + timedelta(minutes=30),
    )

    assert later.loads(value).expires_at == NOW + timedelta(hours=1)


def test_a_tampered_cookie_is_rejected() -> None:
    """Changing the signature or the payload fails closed."""
    cookie = _cookie()
    payload, _, signature = cookie.dumps(_session()).rpartition(".")

    changed_signature = ("A" if signature[0] != "A" else "B") + signature[1:]
    changed_payload = ("A" if payload[0] != "A" else "B") + payload[1:]

    for tampered in (
        f"{payload}.{changed_signature}",
        f"{changed_payload}.{signature}",
    ):
        with pytest.raises(AuthFailure) as caught:
            cookie.loads(tampered)

        assert caught.value.kind == "session"


def test_another_key_is_rejected() -> None:
    """A value signed with the transaction key is not a session."""
    other = SessionCookie(
        signing_key=AUTH_OAUTH_KEY, max_age_seconds=3600, clock=lambda: NOW
    )

    with pytest.raises(AuthFailure) as caught:
        _cookie().loads(other.dumps(_session()))

    assert caught.value.kind == "session"


def test_a_transaction_cookie_cannot_stand_in_for_a_session() -> None:
    """The two purposes have separate keys and separate salts."""
    transaction = LoginTransaction(
        state="state",
        nonce="nonce",
        code_verifier="verifier",
        return_path="/",
        issued_at=NOW,
        expires_at=NOW + timedelta(minutes=5),
    )
    value = TransactionCookie.from_config(google_config(), lambda: NOW).dumps(
        transaction
    )

    with pytest.raises(AuthFailure) as caught:
        _cookie().loads(value)

    assert caught.value.kind == "session"


def test_an_expired_session_is_rejected() -> None:
    """The absolute expiry is enforced on the server, not by Max-Age alone."""
    cookie = _cookie()
    value = cookie.dumps(_session())

    past = SessionCookie(
        signing_key=cookie.signing_key,
        max_age_seconds=cookie.max_age_seconds,
        clock=lambda: NOW + timedelta(hours=1),
    )

    with pytest.raises(AuthFailure) as caught:
        past.loads(value)

    assert caught.value.kind == "session"


def test_a_session_issued_in_the_future_is_rejected() -> None:
    """A clock-skewed or hand-written issue time is not a valid session."""
    value = _cookie().dumps(
        _session(
            issued_at=NOW + timedelta(minutes=1),
            expires_at=NOW + timedelta(minutes=30),
        )
    )

    with pytest.raises(AuthFailure) as caught:
        _cookie().loads(value)

    assert caught.value.kind == "session"


def test_a_signed_session_longer_than_the_policy_is_rejected() -> None:
    """Even a correct signature cannot stretch the one-hour maximum."""
    cookie = _cookie()
    value = cookie.dumps(
        _session(expires_at=NOW + timedelta(hours=2)),
    )

    with pytest.raises(AuthFailure) as caught:
        cookie.loads(value)

    assert caught.value.kind == "session"


@pytest.mark.parametrize(
    "payload",
    [
        {
            "subject": "sub",
            "email": "sumukh.aithal@gmail.com",
            "issued_at": NOW.isoformat(),
            "expires_at": (NOW + timedelta(hours=1)).isoformat(),
            "session_id": "sid",
            "extra": "no",
        },
        {
            "subject": "sub",
            "email": "sumukh.aithal@gmail.com",
            "issued_at": NOW.isoformat(),
            "session_id": "sid",
        },
        {
            "subject": "",
            "email": "sumukh.aithal@gmail.com",
            "issued_at": NOW.isoformat(),
            "expires_at": (NOW + timedelta(hours=1)).isoformat(),
            "session_id": "sid",
        },
        {
            "subject": "sub",
            "email": "sumukh.aithal@gmail.com",
            "issued_at": NOW.isoformat(),
            "expires_at": (NOW + timedelta(hours=1)).isoformat(),
            "session_id": 5,
        },
        {
            "subject": "sub",
            "email": "sumukh.aithal@gmail.com",
            "issued_at": "2026-10-20T09:00:00",
            "expires_at": (NOW + timedelta(hours=1)).isoformat(),
            "session_id": "sid",
        },
        {
            "subject": "sub",
            "email": "sumukh.aithal@gmail.com",
            "issued_at": "yesterday",
            "expires_at": (NOW + timedelta(hours=1)).isoformat(),
            "session_id": "sid",
        },
        {
            "subject": "sub",
            "email": "sumukh.aithal@gmail.com",
            "issued_at": NOW.isoformat(),
            "expires_at": NOW.isoformat(),
            "session_id": "sid",
        },
    ],
    ids=[
        "extra",
        "missing",
        "empty-subject",
        "non-string-id",
        "naive",
        "bad-timestamp",
        "empty-lifetime",
    ],
)
def test_a_malformed_payload_is_rejected(payload: dict[str, object]) -> None:
    """Signed but wrongly shaped is still refused."""
    with pytest.raises(AuthFailure) as caught:
        _cookie().loads(_signed(payload))

    assert caught.value.kind == "session"


def test_session_cookie_needs_a_configured_key() -> None:
    """There is no default or fallback signing key."""
    with pytest.raises(ValueError, match="session_signing_key"):
        SessionCookie.from_config(Config(), lambda: NOW)


def test_hosted_cookies_use_the_host_prefix_and_secure_flags() -> None:
    """Production gets __Host- names, Secure, HttpOnly, Lax and Path=/."""
    settings = google_config()
    flags = cookie_security(settings)

    assert session_cookie_name(settings) == SESSION_COOKIE
    assert oauth_cookie_name(settings) == OAUTH_COOKIE
    assert flags == {
        "httponly": True,
        "secure": True,
        "samesite": "lax",
        "path": "/",
    }


def test_loopback_uses_its_own_names_without_secure() -> None:
    """Plain http on 127.0.0.1 cannot set a __Host- cookie, so it does not."""
    settings = google_config(
        auth_public_origin="http://127.0.0.1:8080",
        auth_callback_url="http://127.0.0.1:8080/auth/callback",
    )

    assert local_auth(settings) is True
    assert session_cookie_name(settings) == SESSION_COOKIE_LOCAL
    assert oauth_cookie_name(settings) == OAUTH_COOKIE_LOCAL
    assert cookie_security(settings)["secure"] is False
