"""Tests for the data and jobs page model."""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.domain.data_jobs import DataJobsModel, DownloadFailure
from app.domain.models import MAX_QUERY_LIMIT, TelemetryEvent
from app.services.windows import window_for_hours
from tests.services.data_jobs_helpers import (
    NOW,
    FullSource,
    ListSource,
    RecordingSource,
    call_line,
    fallback_line,
    fixture_service,
    freshness_line,
    load_line,
    make_service,
    moment,
    refresh_line,
    retry_line,
)

WINDOW = window_for_hours(168, NOW)
FIVE_MINUTES = timedelta(minutes=5)


def _model(events: list[TelemetryEvent]) -> DataJobsModel:
    """The data and jobs model over the given events, seven-day window."""
    return make_service(ListSource(events)).build(WINDOW)


def test_refresh_runs_are_newest_first_with_their_fields() -> None:
    """Each run carries its time, status, duration, dataset and error."""
    events = [
        refresh_line(
            moment(minutes=100),
            status="failed",
            duration_ms=65002.0,
            dataset=None,
            error="football-data.co.uk answered 503 twice",
        ),
        refresh_line(
            moment(minutes=10),
            status="ok",
            duration_ms=3600.0,
            dataset="football_data_2026-10-08.csv",
        ),
    ]
    model = _model(events)
    assert [run.status for run in model.refreshes] == ["ok", "failed"]
    newest, oldest = model.refreshes
    assert newest.dataset == "football_data_2026-10-08.csv"
    assert newest.error is None
    assert newest.duration_ms == 3600.0
    assert oldest.dataset is None
    assert oldest.error == "football-data.co.uk answered 503 twice"


def test_a_failed_run_shows_the_fallback_that_followed_it() -> None:
    """A fallback one second after a run is shown next to that run."""
    at = moment(minutes=10)
    events = [
        refresh_line(at, status="failed"),
        fallback_line(at + timedelta(seconds=1)),
    ]
    fallbacks = _model(events).refreshes[0].fallbacks
    assert [row.from_path for row in fallbacks] == ["fresh_match_data"]
    assert [row.to_path for row in fallbacks] == ["previous_match_data"]
    assert [row.cause for row in fallbacks] == ["refresh_failed"]


@pytest.mark.parametrize("seconds", [0, 299, 300])
def test_a_fallback_within_five_minutes_is_attached(seconds: int) -> None:
    """The five-minute window is inclusive at both ends."""
    at = moment(minutes=10)
    events = [
        refresh_line(at, status="failed"),
        fallback_line(at + timedelta(seconds=seconds)),
    ]
    assert len(_model(events).refreshes[0].fallbacks) == 1


def test_a_fallback_more_than_five_minutes_later_is_not_attached() -> None:
    """One second past the window and the fallback belongs to no run."""
    at = moment(minutes=10)
    events = [
        refresh_line(at, status="failed"),
        fallback_line(at + timedelta(seconds=301)),
    ]
    assert _model(events).refreshes[0].fallbacks == ()


def test_a_fallback_before_the_run_is_not_attached() -> None:
    """A fallback that happened first cannot have followed the run."""
    at = moment(minutes=10)
    events = [
        refresh_line(at, status="failed"),
        fallback_line(at - timedelta(seconds=1)),
    ]
    assert _model(events).refreshes[0].fallbacks == ()


def test_a_fallback_belongs_to_the_newest_run_before_it() -> None:
    """Two runs three minutes apart: the fallback is the later one's."""
    first = moment(minutes=60)
    second = moment(minutes=3)
    events = [
        refresh_line(first, status="failed"),
        refresh_line(second, status="failed"),
        fallback_line(second + timedelta(seconds=1)),
    ]
    model = _model(events)
    assert [len(run.fallbacks) for run in model.refreshes] == [1, 0]


def test_a_fallback_without_a_run_in_the_window_is_not_shown() -> None:
    """A fallback with no refresh run to belong to is left out."""
    assert _model([fallback_line(moment(minutes=5))]).refreshes == ()


