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
from app.main import create_app
from app.services.crashes import CrashesService

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
    """A client over the fixture sources with a fixed clock."""
    return TestClient(create_app(settings or Config(), clock=lambda: NOW))


def _stubbed(source: StubCrashSource) -> TestClient:
    """A client whose crashes service reads the stub source."""
    app = create_app(Config(), clock=lambda: NOW)
    service = CrashesService(source, lambda: NOW)
    app.dependency_overrides[get_crashes] = lambda: service
    return TestClient(app)


def test_list_page_shows_totals_and_issues_from_the_fixture() -> None:
    """GET /crashes lists the sample issues with the nav link and picker."""
    body = _client().get("/crashes").text
    assert 'href="/crashes"' in body
    assert "java.lang.IllegalStateException" in body
    assert "Prediction is not loaded" in body
    assert "NON_FATAL" in body and "ANR" in body
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
    app = create_app(settings, clock=lambda: NOW)
    service = CrashesService(StubCrashSource(), lambda: NOW)
    app.dependency_overrides[get_crashes] = lambda: service
    client = TestClient(app)
    assert client.get("/crashes").status_code == 200
    assert 'href="/crashes"' in client.get("/crashes").text
