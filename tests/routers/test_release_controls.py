"""Full/partial selection controls preserve URL state without mixing scopes."""

import re
from datetime import UTC, datetime
from html import unescape
from urllib.parse import parse_qs, urlsplit

import pytest

from app.domain.errors import SourceUnavailableError
from app.domain.models import EventQuery, TimeWindow
from app.domain.releases import ReleaseCatalogue
from tests.routers.pages_helpers import make_client


@pytest.mark.parametrize(
    "path",
    [
        "/",
        "/requests",
        "/errors",
        "/assistant",
        "/data",
        "/access",
        "/crashes",
        "/partials/overview",
        "/partials/requests",
        "/partials/errors",
        "/partials/assistant",
        "/partials/data",
        "/partials/access",
        "/partials/crashes",
    ],
)
def test_every_telemetry_page_keeps_unknown_selection(path: str) -> None:
    """Controls render in every full/partial view and retain absent choices."""
    response = make_client().get(path, params={"api_version": "unknown", "hours": 24})
    assert response.status_code == 200
    assert 'name="api_version"' in response.text
    assert 'value="unknown" selected' in response.text
    assert "Unknown API release" in response.text
    assert "start_ist" in response.text and "end_ist" in response.text


def test_selector_retains_missing_label_and_reports_discovery_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A discovery error cannot revert the selected URL to all or claim no rows."""
    client = make_client()

    def broken(window: object) -> ReleaseCatalogue:
        raise SourceUnavailableError("unavailable", "discovery is offline")

    monkeypatch.setattr(client.app.state.source, "release_catalogue", broken)
    response = client.get("/?api_version=2.9.0")
    assert response.status_code == 200
    assert 'value="2.9.0" selected' in response.text
    assert "Release discovery unavailable" in response.text
    assert "discovery is offline" in response.text


def test_native_selection_converts_ist_to_canonical_url_and_resets_cursor() -> None:
    """Native forms need neither browser timezone guesses nor inline JavaScript."""
    response = make_client().get(
        "/selection",
        params={
            "page": "/requests",
            "start_ist": "2026-10-01T00:00",
            "end_ist": "2026-10-02T00:00",
            "api_version": "2.6.0",
            "status": "5xx",
            "before_id": "request-12345678",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    query = parse_qs(urlsplit(unescape(response.headers["location"])).query)
    assert query["start"] == ["2026-09-30T18:30:00+00:00"]
    assert query["end"] == ["2026-10-01T18:30:00+00:00"]
    assert query["api_version"] == ["2.6.0"] and query["status"] == ["5xx"]
    assert "before_id" not in query


@pytest.mark.parametrize(
    "page",
    [
        "https://evil.example",
        "//evil.example",
        "/auth/google",
        "/invites",
        "/selection",
    ],
)
def test_selection_return_target_is_a_telemetry_page_only(page: str) -> None:
    """The native selection endpoint is not an open redirect or write target."""
    assert (
        make_client()
        .get("/selection", params={"page": page}, follow_redirects=False)
        .status_code
        == 422
    )


@pytest.mark.parametrize(
    "path", ["/", "/requests", "/errors", "/assistant", "/data", "/access", "/crashes"]
)
def test_historical_window_reaches_each_page_source(
    path: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Custom windows actually change reads rather than only the page subtitle."""
    client = make_client()
    source = client.app.state.source
    original = source.events
    calls: list[EventQuery] = []

    def record(query: EventQuery) -> object:
        calls.append(query)
        return original(query)

    monkeypatch.setattr(source, "events", record)
    response = client.get(
        path, params={"start": "2026-10-01T00:00:00Z", "end": "2026-10-02T00:00:00Z"}
    )
    assert response.status_code == 200
    assert "01 Oct 2026 05:30" in response.text
    if path != "/crashes":
        expected = TimeWindow(
            datetime(2026, 10, 1, tzinfo=UTC), datetime(2026, 10, 2, tzinfo=UTC)
        )
        assert any(query.window == expected for query in calls)


def test_navigation_refresh_filters_and_detail_urls_keep_scope() -> None:
    """Internal navigation and refresh never drop the selected exact release."""
    response = make_client().get("/?hours=6&api_version=2.6.0")
    targets = []
    for url in re.findall(r'(?:href|hx-get)="([^\"]+)"', response.text):
        url = unescape(url)
        if url.startswith(("/static", "/auth")) or not url.startswith("/"):
            continue
        targets.append(url)
        assert parse_qs(urlsplit(url).query).get("api_version") == ["2.6.0"]
    assert any(url.startswith("/requests?") for url in targets)
    assert any(url.startswith("/partials/overview?") for url in targets)


@pytest.mark.parametrize(
    "query",
    [
        "api_version=",
        "hours=24&hours=6",
        "start=broken&end=broken",
        "api_version=" + "x" * 65,
    ],
)
def test_invalid_scope_is_rejected_before_source_reads(
    query: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Validation cannot turn hostile/ambiguous scope into broad source reads."""
    client = make_client()

    def forbidden(*args: object) -> object:
        raise AssertionError("a bad scope must never read telemetry")

    monkeypatch.setattr(client.app.state.source, "events", forbidden)
    assert client.get("/?" + query).status_code == 422


def test_hostile_label_is_html_escaped_and_selected() -> None:
    """Recorded printable labels cannot inject markup into controls or headings."""
    label = '"><script>alert(1)</script>'
    response = make_client().get("/", params={"api_version": label})
    assert response.status_code == 200
    assert "<script>alert(1)</script>" not in response.text
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in response.text
