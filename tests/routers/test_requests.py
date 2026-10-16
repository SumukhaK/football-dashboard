"""Tests for the requests routes and the request detail."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from app.config import Config
from app.contract import load_contract
from app.dependencies import get_requests
from app.domain.errors import SourceUnavailableError
from app.domain.models import (
    MAX_QUERY_LIMIT,
    ErrorGroup,
    EventQuery,
    PlatformEvent,
    TelemetryEvent,
    TimeWindow,
    Trace,
)
from app.main import create_app
from app.services.requests import RequestsService
from app.services.windows import window_for_hours
from app.sources.filtering import select_events
from app.sources.fixture_source import FixtureSource

CLOCK_TIME = datetime(2026, 10, 8, 18, 0, tzinfo=UTC)
RETRY_TRACE = "923a736994e3bf911a61dbe22e44158b"


def _client() -> TestClient:
    """A test client over the fixture source with a fixed clock."""
    return TestClient(create_app(Config(), clock=lambda: CLOCK_TIME))


def _chat_request_id() -> str:
    """The fixture request whose trace carries the two retries."""
    source = FixtureSource(Config().fixture_dir, load_contract(), now=CLOCK_TIME)
    window = window_for_hours(24, CLOCK_TIME)
    for event in source.events(
        EventQuery(window=window, events=("http.request",), limit=MAX_QUERY_LIMIT)
    ):
        if event.trace_id == RETRY_TRACE and event.request_id:
            return event.request_id
    raise AssertionError("the fixture chat request was not found")


def test_requests_page_lists_requests_and_filters() -> None:
    """GET /requests shows the filter form and a table of requests."""
    response = _client().get("/requests")
    assert response.status_code == 200
    body = response.text
    assert 'id="requests-body"' in body
    assert 'class="request-filters"' in body
    assert "Load more" in body


def test_status_class_filter_is_applied_and_selected() -> None:
    """The status filter narrows the list and comes back in the box."""
    body = _client().get("/requests?status=5xx").text
    assert 'name="status"' in body
    assert 'value="5xx"' in body
    assert "status-error" in body


def test_a_blank_filter_form_returns_the_same_rows() -> None:
    """A plain Filter submit sends empty boxes; it must not empty the list."""
    client = _client()
    plain = client.get("/requests?hours=24").text
    blank = client.get(
        "/requests?hours=24&route=&status=&event=&request_id=&component="
    ).text
    assert blank.count('href="/requests/') == plain.count('href="/requests/')
    assert blank.count('href="/requests/') > 0
    assert "No requests match" not in blank


def test_the_form_keeps_an_event_and_a_status_it_cannot_offer() -> None:
    """An event outside the list and an exact status survive a submit."""
    body = _client().get("/requests?event=app.error&status=503").text
    assert 'value="app.error" selected' in body
    assert 'name="status"' in body and 'value="503"' in body


def test_the_form_keeps_a_degraded_links_component() -> None:
    """A degraded-assistant link keeps both its event and its component."""
    body = _client().get("/requests?event=component.degraded&component=assistant").text
    assert 'value="component.degraded" selected' in body
    assert 'name="component" value="assistant"' in body


def test_unsupported_hours_returns_structured_422() -> None:
    """A window the picker does not offer is a 422 with error and detail."""
    response = _client().get("/requests?hours=5")
    assert response.status_code == 422
    assert "error" in response.json()


def test_invalid_status_returns_structured_422() -> None:
    """A status filter that is neither a class nor a code is a 422."""
    response = _client().get("/requests?status=abc")
    assert response.status_code == 422
    assert "detail" in response.json()


def test_a_route_without_a_slash_returns_structured_422() -> None:
    """A route that cannot be a template is a 422 on every source, not a 500."""
    response = _client().get("/requests?route=chat")
    assert response.status_code == 422
    assert "route" in response.json()["detail"]


def test_a_typed_request_id_redirects_to_the_detail() -> None:
    """A request id in the search box jumps straight to the detail page."""
    request_id = _chat_request_id()
    response = _client().get(
        f"/requests?request_id={request_id}", follow_redirects=False
    )
    assert response.status_code == 303
    assert response.headers["location"] == f"/requests/{request_id}"


def test_an_htmx_request_id_asks_the_browser_to_navigate() -> None:
    """HTMX swaps the reply, so it gets an HX-Redirect rather than a 303."""
    request_id = _chat_request_id()
    response = _client().get(
        f"/requests?request_id={request_id}",
        headers={"HX-Request": "true"},
        follow_redirects=False,
    )
    assert response.status_code == 200
    assert response.headers["HX-Redirect"] == f"/requests/{request_id}"


def test_a_blank_request_id_does_not_redirect() -> None:
    """An empty box is no request id, so the list renders as usual."""
    response = _client().get("/requests?request_id=", follow_redirects=False)
    assert response.status_code == 200
    assert "HX-Redirect" not in response.headers


def test_a_malformed_request_id_is_rejected_without_a_redirect() -> None:
    """A typed path cannot be used to land somewhere else."""
    response = _client().get("/requests?request_id=../errors", follow_redirects=False)
    assert response.status_code == 422
    assert "HX-Redirect" not in response.headers
    assert "detail" in response.json()


def test_detail_shows_the_waterfall_with_the_retries() -> None:
    """The chat's detail names its route and draws the two retry markers."""
    body = _client().get(f"/requests/{_chat_request_id()}").text
    assert "/v2/assistant/chat" in body
    assert "Trace waterfall" in body
    assert body.count("wf-marker") >= 2
    assert "retry" in body


