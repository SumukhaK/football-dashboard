"""Creating invites exactly as the platform's ``manage_accounts invite`` does.

The domain errors the router needs are re-exported here, so the router still
imports services only.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol

from app.domain import invites
from app.domain.clock import Clock
from app.domain.errors import SourceUnavailableError
from app.domain.invites import InvalidEmailError

__all__ = [
    "InvalidEmailError",
    "InviteRecord",
    "InviteService",
    "InviteStore",
    "NewInvite",
    "SourceUnavailableError",
]

InviteRecord = dict[str, str | None]


class InviteStore(Protocol):
    """Somewhere to keep one invite record per email."""

    def save(self, email: str, record: InviteRecord) -> None:
        """Create or replace the invite for ``email``."""


@dataclass(frozen=True)
class NewInvite:
    """A just-created invite: the code to show once and when it expires."""

    code: str
    expires_at: datetime


class InviteService:
    """Makes invite codes and saves their records."""

    def __init__(
        self,
        store: InviteStore,
        clock: Clock,
        lifetime_days: int,
        new_code: Callable[[], str] = invites.new_code,
    ) -> None:
        """Save to ``store``; invites expire ``lifetime_days`` after ``clock``."""
        self._store = store
        self._clock = clock
        self._lifetime = timedelta(days=lifetime_days)
        self._new_code = new_code

    def create(self, email: str) -> NewInvite:
        """A new code for ``email``, replacing any earlier invite."""
        key = invites.normalise_email(email)
        code = self._new_code()
        expires = self._clock() + self._lifetime
        record: InviteRecord = {
            "email": key,
            "code_hash": invites.code_hash(code),
            "expires_at": expires.isoformat(),
            "redeemed_at": None,
        }
        self._store.save(key, record)
        return NewInvite(code, expires)
