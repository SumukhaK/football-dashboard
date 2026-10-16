"""Tests for the requests list route: its filters, its rows and its paging."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.config import Config
from app.dependencies import get_requests
from app.main import create_app
from app.services.requests import RequestsService

from .requests_helpers import (
    CLOCK_TIME,
    BrokenSource,
    chat_request_id,
    make_client,
    make_line,
    make_list_client,
)


def test_requests_page_lists_requests_and_filters() -> None:
    """GET /requests shows the filter form and a table of requests."""
    response = make_client().get("/requests")
    assert response.status_code == 200
    body = response.text
    assert 'id="requests-body"' in body
    assert 'class="request-filters"' in body
    assert "Load more" in body


def test_status_filter_is_applied_and_selected() -> None:
    """The status filter narrows the list and comes back in the box."""
    body = make_client().get("/requests?status=5xx").text
    assert 'name="status"' in body
    assert 'value="5xx"' in body
    assert 'class="pill pill-fail"' in body


def test_a_blank_filter_form_returns_the_same_rows() -> None:
    """A plain Filter submit sends empty boxes; it must not empty the list."""
    client = make_client()
    plain = client.get("/requests?hours=24").text
    blank = client.get(
        "/requests?hours=24&route=&status=&event=&request_id=&component="
    ).text
    assert blank.count('href="/requests/') == plain.count('href="/requests/')
    assert blank.count('href="/requests/') > 0
    assert "No requests match" not in blank


def test_the_form_keeps_an_event_and_a_status_it_cannot_offer() -> None:
    """An event outside the list and an exact status survive a submit."""
    body = make_client().get("/requests?event=app.error&status=503").text
    assert 'value="app.error" selected' in body
    assert 'name="status"' in body and 'value="503"' in body


def test_the_form_keeps_a_degraded_links_component() -> None:
    """A degraded-assistant link keeps both its event and its component."""
    body = (
        make_client().get("/requests?event=component.degraded&component=assistant").text
    )
    assert 'value="component.degraded" selected' in body
    assert 'name="component" value="assistant"' in body


def test_unsupported_hours_returns_structured_422() -> None:
    """A window the picker does not offer is a 422 with error and detail."""
    response = make_client().get("/requests?hours=5")
    assert response.status_code == 422
    assert "error" in response.json()


def test_invalid_status_returns_structured_422() -> None:
    """A status filter that is neither a class nor a code is a 422."""
    response = make_client().get("/requests?status=abc")
    assert response.status_code == 422
    assert "detail" in response.json()


def test_a_typed_request_id_redirects_to_the_detail() -> None:
    """A request id in the search box jumps straight to the detail page."""
    request_id = chat_request_id()
    response = make_client().get(
        f"/requests?request_id={request_id}", follow_redirects=False
    )
    assert response.status_code == 303
    assert response.headers["location"] == f"/requests/{request_id}"


def test_an_htmx_request_id_asks_the_browser_to_navigate() -> None:
    """HTMX swaps the reply, so it gets an HX-Redirect rather than a 303."""
    request_id = chat_request_id()
    response = make_client().get(
        f"/requests?request_id={request_id}",
        headers={"HX-Request": "true"},
        follow_redirects=False,
    )
    assert response.status_code == 200
    assert response.headers["HX-Redirect"] == f"/requests/{request_id}"


def test_a_blank_request_id_does_not_redirect() -> None:
    """An empty box is no request id, so the list renders as usual."""
    response = make_client().get("/requests?request_id=", follow_redirects=False)
    assert response.status_code == 200
    assert "HX-Redirect" not in response.headers


def test_a_malformed_request_id_is_rejected_without_a_redirect() -> None:
    """A typed path cannot be used to land somewhere else."""
    response = make_client().get(
        "/requests?request_id=../errors", follow_redirects=False
    )
    assert response.status_code == 422
    assert "HX-Redirect" not in response.headers
    assert "detail" in response.json()


def test_appended_rows_return_only_rows_plus_the_next_button() -> None:
    """The load-more endpoint answers with table rows and an out-of-band button."""
    response = make_client().get("/partials/request_rows?hours=24")
    assert response.status_code == 200
    assert "<!DOCTYPE html>" not in response.text
    assert "<tr>" in response.text
    assert 'hx-swap-oob="true"' in response.text


def test_overview_error_rate_link_lands_on_a_filtered_list() -> None:
    """The Overview's 5xx link opens Requests filtered to 5xx."""
    response = make_client().get("/requests?hours=24&status=5xx")
    assert response.status_code == 200
    assert 'value="5xx"' in response.text


