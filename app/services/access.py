"""Builds the access page model from the telemetry source.

Sign-in outcomes, the lockouts and blocks the backend logged, the rate limiter's
rejections and the guardrail counts become the frozen models the page renders.
Guardrails are the one section that disappears when its events are absent: an
empty section would read as "nothing was refused", which we cannot know.
"""

from __future__ import annotations

from collections import Counter

from app.config import WINDOW_HOURS, Config
from app.domain.access import (
    AccessModel,
    ActionCounts,
    AuthRow,
    ClientRow,
    GuardrailRow,
    OutcomeCount,
)
from app.domain.clock import Clock
from app.domain.errors import SourceUnavailableError
from app.domain.models import MAX_QUERY_LIMIT, EventQuery, TelemetryEvent, TimeWindow
from app.domain.overview import Chart, Series
from app.services.events import by_event, text
from app.services.links import chart_label
from app.services.stats import bucket_by_interval
from app.services.windows import interval_for, resolve_window_hours, window_for_hours
from app.sources.base import TelemetrySource

__all__ = [
    "WINDOW_HOURS",
    "AccessModel",
    "AccessService",
    "SourceUnavailableError",
    "window_for_hours",
]

ACCESS_EVENTS: tuple[str, ...] = (
    "auth.event",
    "ratelimit.rejected",
    "guardrail.event",
)

SIGN_IN = "sign_in"
FAILED_OUTCOME = "failed"
REJECTED_OUTCOMES: tuple[str, ...] = ("locked_out", "blocked")
# The actions counted under "Invites and consent", in the order they are shown.
OTHER_ACTIONS: tuple[str, ...] = ("redeem_invite", "consent")
TOP_CLIENTS = 10


class AccessService:
    """Turns a window of telemetry into the access page model."""

    def __init__(self, source: TelemetrySource, clock: Clock, settings: Config) -> None:
        """Store the source, clock and settings the service reads through."""
        self._source = source
        self._clock = clock
        self._settings = settings

    def resolve_hours(self, hours: int | None) -> int:
        """Return the requested window size, defaulting and validating it."""
        return resolve_window_hours(hours, self._settings.access_default_window_hours)

    def build_for_hours(self, hours: int) -> AccessModel:
        """Return the model for the given window size in hours."""
        return self.build(window_for_hours(hours, self._clock()))

    def build(self, window: TimeWindow) -> AccessModel:
        """Return the access model for the given window."""
        events = self._read(window)
        auth = by_event(events, "auth.event")
        sign_ins = [event for event in auth if _attribute(event, "action") == SIGN_IN]
        limited = by_event(events, "ratelimit.rejected")
        return AccessModel(
            window=window,
            sign_in=_outcome_counts(sign_ins),
            failed_sign_ins=_count_chart(
                [event for event in sign_ins if _outcome(event) == FAILED_OUTCOME],
                window,
                FAILED_OUTCOME,
            ),
            lockouts=_lockouts(auth),
            rate_limited=len(limited),
            rate_limit=_count_chart(limited, window, "429"),
            top_clients=_top_clients(limited),
            other_actions=_action_counts(auth),
            guardrails=_guardrails(by_event(events, "guardrail.event")),
            truncated=len(events) == MAX_QUERY_LIMIT,
            limit=MAX_QUERY_LIMIT,
        )

    def _read(self, window: TimeWindow) -> list[TelemetryEvent]:
        """Read only the event types the page shows, newest first."""
        query = EventQuery(window=window, events=ACCESS_EVENTS, limit=MAX_QUERY_LIMIT)
        return self._source.events(query)


def _attribute(event: TelemetryEvent, name: str) -> str | None:
    """A string attribute of an event, or None when it is absent."""
    return text(event.attributes.get(name))


def _outcome(event: TelemetryEvent) -> str | None:
    """The outcome of an account event, or None when it has none."""
    return _attribute(event, "outcome")


def _outcome_counts(events: list[TelemetryEvent]) -> tuple[OutcomeCount, ...]:
    """How often each outcome happened, commonest first, ties by name."""
    counts = Counter(_outcome(event) or "unknown" for event in events)
    rows = [
        OutcomeCount(outcome=name, count=count)
        for name, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    ]
    return tuple(rows)


def _count_chart(events: list[TelemetryEvent], window: TimeWindow, name: str) -> Chart:
    """A per-interval count of the events, as a one-series chart."""
    buckets = bucket_by_interval(
        events, window, interval_for(window.end - window.start)
    )
    values = tuple(float(len(bucket.events)) for bucket in buckets)
    labels = tuple(chart_label(bucket.start, window) for bucket in buckets)
    return Chart(labels=labels, series=(Series(name=name, values=values),))


def _lockouts(auth: list[TelemetryEvent]) -> tuple[AuthRow, ...]:
    """Every blocked or locked-out account action, newest first.

    The list is not restricted to sign-ins: the backend blocks an account with a
    ``strike`` action as well, and a ban is exactly the kind of block this
    section exists to show. Only the sign-in subset feeds the counts above.
    """
    rows = [
        AuthRow(
            timestamp=event.timestamp,
            action=_attribute(event, "action") or "unknown",
            outcome=_outcome(event) or "unknown",
            user_ref=_attribute(event, "user_ref"),
        )
        for event in auth
        if _outcome(event) in REJECTED_OUTCOMES
    ]
    rows.sort(key=lambda row: row.timestamp, reverse=True)
    return tuple(rows)


def _top_clients(events: list[TelemetryEvent]) -> tuple[ClientRow, ...]:
    """The busiest rejected clients, ties sorted by client_ref for determinism."""
    grouped: dict[str, list[TelemetryEvent]] = {}
    for event in events:
        grouped.setdefault(_attribute(event, "client_ref") or "<unknown>", []).append(
            event
        )
    rows = [
        ClientRow(
            client_ref=client_ref,
            count=len(items),
            routes=tuple(
                sorted({_attribute(event, "route") or "<unknown>" for event in items})
            ),
        )
        for client_ref, items in grouped.items()
    ]
    rows.sort(key=lambda row: (-row.count, row.client_ref))
    return tuple(rows[:TOP_CLIENTS])


def _action_counts(auth: list[TelemetryEvent]) -> tuple[ActionCounts, ...]:
    """The invite and consent counts, one row per action, always both actions."""
    return tuple(
        ActionCounts(
            action=action,
            outcomes=_outcome_counts(
                [event for event in auth if _attribute(event, "action") == action]
            ),
        )
        for action in OTHER_ACTIONS
    )


def _guardrails(events: list[TelemetryEvent]) -> tuple[GuardrailRow, ...]:
    """Guardrail counts by kind and outcome, commonest first, ties by name."""
    counts = Counter(
        (
            _attribute(event, "kind") or "unknown",
            _outcome(event) or "unknown",
        )
        for event in events
    )
    rows = [
        GuardrailRow(kind=kind, outcome=outcome, count=count)
        for (kind, outcome), count in counts.items()
    ]
    rows.sort(key=lambda row: (-row.count, row.kind, row.outcome))
    return tuple(rows)
