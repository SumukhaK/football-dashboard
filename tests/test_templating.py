"""Tests for the shared template filters."""

from __future__ import annotations

from datetime import UTC, datetime

from app.templating import utc_time


def test_utc_time_formats_a_moment() -> None:
    """A moment becomes a short UTC stamp."""
    moment = datetime(2026, 10, 8, 6, 1, tzinfo=UTC)
    assert utc_time(moment) == "08 Oct 06:01 UTC"


def test_utc_time_handles_none() -> None:
    """A missing moment renders as an empty string."""
    assert utc_time(None) == ""
