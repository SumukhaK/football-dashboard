"""Build the configured telemetry source."""

from __future__ import annotations

from functools import partial

from app.config import Config
from app.contract import Contract
from app.domain.clock import Clock
from app.sources.base import TelemetrySource
from app.sources.cached import CachedSource
from app.sources.fixture_source import FixtureSource


def build_source(settings: Config, contract: Contract, clock: Clock) -> TelemetrySource:
    """Return the source named in settings, wrapped in the cache."""
    inner: TelemetrySource
    if settings.source == "fixture":
        inner = FixtureSource(settings.fixture_dir, contract, now=clock())
    else:
        # Imported here so fixture-only runs never load the Google SDKs.
        from app.sources.gcp.source import GcpSource, google_readers

        inner = GcpSource(partial(google_readers, settings, contract))
    return CachedSource(inner, ttl_seconds=settings.cache_ttl_seconds, clock=clock)