def test_downloads_report_attempts_failures_retries_and_last_error() -> None:
    """Attempts, failures by status, retries and the last error are counted."""
    events = [
        call_line(moment(minutes=30), status="http_error", http_status=503, attempt=1),
        call_line(moment(minutes=29), status="http_error", http_status=503, attempt=2),
        retry_line(moment(minutes=30), attempt=1),
        call_line(moment(minutes=20), status="ok", http_status=200),
    ]
    model = _model(events)
    football = model.downloads[0]
    assert football.dependency == "football_data"
    assert football.attempts == 3
    assert football.retries == 1
    assert football.failures == (
        DownloadFailure(status="http_error", http_status=503, count=2),
    )
    assert football.last_error == "http_error (503)"


def test_a_failure_without_an_http_status_shows_the_status_alone() -> None:
    """A timeout has no HTTP status, so the last error is just the status."""
    events = [call_line(moment(minutes=5), status="timeout", http_status=None)]
    football = _model(events).downloads[0]
    assert football.failures == (
        DownloadFailure(status="timeout", http_status=None, count=1),
    )
    assert football.last_error == "timeout"


def test_failures_are_ordered_commonest_first_then_by_status() -> None:
    """The noisiest failure leads; ties break by status then HTTP status."""
    events = [
        call_line(moment(minutes=5), status="timeout", http_status=None),
        call_line(moment(minutes=4), status="http_error", http_status=503),
        call_line(moment(minutes=3), status="http_error", http_status=500),
    ]
    failures = _model(events).downloads[0].failures
    assert [(row.status, row.http_status) for row in failures] == [
        ("http_error", 500),
        ("http_error", 503),
        ("timeout", None),
    ]


def test_downloads_ignore_calls_that_are_not_downloads() -> None:
    """An embedding or chat call is not a match-data download."""
    events = [
        call_line(
            moment(minutes=5),
            dependency="ollama_chat",
            operation="chat",
            status="timeout",
            http_status=None,
        )
    ]
    model = _model(events)
    assert [row.dependency for row in model.downloads] == [
        "football_data",
        "openfootball",
    ]
    assert [row.attempts for row in model.downloads] == [0, 0]


def test_an_unknown_download_dependency_is_listed_after_the_known_two() -> None:
    """A new downloading dependency shows up rather than being hidden."""
    events = [call_line(moment(minutes=5), dependency="wikipedia")]
    assert [row.dependency for row in _model(events).downloads] == [
        "football_data",
        "openfootball",
        "wikipedia",
    ]


def test_only_the_loads_after_a_refresh_are_reloads() -> None:
    """A startup load before the refresh is not a reload."""
    at = moment(minutes=30)
    events = [
        refresh_line(at, status="ok"),
        load_line(moment(minutes=90), component="prediction_model"),
        load_line(at + timedelta(seconds=2), component="fixtures"),
    ]
    assert [row.component for row in _model(events).reloads] == ["fixtures"]


@pytest.mark.parametrize("seconds", [0, 1, 300])
def test_a_load_within_five_minutes_after_a_refresh_is_a_reload(seconds: int) -> None:
    """A load at the refresh, and one at the five-minute boundary, counts."""
    at = moment(minutes=30)
    events = [refresh_line(at), load_line(at + timedelta(seconds=seconds))]
    assert len(_model(events).reloads) == 1


def test_a_load_more_than_five_minutes_after_a_refresh_is_not_a_reload() -> None:
    """A restart an hour later is a startup, not this refresh's reload."""
    at = moment(minutes=120)
    events = [refresh_line(at), load_line(at + timedelta(minutes=61))]
    assert _model(events).reloads == ()


