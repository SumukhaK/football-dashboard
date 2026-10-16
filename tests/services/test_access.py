"""Tests for the access page model."""

from __future__ import annotations

from app.domain.access import AccessModel
from app.domain.models import MAX_QUERY_LIMIT, EventQuery, TelemetryEvent
from app.domain.overview import Chart
from app.services.windows import window_for_hours
from tests.services.access_helpers import (
    NOW,
    ListSource,
    auth_line,
    fixture_service,
    guardrail_line,
    make_service,
    moment,
    ratelimit_line,
)
from tests.services.data_jobs_helpers import RecordingSource

WINDOW = window_for_hours(24, NOW)


def _total(chart: Chart) -> float:
    """The total of a chart's one series, treating a missing point as zero."""
    return sum(value or 0.0 for value in chart.series[0].values)


def _model(events: list[TelemetryEvent]) -> AccessModel:
    """The access model over the given events, one-day window."""
    return make_service(ListSource(events)).build(WINDOW)


class FullSource(ListSource):
    """A source that always returns a full page of one sign-in event."""

    def __init__(self) -> None:
        super().__init__([auth_line(NOW)])

    def events(self, query: EventQuery) -> list[TelemetryEvent]:
        """Return exactly the query's limit, so the service flags truncation."""
        return [self._events[0]] * query.limit


def test_sign_in_outcomes_are_counted_commonest_first_ties_by_name() -> None:
    """Counts lead with the biggest, and a tie breaks on the outcome name."""
    events = [
        auth_line(moment(minutes=5), outcome="ok"),
        auth_line(moment(minutes=4), outcome="ok"),
        auth_line(moment(minutes=3), outcome="failed"),
        auth_line(moment(minutes=2), outcome="failed"),
        auth_line(moment(minutes=1), outcome="failed"),
        auth_line(moment(minutes=1), outcome="blocked"),
    ]
    sign_in = _model(events).sign_in
    assert [(row.outcome, row.count) for row in sign_in] == [
        ("failed", 3),
        ("ok", 2),
        ("blocked", 1),
    ]


def test_sign_ins_ignore_the_other_actions() -> None:
    """A consent or invite event is not a sign-in."""
    events = [
        auth_line(moment(minutes=2), action="consent", outcome="ok"),
        auth_line(moment(minutes=1), action="redeem_invite", outcome="ok"),
    ]
    assert _model(events).sign_in == ()


def test_the_failed_sign_ins_chart_counts_only_failed_outcomes() -> None:
    """The chart counts failed attempts; lockouts are shown, not charted."""
    events = [
        auth_line(moment(minutes=30), outcome="failed"),
        auth_line(moment(minutes=20), outcome="failed"),
        auth_line(moment(minutes=10), outcome="locked_out"),
        auth_line(moment(minutes=5), outcome="ok"),
    ]
    chart = _model(events).failed_sign_ins
    assert chart.series[0].name == "failed"
    assert _total(chart) == 2.0
    assert len(chart.labels) == len(chart.series[0].values)


def test_lockouts_list_the_blocked_and_locked_out_newest_first() -> None:
    """Only the blocking outcomes reach the list, newest first."""
    events = [
        auth_line(moment(minutes=30), outcome="failed", user_ref="aaaa"),
        auth_line(moment(minutes=20), outcome="blocked", user_ref="bbbb"),
        auth_line(moment(minutes=10), outcome="locked_out", user_ref="cccc"),
    ]
    lockouts = _model(events).lockouts
    assert [(row.outcome, row.user_ref) for row in lockouts] == [
        ("locked_out", "cccc"),
        ("blocked", "bbbb"),
    ]
    assert lockouts[0].timestamp == moment(minutes=10)


def test_a_lockout_without_a_known_account_is_shown_with_no_reference() -> None:
    """The account is optional in the contract, so a null user_ref is allowed."""
    events = [auth_line(moment(minutes=1), outcome="blocked", user_ref=None)]
    assert _model(events).lockouts[0].user_ref is None


def test_top_clients_are_ordered_by_count_ties_by_client_ref() -> None:
    """The busiest client leads; equal counts break on the reference."""
    events = [
        ratelimit_line(moment(minutes=5), client_ref="bbb"),
        ratelimit_line(moment(minutes=4), client_ref="bbb"),
        ratelimit_line(moment(minutes=3), client_ref="aaa"),
        ratelimit_line(moment(minutes=2), client_ref="aaa"),
        ratelimit_line(moment(minutes=1), client_ref="ccc"),
    ]
    rows = _model(events).top_clients
    assert [row.client_ref for row in rows] == ["aaa", "bbb", "ccc"]
    assert [row.count for row in rows] == [2, 2, 1]


def test_top_clients_is_capped_at_ten() -> None:
    """Only the ten busiest clients are listed."""
    events = [
        ratelimit_line(moment(minutes=index + 1), client_ref=f"client-{index:02d}")
        for index in range(12)
    ]
    rows = _model(events).top_clients
    assert len(rows) == 10
    assert [row.client_ref for row in rows] == [f"client-{i:02d}" for i in range(10)]


def test_a_client_keeps_the_routes_it_hit_once_and_sorted() -> None:
    """A client's routes are deduplicated and sorted for a stable row."""
    events = [
        ratelimit_line(moment(minutes=3), client_ref="aaa", route="/v2/predict"),
        ratelimit_line(moment(minutes=2), client_ref="aaa", route="/v2/health"),
        ratelimit_line(moment(minutes=1), client_ref="aaa", route="/v2/predict"),
    ]
    rows = _model(events).top_clients
    assert rows[0].routes == ("/v2/health", "/v2/predict")


