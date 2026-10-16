"""Tests for the shared template filters."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.templating import state_class, utc_time


def test_utc_time_formats_a_moment() -> None:
    """A moment becomes a short UTC stamp."""
    moment = datetime(2026, 10, 8, 6, 1, tzinfo=UTC)
    assert utc_time(moment) == "08 Oct 06:01 UTC"


def test_utc_time_handles_none() -> None:
    """A missing moment renders as an empty string."""
    assert utc_time(None) == ""


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        ("ok", "status-healthy"),
        ("degraded", "status-warning"),
        ("failed", "status-error"),
        ("no data", "status-none"),
        ("something new", "status-none"),
    ],
)
def test_state_class_colours_every_tile_state(state: str, expected: str) -> None:
    """Each state maps to a badge class, and an unknown one stays neutral."""
    assert state_class(state) == expected
