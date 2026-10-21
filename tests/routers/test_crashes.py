"""Tests for the crashes routes."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from fastapi.testclient import TestClient

from app.config import REPO_ROOT, Config
from app.dependencies import get_crashes
from app.domain.crashes import CrashEvent
from app.domain.errors import SourceUnavailableError
from app.domain.models import TimeWindow
from app.services.crashes import CrashesService
from tests.auth.console import console, console_client

NOW = datetime(2026, 10, 16, 12, 0, tzinfo=UTC)
FATAL_ISSUE = "4f1c2a9be0d34c5e"


class StubCrashSource:
    """Returns no events, or fails every read."""

    def __init__(self, fail: bool = False) -> None:
        self.fail = fail

    def crash_events(self, window: TimeWindow, limit: int) -> list[CrashEvent]:
        """No events, or a refused read."""
        if self.fail:
            raise SourceUnavailableError("permission_denied", "BigQuery: denied")
        return []

    def issue_events(
        self, issue_id: str, window: TimeWindow, limit: int
    ) -> list[CrashEvent]:
        """Same as crash_events."""
        return self.crash_events(window, limit)


def _client(settings: Config | None = None) -> TestClient:
    """A signed-in client over the fixture sources with a fixed clock."""
    return console_client(settings, clock=lambda: NOW)


def _stubbed(source: StubCrashSource) -> TestClient:
    """A signed-in client whose crashes service reads the stub source."""
    signed = console(clock=lambda: NOW)
    service = CrashesService(source, lambda: NOW)
    signed.app.dependency_overrides[get_crashes] = lambda: service
    return signed.client


def test_list_page_shows_totals_and_issues_from_the_fixture() -> None:
    """GET /crashes lists the sample crashes as type chips and issue rows."""
    body = _client().get("/crashes").text
    assert 'href="/crashes"' in body
    assert "IllegalStateException" in body
    assert "Prediction is not loaded" in body
    assert "Fatal" in body and "Non-fatal" in body and "Not responding" in body
    assert f'href="/crashes/{FATAL_ISSUE}?hours=168"' in body
    assert 'hx-get="/partials/crashes?hours=24"' in body


def test_installation_ids_are_never_rendered() -> None:
    """Only install counts reach the page, never an installation_uuid."""
    rows = json.loads((REPO_ROOT / "fixtures/crashlytics_events.json").read_text())
    client = _client()
    pages = client.get("/crashes").text + client.get(f"/crashes/{FATAL_ISSUE}").text
    assert not any(row["installation_uuid"] in pages for row in rows)


def test_partial_renders_only_the_body() -> None:
    """The HTMX partial has no page chrome."""
    response = _client().get("/partials/crashes?hours=24")
    assert response.status_code == 200
    assert response.text.startswith('<div id="crashes-body">')


def test_detail_page_shows_events_and_frames() -> None:
    """GET /crashes/{issue_id} shows the latest stack and recent events."""
    body = _client().get(f"/crashes/{FATAL_ISSUE}").text
    assert "Blamed frame" in body
    assert "MatchViewModel.showPrediction (MatchViewModel.kt:40)" in body
    assert "Recent events" in body and "2.4.1" in body


def test_unknown_issue_is_404() -> None:
    """An issue with no events in the window is not found."""
    response = _client().get("/crashes/does-not-exist")
    assert response.status_code == 404
    assert response.json()["error"] == "http_error"


def test_type_chips_count_the_window_and_carry_the_filter() -> None:
    """Each chip shows its own window count and links to the list it filters."""
    body = _client().get("/crashes?hours=168&type=FATAL").text
    assert '<span class="type-chip-label">Non-fatal</span>' in body
    assert '<span class="type-chip-count">5</span>' in body
    assert '<span class="type-chip-label">Not responding</span>' in body
    assert '<span class="type-chip-count">1</span>' in body
    assert 'href="/crashes?hours=168&amp;type=NON_FATAL"' in body
    assert 'class="type-chip is-active"' in body


def test_the_type_filter_narrows_the_issue_rows() -> None:
    """Filtering by ANR leaves only the not-responding issue."""
    body = _client().get("/crashes?hours=168&type=ANR").text
    assert "AppNotResponding" in body
    assert "IllegalStateException" not in body


def test_an_unknown_type_is_422() -> None:
    """Only the types the page offers a chip for are accepted."""
    assert _client().get("/crashes?type=OTHER").status_code == 422


def test_the_window_picker_keeps_the_type_filter() -> None:
    """Changing the window keeps the crash type the reader chose."""
    body = _client().get("/crashes?hours=168&type=ANR").text
    assert 'hx-get="/partials/crashes?hours=24&amp;type=ANR"' in body
    assert 'hx-push-url="/crashes?hours=24&amp;type=ANR"' in body


def test_an_open_issue_renders_the_panel_on_a_full_page_load() -> None:
    """A shared list URL with ?open= comes back with the panel already open."""
    body = _client().get(f"/crashes?hours=168&open={FATAL_ISSUE}").text
    assert 'class="crash-panel is-open"' in body
    assert "first app frame" in body
    assert f'href="/crashes/{FATAL_ISSUE}?hours=168"' in body


def test_the_open_panel_keeps_the_list_filters_in_its_close_link() -> None:
    """The panel's Close returns to the list, type filter and window intact."""
    body = _client().get(f"/crashes?hours=168&type=FATAL&open={FATAL_ISSUE}").text
    assert 'class="crash-panel-close" href="/crashes?hours=168&amp;type=FATAL"' in body


