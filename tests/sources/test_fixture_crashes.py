"""Tests for FixtureCrashSource."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.config import REPO_ROOT
from app.domain.models import TimeWindow
from app.sources.fixture_crashes import FixtureCrashSource

NOW = datetime(2026, 10, 16, 12, 0, tzinfo=UTC)
WEEK = TimeWindow(start=NOW - timedelta(days=7), end=NOW + timedelta(minutes=1))


def _source() -> FixtureCrashSource:
    """The committed sample crashes, shifted to NOW."""
    return FixtureCrashSource(REPO_ROOT / "fixtures", now=NOW)


def test_sample_week_is_shifted_to_now_newest_first() -> None:
    """The newest sample event lands on now and the list is newest first."""
    events = _source().crash_events(WEEK, 1000)
    assert len(events) == 16
    assert events[0].timestamp == NOW
    assert events == sorted(events, key=lambda e: e.timestamp, reverse=True)
    assert {e.error_type for e in events} == {"FATAL", "NON_FATAL", "ANR"}


def test_limit_and_window_are_applied() -> None:
    """Only events in [start, end) come back, at most limit of them."""
    source = _source()
    assert len(source.crash_events(WEEK, 2)) == 2
    later = TimeWindow(start=NOW + timedelta(hours=1), end=NOW + timedelta(hours=2))
    assert source.crash_events(later, 1000) == []


def test_issue_events_are_one_issue_with_frames() -> None:
    """issue_events narrows to one issue and keeps the stack frames."""
    source = _source()
    issue_id = source.crash_events(WEEK, 1)[0].issue_id
    events = source.issue_events(issue_id, WEEK, 1000)
    assert events and {e.issue_id for e in events} == {issue_id}
    assert events[0].exceptions[0].frames
