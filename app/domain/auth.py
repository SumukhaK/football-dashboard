"""The console's own sign-in: identity, session and login-transaction values.

These are the values the Google sign-in flow passes between layers. They are
frozen dataclasses, so nothing downstream of the provider can edit an identity
or stretch a session's expiry in place, and nothing carried here is a token:
the provider discards Google's access, refresh and ID tokens at the boundary.

See guide/D9-owner-login.md and guide/adr/001-owner-google-login.md.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

# Production cookies are __Host- prefixed, which a browser only sets for Secure,
# Path=/ and no Domain. Plain HTTP on loopback cannot use that prefix, so the
# explicit local mode has its own names. The two purposes are signed with
# different keys as well, so a pending-login cookie can never be offered as a
# session.
SESSION_COOKIE = "__Host-dashboard-session"
OAUTH_COOKIE = "__Host-dashboard-oauth"
SESSION_COOKIE_LOCAL = "dashboard-session"
OAUTH_COOKIE_LOCAL = "dashboard-oauth"


@dataclass(frozen=True, slots=True)
class VerifiedIdentity:
    """A Google account the provider verified, stripped of every token."""

    subject: str
    email: str
    email_verified: bool


@dataclass(frozen=True, slots=True)
class ConsoleSession:
    """One signed-in session: who, until when, and its CSRF identifier."""

    subject: str
    email: str
    issued_at: datetime
    expires_at: datetime
    session_id: str

    def is_valid_at(self, now: datetime) -> bool:
        """Whether this session may be used at ``now``.

        The issue and expiry times travel in the signed cookie, so paging,
        refreshing or restoring a page cannot renew either of them: a session
        past its absolute expiry stays expired however recently it was used.
        """
        return self.issued_at <= now < self.expires_at


@dataclass(frozen=True, slots=True)
class LoginTransaction:
    """One pending sign-in: the state, nonce and PKCE verifier to check."""

    state: str
    nonce: str
    code_verifier: str
    return_path: str
    issued_at: datetime
    expires_at: datetime

    def is_valid_at(self, now: datetime) -> bool:
        """Whether this transaction may still be completed at ``now``."""
        return self.issued_at <= now < self.expires_at


@dataclass(frozen=True, slots=True)
class LoginStart:
    """A started transaction and the provider URL to send the browser to."""

    transaction: LoginTransaction
    authorization_url: str
