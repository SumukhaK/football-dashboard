"""Tests for EventQuery and the domain error and clock."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.domain.clock import system_clock
from app.domain.errors import SourceUnavailableError
from app.domain.models import EventQuery, TimeWindow

WINDOW = TimeWindow(
    start=datetime(2026, 10, 8, tzinfo=UTC), end=datetime(2026, 10, 9, tzinfo=UTC)
)


def test_defaults() -> None:
    """A query with only a window asks for every event, newest 1000."""
    query = EventQuery(window=WINDOW)
    assert query.events == ()
    assert query.request_id is None
    assert query.request_ids == ()
    assert query.route is None
    assert query.min_status is None
    assert query.max_status is None
    assert query.before is None
    assert query.before_id is None
    assert query.limit == 1000


def test_request_id_and_request_ids_cannot_both_be_set() -> None:
    """One id and a set of ids are two ways to say the same filter."""
    with pytest.raises(ValueError):
        EventQuery(
            window=WINDOW, request_id="req-00000001", request_ids=("req-00000002",)
        )


def test_before_id_needs_a_cursor_timestamp() -> None:
    """A cursor id only means something alongside its timestamp."""
    with pytest.raises(ValueError):
        EventQuery(window=WINDOW, before_id="req-00000001")


def test_status_range_must_be_ordered() -> None:
    """A max_status at or below min_status cannot match anything."""
    with pytest.raises(ValueError):
        EventQuery(window=WINDOW, min_status=500, max_status=500)


@pytest.mark.parametrize("limit", [0, 5001])
def test_limit_out_of_range_is_rejected(limit: int) -> None:
    """Limits outside 1 to 5000 raise ValueError."""
    with pytest.raises(ValueError):
        EventQuery(window=WINDOW, limit=limit)


def test_query_is_hashable() -> None:
    """Queries are frozen, so the cache can use them as keys."""
    assert hash(EventQuery(window=WINDOW)) == hash(EventQuery(window=WINDOW))


def test_source_error_keeps_kind_and_detail() -> None:
    """The error exposes kind and detail for page banners."""
    error = SourceUnavailableError("quota", "too many reads")
    assert (error.kind, error.detail) == ("quota", "too many reads")
    assert "quota" in str(error)


def test_system_clock_is_utc() -> None:
    """The system clock returns an aware UTC time."""
    assert system_clock().tzinfo is UTC
