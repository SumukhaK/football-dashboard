"""Tests for PlatformReader with a fake Cloud Logging client."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from gcp_fakes import FakeEntry, FakeLoggingClient, FakeResource
from google.api_core import exceptions as api_exceptions

from app.config import DEFAULT_PLATFORM_PATTERNS
from app.domain.errors import SourceUnavailableError
from app.domain.models import TimeWindow
from app.sources.gcp.platform_reader import PlatformReader

END = datetime(2026, 10, 8, 18, 0, tzinfo=UTC)
WINDOW = TimeWindow(start=END - timedelta(hours=24), end=END)
REVISION = FakeResource({"revision_name": "football-api-00042-wum"})


def entry(text: str, minutes_ago: int) -> FakeEntry:
    """A system log entry with text, some minutes before END."""
    return FakeEntry(
        payload=text, timestamp=END - timedelta(minutes=minutes_ago), resource=REVISION
    )


def make_reader(client: FakeLoggingClient) -> PlatformReader:
    """Build a reader with the default patterns."""
    return PlatformReader(client, "demo", "football-api", DEFAULT_PLATFORM_PATTERNS)


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
