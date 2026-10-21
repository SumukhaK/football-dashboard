"""Real file sources, pooled service metrics and native/partial historical pages."""

import re
from html import unescape
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from app.domain.models import EventQuery
from app.domain.releases import ReleaseSelection
from app.services.overview import OverviewService
from app.sources.cached import CachedSource
from app.sources.scoped import ReleaseSource
from tests.history.helpers import (
    NOW,
    PARAMS,
    WINDOW,
    comparison_rows,
    request_links,
    retained_source,
    settings,
    signed_history,
)


@pytest.mark.parametrize("kind", ["fixture", "local"])
@pytest.mark.parametrize(
    "version,count",
    [
        (None, 5),
        ("2.5.0", 1),
        ("2.5.1", 1),
        ("2.6.0", 2),
        ("unknown", 1),
        ("missing", 0),
    ],
)
def test_source_service_full_partial_and_cache_agree(
    kind: str, version: str | None, count: int, tmp_path: Path
) -> None:
    """Actual retained rows remain consistent across source, service and URL navigation."""
    source = CachedSource(
        retained_source(kind, tmp_path / "api.jsonl"), 60, lambda: NOW
    )
    selection = ReleaseSelection.from_query(version)
    query = EventQuery(WINDOW, events=("http.request",), release=selection)
    rows = source.events(query)
    assert len(rows) == count
    model = OverviewService(
        ReleaseSource(source, selection), lambda: NOW, settings(), ()
    ).build(WINDOW)
    assert (
        next(item.value for item in model.headlines if item.key == "requests") == count
    )
    signed = signed_history(source)
    params = {**PARAMS, **({"api_version": version} if version else {})}
    for path in ("/requests", "/partials/requests"):
        response = signed.client.get(path, params=params)
        assert response.status_code == 200
        assert request_links(response.text) == {row.request_id for row in rows}
        assert response.headers["cache-control"] == "no-store"
    assert source.events(query) == rows
    if version == "missing":
        assert 'value="missing" selected' in response.text
        assert (
            "No data for this release and period in retained telemetry" in response.text
        )


@pytest.mark.parametrize("kind", ["fixture", "local"])
def test_real_contract_tokens_costs_and_pooled_metrics_reach_table(
    kind: str, tmp_path: Path
) -> None:
    """Contract field names must work without test-only normalization."""
    signed = signed_history(retained_source(kind, tmp_path / "api.jsonl"))
    for path in ("/", "/partials/overview"):
        response = signed.client.get(path, params=PARAMS)
        assert response.status_code == 200
        rows = comparison_rows(response.text)
        combined = rows[-1]
        assert combined[0] == "All API releases (combined)"
        assert combined[1:8] == ["5", "1", "20.0%", "30 ms", "1000 ms", "5/5", "1"]
        assert combined[8:12] == ["2", "10 (1/2)", "5 (1/2)", "INR 20.00 (1/2)"]
        assert sum(int(row[1]) for row in rows[:-1]) == int(combined[1])
        assert rows[-2][0] == "Unknown API release"
        assert "01 Oct 23:59 IST" in combined[-1]
        assert "03 Oct 00:02 IST" in combined[-1]
        assert "1 USD = INR 80" in response.text


def test_old_retained_data_and_catalogue_do_not_bleed_between_cached_windows(
    tmp_path: Path,
) -> None:
    """Historical availability follows retained samples, never the release tag or quick view."""
    from datetime import UTC, datetime, timedelta

    source = CachedSource(
        retained_source("fixture", tmp_path / "unused"), 60, lambda: NOW
    )
    old = type(WINDOW)(
        datetime(2026, 9, 1, tzinfo=UTC), datetime(2026, 9, 2, tzinfo=UTC)
    )
    quick = type(WINDOW)(NOW - timedelta(days=7), NOW)
    for _ in range(2):
        assert len(source.events(EventQuery(old, events=("http.request",)))) == 1
        assert source.events(EventQuery(quick, events=("http.request",))) == []
        assert source.release_catalogue(old).versions == ("2.5.0",)
        assert source.release_catalogue(quick).versions == ()
        assert source.release_catalogue(WINDOW).has_unknown
    signed = signed_history(source)
    params = {
        "start": old.start.isoformat(),
        "end": old.end.isoformat(),
        "api_version": "2.5.0",
    }
    assert request_links(signed.client.get("/requests", params=params).text) == {
        "g7-sep-0001"
    }
    assert request_links(signed.client.get("/requests?hours=168").text) == set()


