"""Builders and fakes shared by the assistant service tests.

Every builder takes the moment first and then the contract's own field names, so
a test reads like the log line it stands for. The fake sources are small: the
arithmetic is checked on hand-written lists, and the fixture source is used for
the one test that proves the committed sample day adds up.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

from app.config import REPO_ROOT, Config
from app.contract import load_contract
from app.domain.models import (
    ALL_CAPABILITIES,
    ErrorGroup,
    EventQuery,
    PlatformEvent,
    SourceCapabilities,
    TelemetryEvent,
    TimeWindow,
    Trace,
)
from app.services.assistant import AssistantService
from app.sources.base import TelemetrySource
from app.sources.filtering import select_events
from app.sources.fixture_source import FixtureSource

NOW = datetime(2026, 10, 8, 18, 0, tzinfo=UTC)
REQUEST = "ae97ba94d0eda82f8f6d05584ef8aa38"


def answer_line(
    moment: datetime,
    path: str = "model",
    duration_ms: float | None = 1000,
    request_id: str | None = REQUEST,
    tool_rounds: int = 0,
    prompt_tokens: int | None = 100,
    completion_tokens: int | None = 20,
    cost_usd: float | None = None,
    top_score: float | None = 0.7,
) -> TelemetryEvent:
    """Build an assistant.answer line with the contract's fields."""
    return TelemetryEvent(
        timestamp=moment,
        severity="INFO",
        event="assistant.answer",
        message="answered",
        request_id=request_id,
        trace_id=None,
        span_id=None,
        revision=None,
        attributes={
            "path": path,
            "question_chars": 40,
            "retrieved_count": 3,
            "top_score": top_score,
            "confidence": 0.8,
            "tool_rounds": tool_rounds,
            "model": "qwen2.5:7b-instruct",
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "cost_usd": cost_usd,
            "duration_ms": duration_ms,
        },
    )


def abstain_line(
    moment: datetime, reason: str | None = "low_score", request_id: str | None = REQUEST
) -> TelemetryEvent:
    """Build an assistant.abstain line."""
    return TelemetryEvent(
        timestamp=moment,
        severity="INFO",
        event="assistant.abstain",
        message="abstained",
        request_id=request_id,
        trace_id=None,
        span_id=None,
        revision=None,
        attributes={"reason": reason},
    )


def tool_line(
    moment: datetime,
    tool: str = "predict_match",
    status: str = "ok",
    duration_ms: float = 10,
    error: str | None = None,
    request_id: str | None = REQUEST,
) -> TelemetryEvent:
    """Build an assistant.tool line."""
    return TelemetryEvent(
        timestamp=moment,
        severity="WARNING" if status == "error" else "INFO",
        event="assistant.tool",
        message=f"tool {tool} {status}",
        request_id=request_id,
        trace_id=None,
        span_id=None,
        revision=None,
        attributes={
            "tool": tool,
            "status": status,
            "duration_ms": duration_ms,
            "error": error,
        },
    )


def call_line(
    moment: datetime,
    dependency: str = "ollama_chat",
    status: str | None = "ok",
    attempt: int = 1,
    duration_ms: float = 100,
    request_id: str | None = REQUEST,
) -> TelemetryEvent:
    """Build a dependency.call line."""
    return TelemetryEvent(
        timestamp=moment,
        severity="WARNING" if status != "ok" else "INFO",
        event="dependency.call",
        message=f"{dependency} {status}",
        request_id=request_id,
        trace_id=None,
        span_id=None,
        revision=None,
        attributes={
            "dependency": dependency,
            "operation": "chat",
            "status": status,
            "http_status": None,
            "attempt": attempt,
            "duration_ms": duration_ms,
        },
    )


def retry_line(
    moment: datetime,
    dependency: str = "ollama_chat",
    attempt: int = 1,
    max_attempts: int = 3,
    request_id: str | None = REQUEST,
) -> TelemetryEvent:
    """Build a retry line."""
    return TelemetryEvent(
        timestamp=moment,
        severity="WARNING",
        event="retry",
        message=f"retrying {dependency}",
        request_id=request_id,
        trace_id=None,
        span_id=None,
        revision=None,
        attributes={
            "dependency": dependency,
            "operation": "chat",
            "attempt": attempt,
            "max_attempts": max_attempts,
            "wait_ms": 500,
            "cause": "timeout",
        },
    )


def fallback_line(
    moment: datetime,
    from_path: str = "tool_calling",
    to_path: str = "answer_without_tools",
    cause: str = "tool_round_limit",
    request_id: str | None = REQUEST,
) -> TelemetryEvent:
    """Build a fallback line."""
    return TelemetryEvent(
        timestamp=moment,
        severity="WARNING",
        event="fallback",
        message=f"{from_path} to {to_path}",
        request_id=request_id,
        trace_id=None,
        span_id=None,
        revision=None,
        attributes={"from_path": from_path, "to_path": to_path, "cause": cause},
    )


class ListSource:
    """An in-test telemetry source backed by a fixed event list."""

    def __init__(self, events: Sequence[TelemetryEvent]) -> None:
        self._events = list(events)

    def events(self, query: EventQuery) -> list[TelemetryEvent]:
        """Return the stored events that match the query, newest first."""
        return select_events(self._events, query)

    def trace(self, trace_id: str) -> Trace | None:
        """There are no traces in the fake."""
        return None

    def error_groups(self, window: TimeWindow) -> list[ErrorGroup]:
        """There are no error groups in the fake."""
        return []

    def platform_events(self, window: TimeWindow) -> list[PlatformEvent]:
        """There are no platform events in the fake."""
        return []

    def capabilities(self) -> SourceCapabilities:
        """Say every query can be answered; the fake is not a local log file."""
        return ALL_CAPABILITIES


class SpySource(ListSource):
    """A list source that also records every query it is asked."""

    def __init__(self, events: Sequence[TelemetryEvent] = ()) -> None:
        super().__init__(events)
        self.queries: list[EventQuery] = []

    def events(self, query: EventQuery) -> list[TelemetryEvent]:
        """Record the query and answer like the list source."""
        self.queries.append(query)
        return super().events(query)


class FullSource(ListSource):
    """A source that always answers one read with exactly its limit."""

    def __init__(self, event: TelemetryEvent | None = None) -> None:
        self._event = event or answer_line(NOW - timedelta(minutes=1))

    def events(self, query: EventQuery) -> list[TelemetryEvent]:
        """Return exactly the query's limit, so the service flags truncation."""
        return [self._event] * query.limit


def make_service(source: TelemetrySource, now: datetime = NOW) -> AssistantService:
    """An assistant service over the given source with a fixed clock."""
    return AssistantService(source, lambda: now, Config())


def fixture_service() -> AssistantService:
    """An assistant service over the committed fixtures with a fixed clock."""
    contract = load_contract()
    source = FixtureSource(REPO_ROOT / "fixtures", contract, now=NOW)
    return make_service(source)
