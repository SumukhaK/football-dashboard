"""IST chart labels must not move UTC windows or the observations in them."""

from datetime import UTC, datetime, timedelta

import pytest

from app.domain.models import TimeWindow
from app.services.links import chart_label

from .overview_helpers import ListSource, make_service, request_line


@pytest.mark.parametrize(("hours", "expected"), [(1, "00:15"), (168, "21 Oct 00:15")])
def test_chart_labels_use_the_ist_date_and_clock(hours: int, expected: str) -> None:
    """The same instant labels the next India day for short and long windows."""
    moment = datetime(2026, 10, 20, 18, 45, tzinfo=UTC)
    window = TimeWindow(moment - timedelta(hours=hours), moment)
    assert chart_label(moment, window) == expected
    assert window.end.isoformat() == "2026-10-20T18:45:00+00:00"


def test_chart_labels_cross_ist_midnight_without_rebucketing() -> None:
    """Only labels change: the UTC buckets still count each request once."""
    start = datetime(2026, 10, 20, 18, 29, tzinfo=UTC)
    end = start + timedelta(minutes=3)
    model = make_service(
        ListSource(
            [request_line(start, 200), request_line(end - timedelta(seconds=1), 200)]
        ),
        end,
    ).build(TimeWindow(start, end))
    assert model.traffic.labels == ("23:59", "00:00", "00:01")
    assert sum(v or 0 for line in model.traffic.series for v in line.values) == 2
    assert model.latency.labels == model.traffic.labels
    assert all(line.labels == model.traffic.labels for line in model.sparklines)
