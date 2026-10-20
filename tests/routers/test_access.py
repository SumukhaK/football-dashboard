"""Tests for the access routes."""

from __future__ import annotations

import re
from datetime import timedelta

from fastapi.testclient import TestClient

from app.config import Config
from app.dependencies import get_access
from app.services.access import AccessService
from tests.auth.console import console
from tests.routers.pages_helpers import CLOCK_TIME, BrokenSource, make_client
from tests.services.access_helpers import auth_line
from tests.services.data_jobs_helpers import ListSource


def test_access_page_shows_the_lockout_run_and_the_429_burst() -> None:
    """GET /access tells the fixture story: the run, the lockout, one abuser."""
    response = make_client().get("/access")
    assert response.status_code == 200
    body = response.text
    assert "locked_out" in body
    assert "d23f0824128b2f33" in body
    assert "9e4c5aabbde6c9d3" in body
    assert "/v2/predict" in body
    assert "Rejected with 429 in this window: 30." in body
    assert "invalid_invite" in body
    assert "consent_required" in body


def test_access_page_offers_the_window_picker_with_one_day_active() -> None:
    """The picker swaps the access body, pushes a URL, and starts on the day."""
    body = make_client().get("/access").text
    assert 'aria-label="Time window"' in body
    assert 'hx-target="#access-body"' in body
    assert 'hx-push-url="/access?hours=' in body
    active = re.search(
        r'class="window-option is-active".*?hx-get="(?P<path>[^"]+)"', body, re.DOTALL
    )
    assert active is not None
    assert active.group("path") == "/partials/access?hours=24"


def test_access_page_renders_the_chart_data_for_both_figures() -> None:
    """Both charts get a JSON block the charts script reads after a swap."""
    body = make_client().get("/access").text
    assert 'id="failed-signins-chart"' in body
    assert 'id="rate-limit-chart"' in body
    assert 'id="access-chart-data"' in body
    assert '"failed_sign_ins"' in body
    assert '"rate_limit"' in body


def test_the_guardrail_section_is_absent_with_the_fixtures() -> None:
    """The fixture has no guardrail event, so the section is not rendered."""
    assert 'aria-label="Guardrails"' not in make_client().get("/access").text


def test_a_short_window_says_the_day_had_nothing() -> None:
    """A one-hour window empties the sections with a sentence, not a crash."""
    body = make_client().get("/access?hours=1").text
    assert "No lockout or block in this window." in body
    assert "No rejected request in this window." in body


def test_partial_returns_body_only() -> None:
    """The HTMX partial renders the access body, not a whole document."""
    response = make_client().get("/partials/access?hours=24")
    assert response.status_code == 200
    assert "<!DOCTYPE html>" not in response.text
    assert 'id="access-body"' in response.text
    assert "Sign-ins" in response.text


def test_unsupported_hours_returns_structured_422() -> None:
    """A window the picker does not offer is a 422 with error and detail."""
    response = make_client().get("/partials/access?hours=5")
    assert response.status_code == 422
    assert "error" in response.json()


def test_a_strike_ban_appears_in_lockouts_and_blocks() -> None:
    """An account banned by a strike shows its action, outcome and reference."""
    signed = console(clock=lambda: CLOCK_TIME)
    app = signed.app
    strike = auth_line(
        CLOCK_TIME - timedelta(minutes=1),
        action="strike",
        outcome="blocked",
        user_ref="synthetic-user-ref",
    )
    service = AccessService(ListSource([strike]), lambda: CLOCK_TIME, Config())
    app.dependency_overrides[get_access] = lambda: service
    client = signed.client

    for path in ("/access", "/partials/access"):
        body = client.get(path).text
        assert 'aria-label="Lockouts and blocks"' in body
        assert "<td>strike</td>" in body
        assert "<td>blocked</td>" in body
        assert '<td class="mono">synthetic-user-ref</td>' in body
        assert "23:29 IST" in body
        assert "No lockout or block in this window." not in body

    full = client.get("/access").text
    assert full.count('class="page-header"') == 1
    assert '<h1 class="page-title">Access</h1>' in full
    assert '<p class="page-subtitle">Last 24 hours</p>' in full


def test_source_error_renders_a_banner_with_status_200() -> None:
    """A failing source shows a banner and 200, never a 500."""
    signed = console(clock=lambda: CLOCK_TIME)
    broken = AccessService(BrokenSource(), lambda: CLOCK_TIME, Config())
    signed.app.dependency_overrides[get_access] = lambda: broken

    response: TestClient = signed.client.get("/access")
    assert response.status_code == 200
    assert "google is down" in response.text
    assert '<h1 class="page-title">Access</h1>' in response.text


def test_the_page_header_appears_once_and_names_the_window() -> None:
    """The full page carries the shared header and the picked window, once."""
    body = make_client().get("/access").text
    assert body.count('class="page-header"') == 1
    assert '<h1 class="page-title">Access</h1>' in body
    assert '<p class="page-subtitle">Last 24 hours</p>' in body
    assert body.count("<main") == 1


def test_a_second_window_changes_the_subtitle() -> None:
    """A supported window updates the subtitle and not only the tables."""
    body = make_client().get("/access?hours=168").text
    assert '<p class="page-subtitle">Last 7 days</p>' in body


def test_the_partial_swaps_the_header_with_the_body() -> None:
    """HTMX replaces the body, so the header travels in it and the shell does not."""
    body = make_client().get("/partials/access?hours=1").text
    assert body.count('class="page-header"') == 1
    assert '<h1 class="page-title">Access</h1>' in body
    assert '<p class="page-subtitle">Last hour</p>' in body
    assert "<main" not in body
