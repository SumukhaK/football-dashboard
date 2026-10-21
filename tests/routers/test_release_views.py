"""Release predicates must reach every backend read without shared state."""

from collections.abc import Callable
from dataclasses import replace
from typing import cast

import pytest
from fastapi import FastAPI

from app.domain.models import EventQuery, TelemetryEvent
from app.domain.releases import ReleaseSelection
from tests.routers.pages_helpers import make_client
from tests.services.requests_helpers import FakeSource, request_line


@pytest.mark.parametrize(
    "path",
    [
        "/",
        "/requests",
        "/errors",
        "/assistant",
        "/data",
        "/access",
        "/partials/overview",
        "/partials/requests",
        "/partials/errors",
        "/partials/assistant",
        "/partials/data",
        "/partials/access",
    ],
)
@pytest.mark.parametrize("version", ["2.6.0", "unknown"])
def test_all_backend_queries_inherit_selection(
    path: str, version: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Comparisons and lookbacks carry the same selection before cache and limit."""
    client = make_client()
    app = cast(FastAPI, client.app)
    source = app.state.source
    original = cast(Callable[[EventQuery], list[TelemetryEvent]], source.events)
    reads: list[EventQuery] = []

    def record(query: EventQuery) -> list[TelemetryEvent]:
        reads.append(query)
        return original(query)

    monkeypatch.setattr(source, "events", record)
    response = client.get(path, params={"api_version": version, "hours": 24})
    assert response.status_code == 200
    assert reads
    scoped = [q for q in reads if not ("errors" in path and not q.events)]
    assert scoped
    assert all(q.release == ReleaseSelection.from_query(version) for q in scoped)
    if "errors" in path:
        assert all(q.release.kind == "all" for q in reads if not q.events)
    assert "currently combine all API releases" not in response.text


def test_detail_rejects_mismatched_release_before_trace() -> None:
    """A shared ID link cannot expose another selection's trace or timeline."""
    from app.config import Config
    from app.services.request_detail import request_detail
    from tests.services.requests_helpers import NOW

    source = FakeSource(
        [replace(request_line(1), api_version="2.5.1", trace_id="wrong")]
    )
    with pytest.raises(ValueError, match="not in the selected release"):
        request_detail(
            source,
            lambda: NOW,
            Config(),
            "req-00000001",
            release=ReleaseSelection("exact", "2.6.0"),
        )


def test_logs_tab_includes_non_request_events() -> None:
    """Requests has an independently filtered log view rather than request rows only."""
    response = make_client().get("/requests?tab=logs&severity=WARNING")
    assert response.status_code == 200
    assert "Log events" in response.text
    assert 'name="severity"' in response.text


@pytest.mark.parametrize(
    "path", ["/requests/req-00000001", "/partials/requests/req-00000001/panel"]
)
def test_mismatched_detail_has_return_control(path: str) -> None:
    """A failed selection is visible to HTMX and can be closed on mobile."""

    client = make_client()
    app = cast(FastAPI, client.app)
    source = FakeSource([replace(request_line(1), api_version="2.5.1")])
    app.state.source = source
    response = client.get(
        path, params={"api_version": "2.6.0"}, headers={"HX-Request": "true"}
    )
    assert response.status_code == 200
    assert "not in the selected release" in response.text
    assert "Close" in response.text or "Return to requests" in response.text
    assert "Trace waterfall" not in response.text


@pytest.mark.parametrize(
    "query",
    [
        "severity=bad",
        "log_page=-1",
        "log_page=50",
        "log_page=no",
        "event=bad",
        "event=retry&event=fallback",
    ],
)
def test_invalid_log_filters_are_rejected(query: str) -> None:
    """Bad filters cannot silently widen a retained log query."""
    assert make_client().get("/requests?tab=logs&" + query).status_code == 422


def test_logs_keep_native_selection_target_and_reset_pagination() -> None:
    """Time/release controls stay valid on a later Logs page."""
    response = make_client().get("/requests?tab=logs&hours=24&log_page=1")
    assert 'name="page" value="/requests"' in response.text
    assert "?tab=logs?" not in response.text
    import re

    assert not any(
        "log_page" in link for link in re.findall('hx-get="([^"]+)"', response.text)
    )


def test_logs_disclose_the_configured_cost_conversion() -> None:
    """Converted log costs carry the rate/date and estimate disclosure too."""
    from datetime import date

    from tests.services.requests_helpers import event_line

    client = make_client()
    app = cast(FastAPI, client.app)
    app.state.config = app.state.config.model_copy(
        update={"inr_per_usd": 80.0, "inr_per_usd_as_of": date(2026, 10, 20)}
    )
    app.state.source = FakeSource(
        [event_line(1, "assistant.answer", None, {"cost_usd": 0.25})]
    )
    response = client.get("/requests?tab=logs")
    assert "INR 20.00" in response.text
    assert "as of 20 Oct 2026" in response.text
    assert "not a cloud billing invoice" in response.text
