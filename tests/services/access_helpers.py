"""Fakes and builders shared by the access service tests.

The fixture-scenario tests use :func:`fixture_service` (a fixed clock keeps the
fixture shift deterministic); the arithmetic tests build their own events so the
hand-computed numbers stay readable.
"""

from __future__ import annotations

from datetime import datetime

from app.config import REPO_ROOT, Config
from app.contract import load_contract
from app.domain.models import TelemetryEvent
from app.services.access import AccessService
from app.sources.base import TelemetrySource
from app.sources.fixture_source import FixtureSource
from tests.services.data_jobs_helpers import NOW, ListSource, line, moment


def make_service(source: TelemetrySource, now: datetime = NOW) -> AccessService:
    """An access service over the given source with a fixed clock."""
    return AccessService(source, lambda: now, Config())


def fixture_service() -> AccessService:
    """An access service over the committed fixtures, fixed clock."""
    source = FixtureSource(REPO_ROOT / "fixtures", load_contract(), now=NOW)
    return make_service(source)


def auth_line(
    at: datetime,
    action: str = "sign_in",
    outcome: str = "ok",
    user_ref: str | None = None,
) -> TelemetryEvent:
    """Build an auth.event."""
    return line(at, "auth.event", action=action, outcome=outcome, user_ref=user_ref)


def ratelimit_line(
    at: datetime,
    client_ref: str = "9e4c5aabbde6c9d3",
    route: str = "/v2/predict",
    retry_after_s: int = 30,
) -> TelemetryEvent:
    """Build a ratelimit.rejected event."""
    return line(
        at,
        "ratelimit.rejected",
        route=route,
        client_ref=client_ref,
        retry_after_s=retry_after_s,
    )


def guardrail_line(
    at: datetime, kind: str = "prompt_injection", outcome: str = "blocked"
) -> TelemetryEvent:
    """Build a guardrail.event."""
    return line(at, "guardrail.event", kind=kind, outcome=outcome)


__all__ = [
    "NOW",
    "ListSource",
    "auth_line",
    "fixture_service",
    "guardrail_line",
    "make_service",
    "moment",
    "ratelimit_line",
]
