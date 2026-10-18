"""Builds the assistant page model from the telemetry source.

Three reads cover the page's eight sections: the answers and abstentions, the
assistant's own tool, retry and fallback lines, and the outbound dependency
calls. The dependency calls are read on their own because they are by far the
noisiest of the three — each answer makes several — and would otherwise fill the
read's limit and push the other events out of the window the page shows.
"""

from __future__ import annotations

from app.config import WINDOW_HOURS, Config
from app.domain.assistant import AssistantModel
from app.domain.clock import Clock
from app.domain.errors import SourceUnavailableError
from app.domain.models import MAX_QUERY_LIMIT, EventQuery, TelemetryEvent, TimeWindow
from app.services.assistant_answers import (
    abstention_rows,
    answered_path_rows,
    cost_summary,
    latency_rows,
    path_rows,
    slowest_answers,
    token_summary,
)
from app.services.assistant_calls import (
    fallback_rows,
    gave_up_ids,
    gave_up_link,
    model_call_rows,
    tool_rows,
    worst_dependency,
)
from app.services.events import by_event
from app.services.stats import rate
from app.services.windows import resolve_window_hours, window_for_hours
from app.sources.base import TelemetrySource

__all__ = [
    "ANSWER_EVENTS",
    "CALL_EVENTS",
    "DEPENDENCY_EVENTS",
    "WINDOW_HOURS",
    "AssistantModel",
    "AssistantService",
    "SourceUnavailableError",
]

# The answer lines, the assistant's own call lines, and the outbound calls.
ANSWER_EVENTS: tuple[str, ...] = ("assistant.answer", "assistant.abstain")
CALL_EVENTS: tuple[str, ...] = ("assistant.tool", "retry", "fallback")
DEPENDENCY_EVENTS: tuple[str, ...] = ("dependency.call",)


class AssistantService:
    """Turns a window of assistant telemetry into the assistant page model."""

    def __init__(self, source: TelemetrySource, clock: Clock, settings: Config) -> None:
        """Store the source, clock and settings the service reads through."""
        self._source = source
        self._clock = clock
        self._settings = settings

    def resolve_hours(self, hours: int | None) -> int:
        """Return the requested window size, defaulting and validating it."""
        return resolve_window_hours(hours, self._settings.default_window_hours)

    def build_for_hours(self, hours: int) -> AssistantModel:
        """Return the assistant model for the given window size in hours."""
        return self.build(window_for_hours(hours, self._clock()))

    def build(self, window: TimeWindow) -> AssistantModel:
        """Return the assistant model for the given window."""
        answers_read = self._read(window, ANSWER_EVENTS)
        calls_read = self._read(window, CALL_EVENTS)
        dependencies = self._read(window, DEPENDENCY_EVENTS)
        answers = by_event(answers_read, "assistant.answer")
        abstains = by_event(answers_read, "assistant.abstain")
        paths = path_rows(answers)
        latency = latency_rows(answers)
        model_calls = model_call_rows(dependencies, by_event(calls_read, "retry"))
        gave_up = gave_up_ids(model_calls)
        cost_total, cost_per_answer = cost_summary(answers)
        return AssistantModel(
            window=window,
            answers=len(answers),
            by_path=paths,
            answered_paths=answered_path_rows(paths, latency),
            abstentions=abstention_rows(abstains),
            abstention_rate=rate(len(abstains), len(answers)),
            latency=latency,
            tools=tool_rows(by_event(calls_read, "assistant.tool")),
            model_calls=model_calls,
            worst_dependency=worst_dependency(model_calls),
            gave_up_count=len(gave_up),
            gave_up_link=gave_up_link(gave_up, window),
            fallbacks=fallback_rows(by_event(calls_read, "fallback")),
            prompt=token_summary(answers, "prompt_tokens"),
            completion=token_summary(answers, "completion_tokens"),
            cost_total=cost_total,
            cost_per_answer=cost_per_answer,
            slowest=slowest_answers(answers),
            truncated=MAX_QUERY_LIMIT
            in (len(answers_read), len(calls_read), len(dependencies)),
            limit=MAX_QUERY_LIMIT,
        )

    def _read(
        self, window: TimeWindow, events: tuple[str, ...]
    ) -> list[TelemetryEvent]:
        """Read only the wanted event types in the window, newest first."""
        query = EventQuery(window=window, events=events, limit=MAX_QUERY_LIMIT)
        return self._source.events(query)
