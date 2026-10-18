"""Tests for the display labels services hand to templates."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.services.labels import (
    display_name,
    format_duration_ms,
    relative_time,
    window_comparison_label,
    window_label,
    window_span,
)

NOW = datetime(2026, 10, 8, 18, 0, tzinfo=UTC)


def test_display_name_raises_the_first_word_only() -> None:
    """A raw underscore name becomes a sentence-case label."""
    assert display_name("prediction_model_v1") == "Prediction model v1"
    assert display_name("model_with_tools") == "Model with tools"


def test_display_name_keeps_the_case_of_the_later_words() -> None:
    """An acronym or a code later in the name is left as the source wrote it."""
    assert display_name("workers_ai") == "Workers ai"
    assert display_name("api_v2_key") == "Api v2 key"


def test_display_name_one_word_and_digits() -> None:
    """A single word, and a word of digits, still get a label."""
    assert display_name("overview") == "Overview"
    assert display_name("v1") == "V1"
    assert display_name("404") == "404"


def test_display_name_empty_stays_empty() -> None:
    """An empty or blank name is not turned into a label."""
    assert display_name("") == ""
    assert display_name("   ") == "   "


def test_display_name_drops_empty_words() -> None:
    """Stray or doubled underscores do not leave a gap in the label."""
    assert display_name("_assistant_tool_") == "Assistant tool"
    assert display_name("model__with_tools") == "Model with tools"


def test_format_duration_below_two_seconds_is_milliseconds() -> None:
    """Under 2,000 ms the duration stays in whole milliseconds."""
    assert format_duration_ms(0) == "0 ms"
    assert format_duration_ms(386) == "386 ms"
    assert format_duration_ms(1999) == "1999 ms"


def test_format_duration_from_two_seconds_is_seconds() -> None:
    """From 2,000 ms the duration is seconds with one decimal."""
    assert format_duration_ms(2000) == "2.0 s"
    assert format_duration_ms(86100) == "86.1 s"


def test_format_duration_none_says_no_data() -> None:
    """A missing duration is named, never shown as a number."""
    assert format_duration_ms(None) == "no data"


def test_window_label_names_the_offered_windows() -> None:
    """Each offered window has the copy the page subtitle uses."""
    assert window_label(1) == "Last hour"
    assert window_label(6) == "Last 6 hours"
    assert window_label(24) == "Last 24 hours"
    assert window_label(168) == "Last 7 days"


def test_window_label_handles_a_window_outside_the_picker() -> None:
    """A window the picker does not offer still reads as a window."""
    assert window_label(3) == "Last 3 hours"


def test_window_span_names_the_picker_options() -> None:
    """The compact window span matches the picker's own labels."""
    assert window_span(1) == "1h"
    assert window_span(6) == "6h"
    assert window_span(24) == "24h"
    assert window_span(168) == "7d"


def test_window_comparison_label_names_the_window_before() -> None:
    """The subtitle compares the window with the one of the same length before."""
    assert window_comparison_label(1) == "Last hour compared with the hour before"
    assert window_comparison_label(24) == (
        "Last 24 hours compared with the 24 hours before"
    )
    assert window_comparison_label(168) == (
        "Last 7 days compared with the 7 days before"
    )


@pytest.mark.parametrize(
    ("ago", "expected"),
    [
        (timedelta(seconds=0), "0 s ago"),
        (timedelta(seconds=59), "59 s ago"),
        (timedelta(minutes=1), "1 min ago"),
        (timedelta(minutes=59), "59 min ago"),
        (timedelta(hours=1), "1 h ago"),
        (timedelta(hours=23), "23 h ago"),
        (timedelta(days=1), "1 day ago"),
        (timedelta(days=2), "2 days ago"),
    ],
)
def test_relative_time_reads_in_seconds_minutes_hours_then_days(
    ago: timedelta, expected: str
) -> None:
    """Each band has its own unit, so a row never says "0 days" or "145 h"."""
    assert relative_time(NOW - ago, NOW) == expected


def test_relative_time_of_a_future_moment_does_not_go_backwards() -> None:
    """A clock skew must not print a negative age."""
    assert relative_time(NOW + timedelta(minutes=5), NOW) == "0 s ago"