def test_ist_midnight_logs_native_selection_and_detail_return_scope(
    tmp_path: Path,
) -> None:
    """Native links and panels keep exact UTC bounds while labels cross IST midnight."""
    signed = signed_history(retained_source("fixture", tmp_path / "unused"))
    logs = signed.client.get("/requests", params={**PARAMS, "tab": "logs"}).text
    assert "01 Oct 23:59 IST" in logs and "02 Oct 00:01 IST" in logs
    assert "Reported assistant measurement" in logs
    redirect = signed.client.get(
        "/selection",
        params={
            "page": "/requests",
            "start_ist": "2026-10-01T23:58",
            "end_ist": "2026-10-03T00:05",
            "api_version": "2.6.0",
        },
        follow_redirects=False,
    )
    assert redirect.status_code == 303
    assert parse_qs(urlsplit(redirect.headers["location"]).query) == {
        **{k: [v] for k, v in PARAMS.items()},
        "api_version": ["2.6.0"],
    }
    for path, label in (
        ("/requests/g7-260-0002", "Return to requests"),
        ("/partials/requests/g7-260-0002/panel", "Close"),
    ):
        response = signed.client.get(path, params={**PARAMS, "api_version": "2.6.0"})
        assert response.status_code == 200
        if "partials" not in path:
            assert "revision-260-b" in response.text
        match = re.search(r'href="([^"]+)">' + label, r" ".join(response.text.split()))
        assert match is not None
        query = parse_qs(urlsplit(unescape(match[1])).query)
        assert all(
            query[k] == [v] for k, v in {**PARAMS, "api_version": "2.6.0"}.items()
        )


def test_multiple_revisions_map_to_same_release_and_unmapped_stays_visible(
    tmp_path: Path,
) -> None:
    """Mapping uses real in-window release evidence, not revision-name guesses."""
    from app.sources.attribution import attributed_platform_events

    source = retained_source("fixture", tmp_path / "unused")
    rows = attributed_platform_events(
        source, WINDOW, ReleaseSelection.from_query("2.6.0")
    )
    assert {row.revision for row in rows if row.api_version == "2.6.0"} == {
        "revision-260-a",
        "revision-260-b",
    }
    assert any(row.api_version is None and row.attribution_note for row in rows)


@pytest.mark.parametrize(
    "path,label,status",
    [
        ("/crashes/abcd1234deadbeef", "Back to crashes", 200),
        ("/partials/crashes/abcd1234deadbeef/panel", "Close", 200),
        ("/crashes/absent-issue", "Back to crashes", 404),
        ("/partials/crashes/absent-issue/panel", "Close", 200),
    ],
)
def test_android_detail_return_keeps_independent_version_and_history(
    path: str, label: str, status: int, tmp_path: Path
) -> None:
    """API choice cannot hide Android records; all full/panel return paths retain both scopes."""
    signed = signed_history(retained_source("fixture", tmp_path / "unused"))
    params = {**PARAMS, "api_version": "2.5.0", "android_version": "2.6.2"}
    response = signed.client.get(path, params=params, headers={"HX-Request": "true"})
    assert response.status_code == status
    match = re.search(r'href="([^"]+)">' + label, response.text)
    assert match is not None
    query = parse_qs(urlsplit(unescape(match[1])).query)
    assert all(query[k] == [v] for k, v in params.items())
    if "absent" not in path:
        assert "2.6.2" in response.text


def test_real_comparison_drill_down_retains_period_and_selects_exact_rows(
    tmp_path: Path,
) -> None:
    """A real retained comparison row is a working scoped navigation target."""
    signed = signed_history(retained_source("fixture", tmp_path / "unused"))
    body = signed.client.get("/", params=PARAMS).text
    match = re.search(r'class="release-label" href="([^"]+)">2.6.0', body)
    assert match is not None
    target = unescape(match[1])
    query = parse_qs(urlsplit(target).query)
    assert query == {**{k: [v] for k, v in PARAMS.items()}, "api_version": ["2.6.0"]}
    selected = signed.client.get(target)
    assert selected.status_code == 200 and "By API release" not in selected.text
    requests = signed.client.get("/requests", params={**PARAMS, "api_version": "2.6.0"})
    assert request_links(requests.text) == {"g7-260-0001", "g7-260-0002"}
