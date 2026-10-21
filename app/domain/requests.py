"""Frozen view models for the requests page and the request detail.

These belong to the domain: they describe what the pages show, with no knowledge
of FastAPI or of any telemetry source. Display classes and the waterfall's pixel
offsets are computed in the services, so the templates only interpolate values.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.domain.models import TimeWindow


@dataclass(frozen=True)
class StatusRange:
    """A half-open range of HTTP status codes, with the label that named it."""

    low: int
    high: int
    label: str


@dataclass(frozen=True)
class RequestFilters:
    """Every filter the requests page understands, already parsed."""

    window: TimeWindow
    hours: int
    route: str | None = None
    status: StatusRange | None = None
    event: str | None = None
    component: str | None = None
    before: datetime | None = None
    before_id: str | None = None


@dataclass(frozen=True)
class RequestRow:
    """One request in the results list.

    Every displayed value is already formatted: the relative age, the duration
    label and the error line, so the template only interpolates them.
    """

    timestamp: datetime
    relative_time: str
    method: str
    route: str
    status: int | None
    status_tone: str
    duration_label: str
    error_text: str | None
    request_id: str | None
    link: str | None
    panel_link: str | None
    open_link: str | None
    api_version: str | None = None


@dataclass(frozen=True)
class FilterChip:
    """One active filter, as a chip that names its value and can be removed."""

    field: str
    label: str
    remove_link: str


@dataclass(frozen=True)
class RequestPage:
    """The results list and everything the page needs to page onward."""

    window: TimeWindow
    hours: int
    filters: RequestFilters
    rows: tuple[RequestRow, ...]
    next_link: str | None
    truncated: bool = False


@dataclass(frozen=True)
class TimelineEntry:
    """One log line of a request, with its attributes as sorted pairs."""

    timestamp: datetime
    severity: str
    severity_tone: str
    event: str | None
    message: str
    attributes: tuple[tuple[str, str], ...]
    api_version: str | None = None
    request_id: str | None = None


@dataclass(frozen=True)
class SpanMarker:
    """A span event drawn as a marker on its span's bar."""

    name: str
    offset_ms: float
    left_pct: float
    detail: str


@dataclass(frozen=True)
class WaterfallRow:
    """One span, positioned on the trace's shared time axis."""

    depth: int
    indent_px: int
    name: str
    offset_ms: float
    duration_ms: float
    left_pct: float
    width_pct: float
    markers: tuple[SpanMarker, ...]
    title: str


@dataclass(frozen=True)
class RequestDetail:
    """Everything the request detail page renders."""

    request_id: str
    timestamp: datetime
    route: str | None
    status: int | None
    status_tone: str
    duration_ms: float | None
    revision: str | None
    error_code: str | None
    user_ref: str | None
    timeline: tuple[TimelineEntry, ...]
    waterfall: tuple[WaterfallRow, ...]
    trace_id: str | None
    trace_url: str | None
    trace_error: str | None = None
    # False when the source holds no traces at all, which is not the same as a
    # trace that failed to load: the page says which of the two it is.
    traces_available: bool = True
    cost_conversion_note: str | None = None
    api_version: str | None = None


@dataclass(frozen=True)
class RequestPanel:
    """The side panel's view of one request: a summary and its waterfall.

    The panel is the detail page's compact form, so it reuses the same trace
    rows and adds only what the list needs beside them.
    """

    request_id: str
    route: str | None
    status: int | None
    status_tone: str
    timestamp: datetime
    relative_time: str
    duration_label: str
    summary: str | None
    summary_tone: str
    waterfall: tuple[WaterfallRow, ...]
    trace_id: str | None
    trace_url: str | None
    trace_error: str | None
    traces_available: bool
    close_link: str
    api_version: str | None = None
