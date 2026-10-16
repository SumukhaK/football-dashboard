"""Tests for the answer, latency, token and slowest-answer builders.

These are pure functions over small hand-written lists, so every number below is
either the count of the list or a percentile that can be checked by hand.
"""

from __future__ import annotations

from datetime import timedelta

from app.domain.assistant import PATH_ORDER
from app.services.assistant_answers import (
    TOP_ANSWERS,
    abstention_rows,
    cost_summary,
    latency_rows,
    path_rows,
    slowest_answers,
    token_summary,
)

from .assistant_helpers import NOW, REQUEST, abstain_line, answer_line


def test_path_rows_count_each_path_in_contract_order() -> None:
    """The donut counts each contract path, in the contract's order."""
    answers = [
        answer_line(NOW - timedelta(minutes=1), path="model"),
        answer_line(NOW - timedelta(minutes=2), path="router"),
        answer_line(NOW - timedelta(minutes=3), path="model"),
        answer_line(NOW - timedelta(minutes=4), path="model_with_tools"),
    ]
    rows = path_rows(answers)

    assert [row.path for row in rows] == list(PATH_ORDER)
    assert [row.answers for row in rows] == [1, 2, 1]
    assert [row.share for row in rows] == [0.25, 0.5, 0.25]


def test_path_rows_show_a_path_outside_the_contract() -> None:
    """A path the contract does not name is shown, never silently dropped."""
    rows = path_rows([answer_line(NOW, path="router"), answer_line(NOW, path="hybrid")])
    assert [row.path for row in rows] == ["router", "hybrid"]
    assert rows[1].share == 0.5


def test_path_rows_share_is_none_without_answers() -> None:
    """An empty window has no shares, not a division by zero."""
    assert path_rows([]) == ()


def test_abstention_rows_count_reasons_most_common_first() -> None:
    """Abstentions are counted per reason, with a null reason kept visible."""
    abstains = [
        abstain_line(NOW, reason="low_score"),
        abstain_line(NOW, reason="low_score"),
        abstain_line(NOW, reason="model_declined"),
        abstain_line(NOW, reason="no_retrieval"),
        abstain_line(NOW, reason=None),
    ]
    rows = abstention_rows(abstains)

    # The most common reason first; the ties are in reason order, so the run
    # stays identical between two loads of the same window.
    assert [(row.reason, row.count) for row in rows] == [
        ("low_score", 2),
        ("<unknown>", 1),
        ("model_declined", 1),
        ("no_retrieval", 1),
    ]


def test_latency_rows_are_per_path_percentiles() -> None:
    """Each path gets its own p50 and p95 over the answers on it."""
    answers = [
        answer_line(NOW, path="model", duration_ms=1499),
        answer_line(NOW, path="model", duration_ms=3292),
        answer_line(NOW, path="model", duration_ms=73627),
        answer_line(NOW, path="router", duration_ms=58),
    ]
    rows = {row.path: row for row in latency_rows(answers)}

    assert rows["model"].answers == 3
    assert rows["model"].p50_ms == 3292
    assert rows["model"].p95_ms == 73627
    assert rows["router"].p50_ms == 58 and rows["router"].p95_ms == 58
    assert [row.path for row in latency_rows(answers)] == ["router", "model"]


def test_latency_rows_are_empty_without_answers() -> None:
    """No answers means no latency rows."""
    assert latency_rows([]) == ()


def test_latency_rows_skip_an_answer_with_no_duration() -> None:
    """A path whose answer reported no duration has no latency row."""
    answers = [
        answer_line(NOW, path="router", duration_ms=None),
        answer_line(NOW, path="model", duration_ms=100),
    ]
    assert [row.path for row in latency_rows(answers)] == ["model"]


def test_token_summary_ignores_nulls_and_totals_the_rest() -> None:
    """Only the reported values count; a null is not a zero."""
    answers = [
        answer_line(NOW, prompt_tokens=10),
        answer_line(NOW, prompt_tokens=None),
        answer_line(NOW, prompt_tokens=30),
        answer_line(NOW, prompt_tokens=20),
    ]
    summary = token_summary(answers, "prompt_tokens")

    assert summary.total == 60
    assert summary.p50 == 20
    assert summary.p95 == 30


def test_token_summary_is_none_when_every_value_is_null() -> None:
    """All-null tokens report nothing at all, so the page can say so."""
    answers = [answer_line(NOW, completion_tokens=None)]
    summary = token_summary(answers, "completion_tokens")

    assert summary.total is None
    assert summary.p50 is None and summary.p95 is None


def test_cost_summary_is_none_not_zero_when_unreported() -> None:
    """A null cost_usd is never estimated or rounded to zero."""
    total, per_answer = cost_summary([answer_line(NOW, cost_usd=None)])
    assert total is None
    assert per_answer is None


def test_cost_summary_averages_only_the_answers_that_report_it() -> None:
    """The per-answer cost divides by the answers that reported a cost."""
    answers = [
        answer_line(NOW, cost_usd=0.02),
        answer_line(NOW, cost_usd=0.04),
        answer_line(NOW, cost_usd=None),
    ]
    total, per_answer = cost_summary(answers)

    assert total == 0.06
    assert per_answer == 0.03


def test_slowest_answers_are_capped_and_tie_broken() -> None:
    """Slowest first, ties by timestamp then request id, and only ten rows."""
    answers = [
        answer_line(
            NOW - timedelta(minutes=minute), duration_ms=1000, request_id=f"r{minute}"
        )
        for minute in range(1, TOP_ANSWERS + 4)
    ]
    answers.append(answer_line(NOW, duration_ms=1000, request_id="first"))
    rows = slowest_answers(answers)

    assert len(rows) == TOP_ANSWERS
    assert rows[0].request_id == "first"
    assert rows[1].request_id == "r1"
    assert rows[-1].request_id == f"r{TOP_ANSWERS - 1}"


def test_slowest_answers_keep_path_rounds_and_a_link() -> None:
    """Each row carries what the table shows and the detail link."""
    answers = [
        answer_line(
            NOW,
            path="model_with_tools",
            tool_rounds=3,
            duration_ms=9744,
            request_id=REQUEST,
        )
    ]
    row = slowest_answers(answers)[0]

    assert row.path == "model_with_tools"
    assert row.tool_rounds == 3
    assert row.link == f"/requests/{REQUEST}"


def test_slowest_answer_without_a_request_id_has_no_link() -> None:
    """An answer with no request id is still listed, just not linked."""
    row = slowest_answers([answer_line(NOW, request_id=None)])[0]
    assert row.request_id is None
    assert row.link == ""


def test_a_null_duration_ranks_last_but_stays_visible() -> None:
    """An answer with no duration is listed last, never as the fastest."""
    rows = slowest_answers(
        [
            answer_line(NOW - timedelta(minutes=1), duration_ms=None),
            answer_line(NOW - timedelta(minutes=2), duration_ms=5),
        ]
    )
    assert [row.duration_ms for row in rows] == [5, None]