def test_reloads_are_newest_first_and_carry_status_reason_and_duration() -> None:
    """Reload rows keep the component's own status, reason and duration."""
    at = moment(minutes=30)
    events = [
        refresh_line(at),
        load_line(at + timedelta(seconds=1), component="fixtures"),
        load_line(
            at + timedelta(seconds=2),
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


def test_no_reloads_without_a_refresh() -> None:
    """Loads with no refresh to follow are startup loads."""
    assert _model([load_line(moment(minutes=5))]).reloads == ()


def test_freshness_is_read_over_the_lookback_not_the_picked_window() -> None:
    """A one-hour window still shows a reading from ninety minutes ago."""
    reading = freshness_line(moment(minutes=90), competition="Serie A", age_hours=1.5)
    model = make_service(ListSource([reading])).build(window_for_hours(1, NOW))
    assert [row.competition for row in model.freshness] == ["Serie A"]
    assert model.freshness_lookback_hours == 168


def test_a_reading_older_than_the_lookback_is_not_shown() -> None:
    """A reading older than the lookback is not shown as current."""
    ancient = freshness_line(moment(hours=200), competition="Serie A")
    model = make_service(ListSource([ancient])).build(window_for_hours(1, NOW))
    assert model.freshness == ()


def test_the_three_reads_ask_for_only_what_the_page_shows() -> None:
    """The page reads jobs, downloads and freshness, each over its own window."""
    source = RecordingSource([])
    make_service(source).build(WINDOW)
    assert [set(query.events) for query in source.queries] == [
        {"refresh.run", "fallback", "component.load"},
        {"dependency.call", "retry"},
        {"data.freshness"},
    ]
    assert source.queries[0].window == WINDOW
    assert source.queries[2].window.start == WINDOW.end - timedelta(hours=168)
    assert [query.limit for query in source.queries] == [MAX_QUERY_LIMIT] * 3


def test_truncation_is_visible_when_a_read_fills_the_page() -> None:
    """A read that returns the whole limit is flagged as partial."""
    model = make_service(FullSource()).build(WINDOW)
    assert model.truncated is True
    assert model.limit == MAX_QUERY_LIMIT


def test_an_empty_window_shows_no_rows_but_both_download_rows() -> None:
    """Nothing read means no rows, and both download rows say zero, not nothing."""
    model = _model([])
    assert model.freshness == ()
    assert model.refreshes == ()
    assert model.reloads == ()
    assert [row.dependency for row in model.downloads] == [
        "football_data",
        "openfootball",
    ]
    assert [(row.attempts, row.retries, row.last_error) for row in model.downloads] == [
        (0, 0, None),
        (0, 0, None),
    ]
    assert model.truncated is False


def test_the_default_window_is_seven_days() -> None:
    """The picker's default on this page is the week, not the platform default."""
    assert make_service(ListSource([])).resolve_hours(None) == 168


def test_an_unsupported_window_is_rejected() -> None:
    """A window the picker does not offer is refused, not silently changed."""
    with pytest.raises(ValueError):
        make_service(ListSource([])).resolve_hours(12)


def test_fixture_scenario_shows_the_failed_and_the_successful_refresh() -> None:
    """The fixture's two runs and the failed one's fallback are all shown."""
    model = fixture_service().build_for_hours(168)
    assert [run.status for run in model.refreshes] == ["ok", "failed"]
    failed = model.refreshes[1]
    assert failed.error == "football-data.co.uk answered 503 twice"
    assert [(row.from_path, row.to_path) for row in failed.fallbacks] == [
        ("fresh_match_data", "previous_match_data")
    ]
    assert model.refreshes[0].dataset == "football_data_2026-10-08.csv"


def test_fixture_scenario_shows_freshness_per_league_and_download_retries() -> None:
    """Every fixture league is graded and the failed download retried once."""
    model = fixture_service().build_for_hours(168)
    assert [row.competition for row in model.freshness] == [
        "Bundesliga",
        "Ligue 1",
        "La Liga",
        "Premier League",
        "Serie A",
    ]
    assert all(row.matches_through for row in model.freshness)
    football = model.downloads[0]
    assert (football.attempts, football.retries) == (3, 1)
    assert football.failures == (
        DownloadFailure(status="http_error", http_status=503, count=2),
    )
    openfootball = model.downloads[1]
    assert (openfootball.attempts, openfootball.retries) == (1, 0)
    assert openfootball.last_error is None


def test_fixture_reloads_follow_the_successful_refresh() -> None:
    """The five data components reloaded after the successful run, and only it."""
    model = fixture_service().build_for_hours(168)
    assert {row.component for row in model.reloads} == {
        "fixtures",
        "match_history",
        "season_history",
        "season_outlook",
        "goals_model",
    }
    assert {row.status for row in model.reloads} == {"ok"}
