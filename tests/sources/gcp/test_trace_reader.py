"""Tests for TraceReader with a fake Cloud Trace client."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import pytest
from google.api_core import exceptions as api_exceptions

from app.domain.errors import SourceUnavailableError
from app.sources.gcp.trace_reader import TraceReader, span_hex

START = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)


@dataclass
class FakeSpan:
    """A v1 TraceSpan."""

    span_id: int
    parent_span_id: int
    name: str
    start_time: datetime
    end_time: datetime
    labels: Mapping[str, str] = field(default_factory=dict)


@dataclass
class FakeTrace:
    """A v1 Trace."""

    spans: list[FakeSpan]


class FakeTraceClient:
    """Returns one canned trace or raises."""

    def __init__(self, trace: FakeTrace | None = None, error: Exception | None = None):
        self.trace = trace
        self.error = error
        self.calls: list[tuple[str, str]] = []

    def get_trace(self, *, project_id: str, trace_id: str) -> FakeTrace:
        """Return the canned trace, or raise the canned error."""
        self.calls.append((project_id, trace_id))
        if self.error is not None:
            raise self.error
        assert self.trace is not None
        return self.trace


def chat_trace() -> FakeTrace:
    """A root span with one dependency child that retried."""
    root = FakeSpan(
        1, 0, "POST /v2/assistant/chat", START, START + timedelta(seconds=3)
    )
    child = FakeSpan(
        0xABC,
        1,
        "dependency.ollama_chat",
        START + timedelta(milliseconds=10),
        START + timedelta(seconds=2),
        {"attempt": "2", "retry.cause": "timeout", "retry.wait_ms": "400"},
    )
    return FakeTrace([root, child])


def test_maps_spans() -> None:
    """IDs become 16 hex characters, the root has no parent, labels map over."""
    client = FakeTraceClient(chat_trace())
    trace = TraceReader(client, "demo").trace("a" * 32)
    assert trace is not None
    assert client.calls == [("demo", "a" * 32)]
    assert trace.root.name == "POST /v2/assistant/chat"
    assert trace.root.span_id == "0000000000000001"
    child = trace.spans[1]
    assert child.span_id == "0000000000000abc"
    assert child.parent_id == trace.root.span_id
    assert child.attributes == {"attempt": "2"}
    assert child.duration_ms == 1990


def test_retry_labels_become_a_span_event() -> None:
    """Labels starting with retry. become one retry span event."""
    trace = TraceReader(FakeTraceClient(chat_trace()), "demo").trace("a" * 32)
    assert trace is not None
    (event,) = trace.spans[1].events
    assert event.name == "retry"
    assert event.attributes == {"retry.cause": "timeout", "retry.wait_ms": "400"}
    assert trace.root.events == ()


def test_not_found_gives_none() -> None:
    """An unknown trace ID returns None instead of raising."""
    client = FakeTraceClient(error=api_exceptions.NotFound("no trace"))
    assert TraceReader(client, "demo").trace("b" * 32) is None


def test_permission_denied_is_a_source_error() -> None:
    """Missing permission surfaces as a source error."""
    client = FakeTraceClient(error=api_exceptions.PermissionDenied("no"))
    with pytest.raises(SourceUnavailableError) as raised:
        TraceReader(client, "demo").trace("c" * 32)
    assert raised.value.kind == "permission_denied"


def test_span_hex_pads_to_sixteen() -> None:
    """Small IDs are zero-padded."""
    assert span_hex(255) == "00000000000000ff"
