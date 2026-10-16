"""Tests for the overview's component tiles and freshness grades.

These use the committed fixtures for the tile grades (a fixed clock keeps them
deterministic) and :class:`ListSource` for the empty, limit and null cases.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.domain.models import MAX_QUERY_LIMIT, TimeWindow
from app.domain.overview import TileState

from .overview_helpers import (
    NOW,
    FullSource,
    ListSource,
    StormSource,
    by_key,
    by_name,
    degraded_line,
    fixture_service,
    freshness_line,
    load_line,
    make_service,
)


def test_assistant_tile_is_failed_before_the_recovery() -> None:
    """The failed assistant load from the fixtures shows as a red tile."""
    window = TimeWindow(
        start=datetime(2026, 10, 7, 18, 0, tzinfo=UTC),
        end=datetime(2026, 10, 8, 4, 30, tzinfo=UTC),
    )
    model = fixture_service().build(window)

    assistant = by_name(model.tiles, "assistant")
    assert assistant.state is TileState.FAILED
    assert "Ollama" in assistant.detail


def test_refresh_tile_is_amber_after_a_failed_run() -> None:
    """A last failed refresh with an older success is the amber tile."""
    window = TimeWindow(
        start=datetime(2026, 10, 7, 18, 0, tzinfo=UTC),
        end=datetime(2026, 10, 8, 4, 30, tzinfo=UTC),
    )
    model = fixture_service().build(window)

    refresh = by_name(model.tiles, "daily_refresh")
    assert refresh.state is TileState.DEGRADED
    assert "503" in refresh.detail


def test_recovered_window_shows_amber_assistant_and_stale_data() -> None:
    """After the second revision the assistant is amber and data is stale."""
    model = fixture_service().build(TimeWindow.last_hours(24, NOW))

    received = by_name(model.tiles, "assistant")
    assert received.state is TileState.DEGRADED
    assert received.degraded_count == 2

    freshness = by_name(model.tiles, "data_freshness")
    assert freshness.state is TileState.FAILED


def test_empty_window_has_no_data_tiles_and_no_rates() -> None:
    """Nothing in the window means grey tiles and None numbers, not crashes."""
    now = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)
    window = TimeWindow(start=now - timedelta(hours=1), end=now)
    model = make_service(ListSource([]), now).build(window)

    assert model.tiles
    assert all(tile.state is TileState.NO_DATA for tile in model.tiles)
    assert by_key(model.headlines, "error_rate").value is None
    assert by_key(model.headlines, "p95_latency").value is None
    assert by_key(model.headlines, "requests").value == 0


def test_short_window_still_grades_the_tiles() -> None:
    """A one-hour window grades a failed load from the lookback, not grey."""
    now = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)
    window = TimeWindow(start=now - timedelta(hours=1), end=now)
    load = load_line(
        now - timedelta(hours=2), "assistant", status="failed", reason="boom"
    )
    model = make_service(ListSource([load]), now).build(window)

    tile = by_name(model.tiles, "assistant")
    assert tile.state is TileState.FAILED
    assert "boom" in tile.detail


def test_degraded_outside_the_window_is_not_counted() -> None:
    """The degraded count is limited to the window, not the lookback."""
    now = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)
    window = TimeWindow(start=now - timedelta(hours=1), end=now)
    events = [
        load_line(now - timedelta(hours=2), "assistant", status="ok"),
        degraded_line(now - timedelta(hours=2), "assistant"),
    ]
    model = make_service(ListSource(events), now).build(window)

    tile = by_name(model.tiles, "assistant")
    assert tile.state is TileState.OK
    assert tile.degraded_count == 0
    assert tile.link is None


def test_degraded_without_any_load_is_amber() -> None:
    """A component that only degraded is amber, not a silent grey."""
    now = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)
    window = TimeWindow(start=now - timedelta(hours=1), end=now)
    model = make_service(
        ListSource([degraded_line(now - timedelta(minutes=10), "goals_model")]), now
    ).build(window)

    tile = by_name(model.tiles, "goals_model")
    assert tile.state is TileState.DEGRADED
    assert tile.degraded_count == 1
    assert tile.link is not None


def test_unknown_component_status_is_failed() -> None:
    """An unknown load status is loud, not quietly grey."""
    now = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)
    window = TimeWindow(start=now - timedelta(hours=1), end=now)
    load = load_line(now - timedelta(minutes=10), "explanation", status="weird")
    model = make_service(ListSource([load]), now).build(window)

    tile = by_name(model.tiles, "explanation")
    assert tile.state is TileState.FAILED
    assert "unknown status" in tile.detail


def test_null_age_is_not_fresh() -> None:
    """A null age_hours means unknown, which is at least amber."""
    now = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)
    window = TimeWindow(start=now - timedelta(hours=1), end=now)
    reading = freshness_line(now - timedelta(minutes=10), "premier_league", None)
    model = make_service(ListSource([reading]), now).build(window)

    tile = by_name(model.tiles, "data_freshness")
    assert tile.state is TileState.DEGRADED
    assert "no data for" in tile.detail


def test_truncated_read_is_flagged() -> None:
    """A read that returns exactly the limit marks the model truncated."""
    now = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)
    window = TimeWindow(start=now - timedelta(hours=1), end=now)
    model = make_service(FullSource(), now).build(window)

    assert model.truncated is True
    assert model.limit == MAX_QUERY_LIMIT


def test_normal_read_is_not_flagged_as_truncated() -> None:
    """A small source is not reported as truncated."""
    model = fixture_service().build(TimeWindow.last_hours(24, NOW))
    assert model.truncated is False


def test_seven_day_window_keeps_the_newest_failure() -> None:
    """A failure 40 minutes before now still lands inside the 7 d window."""
    now = datetime(2026, 10, 8, 17, 59, tzinfo=UTC)
    load = load_line(
        now - timedelta(minutes=40), "assistant", status="failed", reason="boom"
    )
    model = make_service(ListSource([load]), now).build_for_hours(168)

    tile = by_name(model.tiles, "assistant")
    assert tile.state is TileState.FAILED
    assert "boom" in tile.detail


def test_a_flood_of_degradations_does_not_bury_a_failed_load() -> None:
    """The degraded read is separate, so it cannot push the load out of its page."""
    now = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)
    window = TimeWindow(start=now - timedelta(hours=1), end=now)
    load = load_line(
        now - timedelta(hours=2), "assistant", status="failed", reason="boom"
    )
    source = StormSource(load, degraded_line(now - timedelta(minutes=10), "assistant"))
    model = make_service(source, now).build(window)

    tile = by_name(model.tiles, "assistant")
    assert tile.state is TileState.FAILED
    assert "boom" in tile.detail
    assert model.truncated is True
