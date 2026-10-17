"""Regression tests for relating loads and fallbacks to a refresh run.

``refresh.run`` is a completion record: the backend emits it after the download
and the reload have both finished, so a component load or a fixture fallback
happens *inside* its measured interval, while a whole-run failure fallback
follows it. Every case here drives ``DataJobsService.build``, so the source read
and the model are exercised, not only a private helper.

The fixed clock is ``2026-10-08T18:00Z``; ``moment(minutes=n)`` is that many
minutes earlier, and a ten-minute run completes at ``moment(30)`` unless said
otherwise.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import cast

import pytest

from app.domain.data_jobs import DataJobsModel
from app.domain.models import TelemetryEvent
from app.services.windows import window_for_hours
from tests.services.data_jobs_helpers import (
    NOW,
    ListSource,
    fallback_line,
    fixture_fallback_line,
    load_line,
    make_service,
    moment,
    refresh_line,
)

WINDOW = window_for_hours(168, NOW)
TEN_MINUTES_MS = 600000


def _model(events: list[TelemetryEvent]) -> DataJobsModel:
    """The data and jobs model over the given events, seven-day window."""
    return make_service(ListSource(events)).build(WINDOW)


def _at(hour: int, minute: int, second: int) -> datetime:
    """A UTC moment on the fixture day, inside the seven-day window."""
    return datetime(2026, 10, 8, hour, minute, second, tzinfo=UTC)


def test_the_producer_order_example_gives_two_reloads_one_fallback() -> None:
    """The backend's real order: fallback and loads inside, completion last."""
    events = [
        fixture_fallback_line(_at(10, 0, 2)),
        load_line(_at(10, 0, 4), component="fixtures"),
        load_line(_at(10, 0, 5), component="match_history"),
        refresh_line(_at(10, 0, 6), status="ok", duration_ms=6000),
        fallback_line(
            _at(10, 0, 7),
            from_path="tool_calling",
            to_path="answer_without_tools",
            cause="tool_round_limit",
        ),
    ]
    model = _model(events)
    (run,) = model.refreshes
    assert run.status == "ok"
    assert [(row.from_path, row.cause) for row in run.fallbacks] == [
        ("fresh_fixtures", "fixtures_refresh_failed")
    ]
    assert [row.component for row in model.reloads] == ["match_history", "fixtures"]


def test_a_load_inside_the_measured_run_is_a_reload() -> None:
    """The reload happened before the completion record, not after it."""
    end = moment(minutes=30)
    events = [
        refresh_line(end, status="ok", duration_ms=TEN_MINUTES_MS),
        load_line(end - timedelta(minutes=9), component="fixtures"),
    ]
    assert [row.component for row in _model(events).reloads] == ["fixtures"]


@pytest.mark.parametrize("seconds", [0, 600])
def test_a_load_at_either_end_of_the_run_is_a_reload(seconds: int) -> None:
    """The start and the end of the measured interval are both inclusive."""
    end = moment(minutes=30)
    events = [
        refresh_line(end, status="ok", duration_ms=TEN_MINUTES_MS),
        load_line(end - timedelta(seconds=seconds)),
    ]
    assert len(_model(events).reloads) == 1


def test_a_load_just_outside_the_run_is_not_a_reload() -> None:
    """One millisecond outside either end and the load is another process'."""
    end = moment(minutes=30)
    run = refresh_line(end, status="ok", duration_ms=TEN_MINUTES_MS)
    before = end - timedelta(minutes=10) - timedelta(milliseconds=1)
    after = end + timedelta(milliseconds=1)
    for at in (before, after):
        assert _model([run, load_line(at)]).reloads == ()


def test_a_load_with_no_refresh_is_not_a_reload() -> None:
    """Loads with no refresh run at all are startup loads."""
    assert _model([load_line(moment(minutes=5))]).reloads == ()


@pytest.mark.parametrize(
    "duration",
    [None, True, "600000", float("nan"), float("inf"), -1.0, 1e18],
    ids=["missing", "boolean", "text", "nan", "infinite", "negative", "overflowing"],
)
def test_an_unusable_duration_associates_no_load(duration: object) -> None:
    """A duration that cannot bound an interval claims nothing, and never raises."""
    end = moment(minutes=30)
    events = [
        refresh_line(end, status="ok", duration_ms=cast("float | None", duration)),
        load_line(end - timedelta(minutes=5)),
        load_line(end + timedelta(seconds=1)),
    ]
    model = _model(events)
    assert len(model.refreshes) == 1
    assert model.reloads == ()


def test_a_zero_duration_run_covers_only_its_own_completion() -> None:
    """Zero duration is a point interval at the completion timestamp."""
    end = moment(minutes=30)
    events = [
        refresh_line(end, status="ok", duration_ms=0),
        load_line(end, component="fixtures"),
        load_line(end - timedelta(milliseconds=1), component="assistant"),
    ]
    assert [row.component for row in _model(events).reloads] == ["fixtures"]


