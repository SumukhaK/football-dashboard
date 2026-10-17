"""Tests for the shared data-freshness rule."""

from __future__ import annotations

import pytest

from app.config import Config
from app.domain.overview import TileState
from app.services.freshness import (
    age_hours,
    freshness_rows,
    newest_per_competition,
    state_for,
)
from app.services.tiles import freshness_tile
from tests.services.data_jobs_helpers import freshness_line, line, moment

SETTINGS = Config()


@pytest.mark.parametrize(
    ("age", "expected"),
    [
        (0.0, TileState.OK),
        (35.9, TileState.OK),
        (36.0, TileState.DEGRADED),
        (71.9, TileState.DEGRADED),
        (72.0, TileState.DEGRADED),
        (72.1, TileState.FAILED),
        (None, TileState.DEGRADED),
    ],
)
def test_state_at_each_threshold_boundary(
    age: float | None, expected: TileState
) -> None:
    """Green below warn, amber from warn (inclusive) to error, red above it."""
    assert state_for(age, age is None, SETTINGS) == expected


def test_unknown_age_is_at_least_amber_beside_a_fresh_one() -> None:
    """One unknown league lifts the tile out of green even when another is fresh."""
    assert state_for(0.0, True, SETTINGS) == TileState.DEGRADED


def test_thresholds_come_from_the_settings() -> None:
    """A settings change moves the boundaries the state is graded against."""
    settings = Config(freshness_warn_hours=1, freshness_error_hours=2)
    assert state_for(1.5, False, settings) == TileState.DEGRADED
    assert state_for(2.5, False, settings) == TileState.FAILED


def test_newest_per_competition_keeps_the_latest_reading() -> None:
    """Two readings for one league leave only the newer one."""
    older = freshness_line(moment(minutes=10), age_hours=90.0)
    newer = freshness_line(moment(minutes=1), age_hours=5.0)
    found = newest_per_competition([older, newer])
    assert found["Premier League"] is newer


def test_two_readings_at_the_same_moment_keep_the_first() -> None:
    """A tie keeps the reading seen first, so the choice is deterministic."""
    first = freshness_line(moment(minutes=5), age_hours=1.0)
    second = freshness_line(moment(minutes=5), age_hours=2.0)
    found = newest_per_competition([first, second])
    assert found["Premier League"] is first


def test_age_hours_reads_a_number_and_treats_anything_else_as_unknown() -> None:
    """A numeric age is read; a missing or non-numeric one is None."""
    assert age_hours(freshness_line(moment(), age_hours=4.5)) == 4.5
    assert age_hours(freshness_line(moment(), age_hours=None)) is None
    odd = line(moment(), "data.freshness", competition="Serie A", age_hours="4.5")
    assert age_hours(odd) is None


def test_rows_are_graded_and_carry_the_reading() -> None:
    """A row carries the league, its matches-through date, age and read time."""
    at = moment(minutes=3)
    rows = freshness_rows([freshness_line(at, age_hours=40.0)], SETTINGS)
    assert len(rows) == 1
    row = rows[0]
    assert row.competition == "Premier League"
    assert row.matches_through == "2026-10-05"
    assert row.age_hours == 40.0
    assert row.timestamp == at
    assert row.state == TileState.DEGRADED


def test_rows_are_stalest_first_unknown_first_and_ties_by_name() -> None:
    """The stalest league leads, an unknown age leads it, ties break by name."""
    events = [
        freshness_line(moment(minutes=1), "Serie A", age_hours=10.0),
        freshness_line(moment(minutes=1), "Bundesliga", age_hours=90.0),
        freshness_line(moment(minutes=1), "La Liga", age_hours=10.0),
        freshness_line(moment(minutes=1), "Ligue 1", age_hours=None),
    ]
    rows = freshness_rows(events, SETTINGS)
    assert [row.competition for row in rows] == [
        "Ligue 1",
        "Bundesliga",
        "La Liga",
        "Serie A",
    ]


def test_no_events_gives_no_rows() -> None:
    """Nothing read means nothing shown, never a placeholder league."""
    assert freshness_rows([], SETTINGS) == ()


def test_the_tile_and_the_rows_agree_on_a_stale_league() -> None:
    """Both pages grade the same reading with the same rule and thresholds."""
    events = [freshness_line(moment(minutes=1), age_hours=80.0)]
    tile = freshness_tile(events, SETTINGS)
    rows = freshness_rows(events, SETTINGS)
    assert tile.state == rows[0].state == TileState.FAILED
