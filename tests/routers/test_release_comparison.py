"""Full/partial comparison controls preserve exact release/time context."""

import pytest

from tests.routers.pages_helpers import make_client


@pytest.mark.parametrize("path", ["/", "/partials/overview"])
def test_comparison_only_in_combined_mode(path: str) -> None:
    """Combined mode exposes a table, exact mode keeps its selected charts."""
    client = make_client()
    response = client.get(path)
    assert response.status_code == 200
    assert "By API release" in response.text
    assert "All API releases (combined)" in response.text
    assert "Unknown API release" in response.text
    assert 'aria-label="Sort by requests"' in response.text
    assert (
        "By API release" not in client.get(path, params={"api_version": "2.6.0"}).text
    )


@pytest.mark.parametrize(
    "query",
    ["release_sort=bad", "release_order=bad", "release_sort=requests&release_sort=p95"],
)
def test_invalid_comparison_sort_rejected(query: str) -> None:
    """Unsupported or duplicate sort options cannot trigger telemetry reads."""
    assert make_client().get("/?" + query).status_code == 422


def test_sort_and_drill_down_keep_custom_window_and_unknown_identity() -> None:
    """New sort state survives full/partial requests; links select the row rather than all."""
    import re
    from html import unescape
    from urllib.parse import parse_qs, urlsplit

    client = make_client()
    params = {
        "start": "2026-10-07T00:00:00Z",
        "end": "2026-10-08T00:00:00Z",
        "release_sort": "p95",
        "release_order": "asc",
    }
    body = client.get("/", params=params).text
    sort_match = re.search(
        'href="([^"]+)"[^>]*hx-get="[^"]+"[^>]*hx-target="#overview-body"[^>]*hx-swap="outerHTML"[^>]*hx-indicator="#main-content"[^>]*hx-push-url="[^"]+" aria-label="Sort by p95 latency"',
        body,
    )
    assert sort_match is not None
    href = unescape(sort_match.group(1))
    query = parse_qs(urlsplit(href).query)
    assert query["release_order"] == ["desc"] and query["release_sort"] == ["p95"]
    assert query["start"] == ["2026-10-07T00:00:00+00:00"]
    unknown_match = re.search(
        'class="release-label" href="([^"]+)">Unknown API release', body
    )
    assert unknown_match is not None
    unknown = unescape(unknown_match.group(1))
    assert parse_qs(urlsplit(unknown).query)["api_version"] == ["unknown"]
    assert "By API release" not in client.get(unknown).text
    assert 'aria-sort="ascending"' in body
    partial = client.get("/partials/overview", params=params).text
    assert "<!DOCTYPE" not in partial and 'aria-sort="ascending"' in partial


def test_catalogue_is_reused_and_hostile_labels_are_escaped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Even TTL-zero pages discover once and never interpret a release as HTML."""
    from typing import cast

    from fastapi import FastAPI

    from app.domain.models import TimeWindow
    from app.domain.releases import ReleaseCatalogue

    client = make_client()
    app = cast(FastAPI, client.app)
    calls = []

    def catalogue(window: TimeWindow) -> ReleaseCatalogue:
        calls.append(window)
        return ReleaseCatalogue(("<script>alert(1)</script>",), True, False)

    monkeypatch.setattr(app.state.source, "release_catalogue", catalogue)
    body = client.get("/").text
    assert len(calls) == 1
    assert "<script>alert(1)</script>" not in body
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in body
    assert "No observations in compared samples" in body


def test_assistant_read_failure_is_unavailable_not_an_empty_comparison(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed additional sample never fabricates a quiet release or zero provider cost."""
    from typing import cast

    from fastapi import FastAPI

    from app.domain.errors import SourceUnavailableError
    from app.domain.models import EventQuery, TelemetryEvent

    client = make_client()
    app = cast(FastAPI, client.app)
    source = app.state.source
    from collections.abc import Callable

    original = cast(Callable[[EventQuery], list[TelemetryEvent]], source.events)

    def read(query: EventQuery) -> list[TelemetryEvent]:
        if "assistant.answer" in query.events:
            raise SourceUnavailableError("unavailable", "assistant sample offline")
        return original(query)

    monkeypatch.setattr(source, "events", read)
    response = client.get("/")
    assert response.status_code == 200 and "assistant sample offline" in response.text
    assert "All API releases (combined)" not in response.text
