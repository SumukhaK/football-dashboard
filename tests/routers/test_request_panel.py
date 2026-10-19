"""Tests for the panel partial the requests list swaps in beside itself."""

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


def test_the_panel_partial_shows_the_summary_and_the_waterfall() -> None:
    """The known fixture chat opens a panel with its two retry markers."""
    request_id = chat_request_id()
    response = make_client().get(f"/partials/requests/{request_id}/panel")
    assert response.status_code == 200
    assert "<!DOCTYPE html>" not in response.text
    assert "Trace waterfall" in response.text
    assert response.text.count("wf-marker") >= 2
    assert "Open full timeline" in response.text
    assert f"/requests/{request_id}" in response.text


def test_the_panel_partial_returns_404_json_for_an_unknown_id() -> None:
    """An id with no lines is a 404, so the list can tell the two apart."""
    response = make_client().get("/partials/requests/req-unknownx/panel")
    assert response.status_code == 404
    assert "detail" in response.json()


def test_the_panel_partial_rejects_a_malformed_id() -> None:
    """An id that cannot be one is a 422 before the source is read."""
    response = make_client().get("/partials/requests/req-1/panel")
    assert response.status_code == 422


def test_the_panel_keeps_the_list_filters_in_its_close_link() -> None:
    """Close returns to the same filtered list the panel was opened from."""
    request_id = chat_request_id()
    response = make_client().get(
        f"/partials/requests/{request_id}/panel?hours=24&status=5xx"
    )
    assert response.status_code == 200
    assert 'class="panel-close" href="/requests?hours=24&amp;status=5xx"' in (
        response.text
    )


def test_the_panel_names_a_crash_and_links_to_the_full_timeline() -> None:
    """A request whose line crashed says so and offers the full timeline."""
    events = [
        make_line(
            6,
            "http.request",
            "req-aaaaaaaa",
            {"route": "/v2/predict", "status": 500},
        ),
        make_line(
            5,
            "app.crash",
            "req-aaaaaaaa",
            {"exception_type": "builtins.ZeroDivisionError"},
        ),
    ]
    response = make_list_client(events).get("/partials/requests/req-aaaaaaaa/panel")
    assert response.status_code == 200
    assert "app.crash" in response.text
    assert 'href="/requests/req-aaaaaaaa"' in response.text


def test_the_panel_shows_the_relative_age_of_the_request() -> None:
    """The panel reads its time the same way the list rows do."""
    events = [
        make_line(
            9 * 60,
            "http.request",
            "req-aaaaaaaa",
            {"route": "/v2/predict", "status": 200},
        ),
    ]
    response = make_list_client(events).get("/partials/requests/req-aaaaaaaa/panel")
    assert "9 h ago" in response.text


def test_a_broken_source_is_a_banner_not_a_500() -> None:
    """A source read that fails shows its banner inside the panel."""
    app = create_app(Config(), clock=lambda: CLOCK_TIME)
    broken = RequestsService(BrokenSource(), lambda: CLOCK_TIME, Config())
    app.dependency_overrides[get_requests] = lambda: broken

    response = TestClient(app).get("/partials/requests/req-aaaaaaaa/panel")
    assert response.status_code == 200
    assert "google is down" in response.text


def test_a_broken_source_still_offers_close_to_the_filtered_list() -> None:
    """A panel whose read failed still has the way back to the list it came from.

    Below 900 px the open panel covers the list, so a panel that could not read
    its request must still carry the link that closes it.
    """
    app = create_app(Config(), clock=lambda: CLOCK_TIME)
    broken = RequestsService(BrokenSource(), lambda: CLOCK_TIME, Config())
    app.dependency_overrides[get_requests] = lambda: broken

    response = TestClient(app).get(
        "/partials/requests/req-aaaaaaaa/panel"
        "?hours=24&event=component.degraded&component=logging"
    )

    assert response.status_code == 200
    assert "google is down" in response.text
    assert 'class="request-panel is-open"' in response.text
    assert (
        'class="panel-close" '
        'href="/requests?hours=24&amp;event=component.degraded&amp;component=logging"'
    ) in response.text
