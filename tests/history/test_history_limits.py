"""Bounded source evidence never becomes invented complete release history."""

from datetime import timedelta
from pathlib import Path

import pytest

from app.contract import load_contract
from app.domain.errors import SourceUnavailableError
from app.domain.models import EventQuery, TimeWindow
from app.services.overview import OverviewService
from app.sources.cached import CachedSource
from app.sources.local_log_source import LocalLogSource
from tests.history.helpers import (
    DIRECTORY,
    NOW,
    PARAMS,
    WINDOW,
    comparison_rows,
    request_links,
    retained_source,
    settings,
    signed_history,
)


def test_missing_log_is_unavailable_then_recovers_without_caching_failure(
    tmp_path: Path,
) -> None:
    """A missing file is not an empty healthy history, and a later successful read retries."""
    path = tmp_path / "later.jsonl"
    local = LocalLogSource(path, 50_000_000, load_contract(), lambda: NOW)
    cached = CachedSource(local, 60, lambda: NOW)
    query = EventQuery(WINDOW, events=("http.request",))
    with pytest.raises(SourceUnavailableError):
        cached.events(query)
    signed = signed_history(cached)
    response = signed.client.get("/", params={**PARAMS, "api_version": "2.5.0"})
    assert response.status_code == 200 and "Telemetry is unavailable" in response.text
    assert "Release discovery unavailable" in response.text
    assert (
        "No data for this release and period in retained telemetry" not in response.text
    )
    path.write_bytes((DIRECTORY / "events.jsonl").read_bytes())
    assert len(cached.events(query)) == 5
    assert request_links(signed.client.get("/requests", params=PARAMS).text)


def test_byte_tail_discovery_is_incomplete_not_a_complete_empty_catalogue(
    tmp_path: Path,
) -> None:
    """A release lost before the retained byte tail cannot be declared absent."""
    path = tmp_path / "tail.jsonl"
    path.write_bytes((DIRECTORY / "events.jsonl").read_bytes())
    local = LocalLogSource(path, 1600, load_contract(), lambda: NOW)
    assert local.read_stats().truncated
    catalogue = local.release_catalogue(WINDOW)
    assert catalogue.truncated and "2.5.0" not in catalogue.versions
    signed = signed_history(local)
    response = signed.client.get("/requests", params={**PARAMS, "api_version": "2.5.0"})
    assert response.status_code == 200
    assert 'value="2.5.0" selected' in response.text
    assert "Release discovery is incomplete" in response.text
    assert (
        "No data for this release and period in retained telemetry" not in response.text
    )


def test_real_row_cap_reaches_discovery_service_comparison_and_logs(
    tmp_path: Path,
) -> None:
    """The actual source cap is labelled consistently in every downstream representation."""
    path = tmp_path / "capped.jsonl"
    lines = (DIRECTORY / "events.jsonl").read_text(encoding="utf-8").splitlines()
    path.write_text((lines[1] + "\n") * 5001, encoding="utf-8")
    source = CachedSource(
        LocalLogSource(path, 50_000_000, load_contract(), lambda: NOW), 60, lambda: NOW
    )
    assert source.release_catalogue(WINDOW).truncated
    model = OverviewService(source, lambda: NOW, settings(), ()).build(
        WINDOW, compare_releases=True
    )
    assert (
        model.truncated
        and model.release_comparison
        and model.release_comparison.truncated
    )
    signed = signed_history(source)
    response = signed.client.get("/", params=PARAMS)
    assert "5000-event sample cap" in response.text
    rows = comparison_rows(response.text)
    assert sum(int(row[1]) for row in rows[:-1]) == int(rows[-1][1]) == 5000
    logs = signed.client.get("/requests", params={**PARAMS, "tab": "logs"})
    assert "counts and history are incomplete" in logs.text
    assert "Next log page" in logs.text


@pytest.mark.parametrize(
    "start,end",
    [
        ("2025-10-20T12:00:00Z", "2025-10-21T12:00:00Z"),
        ("2026-08-01T00:00:00Z", "2026-09-02T00:00:00Z"),
        ("2026-10-21T00:00:00Z", "2026-10-22T00:00:00Z"),
    ],
)
def test_unsafe_history_bounds_reject_before_any_source_read(
    start: str, end: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The lookback/range safety bounds are enforced before discovery or reads."""
    source = retained_source("fixture", tmp_path / "unused")
    signed = signed_history(source)

    def forbidden(*args: object) -> object:
        raise AssertionError("unsafe history must not query telemetry")

    monkeypatch.setattr(source, "events", forbidden)
    monkeypatch.setattr(source, "release_catalogue", forbidden)
    assert (
        signed.client.get("/", params={"start": start, "end": end}).status_code == 422
    )


@pytest.mark.parametrize(
    "window",
    [
        TimeWindow(NOW - timedelta(days=365), NOW - timedelta(days=364)),
        TimeWindow(NOW - timedelta(days=31), NOW),
    ],
)
def test_allowed_safety_bound_does_not_imply_retained_history(
    window: TimeWindow, tmp_path: Path
) -> None:
    """An accepted period is only a permitted query, never proof of stored data."""
    source = retained_source("fixture", tmp_path / "unused")
    signed = signed_history(source)
    params = {
        "start": window.start.isoformat(),
        "end": window.end.isoformat(),
        "api_version": "missing",
    }
    response = signed.client.get("/", params=params)
    assert response.status_code == 200
    assert "No data for this release and period in retained telemetry" in response.text
    assert 'value="missing" selected' in response.text


def test_page_reuses_catalogue_cache_but_keeps_release_predicate_independent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Changing release never serves rows from a previous choice or rescans the catalogue."""
    source = retained_source("fixture", tmp_path / "unused")
    original = source.release_catalogue
    calls = []

    def counted(window: TimeWindow) -> object:
        calls.append(window)
        return original(window)

    monkeypatch.setattr(source, "release_catalogue", counted)
    signed = signed_history(source)
    for version, expected in [
        ("2.5.0", {"g7-250-0001"}),
        ("2.6.0", {"g7-260-0001", "g7-260-0002"}),
        ("unknown", {"g7-unk-0001"}),
        ("2.5.0", {"g7-250-0001"}),
    ]:
        assert (
            request_links(
                signed.client.get(
                    "/requests", params={**PARAMS, "api_version": version}
                ).text
            )
            == expected
        )
    assert len(calls) == 1
