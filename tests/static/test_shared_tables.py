"""Checks that the shared table rules actually reach the rendered tables.

The redesign moved the table treatment out of the old stylesheet into
``components.css`` and scoped it to ``.page-section``. A page that still renders
a bare section keeps the stylesheet link and answers 200 while silently losing
the table's width, borders and padding, so these tests join the emitted markup
to the shipped selectors instead of trusting the link.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Config
from app.contract import load_contract
from app.dependencies import get_overview
from app.domain.models import (
    ALL_CAPABILITIES,
    ErrorGroup,
    EventQuery,
    PlatformEvent,
    SourceCapabilities,
    TelemetryEvent,
    TimeWindow,
    Trace,
)
from app.main import create_app
from app.services.overview import OverviewService

CSS_DIR = Path(__file__).resolve().parents[2] / "app" / "static" / "css"
COMPONENTS_CSS = CSS_DIR / "components.css"
CONTRACT_COMPONENTS = tuple(load_contract().components)
CLOCK_TIME = datetime(2026, 10, 8, 18, 0, tzinfo=UTC)

RULE = re.compile(r"(?P<selectors>[^{}]+)\{(?P<body>[^{}]*)\}")
SLOWEST = re.compile(
    r'<section class="(?P<classes>[^"]+)" aria-label="Slowest routes">'
    r"(?P<markup>.*?)</section>",
    re.DOTALL,
)


class EmptySource:
    """A telemetry source that holds no events at all."""

    def events(self, query: EventQuery) -> list[TelemetryEvent]:
        """Return nothing."""
        return []

    def trace(self, trace_id: str) -> Trace | None:
        """There is no trace."""
        return None

    def error_groups(self, window: TimeWindow) -> list[ErrorGroup]:
        """There are no error groups."""
        return []

    def platform_events(self, window: TimeWindow) -> list[PlatformEvent]:
        """There are no platform events."""
        return []

    def capabilities(self) -> SourceCapabilities:
        """Say every query can be answered; the fake is not a local log file."""
        return ALL_CAPABILITIES


def _rules() -> list[tuple[list[str], str]]:
    """Every rule in components.css as (selector list, body), comments removed."""
    text = re.sub(
        r"/\*.*?\*/", "", COMPONENTS_CSS.read_text(encoding="utf-8"), flags=re.DOTALL
    )
    return [
        ([part.strip() for part in selectors.split(",")], body)
        for selectors, body in RULE.findall(text)
    ]


def _ancestors_of(tag: str) -> set[str]:
    """The ancestor classes the shared rules require for a tag, read from the CSS."""
    found: set[str] = set()
    for selectors, _ in _rules():
        for selector in selectors:
            match = re.fullmatch(r"\.([\w-]+)\s+" + tag, selector)
            if match:
                found.add(match.group(1))
    return found


def _rule_for(selector: str) -> str:
    """The body of the rule whose selector list contains the selector."""
    for selectors, body in _rules():
        if selector in selectors:
            return body
    raise AssertionError(f"no rule for {selector}")


def _slowest(body: str) -> tuple[set[str], str]:
    """The class set and markup of the real Slowest routes section."""
    match = SLOWEST.search(body)
    assert match is not None, "the page has no Slowest routes section"
    assert "<table>" in match.group("markup"), "the section has no table to style"
    return set(match.group("classes").split()), match.group("markup")


def _body(path: str, empty: bool = False) -> str:
    """The rendered page, optionally over a source with no events at all."""
    app = create_app(Config(), clock=lambda: CLOCK_TIME)
    if empty:
        service = OverviewService(
            EmptySource(), lambda: CLOCK_TIME, Config(), CONTRACT_COMPONENTS
        )
        app.dependency_overrides[get_overview] = lambda: service
    return str(TestClient(app).get(path).text)


@pytest.mark.parametrize("path", ("/", "/partials/overview?hours=24"))
def test_the_slowest_table_sits_under_the_shared_ancestor(path: str) -> None:
    """Both the full page and the partial put the table under the shared rule."""
    classes, _ = _slowest(_body(path))
    ancestors = _ancestors_of("table")
    assert "page-section" in ancestors, ancestors
    assert classes & ancestors, f"{sorted(classes)} matches none of {sorted(ancestors)}"


@pytest.mark.parametrize("path", ("/", "/partials/overview?hours=24"))
def test_the_slowest_cells_sit_under_the_shared_ancestor(path: str) -> None:
    """The header and body cells are covered by the shared cell rule too."""
    classes, _ = _slowest(_body(path))
    assert classes & _ancestors_of("td")


def test_the_no_data_table_is_styled_too() -> None:
    """An empty window still renders the table, inside the shared ancestor."""
    classes, markup = _slowest(_body("/partials/overview?hours=24", empty=True))
    assert "No requests in this window." in markup
    assert classes & _ancestors_of("table")


def test_the_shared_rules_keep_the_table_treatment() -> None:
    """The properties the old .slowest rules carried still live on the shared rule."""
    table = _rule_for(".page-section table")
    assert "width: 100%" in table
    assert "border-collapse: collapse" in table
    assert "background: var(--surface)" in table
    cells = _rule_for(".page-section td")
    assert "padding: 8px 10px" in cells
    assert "text-align: left" in cells
    assert "border-bottom: 1px solid var(--line)" in cells
    assert "white-space: nowrap" in cells