def test_appended_rows_return_only_rows_plus_the_next_button() -> None:
    """The load-more endpoint answers with table rows and an out-of-band button."""
    response = _client().get("/partials/request_rows?hours=24")
    assert response.status_code == 200
    assert "<!DOCTYPE html>" not in response.text
    assert "<tr>" in response.text
    assert 'hx-swap-oob="true"' in response.text


def test_unknown_request_returns_structured_404() -> None:
    """An id with no lines is a 404 with error and detail."""
    response = _client().get("/requests/req-unknown001")
    assert response.status_code == 404
    assert "error" in response.json()


def test_invalid_request_id_returns_structured_422() -> None:
    """An id that is not the right shape is a 422 before any read."""
    response = _client().get("/requests/tiny")
    assert response.status_code == 422
    assert "detail" in response.json()


def test_overview_error_rate_link_lands_on_a_filtered_list() -> None:
    """The Overview's 5xx link opens Requests filtered to 5xx."""
    response = _client().get("/requests?hours=24&status=5xx")
    assert response.status_code == 200
    assert 'value="5xx"' in response.text


class BrokenSource:
    """A telemetry source whose reads always fail."""

    def events(self, query: EventQuery) -> list[TelemetryEvent]:
        """Always fails."""
        raise SourceUnavailableError("unavailable", "google is down")

    def trace(self, trace_id: str) -> Trace | None:
        """Always fails."""
        raise SourceUnavailableError("unavailable", "google is down")

    def error_groups(self, window: TimeWindow) -> list[ErrorGroup]:
        """Always fails."""
        raise SourceUnavailableError("unavailable", "google is down")

    def platform_events(self, window: TimeWindow) -> list[PlatformEvent]:
        """Always fails."""
        raise SourceUnavailableError("unavailable", "google is down")


def test_source_error_renders_a_banner_with_status_200() -> None:
    """A failing source shows a banner and 200, never a 500."""
    app = create_app(Config(), clock=lambda: CLOCK_TIME)
    broken = RequestsService(BrokenSource(), lambda: CLOCK_TIME, Config())
    app.dependency_overrides[get_requests] = lambda: broken

    response = TestClient(app).get("/requests")
    assert response.status_code == 200
    assert "google is down" in response.text


class BrokenTraceSource(FixtureSource):
    """The fixture source with a failing trace read."""

    def trace(self, trace_id: str) -> Trace | None:
        """Always fails."""
        raise SourceUnavailableError("unavailable", "trace is down")


def test_a_detail_source_failure_renders_a_banner() -> None:
    """A failing read on the detail page shows the banner, never a 500."""
    app = create_app(Config(), clock=lambda: CLOCK_TIME)
    broken = RequestsService(BrokenSource(), lambda: CLOCK_TIME, Config())
    app.dependency_overrides[get_requests] = lambda: broken

    response = TestClient(app).get("/requests/req-00000001")
    assert response.status_code == 200
    assert "google is down" in response.text
    assert "Timeline" not in response.text


