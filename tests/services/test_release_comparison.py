"""Release comparisons reconcile the same bounded samples as the overview."""

from dataclasses import replace
from datetime import date

import pytest

from app.config import Config
from app.domain.models import EventQuery, TelemetryEvent
from app.services.overview import OverviewService
from tests.services.requests_helpers import (
    NOW,
    WINDOW,
    FakeSource,
    event_line,
    request_line,
)


class RecordingSource(FakeSource):
    """Count source operations to catch per-release query growth."""

    def __init__(self, events: list[TelemetryEvent]) -> None:
        """Keep mixed events and each query's immutable predicates."""
        super().__init__(events)
        self.queries: list[EventQuery] = []

    def events(self, query: EventQuery) -> list[TelemetryEvent]:
        """Record then apply the real shared filter before limits."""
        self.queries.append(query)
        return super().events(query)


def mixed_events() -> list[TelemetryEvent]:
    """Uneven traffic makes averaging per-release rates/percentiles incorrect."""
    requests = [
        replace(
            request_line(1, status_code=200),
            api_version="2.5.0",
            attributes={"status": 200, "duration_ms": 10},
        )
        for _ in range(19)
    ]
    requests += [
        replace(
            request_line(2, status_code=503),
            api_version="2.6.0",
            attributes={"status": 503, "duration_ms": 1000},
        ),
        replace(
            request_line(3, status_code=302),
            api_version=None,
            attributes={"status": 302, "duration_ms": 20},
        ),
    ]
    crashes = [replace(event_line(1, "app.crash", None), api_version="2.6.0")]
    return requests + _mixed_answers() + crashes


def _mixed_answers() -> list[TelemetryEvent]:
    """One reported and one unreported assistant cost in different releases."""
    answers = [
        replace(
            event_line(
                1,
                "assistant.answer",
                None,
                {"tokens_in": 10, "tokens_out": 5, "cost_usd": 0.25},
            ),
            api_version="2.5.0",
        ),
        replace(
            event_line(
                2,
                "assistant.answer",
                None,
                {"tokens_in": None, "tokens_out": None, "cost_usd": None},
            ),
            api_version="2.6.0",
        ),
    ]
    return answers


def test_combined_metrics_use_pooled_samples_not_release_averages() -> None:
    """Counts, rates, percentiles and reported-only costs reconcile including unknown."""
    config = Config(inr_per_usd=80, inr_per_usd_as_of=date(2026, 10, 21))
    source = RecordingSource(mixed_events())
    model = OverviewService(source, lambda: NOW, config, ()).build(
        WINDOW, compare_releases=True, release_labels=("quiet",)
    )
    comparison = model.release_comparison
    assert comparison is not None
    total = comparison.total
    assert total.requests == 21 and total.server_errors == 1
    assert total.error_rate == pytest.approx(1 / 21)
    assert total.p50_ms == 10 and total.p95_ms == 20
    assert total.crashes == 1
    assert total.tokens_in == 10 and total.tokens_out == 5
    assert total.cost_label == "INR 20.00" and total.cost_samples == 1
    assert total.assistant_answers == 2
    assert sum(row.requests for row in comparison.rows) == total.requests
    assert sum(row.server_errors for row in comparison.rows) == total.server_errors
    assert sum(row.crashes for row in comparison.rows) == total.crashes
    quiet = next(row for row in comparison.rows if row.version == "quiet")
    assert quiet.observations == 0 and quiet.first_seen is None
    assert quiet.cost_usd is None and quiet.error_rate is None
    assert comparison.rows[-1].version is None
    assert len(source.queries) == 7
    assert len([q for q in source.queries if "assistant.answer" in q.events]) == 1


def test_comparison_is_optional_for_selected_release_views() -> None:
    """Selected charts and six existing queries remain unchanged."""
    source = RecordingSource(mixed_events())
    model = OverviewService(source, lambda: NOW, Config(), ()).build(WINDOW)
    assert model.release_comparison is None and len(source.queries) == 6


