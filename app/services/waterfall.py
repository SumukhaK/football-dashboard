"""Builds the trace waterfall geometry for the request detail page.

Pure: it takes one ``Trace`` and returns rows positioned on a shared axis, so the
template and the browser only interpolate the pre-computed percentages. The walk
is iterative and remembers what it has drawn, so a span that lists itself as its
own parent cannot loop.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from app.domain.models import Span, SpanEvent, Trace
from app.domain.requests import SpanMarker, WaterfallRow

# How far one level of nesting indents a row, in pixels.
INDENT_PX = 12


def build_waterfall(trace: Trace) -> list[WaterfallRow]:
    """Order a trace's spans and place each one on the shared time axis."""
    spans = list(trace.spans)
    if not spans:
        return []
    origin = min(span.start for span in spans)
    span_ms = (max(span.end for span in spans) - origin).total_seconds() * 1000.0
    return [_row(span, depth, origin, span_ms) for depth, span in _ordered(spans)]


def _ordered(spans: list[Span]) -> list[tuple[int, Span]]:
    """Depth-first order: parents before children, siblings by start then id."""
    known = {span.span_id for span in spans}
    children = _children(spans, known)
    order: list[tuple[int, Span]] = []
    seen: set[str] = set()
    stack = [(0, span) for span in reversed(_by_start(children.get(None)))]
    while stack:
        depth, span = stack.pop()
        if span.span_id in seen:
            continue
        seen.add(span.span_id)
        order.append((depth, span))
        stack.extend(
            (depth + 1, child)
            for child in reversed(_by_start(children.get(span.span_id)))
        )
    return order


def _children(spans: list[Span], known: set[str]) -> dict[str | None, list[Span]]:
    """Group spans by parent, treating a missing parent as the root level."""
    children: dict[str | None, list[Span]] = {}
    for span in spans:
        parent = span.parent_id if span.parent_id in known else None
        children.setdefault(parent, []).append(span)
    return children


def _by_start(spans: list[Span] | None) -> list[Span]:
    """Siblings ordered by start, then id, so the order is deterministic."""
    return sorted(spans or (), key=lambda span: (span.start, span.span_id))


def _row(span: Span, depth: int, origin: datetime, span_ms: float) -> WaterfallRow:
    """Place one span on the axis, with its span events as markers."""
    offset_ms = (span.start - origin).total_seconds() * 1000.0
    duration_ms = float(span.duration_ms)
    return WaterfallRow(
        depth=depth,
        indent_px=depth * INDENT_PX,
        name=span.name,
        offset_ms=offset_ms,
        duration_ms=duration_ms,
        left_pct=_pct(offset_ms, span_ms),
        width_pct=_pct(duration_ms, span_ms) if span_ms else 100.0,
        markers=tuple(_marker(event, origin, span_ms) for event in span.events),
        title=_title(span.attributes),
    )


def _marker(event: SpanEvent, origin: datetime, span_ms: float) -> SpanMarker:
    """One span event as a marker, positioned relative to the trace start."""
    offset_ms = (event.timestamp - origin).total_seconds() * 1000.0
    return SpanMarker(
        name=event.name,
        offset_ms=offset_ms,
        left_pct=_pct(offset_ms, span_ms),
        detail=_title(event.attributes),
    )


def _title(attributes: Mapping[str, Any]) -> str:
    """An attribute map as a one-line, sorted hover title."""
    return ", ".join(
        f"{key}={'null' if value is None else value}"
        for key, value in sorted(attributes.items())
    )


def _pct(value_ms: float, span_ms: float) -> float:
    """A value as a percentage of the trace span, or zero for a zero-length trace."""
    return value_ms / span_ms * 100.0 if span_ms else 0.0
