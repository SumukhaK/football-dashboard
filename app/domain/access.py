"""Frozen view models for the access page.

These belong to the domain: they describe what the page shows, with no knowledge
of FastAPI or of any telemetry source. Only hashed references ever reach them:
no email address, IP address or account id is read, let alone rendered.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.domain.models import TimeWindow
from app.domain.overview import Chart


@dataclass(frozen=True)
class OutcomeCount:
    """How many times one outcome happened."""

    outcome: str
    count: int


@dataclass(frozen=True)
class ActionCounts:
    """One account action and the counts of its outcomes."""

    action: str
    outcomes: tuple[OutcomeCount, ...]


@dataclass(frozen=True)
class AuthRow:
    """One blocked or locked-out account action, with the hashed reference.

    The action is the one the backend logged, so a sign-in lockout, a blocked
    sign-in and an account ban issued as a ``strike`` all render here.
    """

    timestamp: datetime
    action: str
    outcome: str
    user_ref: str | None


@dataclass(frozen=True)
class ClientRow:
    """One client's rejected requests and the routes they hit."""

    client_ref: str
    count: int
    routes: tuple[str, ...]


@dataclass(frozen=True)
class GuardrailRow:
    """One guardrail kind and outcome, and how often they met."""

    kind: str
    outcome: str
    count: int


@dataclass(frozen=True)
class AccessModel:
    """Everything the access page renders.

    ``guardrails`` being empty is the signal that the section is not rendered at
    all; every other section is always shown, saying so when it has nothing.
    """

    window: TimeWindow
    sign_in: tuple[OutcomeCount, ...]
    failed_sign_ins: Chart
    lockouts: tuple[AuthRow, ...]
    rate_limited: int
    rate_limit: Chart
    top_clients: tuple[ClientRow, ...]
    other_actions: tuple[ActionCounts, ...]
    guardrails: tuple[GuardrailRow, ...]
    truncated: bool = False
    limit: int = 0