def test_a_failed_trace_read_still_shows_the_timeline() -> None:
    """The lines were read, so the page only reports that the trace is missing."""
    request_id = _chat_request_id()
    source = BrokenTraceSource(Config().fixture_dir, load_contract(), now=CLOCK_TIME)
    app = create_app(Config(), clock=lambda: CLOCK_TIME)
    app.dependency_overrides[get_requests] = lambda: RequestsService(
        source, lambda: CLOCK_TIME, Config()
    )

    response = TestClient(app).get(f"/requests/{request_id}")
    assert response.status_code == 200
    assert "Timeline" in response.text
    assert "Trace waterfall" not in response.text
    assert "could not be loaded" in response.text


def _line(
    minutes_ago: int,
    event: str,
    request_id: str,
    attributes: dict[str, object],
) -> TelemetryEvent:
    """One catalogued line, minutes_ago before the fixed clock."""
    return TelemetryEvent(
        timestamp=CLOCK_TIME - timedelta(minutes=minutes_ago),
        severity="INFO",
        event=event,
        message=event,
        request_id=request_id,
        trace_id=None,
        span_id=None,
        revision=None,
        attributes=attributes,
    )


class ListSource:
    """An in-memory source over a fixed list of events."""

    def __init__(self, events: list[TelemetryEvent]) -> None:
        self._events = events

    def events(self, query: EventQuery) -> list[TelemetryEvent]:
        """Return the stored events that match the query, newest first."""
        return select_events(self._events, query)

    def trace(self, trace_id: str) -> Trace | None:
        """There are no traces here."""
        return None

    def error_groups(self, window: TimeWindow) -> list[ErrorGroup]:
        """There are no error groups here."""
        return []

    def platform_events(self, window: TimeWindow) -> list[PlatformEvent]:
        """There are no platform events here."""
        return []


def _list_client(events: list[TelemetryEvent]) -> TestClient:
    """A test client whose requests service reads a fixed list of events."""
    app = create_app(Config(), clock=lambda: CLOCK_TIME)
    service = RequestsService(ListSource(events), lambda: CLOCK_TIME, Config())
    app.dependency_overrides[get_requests] = lambda: service
    return TestClient(app)


def test_an_event_filter_with_no_matches_shows_the_empty_message() -> None:
    """A crash filter on a window without a crash lists nothing, not everything."""
    client = _list_client(
        [
            _line(
                10,
                "http.request",
                "req-aaaaaaaa",
                {"route": "/v2/predict", "status": 200},
            )
        ]
    )
    body = client.get("/requests?hours=1&event=app.crash").text
    assert "No requests match these filters" in body
    assert "Load more" not in body


def test_a_component_filter_with_no_matches_shows_the_empty_message() -> None:
    """A degradation of another component lists nothing either."""
    client = _list_client(
        [
            _line(
                10,
                "http.request",
                "req-aaaaaaaa",
                {"route": "/v2/predict", "status": 200},
            ),
            _line(
                5,
                "component.degraded",
                "req-aaaaaaaa",
                {"component": "fixtures"},
            ),
        ]
    )
    body = client.get(
        "/requests?hours=1&event=component.degraded&component=assistant"
    ).text
    assert "No requests match these filters" in body
    assert "Load more" not in body


def test_switching_the_event_after_a_degraded_link_keeps_the_rows() -> None:
    """The degraded link's component must not survive a change of event."""
    client = _list_client(
        [
            _line(
                10,
                "http.request",
                "req-aaaaaaaa",
                {"route": "/v2/predict", "status": 200},
            ),
            _line(5, "retry", "req-aaaaaaaa", {"dependency": "ollama_chat"}),
        ]
    )
    body = client.get("/requests?hours=1&event=retry&component=assistant").text
    assert 'name="component"' not in body
    assert "No requests match" not in body
    assert 'href="/requests/req-aaaaaaaa"' in body


def test_an_htmx_invalid_request_id_reports_it_under_the_field() -> None:
    """HTMX cannot swap a 422 body, so the message comes back in the body."""
    response = _client().get(
        "/requests?request_id=../errors",
        headers={"HX-Request": "true"},
        follow_redirects=False,
    )
    assert response.status_code == 200
    assert 'id="requests-body"' in response.text
    assert "Not a valid request ID" in response.text
    assert "HX-Redirect" not in response.headers