def test_reloads_keep_their_own_status_reason_and_duration() -> None:
    """A component that failed to load stays visible as failed, newest first."""
    end = moment(minutes=30)
    events = [
        refresh_line(end, status="ok", duration_ms=TEN_MINUTES_MS),
        load_line(end - timedelta(minutes=8), component="fixtures"),
        load_line(
            end - timedelta(minutes=7),
            component="assistant",
            status="failed",
            duration_ms=2168.0,
            reason="Ollama did not answer",
        ),
    ]
    reloads = _model(events).reloads
    assert [row.component for row in reloads] == ["assistant", "fixtures"]
    assert reloads[0].status == "failed"
    assert reloads[0].reason == "Ollama did not answer"
    assert reloads[0].duration_ms == 2168.0


def test_the_output_does_not_depend_on_the_input_order() -> None:
    """Two sequential runs and their loads read the same whatever the order."""
    first = moment(minutes=120)
    second = moment(minutes=30)
    events = [
        load_line(first - timedelta(seconds=5), component="fixtures"),
        load_line(second - timedelta(seconds=5), component="goals_model"),
        refresh_line(first, status="ok", duration_ms=TEN_MINUTES_MS),
        refresh_line(second, status="ok", duration_ms=TEN_MINUTES_MS),
    ]
    forwards = _model(events)
    backwards = _model(list(reversed(events)))
    assert [row.component for row in forwards.reloads] == ["goals_model", "fixtures"]
    assert [row.component for row in backwards.reloads] == ["goals_model", "fixtures"]
    assert [run.timestamp for run in backwards.refreshes] == [second, first]


def test_a_load_from_a_known_other_revision_is_not_a_reload() -> None:
    """A recorded mismatch rejects the match; an absent revision still matches."""
    end = moment(minutes=30)
    inside = end - timedelta(minutes=5)
    run = refresh_line(end, status="ok", duration_ms=TEN_MINUTES_MS, revision="rev-a")
    assert _model([run, load_line(inside, revision="rev-a")]).reloads != ()
    assert _model([run, load_line(inside, revision="rev-b")]).reloads == ()
    assert _model([run, load_line(inside, revision=None)]).reloads != ()


def test_overlapping_runs_leave_a_load_unassigned() -> None:
    """A load two intervals both cover is left out; a clear one is kept."""
    events = [
        refresh_line(moment(minutes=35), status="ok", duration_ms=TEN_MINUTES_MS),
        refresh_line(moment(minutes=30), status="ok", duration_ms=TEN_MINUTES_MS),
        load_line(moment(minutes=37), component="fixtures"),
        load_line(moment(minutes=42), component="assistant"),
    ]
    assert [row.component for row in _model(events).reloads] == ["assistant"]


def test_two_runs_completing_together_leave_a_load_unassigned() -> None:
    """Identical completions and no other metadata: the load is not claimed."""
    end = moment(minutes=30)
    events = [
        refresh_line(end, status="ok", duration_ms=TEN_MINUTES_MS, dataset="a.csv"),
        refresh_line(end, status="ok", duration_ms=TEN_MINUTES_MS, dataset="b.csv"),
        load_line(end - timedelta(minutes=1)),
    ]
    assert _model(events).reloads == ()


def test_a_fixture_fallback_inside_a_successful_run_is_shown_on_it() -> None:
    """Keeping the previous fixtures does not fail the results refresh."""
    end = moment(minutes=30)
    events = [
        refresh_line(end, status="ok", duration_ms=TEN_MINUTES_MS),
        fixture_fallback_line(end - timedelta(minutes=8)),
    ]
    model = _model(events)
    assert [run.status for run in model.refreshes] == ["ok"]
    assert [
        (row.from_path, row.to_path, row.cause) for row in model.refreshes[0].fallbacks
    ] == [("fresh_fixtures", "previous_fixtures", "fixtures_refresh_failed")]


@pytest.mark.parametrize("seconds", [-601, 1])
def test_a_fixture_fallback_outside_the_run_is_not_attached(seconds: int) -> None:
    """A fixture fallback is matched by the interval, not by being nearby."""
    end = moment(minutes=30)
    events = [
        refresh_line(end, status="ok", duration_ms=TEN_MINUTES_MS),
        fixture_fallback_line(end + timedelta(seconds=seconds)),
    ]
    assert _model(events).refreshes[0].fallbacks == ()


def test_a_whole_run_fallback_after_a_failed_completion_is_shown() -> None:
    """The exact refresh_failed triple after a failed run is shown on it."""
    end = moment(minutes=30)
    events = [
        refresh_line(end, status="failed"),
        fallback_line(end + timedelta(seconds=1)),
    ]
    fallbacks = _model(events).refreshes[0].fallbacks
    assert [(row.from_path, row.to_path, row.cause) for row in fallbacks] == [
        ("fresh_match_data", "previous_match_data", "refresh_failed")
    ]