def test_an_unknown_open_issue_still_offers_close() -> None:
    """A panel with no crash for that id still leads back to the list.

    Below 900 px the open panel covers the list, so a panel that cannot show its
    issue must still carry the link that closes it.
    """
    body = _client().get("/crashes?hours=168&open=does-not-exist").text
    assert "No crash with that ID in this window." in body
    assert 'class="crash-panel is-open"' in body
    assert 'class="crash-panel-close" href="/crashes?hours=168"' in body


def test_the_panel_partial_shows_the_stack_and_links_to_the_page() -> None:
    """The panel partial has no page chrome and links to the full page."""
    response = _client().get(f"/partials/crashes/{FATAL_ISSUE}/panel?hours=168")
    assert response.status_code == 200
    assert "<!DOCTYPE html>" not in response.text
    assert "first app frame" in response.text
    assert f'href="/crashes/{FATAL_ISSUE}?hours=168"' in response.text


def test_the_panel_partial_of_an_unknown_issue_is_404() -> None:
    """A row always names a real issue, so an unknown one is an error."""
    response = _client().get("/partials/crashes/does-not-exist/panel")
    assert response.status_code == 404
    assert response.json()["error"] == "http_error"


def test_a_failed_read_still_offers_close_in_the_panel() -> None:
    """A panel whose read failed keeps the way back to the filtered list."""
    response = _stubbed(StubCrashSource(fail=True)).get(
        f"/partials/crashes/{FATAL_ISSUE}/panel?hours=24&type=FATAL"
    )
    assert response.status_code == 200
    assert "permission_denied" in response.text
    assert 'class="crash-panel is-open"' in response.text
    assert (
        'class="crash-panel-close" href="/crashes?hours=24&amp;type=FATAL"'
        in response.text
    )


def test_unsupported_window_is_422() -> None:
    """Only the picker's windows are accepted."""
    assert _client().get("/crashes?hours=5").status_code == 422


def test_no_rows_shows_the_empty_state() -> None:
    """No exported rows reads as an honest empty state, not an error."""
    body = _stubbed(StubCrashSource()).get("/crashes").text
    assert "No crash data exported yet" in body
    assert "banner-error" not in body


def test_source_failure_shows_a_banner() -> None:
    """A refused read becomes the shared banner on both pages, never a 500."""
    client = _stubbed(StubCrashSource(fail=True))
    for path in ("/crashes", f"/crashes/{FATAL_ISSUE}"):
        response = client.get(path)
        assert response.status_code == 200
        assert "Crash data is unavailable (permission_denied)" in response.text


def test_gcp_without_firebase_project_has_no_crashes_page() -> None:
    """source=gcp with no crashlytics_project_id: no routes, no nav link."""
    client = _client(Config(source="gcp", gcp_project_id="demo-project"))
    for path in ("/crashes", "/partials/crashes", f"/crashes/{FATAL_ISSUE}"):
        assert client.get(path).status_code == 404
    assert 'href="/crashes"' not in client.get("/").text


def test_gcp_with_firebase_project_mounts_without_calling_google() -> None:
    """Configuring the Firebase project mounts the page; nothing is queried yet."""
    settings = Config(
        source="gcp",
        gcp_project_id="demo-project",
        crashlytics_project_id="football-intelligent-platform",
    )
    signed = console(settings, clock=lambda: NOW)
    service = CrashesService(StubCrashSource(), lambda: NOW)
    signed.app.dependency_overrides[get_crashes] = lambda: service
    client = signed.client
    assert client.get("/crashes").status_code == 200
    assert 'href="/crashes"' in client.get("/crashes").text
