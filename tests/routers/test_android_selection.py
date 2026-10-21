"""Android selection is independent from API release and survives navigation."""

from typing import cast

import pytest
from fastapi import FastAPI

from app.sources.cached import CachedCrashSource
from app.sources.fixture_crashes import FixtureCrashSource
from tests.routers.pages_helpers import make_client


@pytest.mark.parametrize("path", ["/crashes", "/partials/crashes"])
def test_android_picker_is_independent_and_retains_absent_selection(path: str) -> None:
    """An absent Android release stays selected without borrowing another version."""
    response = make_client().get(
        path, params={"api_version": "2.6.0", "android_version": "2.5.1", "hours": 168}
    )
    assert response.status_code == 200
    assert '<select id="android-version" name="android_version">' in response.text
    assert 'value="2.5.1" selected' in response.text
    assert "independently scoped" in response.text
    assert "No data for this Android version and period" in response.text


def test_crash_links_retain_android_version_and_api_context() -> None:
    """Issue panels, Close, type chips and full details keep independent scope."""
    client = make_client()
    app = cast(FastAPI, client.app)
    cached = app.state.crash_source
    assert isinstance(cached, CachedCrashSource)
    source = cached._inner
    assert isinstance(source, FixtureCrashSource)
    selected = source._events[-1].app_version
    response = client.get(
        "/crashes",
        params={"api_version": "2.6.0", "android_version": selected, "hours": 168},
    )
    assert response.status_code == 200
    assert "android_version=" in response.text
    import re
    from html import unescape

    links = [
        unescape(s)
        for s in re.findall('href="([^"]+)"', response.text)
        if s.startswith("/crashes/")
    ]
    assert links
    detail = client.get(links[0])
    assert detail.status_code == 200
    assert 'name="android_version"' in detail.text
    assert "Back to crashes" in detail.text


@pytest.mark.parametrize("value", ["x" * 65, " ", "bad\nversion"])
def test_invalid_android_versions_fail_before_reads(value: str) -> None:
    """Malformed app versions cannot widen a query."""
    assert (
        make_client().get("/crashes", params={"android_version": value}).status_code
        == 422
    )
