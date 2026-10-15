"""Tests for the requests routes and the request detail."""

from __future__ import annotations

from datetime import UTC, datetime

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
    """The status filter narrows the list and comes back selected."""
    body = _client().get("/requests?status=5xx").text
    assert 'value="5xx" selected' in body
    assert "status-error" in body


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


def test_a_typed_request_id_redirects_to_the_detail() -> None:
    """A request id in the search box jumps straight to the detail page."""
    request_id = _chat_request_id()
    response = _client().get(
        f"/requests?request_id={request_id}", follow_redirects=False
    )
    assert response.status_code == 307
    assert response.headers["location"] == f"/requests/{request_id}"


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
    assert 'value="5xx" selected' in response.text


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
