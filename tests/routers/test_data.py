"""Tests for the data and jobs routes."""

from __future__ import annotations

import re

from fastapi.testclient import TestClient

from app.config import Config
from app.dependencies import get_data
from app.main import create_app
from app.services.data_jobs import DataJobsService
from tests.routers.pages_helpers import CLOCK_TIME, BrokenSource, make_client


def test_data_page_shows_the_fixture_refresh_freshness_and_downloads() -> None:
    """GET /data tells the whole fixture story: both runs, the fallback, downloads."""
    response = make_client().get("/data")
    assert response.status_code == 200
    body = response.text
    assert "football-data.co.uk answered 503 twice" in body
    assert "fresh_match_data" in body
    assert "previous_match_data" in body
    assert "football_data_2026-10-08.csv" in body
    assert "Premier League" in body
    assert "http_error" in body
    assert "football_data" in body
    assert "openfootball" in body


def test_data_page_offers_the_window_picker_with_seven_days_active() -> None:
    """The picker swaps the data body, pushes a URL, and starts on the week."""
    body = make_client().get("/data").text
    assert 'aria-label="Time window"' in body
    assert 'hx-target="#data-body"' in body
    assert 'hx-push-url="/data?hours=' in body
    active = re.search(
        r'class="window-option is-active".*?hx-get="(?P<path>[^"]+)"', body, re.DOTALL
    )
    assert active is not None
    assert active.group("path") == "/partials/data?hours=168"


def test_a_short_window_keeps_the_freshness_from_the_lookback() -> None:
    """The refresh table empties, the freshness table does not, and both say so."""
    body = make_client().get("/data?hours=1").text
    assert "No refresh run in this window." in body
    assert "Premier League" in body
    assert "No freshness reading in the last 168 hours." not in body


def test_partial_returns_body_only() -> None:
    """The HTMX partial renders the data body, not a whole document."""
    response = make_client().get("/partials/data?hours=24")
    assert response.status_code == 200
    assert "<!DOCTYPE html>" not in response.text
    assert 'id="data-body"' in response.text
    assert "Refresh runs" in response.text


def test_unsupported_hours_returns_structured_422() -> None:
    """A window the picker does not offer is a 422 with error and detail."""
    response = make_client().get("/partials/data?hours=5")
    assert response.status_code == 422
    assert "error" in response.json()


def test_source_error_renders_a_banner_with_status_200() -> None:
    """A failing source shows a banner and 200, never a 500."""
    app = create_app(Config(), clock=lambda: CLOCK_TIME)
    broken = DataJobsService(BrokenSource(), lambda: CLOCK_TIME, Config())
    app.dependency_overrides[get_data] = lambda: broken

    response: TestClient = TestClient(app).get("/data")
    assert response.status_code == 200
    assert "google is down" in response.text
