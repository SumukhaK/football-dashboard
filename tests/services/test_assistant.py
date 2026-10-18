"""Tests for the assistant service over small lists and the committed fixtures.

The fixture test pins the numbers the guide's "done when" names: the split
between router and model answers, the tool error rate, the ``ollama_chat``
retries and the one request that gave up. The rest cover the cases that are easy
to get wrong on purpose: an empty window, a read that hit the limit, an answer
on a window boundary and a window where nothing reported usage.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.config import Config
from app.domain.models import MAX_QUERY_LIMIT, TimeWindow
from app.services.windows import window_for_hours

from .assistant_helpers import (
    NOW,
    FullSource,
    ListSource,
    SpySource,
    answer_line,
    call_line,
    fallback_line,
    fixture_service,
    make_service,
    retry_line,
    tool_line,
)

WINDOW = TimeWindow(start=NOW - timedelta(hours=1), end=NOW)
GAVE_UP = "5051c1ccd17f9acae01f5057ca02135e"
SLOWEST = "ae97ba94d0eda82f8f6d05584ef8aa38"


def test_fixture_shows_the_split_the_tool_error_and_the_gave_up_request() -> None:
    """The sample day: 7 answers, one third of the predict calls failed."""
    model = fixture_service().build(window_for_hours(24, NOW))

    assert model.answers == 7
    assert {row.path: row.answers for row in model.by_path} == {
        "router": 1,
        "model": 3,
        "model_with_tools": 3,
    }
    assert [(row.reason, row.count) for row in model.abstentions] == [("low_score", 1)]
    assert model.abstention_rate == pytest.approx(1 / 7)

    tools = {row.tool: row for row in model.tools}
    assert tools["predict_match"].calls == 3
    assert tools["predict_match"].errors == 1
    assert tools["predict_match"].last_error == "Unknown team in the served season"
    assert model.tools[0].tool == "predict_match"

    calls = {row.dependency: row for row in model.model_calls}
    assert calls["ollama_chat"].retries == 4
    assert [item.request_id for item in calls["ollama_chat"].gave_up] == [GAVE_UP]
    assert calls["ollama_chat"].gave_up[0].link == f"/requests/{GAVE_UP}"
    assert calls["ollama_embed"].gave_up == ()

    assert [(row.from_path, row.to_path, row.count) for row in model.fallbacks] == [
        ("fresh_match_data", "previous_match_data", 1),
        ("tool_calling", "answer_without_tools", 1),
    ]
    assert model.slowest[0].duration_ms == 73627
    assert model.slowest[0].link == f"/requests/{SLOWEST}"
    assert model.truncated is False


def test_fixture_reports_tokens_and_no_cost() -> None:
    """Local Ollama reports tokens but no cost, so cost is not invented."""
    model = fixture_service().build(window_for_hours(24, NOW))

    assert model.prompt.total == 10933
    assert model.prompt.p50 == 1848
    assert model.prompt.p95 == 2325
    assert model.completion.total == 1287
    assert model.reported_cost is False
    assert model.cost_total is None and model.cost_per_answer is None
    assert model.usage_reported is True


def test_fixture_names_the_worst_dependency_and_the_gave_up_request() -> None:
    """The failing chat dependency is the worst, and one request gave up."""
    model = fixture_service().build(window_for_hours(24, NOW))

    assert model.worst_dependency is not None
    assert model.worst_dependency.dependency == "ollama_chat"
    assert model.gave_up_count == 1
    assert model.gave_up_link == f"/requests/{GAVE_UP}"
    assert model.top_abstention == "Low score"


def test_fixture_answered_paths_join_split_and_latency() -> None:
    """The one table shows each path's answers, share and formatted latency."""
    model = fixture_service().build(window_for_hours(24, NOW))

    rows = {row.path: row for row in model.answered_paths}
    assert set(rows) == {"router", "model", "model_with_tools"}
    assert rows["router"].answers == 1
    assert rows["router"].p50_label == "58 ms"
    assert rows["model"].p95_label == "73.6 s"
    assert rows["model"].slow is True
    assert rows["model_with_tools"].slow is False


def test_empty_window_reports_nothing_and_no_rate() -> None:
    """An empty window is zeros and None, never a rate over everything."""
    model = make_service(ListSource([])).build(WINDOW)

    assert model.answers == 0
    assert model.by_path == () and model.latency == () and model.tools == ()
    assert model.model_calls == () and model.fallbacks == () and model.slowest == ()
    assert model.abstentions == ()
    assert model.abstention_rate is None
    assert model.prompt.total is None
    assert model.usage_reported is False
    assert model.truncated is False


