"""Tests for the requests list route: its filters, its rows and its paging."""

from __future__ import annotations

import json
import re
from pathlib import Path

from app.config import Config
from app.dependencies import get_requests
from app.services.requests import RequestsService
from tests.auth.console import console

from .pages_helpers import fixture_line, make_local_client
from .requests_helpers import (
    CLOCK_TIME,
    BrokenSource,
    chat_request_id,
    make_client,
    make_line,
    make_list_client,
)


def test_requests_page_lists_requests_and_filters() -> None:
    """GET /requests shows the search box, the chips bar and the list."""
    response = make_client().get("/requests")
    assert response.status_code == 200
    body = response.text
    assert 'id="requests-body"' in body
    assert 'class="request-search"' in body
    assert 'placeholder="Filter by route, or paste a request ID to open it"' in body
    assert "Load more" in body
    assert 'class="request-row"' in body


def test_status_filter_is_applied_and_selected() -> None:
    """The status filter narrows the list and comes back chosen."""
    body = make_client().get("/requests?status=5xx").text
    assert '<input type="hidden" name="status" value="5xx">' in body
    assert '<span class="chip-label">5xx</span>' in body
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
    assert '<input type="hidden" name="event" value="app.error">' in body
    assert '<input type="hidden" name="status" value="503">' in body
    assert '<span class="chip-label">app.error</span>' in body
    assert '<span class="chip-label">503</span>' in body


def test_the_form_keeps_a_degraded_links_component() -> None:
    """A degraded-assistant link keeps both its event and its component."""
    body = (
        make_client().get("/requests?event=component.degraded&component=assistant").text
    )
    assert '<input type="hidden" name="event" value="component.degraded">' in body
    assert '<input type="hidden" name="component" value="assistant">' in body
    assert '<span class="chip-label">assistant</span>' in body


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
    """The load-more endpoint answers with list items and an out-of-band button."""
    response = make_client().get("/partials/request_rows?hours=24")
    assert response.status_code == 200
    assert "<!DOCTYPE html>" not in response.text
    assert 'class="request-row"' in response.text
    assert 'hx-swap-oob="true"' in response.text


def test_overview_error_rate_link_lands_on_a_filtered_list() -> None:
    """The Overview's 5xx link opens Requests filtered to 5xx."""
    response = make_client().get("/requests?hours=24&status=5xx")
    assert response.status_code == 200
    assert 'value="5xx"' in response.text


def test_source_error_renders_a_banner_with_status_200() -> None:
    """A failing source shows a banner and 200, never a 500."""
    signed = console(clock=lambda: CLOCK_TIME)
    broken = RequestsService(BrokenSource(), lambda: CLOCK_TIME, Config())
    signed.app.dependency_overrides[get_requests] = lambda: broken

    response = signed.client.get("/requests")
    assert response.status_code == 200
    assert "google is down" in response.text


def test_a_timezone_less_line_does_not_break_the_requests_page(
    tmp_path: Path,
) -> None:
    """A line with no timezone offset is counted, and the real request lists."""
    line = fixture_line("http.request")
    line["request_id"] = "req-bad00001"
    line["timestamp"] = "2026-10-08T17:00:00.000Z"
    naive = dict(line)
    naive["request_id"] = "req-bad00002"
    naive["timestamp"] = "2026-10-08T16:00:00"
    path = tmp_path / "api.jsonl"
    path.write_text(
        json.dumps(naive) + "\n" + json.dumps(line) + "\n", encoding="utf-8"
    )

    response = make_local_client(path).get("/requests")
    assert response.status_code == 200
    assert 'href="/requests/req-bad00001"' in response.text
    assert "req-bad00002" not in response.text


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
    assert 'href="/requests/req-aaaaaaaa?hours=1"' in body


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


def test_a_chip_removes_only_its_own_filter() -> None:
    """Each chip's remove link keeps every other active filter."""
    body = make_client().get("/requests?hours=24&status=5xx&event=app.error").text
    assert 'href="/requests?hours=24&amp;event=app.error"' in body
    assert 'href="/requests?hours=24&amp;status=5xx"' in body


def test_clear_all_drops_every_filter() -> None:
    """Clear all is the list for the same window with nothing filtered."""
    body = make_client().get("/requests?hours=24&status=5xx&event=app.error").text
    assert 'class="clear-all" href="/requests?hours=24"' in body


def test_a_typed_request_id_in_the_search_box_opens_the_detail() -> None:
    """The box filters by route, but a pasted id jumps to its detail page."""
    request_id = chat_request_id()
    response = make_client().get(
        f"/requests?route={request_id}", follow_redirects=False
    )
    assert response.status_code == 303
    assert response.headers["location"] == f"/requests/{request_id}"


def test_a_row_opens_its_panel_and_pushes_the_panel_url() -> None:
    """The whole row is a link that swaps the panel in and records it in the URL."""
    body = make_client().get("/requests?hours=24").text
    match = re.search(r'href="/requests/([A-Za-z0-9._-]+)\?hours=24"', body)
    assert match is not None
    request_id = match.group(1)
    assert f'hx-get="/partials/requests/{request_id}/panel?' in body
    assert 'hx-target="#request-panel"' in body
    assert f"open={request_id}" in body


def test_an_open_id_renders_the_panel_on_a_full_page_load() -> None:
    """A shared list URL with ?open= comes back with the panel already open."""
    request_id = chat_request_id()
    body = make_client().get(f"/requests?hours=24&open={request_id}").text
    assert 'class="request-panel is-open"' in body
    assert "Trace waterfall" in body
    assert "Open full timeline" in body


def test_an_unknown_open_id_says_so_without_a_500() -> None:
    """A panel for an id that is not in the window is a note, not an error."""
    response = make_client().get("/requests?hours=24&open=req-unknownx")
    assert response.status_code == 200
    assert "No request with that ID" in response.text


def test_an_unknown_open_id_still_offers_close_with_the_filters() -> None:
    """A panel with no request still has the way back to the list it came from.

    Below 900 px the open panel is an overlay over the list, so a panel that
    cannot show its request must still carry the link that closes it.
    """
    response = make_client().get(
        "/requests?hours=24&route=%2Fv2%2Fpredict&status=5xx&open=req-unknownx"
    )

    assert response.status_code == 200
    assert "No request with that ID" in response.text
    assert 'class="request-panel is-open"' in response.text
    assert (
        'class="panel-close" '
        'href="/requests?hours=24&amp;route=%2Fv2%2Fpredict&amp;status=5xx"'
    ) in response.text


def test_a_malformed_open_id_is_rejected() -> None:
    """The open filter is validated like every other request id."""
    response = make_client().get("/requests?open=../errors")
    assert response.status_code == 422
    assert "detail" in response.json()
