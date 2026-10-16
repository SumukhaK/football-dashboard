"""Frozen view models for the assistant page.

These belong to the domain: they describe what the page shows, with no knowledge
of FastAPI or of any telemetry source. The three tuples below are the contract's
own values, and the service keeps them in that order so two loads of the same
window render identically.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.domain.models import TimeWindow

# The answer paths the contract names, in the order the donut and legend show.
PATH_ORDER: tuple[str, ...] = ("router", "model", "model_with_tools")

# The dependencies that mean the assistant called something, in report order.
MODEL_DEPENDENCIES: tuple[str, ...] = ("ollama_chat", "ollama_embed", "workers_ai")

# The failure statuses the model-calls table names, in contract order.
FAILURE_STATUSES: tuple[str, ...] = ("timeout", "http_error", "connection_error")


@dataclass(frozen=True)
class PathAnswerRow:
    """Answers along one path and their share of all the window's answers."""

    path: str
    answers: int
    share: float | None


@dataclass(frozen=True)
class AbstentionRow:
    """How often the assistant abstained for one reason."""

    reason: str
    count: int


@dataclass(frozen=True)
class LatencyRow:
    """Answer latency percentiles for one path."""

    path: str
    answers: int
    p50_ms: float | None
    p95_ms: float | None


@dataclass(frozen=True)
class ToolRow:
    """One tool's calls, its error rate and its newest error message."""

    tool: str
    calls: int
    errors: int
    error_rate: float | None
    p95_ms: float | None
    last_error: str | None


@dataclass(frozen=True)
class StatusCount:
    """How many attempts of one dependency failed with one status."""

    status: str
    count: int


@dataclass(frozen=True)
class GaveUpRequest:
    """A request whose newest call to a dependency failed."""

    request_id: str
    link: str


@dataclass(frozen=True)
class ModelCallRow:
    """One model dependency's attempts, failures, retries and gave-up requests."""

    dependency: str
    attempts: int
    failures: tuple[StatusCount, ...]
    failure_rate: float | None
    retries: int
    gave_up: tuple[GaveUpRequest, ...]


@dataclass(frozen=True)
class FallbackRow:
    """One fallback path that was taken, and how often."""

    from_path: str
    to_path: str
    cause: str
    count: int


@dataclass(frozen=True)
class TokenSummary:
    """One token field's percentiles and total over the window."""

    p50: float | None
    p95: float | None
    total: float | None


@dataclass(frozen=True)
class SlowestAnswer:
    """One of the slowest answers, linked to its request when it has one."""

    request_id: str | None
    path: str
    tool_rounds: int
    duration_ms: float | None
    link: str


@dataclass(frozen=True)
class AssistantModel:
    """Everything the assistant page renders."""

    window: TimeWindow
    answers: int
    by_path: tuple[PathAnswerRow, ...]
    abstentions: tuple[AbstentionRow, ...]
    abstention_rate: float | None
    latency: tuple[LatencyRow, ...]
    tools: tuple[ToolRow, ...]
    model_calls: tuple[ModelCallRow, ...]
    fallbacks: tuple[FallbackRow, ...]
    prompt: TokenSummary
    completion: TokenSummary
    cost_total: float | None
    cost_per_answer: float | None
    slowest: tuple[SlowestAnswer, ...]
    truncated: bool = False
    limit: int = 0

    @property
    def usage_reported(self) -> bool:
        """Whether the window reported any tokens or cost at all."""
        return any(
            value is not None
            for value in (self.prompt.total, self.completion.total, self.cost_total)
        )

    @property
    def reported_cost(self) -> bool:
        """Whether any answer reported a cost."""
        return self.cost_total is not None
