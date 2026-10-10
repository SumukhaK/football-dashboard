"""Build a ``TelemetrySource`` from ``Config`` and a clock."""

from __future__ import annotations

from datetime import datetime

from app.config import Config
from app.contract import Contract
from app.domain.clock import Clock, system_clock
from app.sources.cached import CachedSource
from app.sources.fixture_source import FixtureSource
from app.sources.base import TelemetrySource


def build_source(settings: Config, contract: Contract, clock: Clock) -> TelemetrySource:
    """Build a ``TelemetrySource`` from ``Config`` and a clock.

    :param settings: Application settings.
    :param contract: The telemetry contract (already loaded in ``create_app``).
    :param clock: Clock for time injection; defaults to ``system_clock``.
    :returns: A ``TelemetrySource`` instance.
    """
    if clock is None:
        clock = system_clock

    if settings.source == "fixture":
        fixture_dir = settings.fixture_dir
        return CachedSource(
            FixtureSource(fixture_dir, contract, now=clock()),
            ttl_seconds=settings.cache_ttl_seconds,
            clock=clock,
        )

    # GCP source not implemented in D2; raise a clear error
    raise NotImplementedError("GCP source not available in D2")