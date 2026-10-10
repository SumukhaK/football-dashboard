"""Tests for ErrorsReader with a fake Error Reporting client."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from google.api_core import exceptions as api_exceptions
from google.cloud import errorreporting_v1beta1 as errorreporting

from app.domain.errors import SourceUnavailableError
from app.domain.models import TimeWindow
from app.sources.gcp.errors_reader import ErrorsReader, parse_exception, period_for

END = datetime(2026, 10, 8, 18, 0, tzinfo=UTC)
Period = errorreporting.QueryTimeRange.Period
STACK = (
    "Traceback (most recent call last):\n"
    '  File "main.py", line 3, in handler\n'
    "KeyError: 'team'\n"
)


def group_stats(group_id: str, last_seen: datetime) -> Any:
    """Build an object shaped like ErrorGroupStats."""
    return SimpleNamespace(
        group=SimpleNamespace(group_id=group_id),
        count=3,
        first_seen_time=last_seen - timedelta(hours=2),
        last_seen_time=last_seen,
        representative=SimpleNamespace(message=STACK),
    )


class FakeErrorStatsClient:
    """Records the request and returns canned stats or raises."""

    def __init__(self, stats: list[Any] | None = None, error: Exception | None = None):
        self.stats = stats or []
        self.error = error
        self.requests: list[errorreporting.ListGroupStatsRequest] = []

    def list_group_stats(self, request: errorreporting.ListGroupStatsRequest) -> Any:
        """Return the canned stats, or raise the canned error."""
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        return iter(self.stats)


def window(hours: float) -> TimeWindow:
    """A window of the given length ending at END."""
    return TimeWindow(start=END - timedelta(hours=hours), end=END)


@pytest.mark.parametrize(
    ("hours", "period"),
    [
        (1, Period.PERIOD_1_HOUR),
        (2, Period.PERIOD_6_HOURS),
        (24, Period.PERIOD_1_DAY),
        (25, Period.PERIOD_1_WEEK),
        (24 * 30, Period.PERIOD_30_DAYS),
        (24 * 40, Period.PERIOD_30_DAYS),
    ],
)
def test_period_is_smallest_covering(hours: float, period: int) -> None:
    """The smallest Error Reporting period that covers the window is used."""
    assert period_for(window(hours)) == period


def test_parse_exception() -> None:
    """The type and message come from the traceback's last line."""
    assert parse_exception(STACK) == ("KeyError", "'team'")
    assert parse_exception("") == ("unknown", "")
    assert parse_exception("SystemExit") == ("SystemExit", "")


def test_maps_groups_and_request() -> None:
    """Groups map onto ErrorGroup; the request names project, service, period."""
    client = FakeErrorStatsClient([group_stats("g1", END - timedelta(minutes=5))])
    groups = ErrorsReader(client, "demo", "football-api").error_groups(window(24))
    (group,) = groups
    assert (group.group_id, group.exception_type, group.message) == (
        "g1",
        "KeyError",
        "'team'",
    )
    assert group.count == 3
    assert group.affected_routes == ()
    request = client.requests[0]
    assert request.project_name == "projects/demo"
    assert request.service_filter.service == "football-api"
    assert request.time_range.period == Period.PERIOD_1_DAY


def test_groups_last_seen_before_window_are_dropped() -> None:
    """A period wider than the window can return old groups; they are dropped."""
    stats = [
        group_stats("old", END - timedelta(hours=5)),
        group_stats("new", END - timedelta(minutes=1)),
    ]
    groups = ErrorsReader(FakeErrorStatsClient(stats), "demo", "x").error_groups(
        window(2)
    )
    assert [g.group_id for g in groups] == ["new"]


def test_quota_error_is_a_source_error() -> None:
    """Quota errors surface as a source error."""
    client = FakeErrorStatsClient(error=api_exceptions.ResourceExhausted("slow"))
    with pytest.raises(SourceUnavailableError) as raised:
        ErrorsReader(client, "demo", "x").error_groups(window(1))
    assert raised.value.kind == "quota"
