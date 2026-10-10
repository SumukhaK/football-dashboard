"""Tests for GcpSource delegation and lazy client creation."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from gcp_fakes import FakeLoggingClient
from google.auth import exceptions as auth_exceptions

from app.config import DEFAULT_PLATFORM_PATTERNS
from app.contract import load_contract
from app.domain.errors import SourceUnavailableError
from app.domain.models import EventQuery, TimeWindow
from app.sources.gcp.errors_reader import ErrorsReader
from app.sources.gcp.logging_reader import LoggingReader
from app.sources.gcp.platform_reader import PlatformReader
from app.sources.gcp.source import GcpReaders, GcpSource
from app.sources.gcp.trace_reader import TraceReader

END = datetime(2026, 10, 8, 18, 0, tzinfo=UTC)
WINDOW = TimeWindow(start=END - timedelta(hours=1), end=END)


class EmptyTraceClient:
    """Always answers with an empty trace."""

    def get_trace(self, *, project_id: str, trace_id: str) -> Any:
        """Return a trace with no spans."""
        return type("T", (), {"spans": []})()


class EmptyErrorsClient:
    """Always answers with no groups."""

    def list_group_stats(self, request: Any) -> Any:
        """Return no groups."""
        return iter([])


def readers(log_client: FakeLoggingClient) -> GcpReaders:
    """Readers over fake clients."""
    return GcpReaders(
        logging=LoggingReader(log_client, load_contract(), "football-api", 1000),
        traces=TraceReader(EmptyTraceClient(), "demo"),
        errors=ErrorsReader(EmptyErrorsClient(), "demo", "football-api"),
        platform=PlatformReader(
            log_client, "demo", "football-api", DEFAULT_PLATFORM_PATTERNS
        ),
    )


def test_delegates_each_method_and_builds_readers_once() -> None:
    """Each protocol method goes to its reader; readers are built on first use."""
    builds: list[int] = []
    log_client = FakeLoggingClient()

    def build() -> GcpReaders:
        builds.append(1)
        return readers(log_client)

    source = GcpSource(build)
    assert builds == []
    assert source.events(EventQuery(window=WINDOW)) == []
    assert source.platform_events(WINDOW) == []
    assert source.error_groups(WINDOW) == []
    trace = source.trace("a" * 32)
    assert trace is not None and trace.spans == ()
    assert builds == [1]
    assert len(log_client.calls) == 2


def test_missing_credentials_is_a_source_error() -> None:
    """No Application Default Credentials surfaces as permission_denied."""

    def build() -> GcpReaders:
        raise auth_exceptions.DefaultCredentialsError("no ADC")

    with pytest.raises(SourceUnavailableError) as raised:
        GcpSource(build).events(EventQuery(window=WINDOW))
    assert raised.value.kind == "permission_denied"
