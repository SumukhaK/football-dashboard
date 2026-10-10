"""Read traces from Cloud Trace (v1 API)."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Protocol

from google.api_core import exceptions as api_exceptions

from app.domain.models import Span, SpanEvent, Trace
from app.sources.gcp.errors import guarded

RETRY_LABEL_PREFIX = "retry."


class TraceSpanLike(Protocol):
    """The fields of a v1 TraceSpan this reader uses."""

    @property
    def span_id(self) -> int: ...
    @property
    def parent_span_id(self) -> int: ...
    @property
    def name(self) -> str: ...
    @property
    def start_time(self) -> datetime: ...
    @property
    def end_time(self) -> datetime: ...
    @property
    def labels(self) -> Mapping[str, str]: ...


class TraceLike(Protocol):
    """A v1 Trace."""

    @property
    def spans(self) -> Iterable[TraceSpanLike]: ...


class TraceClient(Protocol):
    """The part of trace_v1.TraceServiceClient this reader uses."""

    def get_trace(self, *, project_id: str, trace_id: str) -> TraceLike:
        """Fetch one trace."""
        ...


class TraceReader:
    """Fetches one trace and maps it onto the domain model."""

    def __init__(self, client: TraceClient, project_id: str) -> None:
        self._client = client
        self._project_id = project_id

    def trace(self, trace_id: str) -> Trace | None:
        """Return the trace, or None when Cloud Trace has no such trace."""
        try:
            found = guarded(
                "Cloud Trace",
                lambda: self._client.get_trace(
                    project_id=self._project_id, trace_id=trace_id
                ),
            )
        except api_exceptions.NotFound:
            return None
        return Trace(trace_id=trace_id, spans=tuple(to_span(s) for s in found.spans))


def span_hex(span_id: int) -> str:
    """Format a v1 integer span ID as the 16 hex characters used in logs."""
    return f"{span_id:016x}"


def to_span(span: TraceSpanLike) -> Span:
    """Map one v1 span; labels become attributes, retry labels a span event."""
    labels = dict(span.labels)
    retry = {k: v for k, v in labels.items() if k.startswith(RETRY_LABEL_PREFIX)}
    attributes = {k: v for k, v in labels.items() if k not in retry}
    events = (
        (SpanEvent(name="retry", timestamp=span.start_time, attributes=retry),)
        if retry
        else ()
    )
    return Span(
        span_id=span_hex(span.span_id),
        parent_id=span_hex(span.parent_span_id) if span.parent_span_id else None,
        name=span.name,
        start=span.start_time,
        end=span.end_time,
        attributes=attributes,
        events=events,
    )
