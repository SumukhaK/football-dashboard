"""Tests for the request detail route: its waterfall, its 404 and its banners."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.config import Config
from app.contract import load_contract
from app.dependencies import get_requests
from app.main import create_app
from app.services.requests import RequestsService

from .requests_helpers import (
    CLOCK_TIME,
    BrokenSource,
    BrokenTraceSource,
    chat_request_id,
    make_client,
)


def test_detail_shows_the_waterfall_with_the_retries() -> None:
    """The chat's detail names its route and draws the two retry markers."""
    body = make_client().get(f"/requests/{chat_request_id()}").text
    assert "/v2/assistant/chat" in body
    assert "Trace waterfall" in body
    assert body.count("wf-marker") >= 2
    assert "retry" in body


def test_unknown_request_returns_structured_404() -> None:
    """An id with no lines is a 404 with error and detail."""
    response = make_client().get("/requests/req-unknown001")
    assert response.status_code == 404
    assert "error" in response.json()


def test_invalid_request_id_returns_structured_422() -> None:
    """An id that is not the right shape is a 422 before any read."""
    response = make_client().get("/requests/tiny")
    assert response.status_code == 422
    assert "detail" in response.json()


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
    request_id = chat_request_id()
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
