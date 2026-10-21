"""Fixed retained-history inputs shared by cross-layer acceptance tests."""

import re
from datetime import UTC, date, datetime
from html import unescape
from pathlib import Path

from app.config import REPO_ROOT, Config
from app.contract import load_contract
from app.domain.models import TimeWindow
from app.services.overview import OverviewService
from app.sources.base import TelemetrySource
from app.sources.cached import CachedSource
from app.sources.fixture_source import FixtureSource
from app.sources.local_log_source import LocalLogSource
from tests.auth.console import Console, console

DIRECTORY = REPO_ROOT / "tests/fixtures/release_history"
NOW = datetime(2026, 10, 21, 12, tzinfo=UTC)
WINDOW = TimeWindow(
    datetime(2026, 10, 1, 18, 28, tzinfo=UTC),
    datetime(2026, 10, 2, 18, 35, tzinfo=UTC),
)
PARAMS = {"start": WINDOW.start.isoformat(), "end": WINDOW.end.isoformat()}


def settings() -> Config:
    """Use a synthetic FX rate/date and a fixed-clock sample directory."""
    return Config(
        source="fixture",
        invites_enabled=False,
        fixture_dir=DIRECTORY,
        inr_per_usd=80,
        inr_per_usd_as_of=date(2026, 10, 21),
    )


def retained_source(kind: str, path: Path) -> FixtureSource | LocalLogSource:
    """Load the same committed contract records through each real file adapter."""
    if kind == "fixture":
        return FixtureSource(DIRECTORY, load_contract())
    path.write_bytes((DIRECTORY / "events.jsonl").read_bytes())
    return LocalLogSource(path, 50_000_000, load_contract(), lambda: NOW)


def signed_history(source: TelemetrySource) -> Console:
    """Install one cached source shared by discovery, selected pages and all-mode Overview."""
    signed = console(settings(), clock=lambda: NOW)
    cached = CachedSource(source, 60, lambda: NOW)
    signed.app.state.source = cached
    signed.app.state.overview = OverviewService(cached, lambda: NOW, settings(), ())
    return signed


def request_links(body: str) -> set[str]:
    """Collect actual request-row IDs, excluding picker/navigation text."""
    return set(re.findall(r'class="request-row" href="/requests/([^?"/]+)', body))


def comparison_rows(body: str) -> list[list[str]]:
    """Read visible comparison body/footer cells without depending on whitespace."""
    table = re.search(
        r"<table><caption[^>]*>API release metrics.*?</table>", body, re.DOTALL
    )
    assert table is not None
    return [
        [
            unescape(re.sub(r"<[^>]*>", "", cell)).strip()
            for cell in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.DOTALL)
        ]
        for row in re.findall(r"<tr>(.*?)</tr>", table.group(), re.DOTALL)[1:]
    ]
