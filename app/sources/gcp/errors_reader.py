"""Read crash groups from Error Reporting."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import timedelta
from typing import Any, Protocol

from google.cloud import errorreporting_v1beta1 as errorreporting

from app.domain.models import ErrorGroup, TimeWindow
from app.sources.gcp.errors import guarded

Period = errorreporting.QueryTimeRange.Period
# Typed as int: the generated proto enum members are plain ints to mypy.
PERIODS: tuple[tuple[timedelta, int], ...] = (
    (timedelta(hours=1), Period.PERIOD_1_HOUR),
    (timedelta(hours=6), Period.PERIOD_6_HOURS),
    (timedelta(days=1), Period.PERIOD_1_DAY),
    (timedelta(weeks=1), Period.PERIOD_1_WEEK),
    (timedelta(days=30), Period.PERIOD_30_DAYS),
)
UNKNOWN_EXCEPTION = "unknown"


class ErrorStatsClient(Protocol):
    """The part of ErrorStatsServiceClient this reader uses."""

    def list_group_stats(
        self, request: errorreporting.ListGroupStatsRequest
    ) -> Iterable[Any]:  # Any: ErrorGroupStats or a test fake.
        """Iterate over group stats."""
        ...


def period_for(window: TimeWindow) -> int:
    """Return the smallest Error Reporting period that covers the window."""
    span = window.end - window.start
    for length, period in PERIODS:
        if span <= length:
            return period
    return Period.PERIOD_30_DAYS


def parse_exception(stack: str) -> tuple[str, str]:
    """Return (exception type, message) from the last line of a Python traceback."""
    lines = [line for line in stack.strip().splitlines() if line.strip()]
    if not lines:
        return UNKNOWN_EXCEPTION, ""
    last = lines[-1].strip()
    if ":" not in last:
        return (last or UNKNOWN_EXCEPTION), ""
    exception_type, message = last.split(":", 1)
    return exception_type.strip(), message.strip()


class ErrorsReader:
    """Lists Error Reporting groups for the service and maps them."""

    def __init__(
        self, client: ErrorStatsClient, project_id: str, service_name: str
    ) -> None:
        self._client = client
        self._project_id = project_id
        self._service_name = service_name

    def error_groups(self, window: TimeWindow) -> list[ErrorGroup]:
        """Return groups seen inside the window, most recently seen first."""
        request = errorreporting.ListGroupStatsRequest(
            project_name=f"projects/{self._project_id}",
            service_filter=errorreporting.ServiceContextFilter(
                service=self._service_name
            ),
            time_range=errorreporting.QueryTimeRange(period=period_for(window)),
        )
        stats = guarded(
            "Error Reporting", lambda: list(self._client.list_group_stats(request))
        )
        groups = [to_group(item) for item in stats]
        inside = [g for g in groups if g.last_seen >= window.start]
        return sorted(inside, key=lambda g: g.last_seen, reverse=True)


def to_group(stats: Any) -> ErrorGroup:  # Any: ErrorGroupStats or a test fake.
    """Map one ErrorGroupStats onto the domain ErrorGroup."""
    exception_type, message = parse_exception(stats.representative.message)
    return ErrorGroup(
        group_id=stats.group.group_id,
        exception_type=exception_type,
        message=message,
        count=int(stats.count),
        first_seen=stats.first_seen_time,
        last_seen=stats.last_seen_time,
        # Error Reporting only has raw URLs, which can carry IDs and query
        # strings; route templates come from app.crash events instead.
        affected_routes=(),
    )
