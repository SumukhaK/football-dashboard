"""Human timestamps use IST while links and source observations retain UTC."""

import re
from datetime import UTC, datetime
from html import unescape
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from app.config import Config
from tests.auth.console import console_client

from .pages_helpers import make_local_client, make_local_log
from .requests_helpers import make_line, make_list_client

NOW = datetime(2026, 10, 20, 18, 45, tzinfo=UTC)
ISSUE = "4f1c2a9be0d34c5e"


@pytest.mark.parametrize(
    "path",
    [
        "/",
        "/partials/overview?hours=1",
        "/requests",
        "/partials/requests?hours=1",
        "/errors",
        "/partials/errors?hours=1",
        "/assistant",
        "/partials/assistant?hours=1",
        "/data",
        "/partials/data?hours=1",
        "/access",
        "/partials/access?hours=1",
        "/crashes",
        "/partials/crashes?hours=168",
        f"/crashes/{ISSUE}?hours=168",
        "/source",
    ],
)
def test_pages_and_partials_identify_ist_without_utc_displays(path: str) -> None:
    """Full/HTMX views share the display zone, including crash event rows."""
    client = console_client(Config(source="fixture"), clock=lambda: NOW)
    response = client.get(path)
    assert response.status_code == 200
    assert "All times IST" in response.text
    assert " UTC" not in response.text
    assert "+00:00" not in response.text
    if path in {"/", "/partials/overview?hours=1"}:
        assert "Updated 00:15 IST" in response.text


@pytest.mark.parametrize(
    "path",
    [
        "/requests",
        "/partials/requests",
        "/requests/req-aaaaaaaa",
        "/partials/requests/req-aaaaaaaa/panel",
    ],
)
def test_request_titles_timeline_and_panel_use_ist(path: str) -> None:
    """A known request's absolute time agrees in every form, including hover."""
    client = make_list_client(
        [
            make_line(
                15,
                "http.request",
                "req-aaaaaaaa",
                {"route": "/v2/predict", "status": 200, "duration_ms": 12},
            ),
        ]
    )
    response = client.get(path)
    assert response.status_code == 200
    assert "08 Oct 23:15 IST" in response.text
    assert " UTC" not in response.text
    if path in {"/requests", "/partials/requests"}:
        assert 'title="08 Oct 23:15 IST"' in response.text
        assert "15 min ago" in response.text


def test_source_read_time_is_ist(tmp_path: Path) -> None:
    """Local read diagnostics convert the frozen read clock for display."""
    path, _ = make_local_log(tmp_path)
    response = make_local_client(path).get("/source")
    assert response.status_code == 200
    assert "08 Oct 23:30 IST" in response.text
    assert " UTC" not in response.text


def test_ist_rows_keep_utc_pagination_cursors() -> None:
    """The India clock on row 100 must not shift the next page's UTC boundary."""
    client = make_list_client(
        [
            make_line(
                minute,
                "http.request",
                f"req-{minute:08d}",
                {"route": "/v2/predict", "status": 200},
            )
            for minute in range(1, 102)
        ]
    )
    body = client.get("/requests").text
    assert 'title="08 Oct 21:50 IST"' in body
    match = re.search(r'hx-get="([^"]*before=[^"]+)"', body)
    assert match is not None
    link = unescape(match.group(1))
    assert parse_qs(urlsplit(link).query)["before"] == ["2026-10-08T16:20:00+00:00"]
    response = client.get(link)
    assert response.status_code == 200
    assert "/requests/req-00000101" in response.text
    assert "/requests/req-00000100" not in response.text
