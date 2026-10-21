"""The owner policy and the typed seam to the Google provider.

The whole authorization rule lives here: a session belongs to the owner only
when the provider verified exactly the configured address, and every session
carries an absolute expiry. Nothing in this module reads navigation, a request
header or a query parameter to decide who somebody is.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol

from app.config import SESSION_MAX_AGE_SECONDS, TRANSACTION_MAX_AGE_SECONDS, Config
from app.domain.auth import (
    ConsoleSession,
    LoginStart,
    LoginTransaction,
    VerifiedIdentity,
)
from app.domain.clock import Clock


class AuthFailure(Exception):
    """A sign-in step that failed, named only by a generic category.

    The categories feed a log line and a generic retry page. They never carry a
    provider payload, a token, or the address that was refused.
    """

    def __init__(self, kind: str) -> None:
        super().__init__(kind)
        self.kind = kind


@dataclass(frozen=True, slots=True)
class AuthPolicy:
    """Who may sign in, and how long a session or a pending sign-in lives."""

    owner_email: str
    session_max_age_seconds: int = SESSION_MAX_AGE_SECONDS
    transaction_max_age_seconds: int = TRANSACTION_MAX_AGE_SECONDS

    @classmethod
    def from_config(cls, settings: Config) -> AuthPolicy:
        """The policy a console runs with, built from its validated settings."""
        return cls(
            owner_email=settings.owner_email,
            session_max_age_seconds=settings.session_max_age_seconds,
            transaction_max_age_seconds=settings.oauth_transaction_max_age_seconds,
        )

    def allows(self, identity: VerifiedIdentity) -> bool:
        """Whether a verified identity is the owner.

        The address must match after lower-casing and nothing else: no
        wildcard, no plus-address folding and no Gmail dot folding.
        """
        return (
            identity.email_verified is True
            and _normalise(identity.email) == self.owner_email
        )

    def new_session(
        self, identity: VerifiedIdentity, session_id: str, clock: Clock
    ) -> ConsoleSession:
        """The session a freshly verified owner gets.

        The absolute expiry is computed once, here. A later request re-reads it
        from the cookie instead of extending it.
        """
        if not self.allows(identity):
            raise AuthFailure("identity")
        issued_at = clock()
        return ConsoleSession(
            subject=identity.subject,
            email=_normalise(identity.email),
            issued_at=issued_at,
            expires_at=issued_at + timedelta(seconds=self.session_max_age_seconds),
            session_id=session_id,
        )

    def problem(self, session: ConsoleSession, now: datetime) -> str | None:
        """Why a session may not be used now, or None when it is valid.

        The categories are "identity" (a missing subject or a session for
        another address) and "expired" (past the absolute expiry).
        """
        if not session.subject or not session.session_id:
            return "identity"
        if _normalise(session.email) != self.owner_email:
            return "identity"
        if not session.is_valid_at(now):
            return "expired"
        return None

    def new_transaction(
        self,
        state: str,
        nonce: str,
        code_verifier: str,
        return_path: str,
        clock: Clock,
    ) -> LoginTransaction:
        """One pending sign-in, which replaces any earlier attempt."""
        issued_at = clock()
        return LoginTransaction(
            state=state,
            nonce=nonce,
            code_verifier=code_verifier,
            return_path=return_path,
            issued_at=issued_at,
            expires_at=issued_at + timedelta(seconds=self.transaction_max_age_seconds),
        )

    def transaction_problem(
        self, transaction: LoginTransaction, state: str | None, now: datetime
    ) -> str | None:
        """Why a callback may not be trusted, or None when it may be.

        The categories are "state" (absent, empty or not the bound value) and
        "expired" (past the five-minute window).
        """
        if not state or state != transaction.state:
            return "state"
        if not transaction.is_valid_at(now):
            return "expired"
        return None


def _normalise(email: str) -> str:
    """The comparison form of an address: trimmed and lower-cased, no more."""
    return email.strip().lower()


class IdentityProvider(Protocol):
    """The seam to Google: start a sign-in, then verify what came back.

    The adapter behind this owns every network call and every piece of library
    validation, so the routers stay thin and the tests can run a fake provider
    without a Google credential. D9.2 supplies the Google implementation.

    The seam is asynchronous because the supported Authlib flow is; the rest of
    this console's services stay synchronous and are called from the routes that
    need them. The adapter holds its own injected clock.
    """

    async def start(self, return_path: str) -> LoginStart:
        """Build the signed transaction and the Google authorization URL."""
        ...

    async def finish(
        self,
        code: str,
        state: str,
        transaction: LoginTransaction,
    ) -> VerifiedIdentity:
        """Exchange the code and return the verified identity, or raise."""
        ...