@pytest.mark.parametrize("seconds", [0, 299, 300])
def test_the_whole_run_bound_is_inclusive(seconds: int) -> None:
    """The conservative five-minute bound includes both of its ends."""
    end = moment(minutes=30)
    events = [
        refresh_line(end, status="failed"),
        fallback_line(end + timedelta(seconds=seconds)),
    ]
    assert len(_model(events).refreshes[0].fallbacks) == 1


def test_a_whole_run_fallback_past_the_bound_is_not_attached() -> None:
    """One second past the bound and the fallback belongs to no run."""
    end = moment(minutes=30)
    events = [
        refresh_line(end, status="failed"),
        fallback_line(end + timedelta(seconds=301)),
    ]
    assert _model(events).refreshes[0].fallbacks == ()


def test_a_whole_run_fallback_before_the_run_is_not_attached() -> None:
    """A fallback that happened first cannot have followed the run."""
    end = moment(minutes=30)
    events = [
        refresh_line(end, status="failed"),
        fallback_line(end - timedelta(seconds=1)),
    ]
    assert _model(events).refreshes[0].fallbacks == ()


def test_a_whole_run_fallback_on_a_successful_run_is_not_attached() -> None:
    """A run that succeeded never owns a refresh_failed fallback."""
    end = moment(minutes=30)
    events = [
        refresh_line(end, status="ok", duration_ms=TEN_MINUTES_MS),
        fallback_line(end + timedelta(seconds=1)),
    ]
    assert _model(events).refreshes[0].fallbacks == ()


def test_a_whole_run_fallback_belongs_to_the_newest_failed_run() -> None:
    """Two failed runs three minutes apart: the later one owns it."""
    first = moment(minutes=60)
    second = moment(minutes=3)
    events = [
        refresh_line(first, status="failed"),
        refresh_line(second, status="failed"),
        fallback_line(second + timedelta(seconds=1)),
    ]
    assert [len(run.fallbacks) for run in _model(events).refreshes] == [1, 0]


def test_a_whole_run_fallback_is_not_carried_across_a_newer_run() -> None:
    """A successful run in between means no older failure can claim it."""
    failed = moment(minutes=60)
    newer = moment(minutes=10)
    events = [
        refresh_line(failed, status="failed"),
        refresh_line(newer, status="ok"),
        fallback_line(newer + timedelta(seconds=1)),
    ]
    assert [run.fallbacks for run in _model(events).refreshes] == [(), ()]


def test_two_runs_completing_together_leave_the_fallback_unassigned() -> None:
    """Two failed runs at one moment are indistinguishable, so neither owns it."""
    end = moment(minutes=30)
    events = [
        refresh_line(end, status="failed", dataset="a.csv"),
        refresh_line(end, status="failed", dataset="b.csv"),
        fallback_line(end + timedelta(seconds=1)),
    ]
    assert [run.fallbacks for run in _model(events).refreshes] == [(), ()]


@pytest.mark.parametrize("seconds", [-300, 1])
def test_an_assistant_fallback_is_never_attached(seconds: int) -> None:
    """A tool-round fallback is not a data fallback, inside the run or after it."""
    end = moment(minutes=30)
    events = [
        refresh_line(end, status="failed", duration_ms=TEN_MINUTES_MS),
        fallback_line(
            end + timedelta(seconds=seconds),
            from_path="tool_calling",
            to_path="answer_without_tools",
            cause="tool_round_limit",
        ),
    ]
    assert _model(events).refreshes[0].fallbacks == ()


def test_a_fallback_with_the_wrong_cause_is_not_attached() -> None:
    """Right paths with the wrong cause, and the reverse, are both excluded."""
    end = moment(minutes=30)
    events = [
        refresh_line(end, status="failed", duration_ms=TEN_MINUTES_MS),
        fallback_line(
            end - timedelta(minutes=5),
            from_path="fresh_fixtures",
            to_path="previous_fixtures",
            cause="tool_round_limit",
        ),
        fallback_line(
            end + timedelta(seconds=1),
            from_path="previous_match_data",
            to_path="fresh_match_data",
            cause="refresh_failed",
        ),
    ]
    assert _model(events).refreshes[0].fallbacks == ()


def test_a_fallback_from_a_known_other_revision_is_not_attached() -> None:
    """The revision check applies to a fixture fallback as well."""
    end = moment(minutes=30)
    events = [
        refresh_line(
            end, status="failed", duration_ms=TEN_MINUTES_MS, revision="rev-a"
        ),
        fixture_fallback_line(end - timedelta(minutes=5), revision="rev-b"),
    ]
    assert _model(events).refreshes[0].fallbacks == ()


def test_a_fallback_without_a_refresh_run_is_not_shown() -> None:
    """A fallback with no run in the window has nothing to belong to."""
    assert _model([fallback_line(moment(minutes=5))]).refreshes == ()