def test_every_read_names_its_events_and_the_window() -> None:
    """No read can fall back to "everything": each carries names and a window."""
    source = SpySource([])
    make_service(source).build(WINDOW)

    assert len(source.queries) == 3
    for query in source.queries:
        assert query.events
        assert query.window == WINDOW
        assert query.limit == MAX_QUERY_LIMIT
    assert {name for query in source.queries for name in query.events} == {
        "assistant.answer",
        "assistant.abstain",
        "assistant.tool",
        "retry",
        "fallback",
        "dependency.call",
    }


def test_a_read_at_the_limit_is_flagged_as_truncated() -> None:
    """A read that returns exactly the limit says so, with its number."""
    model = make_service(FullSource()).build(WINDOW)

    assert model.truncated is True
    assert model.limit == MAX_QUERY_LIMIT


def test_an_answer_on_the_window_start_is_inside_it() -> None:
    """The window is start-inclusive, so an answer at the start counts."""
    model = make_service(ListSource([answer_line(WINDOW.start)])).build(WINDOW)
    assert model.answers == 1


def test_an_answer_on_the_window_end_is_outside_it() -> None:
    """The window is end-exclusive, so nothing is counted twice."""
    model = make_service(ListSource([answer_line(WINDOW.end)])).build(WINDOW)
    assert model.answers == 0


def test_a_window_with_only_answers_counts_them_all() -> None:
    """A hand-written window adds up: split, latency, tokens and slowest."""
    answers = [
        answer_line(NOW - timedelta(minutes=3), path="router", duration_ms=58),
        answer_line(
            NOW - timedelta(minutes=2),
            path="model_with_tools",
            tool_rounds=1,
            duration_ms=5309,
        ),
        answer_line(NOW - timedelta(minutes=1), path="model", duration_ms=1499),
    ]
    model = make_service(ListSource(answers)).build(WINDOW)

    assert model.answers == 3
    assert [row.duration_ms for row in model.slowest] == [5309, 1499, 58]
    assert {row.path: row.answers for row in model.by_path} == {
        "router": 1,
        "model": 1,
        "model_with_tools": 1,
    }


def test_all_null_usage_is_not_reported() -> None:
    """When every token and the cost are null, the page says so."""
    answers = [
        answer_line(
            NOW - timedelta(minutes=1),
            prompt_tokens=None,
            completion_tokens=None,
            cost_usd=None,
        )
    ]
    model = make_service(ListSource(answers)).build(WINDOW)

    assert model.usage_reported is False
    assert model.reported_cost is False
    assert model.answers == 1


def test_some_cost_reported_is_reported() -> None:
    """One answer with a cost is enough to show the cost column."""
    model = make_service(
        ListSource(
            [
                answer_line(NOW - timedelta(minutes=2), cost_usd=0.002),
                answer_line(NOW - timedelta(minutes=1), cost_usd=None),
            ]
        )
    ).build(WINDOW)

    assert model.reported_cost is True
    assert model.cost_total == 0.002
    assert model.cost_per_answer == 0.002


def test_resolve_hours_defaults_and_rejects() -> None:
    """The page offers the same windows as the others and rejects the rest."""
    service = make_service(ListSource([]))
    assert service.resolve_hours(None) == Config().default_window_hours
    assert service.resolve_hours(1) == 1
    with pytest.raises(ValueError):
        service.resolve_hours(5)


def test_build_for_hours_ends_at_the_clock_interval() -> None:
    """A service load rounds the window end up like every other page."""
    model = make_service(ListSource([])).build_for_hours(24)
    assert model.window == window_for_hours(24, NOW)


def test_one_answer_with_tools_and_calls_adds_up() -> None:
    """A full request: one answer, a tool, two chat attempts and a fallback."""
    events = [
        answer_line(
            NOW - timedelta(minutes=1),
            path="model_with_tools",
            tool_rounds=1,
            duration_ms=5309,
            request_id="req-aaaaaaaa",
        ),
        tool_line(NOW - timedelta(minutes=2), request_id="req-aaaaaaaa"),
        call_line(
            NOW - timedelta(minutes=3),
            status="timeout",
            attempt=1,
            request_id="req-aaaaaaaa",
        ),
        call_line(NOW - timedelta(minutes=2), attempt=2, request_id="req-aaaaaaaa"),
        retry_line(NOW - timedelta(minutes=3), request_id="req-aaaaaaaa"),
        fallback_line(NOW - timedelta(minutes=2), request_id="req-aaaaaaaa"),
    ]
    model = make_service(ListSource(events)).build(WINDOW)

    row = model.model_calls[0]
    assert row.attempts == 2
    assert row.failure_rate == 0.5
    assert row.retries == 1
    assert row.gave_up == ()
    assert model.answers == 1 and model.abstention_rate == 0.0
