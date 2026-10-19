"""Tests for the owner policy and the typed seam to the Google provider.

The policy is the whole authorization rule: one address, verified by the
provider, compared exactly. The provider seam is structural, so the router
depends on this shape and the tests use a fake with no Google credentials.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from app.config import Config
from app.domain.auth import (
    ConsoleSession,
    LoginStart,
    LoginTransaction,
    VerifiedIdentity,
)
from app.domain.clock import Clock
from app.services.auth import AuthFailure, AuthPolicy, IdentityProvider

NOW = datetime(2026, 10, 19, 9, 0, tzinfo=UTC)
OWNER = "sumukh.aithal@gmail.com"
SESSION_ID = "4b1d0c9a5e6f47a8b2c3d4e5f6071829"


def _clock() -> datetime:
    """A clock frozen at the moment the tests reason about."""
    return NOW


def _identity(verified: Any = True, email: str = OWNER) -> VerifiedIdentity:
    """A verified Google identity for ``email``."""
    return VerifiedIdentity(
        subject="114958444175290515788", email=email, email_verified=verified
    )


def _policy(**overrides: Any) -> AuthPolicy:
    """The default policy, with named lifetimes overridden."""
    return AuthPolicy(owner_email=OWNER, **overrides)


def _session(email: str = OWNER, session_id: str = SESSION_ID) -> ConsoleSession:
    """An owner session issued now, expiring in the policy's default hour."""
    return ConsoleSession(
        subject="114958444175290515788",
        email=email,
        issued_at=NOW,
        expires_at=NOW + timedelta(seconds=3600),
        session_id=session_id,
    )


def test_only_the_verified_owner_is_allowed() -> None:
    """Google's verified flag and an exact address are both required."""
    policy = _policy()

    assert policy.allows(_identity())
    assert policy.allows(_identity(email="  Sumukh.Aithal@Gmail.COM  "))
    assert not policy.allows(_identity(email="someone.else@gmail.com"))
    assert not policy.allows(_identity(verified=False))


def test_a_string_verification_is_not_a_verified_identity() -> None:
    """The claim must be the boolean true, not the text 'true'."""
    policy = _policy()

    assert not policy.allows(_identity(verified="true"))
    assert not policy.allows(_identity(verified=1))


def test_gmail_dots_and_plus_addresses_are_never_equivalent() -> None:
    """Only lower-casing normalises an address; nothing else is folded."""
    policy = _policy()

    assert not policy.allows(_identity(email="sumukhaithal@gmail.com"))
    assert not policy.allows(_identity(email="sumukh.aithal+console@gmail.com"))


def test_the_policy_reads_the_owner_and_the_lifetimes_from_settings() -> None:
    """One configuration, read once, is what the policy enforces."""
    settings = Config(
        auth_mode="fixture",
        owner_email="Owner@Example.COM",
        session_max_age_seconds=900,
        oauth_transaction_max_age_seconds=120,
    )

    policy = AuthPolicy.from_config(settings)

    assert policy.owner_email == "owner@example.com"
    assert policy.session_max_age_seconds == 900
    assert policy.transaction_max_age_seconds == 120


def test_the_default_lifetimes_are_one_hour_and_five_minutes() -> None:
    """The console session lasts an hour; a pending sign-in lasts five minutes."""
    policy = _policy()

    assert policy.session_max_age_seconds == 3600
    assert policy.transaction_max_age_seconds == 300


def test_a_new_session_starts_the_absolute_expiry_clock() -> None:
    """The session carries who, until when, and its CSRF identifier."""
    session = _policy().new_session(_identity(), SESSION_ID, _clock)

    assert session.subject == "114958444175290515788"
    assert session.email == OWNER
    assert session.issued_at == NOW
    assert session.expires_at == NOW + timedelta(seconds=3600)
    assert session.session_id == SESSION_ID


def test_a_session_is_only_created_for_the_owner() -> None:
    """No other identity gets a session, however it reached this code."""
    with pytest.raises(AuthFailure) as refused:
        _policy().new_session(
            _identity(email="someone.else@gmail.com"), SESSION_ID, _clock
        )

    assert refused.value.kind == "identity"


def test_a_problem_names_expiry_or_identity_and_nothing_else() -> None:
    """Denials are a couple of generic categories, never a payload."""
    policy = _policy()

    assert policy.problem(_session(), NOW) is None
    assert policy.problem(_session(), NOW + timedelta(hours=1)) == "expired"
    assert policy.problem(_session(email="someone.else@gmail.com"), NOW) == "identity"
    assert policy.problem(_session(session_id=""), NOW) == "identity"


def test_a_session_that_is_validated_later_never_renews() -> None:
    """Checking a session at a later moment does not move its own clock."""
    policy = _policy()
    session = _session()

    assert policy.problem(session, NOW + timedelta(minutes=30)) is None
    assert policy.problem(session, NOW + timedelta(minutes=61)) == "expired"
    assert session.expires_at == NOW + timedelta(seconds=3600)


def test_a_transaction_is_bounded_and_bound_to_its_state() -> None:
    """State must match exactly, and the five-minute window must hold."""
    policy = _policy()
    transaction = policy.new_transaction(
        "st-8f14e45fceea167a",
        "no-4f6a1c37b90d2e58",
        "cv-a3f1c9d2b7e45068",
        "/requests",
        _clock,
    )

    assert transaction.expires_at == NOW + timedelta(seconds=300)
    assert transaction.return_path == "/requests"
    assert policy.transaction_problem(transaction, "st-8f14e45fceea167a", NOW) is None
    assert policy.transaction_problem(transaction, "st-someone-else", NOW) == "state"
    assert policy.transaction_problem(transaction, None, NOW) == "state"
    assert (
        policy.transaction_problem(
            transaction, "st-8f14e45fceea167a", NOW + timedelta(seconds=300)
        )
        == "expired"
    )


def test_a_transaction_carries_only_what_the_exchange_needs() -> None:
    """No tokens, no profile, no email: the callback does not have them yet."""
    transaction = _policy().new_transaction("st-1", "no-1", "cv-1", "/", _clock)

    assert transaction.state == "st-1"
    assert transaction.nonce == "no-1"
    assert transaction.code_verifier == "cv-1"


class FakeProvider:
    """A provider that answers from a fixed identity, as the tests need."""

    def start(self, return_path: str, clock: Clock) -> LoginStart:
        """Start a transaction and point at an example authorization URL."""
        now = clock()
        transaction = LoginTransaction(
            state="st-fake",
            nonce="no-fake",
            code_verifier="cv-fake",
            return_path=return_path,
            issued_at=now,
            expires_at=now + timedelta(seconds=300),
        )
        return LoginStart(
            transaction=transaction, authorization_url="https://example.test/auth"
        )

    def finish(
        self,
        code: str,
        state: str,
        transaction: LoginTransaction,
        clock: Clock,
    ) -> VerifiedIdentity:
        """Return the verified owner for the expected code and state."""
        if code != "the-code" or state != transaction.state:
            raise AuthFailure("provider")
        return _identity()


def test_the_provider_seam_is_anything_that_starts_and_finishes_a_login() -> None:
    """The router depends on this shape, and tests inject a fake for it."""
    provider: IdentityProvider = FakeProvider()

    start = provider.start("/requests", _clock)
    identity = provider.finish("the-code", "st-fake", start.transaction, _clock)

    assert start.transaction.return_path == "/requests"
    assert identity.email == OWNER

    with pytest.raises(AuthFailure) as refused:
        provider.finish("wrong-code", "st-fake", start.transaction, _clock)

    assert refused.value.kind == "provider"
