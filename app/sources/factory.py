"""Build the configured telemetry and crash sources."""

from __future__ import annotations

from functools import partial

from app.config import Config
from app.contract import Contract
from app.domain.clock import Clock
from app.sources.base import CrashSource, TelemetrySource
from app.sources.cached import CachedCrashSource, CachedSource
from app.sources.fixture_crashes import FixtureCrashSource
from app.sources.fixture_source import FixtureSource
from app.sources.local_log_source import LocalLogSource


def build_source(settings: Config, contract: Contract, clock: Clock) -> TelemetrySource:
    """Return the source named in settings, wrapped in the cache."""
    inner: TelemetrySource
    if settings.source == "fixture":
        inner = FixtureSource(settings.fixture_dir, contract, now=clock())
    elif settings.source == "local":
        inner = LocalLogSource(
            settings.local_log_file(),
            settings.local_log_max_bytes,
            contract,
            clock,
        )
    else:
        # Imported here so fixture-only runs never load the Google SDKs.
        from app.sources.gcp.source import GcpSource, google_readers

        inner = GcpSource(partial(google_readers, settings, contract))
    return CachedSource(inner, ttl_seconds=settings.cache_ttl_seconds, clock=clock)


def build_crash_source(settings: Config, clock: Clock) -> CrashSource | None:
    """Return the cached crash source, or None when the crashes page is off."""
    if not settings.crashes_enabled:
        return None
    inner: CrashSource
    if settings.source == "fixture":
        inner = FixtureCrashSource(settings.fixture_dir, now=clock())
    else:
        # Imported here so fixture-only runs never load the Google SDKs.
        from app.sources.gcp.crashlytics_reader import (
            BigQueryCrashSource,
            bigquery_client,
        )

        project = settings.crashlytics_project_id or ""
        inner = BigQueryCrashSource(
            partial(bigquery_client, project, settings.crashlytics_location),
            f"{project}.{settings.crashlytics_dataset}.{settings.crashlytics_table}",
            settings.crashlytics_location,
            settings.crashlytics_max_bytes_billed,
        )
    return CachedCrashSource(inner, settings.cache_ttl_seconds, clock)