def test_source_error_renders_a_banner_with_status_200() -> None:
    """A failing source shows a banner and 200, never a 500."""
    app = create_app(Config(), clock=lambda: CLOCK_TIME)
    broken = RequestsService(BrokenSource(), lambda: CLOCK_TIME, Config())
    app.dependency_overrides[get_requests] = lambda: broken

    response = TestClient(app).get("/requests")
    assert response.status_code == 200
    assert "google is down" in response.text


def test_an_event_filter_with_no_matches_shows_the_empty_message() -> None:
    """A crash filter on a window without a crash lists nothing, not everything."""
    client = make_list_client(
        [
            make_line(
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
    client = make_list_client(
        [
            make_line(
                10,
                "http.request",
                "req-aaaaaaaa",
                {"route": "/v2/predict", "status": 200},
            ),
            make_line(
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
    client = make_list_client(
        [
            make_line(
                10,
                "http.request",
                "req-aaaaaaaa",
                {"route": "/v2/predict", "status": 200},
            ),
            make_line(5, "retry", "req-aaaaaaaa", {"dependency": "ollama_chat"}),
        ]
    )
    body = client.get("/requests?hours=1&event=retry&component=assistant").text
    assert 'name="component"' not in body
    assert "No requests match" not in body
    assert 'href="/requests/req-aaaaaaaa"' in body


def test_an_htmx_invalid_request_id_reports_it_under_the_field() -> None:
    """HTMX cannot swap a 422 body, so the message comes back in the body."""
    response = make_client().get(
        "/requests?request_id=../errors",
        headers={"HX-Request": "true"},
        follow_redirects=False,
    )
    assert response.status_code == 200
    assert 'id="requests-body"' in response.text
    assert "Not a valid request ID" in response.text
    assert "HX-Redirect" not in response.headers


def test_a_route_without_a_path_returns_structured_422() -> None:
    """A route box Cloud Logging would reject is a 422, never a 500."""
    response = make_client().get("/requests?route=chat")
    assert response.status_code == 422
    assert "detail" in response.json()


def test_an_htmx_invalid_route_reports_it_under_the_field() -> None:
    """An HTMX submit keeps the list around and points at the route box."""
    response = make_client().get(
        "/requests?route=chat",
        headers={"HX-Request": "true"},
        follow_redirects=False,
    )
    assert response.status_code == 200
    assert 'id="requests-body"' in response.text
    assert "field-error" in response.text
    assert "Enter a route starting with /" in response.text
    assert 'value="chat"' in response.text


def test_a_row_without_a_request_id_renders_no_link() -> None:
    """A line with no request id shows its time without a link to nowhere."""
    client = make_list_client(
        [
            make_line(
                10,
                "http.request",
                None,
                {"route": "/v2/predict", "status": 200},
            )
        ]
    )
    body = client.get("/requests?hours=1").text
    assert "/requests/None" not in body
    assert "No requests match" not in body


def test_the_truncation_banner_shows_when_the_id_cap_is_hit() -> None:
    """More matching requests than the cap means the page says it is partial."""
    events = [
        make_line(
            minute,
            "http.request",
            f"req-{minute:08d}",
            {"route": "/v2/predict", "status": 200},
        )
        for minute in range(1, 251)
    ]
    events += [
        make_line(minute, "retry", f"req-{minute:08d}", {}) for minute in range(1, 251)
    ]

    body = make_list_client(events).get("/requests?hours=24&event=retry").text
    assert "narrow them" in body
    assert "Load more" in body
