"""Tests for PlatformReader with a fake Cloud Logging client."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from gcp_fakes import FakeEntry, FakeLoggingClient, FakeResource
from google.api_core import exceptions as api_exceptions
from google.api_core.retry import Retry

from app.config import DEFAULT_PLATFORM_PATTERNS
from app.domain.errors import SourceUnavailableError
from app.domain.models import TimeWindow
from app.sources.gcp.budget import READ_BUDGET_SECONDS, RPC_TIMEOUT_SECONDS
from app.sources.gcp.logging_reader import LoggingClient
from app.sources.gcp.platform_reader import PLATFORM_EVENT_LIMIT, PlatformReader

END = datetime(2026, 10, 8, 18, 0, tzinfo=UTC)
WINDOW = TimeWindow(start=END - timedelta(hours=24), end=END)
REVISION = FakeResource({"revision_name": "football-api-00042-wum"})


def entry(text: str, minutes_ago: int) -> FakeEntry:
    """A system log entry with text, some minutes before END."""
    return FakeEntry(
        payload=text, timestamp=END - timedelta(minutes=minutes_ago), resource=REVISION
    )


def make_reader(
    client: LoggingClient,
    *,
    monotonic: Callable[[], float] | None = None,
) -> PlatformReader:
    """Build a reader with the default patterns and an optional test clock."""
    if monotonic is None:
        return PlatformReader(client, "demo", "football-api", DEFAULT_PLATFORM_PATTERNS)
    return PlatformReader(
        client,
        "demo",
        "football-api",
        DEFAULT_PLATFORM_PATTERNS,
        monotonic=monotonic,
    )


def test_classifies_known_lines_and_ignores_others() -> None:
    """Matching lines become platform events; others are skipped."""
    client = FakeLoggingClient(
        [
            entry("Memory limit of 512 MiB exceeded with 530 MiB used.", 5),
            entry("Default STARTUP TCP probe succeeded", 6),
            entry("Starting new instance. Reason: AUTOSCALING", 60),
        ]
    )
    events = make_reader(client).platform_events(WINDOW)
    assert [e.kind for e in events] == ["out_of_memory", "instance_started"]
    assert events[0].revision == "football-api-00042-wum"
    assert "Memory limit" in events[0].message
    assert "run.googleapis.com%2Fvarlog%2Fsystem" in client.calls[0]["filter_"]


def test_missing_revision_and_timestamp() -> None:
    """No revision label gives 'unknown'; a line with no timestamp is skipped."""
    no_resource = FakeEntry(payload="Container called exit(1).", timestamp=END)
    no_time = FakeEntry(payload="Container called exit(1).", timestamp=None)
    events = make_reader(FakeLoggingClient([no_resource, no_time])).platform_events(
        WINDOW
    )
    assert [(e.kind, e.revision) for e in events] == [("container_exit", "unknown")]


def test_json_payload_is_matched_as_text() -> None:
    """Structured system entries are matched on their text form."""
    structured = FakeEntry(
        payload={"message": "failed to start and listen on port 8080"},
        timestamp=END,
        resource=REVISION,
    )
    (event,) = make_reader(FakeLoggingClient([structured])).platform_events(WINDOW)
    assert event.kind == "startup_failed"


def test_unavailable_is_a_source_error() -> None:
    """Service errors surface as a source error."""
    client = FakeLoggingClient(error=api_exceptions.ServiceUnavailable("down"))
    with pytest.raises(SourceUnavailableError) as raised:
        make_reader(client).platform_events(WINDOW)
    assert raised.value.kind == "unavailable"


def test_bounds_the_platform_read_with_timeout_and_retry() -> None:
    """The system-log pager gets one finite timeout and retry deadline."""
    client = FakeLoggingClient()
    make_reader(client, monotonic=lambda: 0.0).platform_events(WINDOW)

    call = client.calls[0]
    assert call["timeout"] == RPC_TIMEOUT_SECONDS
    assert isinstance(call["retry"], Retry)
    assert call["retry"].deadline == RPC_TIMEOUT_SECONDS
    assert call["max_results"] == PLATFORM_EVENT_LIMIT
    assert call["page_size"] == PLATFORM_EVENT_LIMIT
    assert len(client.calls) == 1


def test_an_expired_platform_budget_does_not_start_the_call() -> None:
    """A budget that is already gone fails before touching Cloud Logging."""
    client = FakeLoggingClient()
    times = iter([0.0, READ_BUDGET_SECONDS + 1.0])
    reader = make_reader(client, monotonic=lambda: next(times))

    with pytest.raises(SourceUnavailableError) as raised:
        reader.platform_events(WINDOW)

    assert raised.value.kind == "unavailable"
    assert "Cloud Logging: read budget exhausted" in raised.value.detail
    assert client.calls == []


class ExpiringPlatformEntries:
    """One system log entry, followed by an exhausted read budget."""

    def __init__(self) -> None:
        self.expired = False
        self.sent = False

    def __iter__(self) -> Iterator[Any]:
        """Return this one-shot iterator."""
        return self

    def __next__(self) -> Any:
        """Expire the clock while yielding the first entry."""
        if self.sent:
            raise StopIteration
        self.sent = True
        self.expired = True
        return entry("Container called exit(1).", 1)


class ExpiringPlatformClient:
    """Returns a pager that consumes the whole read budget while iterating."""

    def __init__(self) -> None:
        self.pager = ExpiringPlatformEntries()
        self.calls: list[dict[str, Any]] = []

    def list_entries(self, **kwargs: Any) -> Iterable[Any]:
        """Record the call and return the expiring pager."""
        self.calls.append(kwargs)
        return self.pager


def test_platform_budget_expiry_during_iteration_is_a_source_error() -> None:
    """The whole-read budget is checked after each pager item."""
    client = ExpiringPlatformClient()

    def clock() -> float:
        return READ_BUDGET_SECONDS + 1.0 if client.pager.expired else 0.0

    reader = make_reader(client, monotonic=clock)

    with pytest.raises(SourceUnavailableError) as raised:
        reader.platform_events(WINDOW)

    assert raised.value.kind == "unavailable"
    assert "Cloud Logging: read budget exhausted" in raised.value.detail
    assert len(client.calls) == 1


class FailingPlatformClient:
    """A pager that fails after yielding its first system log entry."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def list_entries(self, **kwargs: Any) -> Iterable[Any]:
        """Record the call and return a pager that fails during iteration."""
        self.calls.append(kwargs)
        return self._entries()

    @staticmethod
    def _entries() -> Iterable[Any]:
        yield entry("Container called exit(1).", 1)
        raise api_exceptions.ServiceUnavailable("pager broke")


def test_platform_pager_failure_is_a_source_error() -> None:
    """A failure after pager creation is still mapped by guarded()."""
    client = FailingPlatformClient()

    with pytest.raises(SourceUnavailableError) as raised:
        make_reader(client).platform_events(WINDOW)

    assert raised.value.kind == "unavailable"
    assert len(client.calls) == 1