def test_semantic_order_stable_metric_ties_and_missing_values_last() -> None:
    """Semantic order is the tie-break; null metrics and unknown are always last."""
    from app.services.release_comparison import compare_releases, sorted_rows

    comparison = compare_releases(
        [], [], [], ("2.9.0", "2.10.0", "2.10.0-rc.1", "label"), Config()
    )
    assert [r.version for r in comparison.rows] == [
        "2.10.0",
        "2.10.0-rc.1",
        "2.9.0",
        "label",
        None,
    ]
    rows = tuple(
        replace(
            r,
            requests=5,
            error_rate=None if r.version == "2.10.0" else 0.5,
            p95_ms=None if r.version == "2.10.0" else 50,
        )
        for r in comparison.rows
    )
    for key in ("requests", "error_rate", "p95"):
        for descending in (True, False):
            ordered = sorted_rows(rows, key, descending)
            assert ordered[-1].version is None
            if key != "requests":
                assert ordered[-2].version == "2.10.0"
                assert ordered[0].version == "2.10.0-rc.1"
    assert sorted_rows(rows, "version", False)[-1].version is None
    with pytest.raises(ValueError):
        sorted_rows(rows, "bad", True)


@pytest.mark.parametrize(
    "value", [None, True, "0.25", float("nan"), float("inf"), -1, 10**400]
)
def test_unusable_cost_and_tokens_are_unreported(value: object) -> None:
    """Unusable measurements cannot inflate totals or claim zero reported cost."""
    from app.services.release_comparison import compare_releases

    answer = event_line(
        1,
        "assistant.answer",
        None,
        {"cost_usd": value, "tokens_in": value, "tokens_out": value},
    )
    total = compare_releases([], [], [answer], (), Config()).total
    assert total.cost_usd is None and total.tokens_in is None
    assert total.cost_samples == total.token_in_samples == 0
    assert total.assistant_answers == 1 and total.cost_label == "Not reported"


def test_zero_cost_and_unconfigured_rate_stay_distinct() -> None:
    """A real zero is reported, but cannot be labelled INR without a configured FX rate."""
    from app.services.release_comparison import compare_releases

    answer = event_line(
        1, "assistant.answer", None, {"cost_usd": 0, "tokens_in": 0, "tokens_out": 0}
    )
    total = compare_releases([], [], [answer], (), Config()).total
    assert total.cost_samples == 1 and total.tokens_in == 0
    assert total.cost_usd == 0 and total.cost_label == "INR conversion unavailable"


def test_cap_boundaries_and_query_count_do_not_scale_with_release_labels() -> None:
    """Comparison reuses the capped request sample instead of independently recounting rows."""
    from app.domain.models import MAX_QUERY_LIMIT

    source = RecordingSource(
        [replace(request_line(1), api_version="2.6.0")] * MAX_QUERY_LIMIT
    )
    model = OverviewService(source, lambda: NOW, Config(), ()).build(
        WINDOW,
        compare_releases=True,
        release_labels=tuple(f"label-{i}" for i in range(100)),
    )
    comparison = model.release_comparison
    assert (
        comparison
        and comparison.truncated
        and comparison.total.requests == MAX_QUERY_LIMIT
    )
    assert sum(r.requests for r in comparison.rows) == MAX_QUERY_LIMIT
    headline = next(n for n in model.headlines if n.key == "requests")
    assert comparison.total.requests == headline.value
    assert len(source.queries) == 7


def test_4xx_and_redirects_are_not_server_errors_and_missing_latency_is_not_zero() -> (
    None
):
    """All requests form the denominator while latency has its own measured sample."""
    from app.services.release_comparison import compare_releases

    rows = [
        replace(request_line(1, status_code=code), attributes={"status": code})
        for code in (302, 404, 503)
    ]
    total = compare_releases(rows, [], [], (), Config()).total
    assert (
        total.requests == 3
        and total.server_errors == 1
        and total.error_rate == pytest.approx(1 / 3)
    )
    assert total.p50_ms is None and total.p95_ms is None and total.latency_samples == 0
