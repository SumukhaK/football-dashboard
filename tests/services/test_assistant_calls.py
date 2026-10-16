"""Tests for the tool, model-call, fallback and gave-up builders.

``gave_up_requests`` gets the most attention here: it is the one rule on the page
that has to reason about a sequence of attempts rather than a single line.
"""

from __future__ import annotations

from datetime import timedelta

from app.domain.assistant import FAILURE_STATUSES, MODEL_DEPENDENCIES
from app.services.assistant_calls import (
    fallback_rows,
    gave_up_requests,
    model_call_rows,
    tool_rows,
)

from .assistant_helpers import (
    NOW,
    REQUEST,
    call_line,
    fallback_line,
    retry_line,
    tool_line,
)

OTHER = "5051c1ccd1243f8ad2f1e0b5b2c4a6d9"


def test_gave_up_is_empty_after_two_failures_then_a_success() -> None:
    """Retrying twice and then answering is not giving up."""
    calls = [
        call_line(NOW - timedelta(minutes=3), status="timeout", attempt=1),
        call_line(NOW - timedelta(minutes=2), status="timeout", attempt=2),
        call_line(NOW - timedelta(minutes=1), status="ok", attempt=3),
    ]
    assert gave_up_requests(calls) == set()


def test_gave_up_after_three_failed_attempts() -> None:
    """A request whose last attempt failed gave up."""
    calls = [
        call_line(NOW - timedelta(minutes=3), status="connection_error", attempt=1),
        call_line(NOW - timedelta(minutes=2), status="connection_error", attempt=2),
        call_line(NOW - timedelta(minutes=1), status="connection_error", attempt=3),
    ]
    assert gave_up_requests(calls) == {REQUEST}


def test_gave_up_keeps_two_interleaved_requests_apart() -> None:
    """Attempts from two requests are judged per request, not per list order."""
    calls = [
        call_line(NOW - timedelta(minutes=4), status="timeout", attempt=1),
        call_line(
            NOW - timedelta(minutes=4), status="timeout", attempt=1, request_id=OTHER
        ),
        call_line(NOW - timedelta(minutes=3), status="ok", attempt=2),
        call_line(
            NOW - timedelta(minutes=3), status="timeout", attempt=2, request_id=OTHER
        ),
        call_line(
            NOW - timedelta(minutes=2), status="timeout", attempt=3, request_id=OTHER
        ),
    ]
    assert gave_up_requests(calls) == {OTHER}


def test_gave_up_ignores_calls_without_a_request_id() -> None:
    """A call with no request id cannot be attributed, so it decides nothing."""
    calls = [
        call_line(NOW - timedelta(minutes=2), status="http_error", request_id=None),
        call_line(NOW - timedelta(minutes=1), status="ok"),
    ]
    assert gave_up_requests(calls) == set()


def test_gave_up_breaks_a_tie_on_the_later_timestamp() -> None:
    """Two calls sharing an attempt number are judged by the later one."""
    earlier = call_line(NOW - timedelta(minutes=2), status="timeout", attempt=1)
    later = call_line(NOW - timedelta(minutes=1), status="ok", attempt=1)
    assert gave_up_requests([earlier, later]) == set()
    assert gave_up_requests([later, earlier]) == set()

    late_failure = call_line(NOW, status="timeout", attempt=1)
    assert gave_up_requests([later, late_failure]) == {REQUEST}


def test_gave_up_treats_a_missing_status_as_a_failure() -> None:
    """A status that cannot be read is not a success, so it stays visible."""
    calls = [call_line(NOW, status=None)]
    assert gave_up_requests(calls) == {REQUEST}


def test_tool_rows_count_errors_and_the_last_message() -> None:
    """Each tool gets its calls, errors, rate, p95 and newest error message."""
    tools = [
        tool_line(
            NOW - timedelta(minutes=5), tool="predict_match", error="old failure"
        ),
        tool_line(NOW - timedelta(minutes=4), tool="predict_match", duration_ms=50),
        tool_line(
            NOW - timedelta(minutes=3),
            tool="predict_match",
            status="error",
            duration_ms=77,
            error="Unknown team in the served season",
        ),
        tool_line(NOW - timedelta(minutes=2), tool="league_table", duration_ms=56),
    ]
    rows = {row.tool: row for row in tool_rows(tools)}

    match = rows["predict_match"]
    assert (match.calls, match.errors) == (3, 1)
    assert match.error_rate == 1 / 3
    assert match.p95_ms == 77
    assert match.last_error == "Unknown team in the served season"
    assert rows["league_table"].error_rate == 0.0


