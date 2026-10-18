"""Tests for the source page and the shell footer's line about a local log.

The page is the console's answer to "which source am I reading, and what can it
answer?" - the question a local run asks first. It hangs off the footer, so it
gets its own file rather than a place in the main navigation tests.
"""

from __future__ import annotations

import re
from pathlib import Path

from .pages_helpers import make_client, make_local_client, make_local_log


def capability(body: str, name: str) -> str:
    """The availability cell the source page prints beside one capability."""
    match = re.search(rf"<td>{re.escape(name)}</td>\s*<td>(yes|no)</td>", body)
    assert match is not None, name
    return match.group(1)


def test_source_page_lists_what_the_sample_files_can_answer() -> None:
    """The sample files answer all three queries, and read no log file."""
    body = make_client().get("/source").text
    assert '<h1 class="page-title">Source</h1>' in body
    assert '<p class="page-subtitle">fixture</p>' in body
    assert capability(body, "Error Reporting groups") == "yes"
    assert capability(body, "Platform events") == "yes"
    assert capability(body, "Traces") == "yes"
    assert "Local log read" not in body


def test_source_page_names_what_a_local_log_cannot_answer(tmp_path: Path) -> None:
    """A local file groups its own crashes, but has no traces or platform events."""
    path, _ = make_local_log(tmp_path)
    body = make_local_client(path).get("/source").text
    assert '<p class="page-subtitle">local</p>' in body
    assert capability(body, "Error Reporting groups") == "yes"
    assert capability(body, "Platform events") == "no"
    assert capability(body, "Traces") == "no"


def test_source_page_describes_the_local_read(tmp_path: Path) -> None:
    """The counts, the file and the rejected line are all on the page."""
    path, _ = make_local_log(tmp_path)
    body = make_local_client(path).get("/source").text
    assert "Local log read" in body
    assert str(path) in body
    assert "<td>3</td>" in body  # lines read: two events and one banner line
    assert "<td>2</td>" in body  # events kept
    assert "not JSON: INFO:     not json at all" in body
    assert "<td>no</td>" in body  # the read was not cut short


def test_the_footer_links_to_the_source_page_for_a_local_log(tmp_path: Path) -> None:
    """The shell footer names the file and its counts, and links to /source."""
    path, _ = make_local_log(tmp_path)
    body = make_local_client(path).get("/").text
    assert 'class="sidebar-log" href="/source"' in body
    assert str(path) in body
    assert "2 events, 1 skipped" in body


def test_the_footer_says_nothing_without_a_local_log() -> None:
    """With the sample files there is no log file, so no line links to /source."""
    assert 'href="/source"' not in make_client().get("/").text


def test_the_source_page_is_not_in_the_main_navigation() -> None:
    """It hangs off the footer, so no navigation section claims it."""
    body = make_client().get("/source").text
    assert "Backend" in body
    assert 'aria-current="page"' not in body


def test_a_missing_local_log_shows_the_banner_on_the_source_page(
    tmp_path: Path,
) -> None:
    """An unreadable log file is the usual banner, not a 500."""
    missing = tmp_path / "missing.jsonl"
    response = make_local_client(missing).get("/source")
    assert response.status_code == 200
    assert "not_found" in response.text
    assert str(missing) in response.text
    assert "No read to show" in response.text


def test_a_missing_local_log_does_not_break_the_other_pages(tmp_path: Path) -> None:
    """The footer swallows the read error; the page above it still renders."""
    response = make_local_client(tmp_path / "missing.jsonl").get("/")
    assert response.status_code == 200
    assert 'href="/source"' not in response.text
