"""Tests for the console's own identity, session and transaction models.

These are the values the sign-in flow passes between layers. They are frozen
on purpose: nothing downstream may edit an identity or stretch a session's
expiry in place, and nothing carried here is a Google token.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError, fields
from datetime import UTC, datetime, timedelta

import pytest

from app.domain.auth import (
    OAUTH_COOKIE,
    OAUTH_COOKIE_LOCAL,
    SESSION_COOKIE,
    SESSION_COOKIE_LOCAL,
    ConsoleSession,
    LoginStart,
    LoginTransaction,
    VerifiedIdentity,
)

ISSUED = datetime(2026, 10, 19, 9, 0, tzinfo=UTC)
SESSION_ID = "4b1d0c9a5e6f47a8b2c3d4e5f6071829"


def _session(issued_at: datetime = ISSUED) -> ConsoleSession:
    """A one-hour owner session issued at ``issued_at``."""
    return ConsoleSession(
        subject="114958444175290515788",
        email="sumukh.aithal@gmail.com",
        issued_at=issued_at,
        expires_at=issued_at + timedelta(hours=1),
        session_id=SESSION_ID,
    )


def _transaction(issued_at: datetime = ISSUED) -> LoginTransaction:
    """A five-minute login transaction issued at ``issued_at``."""
    return LoginTransaction(
        state="st-8f14e45fceea167a",
        nonce="no-4f6a1c37b90d2e58",
        code_verifier="cv-a3f1c9d2b7e45068",
        return_path="/requests",
        issued_at=issued_at,
        expires_at=issued_at + timedelta(minutes=5),
    )


def test_a_verified_identity_carries_no_token() -> None:
    """The provider hands over the claim it verified, and nothing else."""
    identity = VerifiedIdentity(
        subject="114958444175290515788",
        email="sumukh.aithal@gmail.com",
        email_verified=True,
    )

    assert [field.name for field in fields(identity)] == [
        "subject",
        "email",
        "email_verified",
    ]


def test_a_session_is_valid_until_its_absolute_expiry() -> None:
    """The expiry is absolute: being used recently does not extend it."""
    session = _session()

    assert session.is_valid_at(ISSUED)
    assert session.is_valid_at(ISSUED + timedelta(minutes=59, seconds=59))
    assert not session.is_valid_at(ISSUED + timedelta(hours=1))
    assert not session.is_valid_at(ISSUED + timedelta(hours=2))


def test_a_session_issued_in_the_future_is_not_valid_yet() -> None:
    """A clock that disagrees with the issuer must not widen the session."""
    session = _session()

    assert not session.is_valid_at(ISSUED - timedelta(seconds=1))


def test_a_session_cannot_be_edited_in_place() -> None:
    """Nothing downstream may stretch or rewrite a session."""
    session = _session()

    with pytest.raises(FrozenInstanceError):
        # setattr rather than assignment: a writable field would make the line
        # below legal, and the point is that this one is not.
        setattr(session, "expires_at", ISSUED + timedelta(days=1))  # noqa: B010


def test_a_transaction_is_valid_only_for_its_bounded_window() -> None:
    """A pending sign-in lasts five minutes, and not a second longer."""
    transaction = _transaction()

    assert transaction.is_valid_at(ISSUED)
    assert transaction.is_valid_at(ISSUED + timedelta(minutes=4, seconds=59))
    assert not transaction.is_valid_at(ISSUED + timedelta(minutes=5))
    assert not transaction.is_valid_at(ISSUED - timedelta(seconds=1))


def test_a_started_login_carries_the_transaction_and_the_provider_url() -> None:
    """The router sends the browser to the URL and keeps the cookie payload."""
    transaction = _transaction()
    start = LoginStart(
        transaction=transaction,
        authorization_url="https://accounts.google.com/o/oauth2/v2/auth?state=st-8f14",
    )

    assert start.transaction is transaction
    assert start.authorization_url.startswith("https://accounts.google.com/")


def test_the_cookie_names_are_host_prefixed_apart_from_local_development() -> None:
    """Production cookies carry __Host-; the loopback development ones cannot."""
    assert SESSION_COOKIE == "__Host-dashboard-session"
    assert OAUTH_COOKIE == "__Host-dashboard-oauth"
    assert SESSION_COOKIE_LOCAL == "dashboard-session"
    assert OAUTH_COOKIE_LOCAL == "dashboard-oauth"
    for name in (SESSION_COOKIE, OAUTH_COOKIE):
        assert name.startswith("__Host-")