def test_tool_rows_sort_by_error_rate_then_name() -> None:
    """The worst tool first; equal rates keep a stable name order."""
    tools = [
        tool_line(NOW, tool="league_table"),
        tool_line(NOW, tool="explain_match"),
        tool_line(NOW, tool="predict_match", status="error", error="boom"),
    ]
    rows = tool_rows(tools)

    assert [row.tool for row in rows] == [
        "predict_match",
        "explain_match",
        "league_table",
    ]


def test_tool_row_with_a_null_error_message() -> None:
    """An error row with no message has no last error, not an empty string."""
    rows = tool_rows([tool_line(NOW, status="error", error=None)])
    assert rows[0].errors == 1
    assert rows[0].last_error is None


def test_model_call_rows_count_attempts_failures_and_retries() -> None:
    """Attempts, failures by status, the failure rate and the retry count."""
    calls = [
        call_line(NOW - timedelta(minutes=9), status="timeout", attempt=1),
        call_line(NOW - timedelta(minutes=8), status="timeout", attempt=2),
        call_line(NOW - timedelta(minutes=7), status="connection_error", attempt=3),
        call_line(NOW - timedelta(minutes=6), status="ok"),
        call_line(NOW - timedelta(minutes=5), dependency="ollama_embed"),
    ]
    retries = [
        retry_line(NOW - timedelta(minutes=9), attempt=1),
        retry_line(NOW - timedelta(minutes=8), attempt=2),
        retry_line(NOW - timedelta(minutes=9), dependency="football_data"),
    ]
    rows = {row.dependency: row for row in model_call_rows(calls, retries)}

    chat = rows["ollama_chat"]
    assert chat.attempts == 4
    assert [(item.status, item.count) for item in chat.failures] == [
        ("timeout", 2),
        ("connection_error", 1),
    ]
    assert chat.failure_rate == 0.75
    assert chat.retries == 2
    assert rows["ollama_embed"].attempts == 1
    assert rows["ollama_embed"].failure_rate == 0.0
    assert [row.dependency for row in model_call_rows(calls, retries)] == [
        "ollama_chat",
        "ollama_embed",
    ]


def test_model_call_rows_link_the_gave_up_requests() -> None:
    """The requests that gave up are listed with their detail links."""
    calls = [
        call_line(NOW, status="connection_error", attempt=1, request_id=OTHER),
        call_line(NOW, status="connection_error", attempt=2, request_id=OTHER),
    ]
    row = model_call_rows(calls, [])[0]

    assert row.attempts == 2
    assert [item.request_id for item in row.gave_up] == [OTHER]
    assert row.gave_up[0].link == f"/requests/{OTHER}"


def test_model_call_rows_skip_dependencies_outside_the_contract() -> None:
    """A refresh dependency is not a model call, so it is not a row here."""
    calls = [call_line(NOW, dependency="football_data", status="http_error")]
    retries = [retry_line(NOW, dependency="football_data")]
    assert model_call_rows(calls, retries) == ()


def test_model_call_rows_count_a_dependency_that_only_retried() -> None:
    """A retry with no readable call still shows, so the count is not hidden."""
    rows = model_call_rows([], [retry_line(NOW, dependency="workers_ai")])
    assert [row.dependency for row in rows] == ["workers_ai"]
    assert rows[0].attempts == 0
    assert rows[0].retries == 1
    assert rows[0].failure_rate is None


def test_model_call_rows_are_empty_without_calls() -> None:
    """An empty window has no model-call rows at all."""
    assert model_call_rows([], []) == ()
    assert MODEL_DEPENDENCIES[0] == "ollama_chat"


def test_model_call_failures_follow_the_contract_order() -> None:
    """The named failure statuses are listed in the contract's order."""
    calls = [
        call_line(NOW - timedelta(minutes=3), status="connection_error"),
        call_line(NOW - timedelta(minutes=2), status="http_error"),
        call_line(NOW - timedelta(minutes=1), status="timeout"),
    ]
    row = model_call_rows(calls, [])[0]
    assert [item.status for item in row.failures] == list(FAILURE_STATUSES)


def test_fallback_rows_group_count_and_sort() -> None:
    """Fallbacks are counted per from/to/cause, the commonest first."""
    fallbacks = [
        fallback_line(NOW - timedelta(minutes=5)),
        fallback_line(NOW - timedelta(minutes=4)),
        fallback_line(
            NOW - timedelta(minutes=3),
            from_path="fresh_match_data",
            to_path="previous_match_data",
            cause="refresh_failed",
        ),
    ]
    rows = fallback_rows(fallbacks)

    assert [(row.from_path, row.to_path, row.cause, row.count) for row in rows] == [
        ("tool_calling", "answer_without_tools", "tool_round_limit", 2),
        ("fresh_match_data", "previous_match_data", "refresh_failed", 1),
    ]