def test_rate_limiting_totals_and_charts_the_rejections() -> None:
    """The total count and the per-interval chart both follow the same events."""
    events = [
        ratelimit_line(moment(minutes=5)),
        ratelimit_line(moment(minutes=4)),
        ratelimit_line(moment(minutes=3)),
    ]
    model = _model(events)
    assert model.rate_limited == 3
    assert model.rate_limit.series[0].name == "429"
    assert _total(model.rate_limit) == 3.0


def test_invites_and_consent_always_list_both_actions() -> None:
    """An empty window still lists the actions, saying there was nothing."""
    assert [(row.action, row.outcomes) for row in _model([]).other_actions] == [
        ("redeem_invite", ()),
        ("consent", ()),
    ]


def test_invites_and_consent_count_each_action_by_outcome() -> None:
    """Each action keeps its own outcome counts."""
    events = [
        auth_line(moment(minutes=4), action="redeem_invite", outcome="ok"),
        auth_line(moment(minutes=3), action="redeem_invite", outcome="invalid_invite"),
        auth_line(moment(minutes=2), action="consent", outcome="consent_required"),
        auth_line(moment(minutes=1), action="consent", outcome="ok"),
    ]
    actions = _model(events).other_actions
    assert [
        (row.action, [(o.outcome, o.count) for o in row.outcomes]) for row in actions
    ] == [
        ("redeem_invite", [("invalid_invite", 1), ("ok", 1)]),
        ("consent", [("consent_required", 1), ("ok", 1)]),
    ]


def test_the_guardrail_section_is_absent_without_events() -> None:
    """No guardrail events means no rows, which the template reads as no section."""
    assert _model([]).guardrails == ()


def test_the_guardrail_section_appears_with_one_event() -> None:
    """One guardrail event is counted by kind and outcome."""
    rows = _model([guardrail_line(moment(minutes=1))]).guardrails
    assert [(row.kind, row.outcome, row.count) for row in rows] == [
        ("prompt_injection", "blocked", 1)
    ]


def test_guardrails_are_ordered_commonest_first_then_by_name() -> None:
    """The noisiest guardrail leads; ties break on kind then outcome."""
    events = [
        guardrail_line(moment(minutes=3), kind="pii", outcome="redacted"),
        guardrail_line(moment(minutes=2), kind="pii", outcome="redacted"),
        guardrail_line(moment(minutes=1), kind="prompt_injection", outcome="blocked"),
    ]
    rows = _model(events).guardrails
    assert [(row.kind, row.outcome) for row in rows] == [
        ("pii", "redacted"),
        ("prompt_injection", "blocked"),
    ]


def test_the_access_page_reads_only_the_three_access_event_types() -> None:
    """One read, asking for the sign-in, rate-limit and guardrail events only."""
    source = RecordingSource([])
    make_service(source).build(WINDOW)
    assert len(source.queries) == 1
    query = source.queries[0]
    assert set(query.events) == {"auth.event", "ratelimit.rejected", "guardrail.event"}
    assert query.window == WINDOW
    assert query.limit == MAX_QUERY_LIMIT


def test_truncation_is_visible_when_the_read_fills_the_page() -> None:
    """A read that returns the whole limit is flagged as partial."""
    model = make_service(FullSource()).build(WINDOW)
    assert model.truncated is True
    assert model.limit == MAX_QUERY_LIMIT


def test_an_empty_window_says_nothing_happened_in_every_section() -> None:
    """Nothing read means empty sections, never a fabricated row."""
    model = _model([])
    assert model.sign_in == ()
    assert model.lockouts == ()
    assert model.rate_limited == 0
    assert _total(model.rate_limit) == 0.0
    assert model.top_clients == ()
    assert model.guardrails == ()
    assert model.truncated is False


def test_the_default_window_is_one_day() -> None:
    """The picker's default on this page is the day."""
    assert make_service(ListSource([])).resolve_hours(None) == 24


def test_fixture_scenario_shows_the_lockout_run_and_the_429_burst() -> None:
    """The fixture's failed run ends in a lockout and one client takes the 429s."""
    model = fixture_service().build_for_hours(24)
    outcomes = {row.outcome: row.count for row in model.sign_in}
    assert outcomes == {"ok": 40, "failed": 5, "locked_out": 1, "blocked": 1}
    assert _total(model.failed_sign_ins) == 5.0
    assert [(row.outcome, row.user_ref) for row in model.lockouts] == [
        ("locked_out", "d23f0824128b2f33"),
        ("blocked", "1818e811892f902b"),
    ]
    assert model.rate_limited == 30
    assert [(row.client_ref, row.count, row.routes) for row in model.top_clients] == [
        ("9e4c5aabbde6c9d3", 30, ("/v2/predict",))
    ]


def test_fixture_scenario_shows_the_invite_and_consent_counts() -> None:
    """Invite and consent outcomes are counted apart from the sign-ins."""
    actions = {
        row.action: {outcome.outcome: outcome.count for outcome in row.outcomes}
        for row in fixture_service().build_for_hours(24).other_actions
    }
    assert actions["redeem_invite"] == {
        "ok": 1,
        "invalid_invite": 1,
        "weak_password": 1,
    }
    assert actions["consent"] == {"ok": 24, "consent_required": 1}


def test_fixture_scenario_has_no_guardrail_events() -> None:
    """The fixture carries no guardrail event, so the section stays away."""
    assert fixture_service().build_for_hours(24).guardrails == ()
