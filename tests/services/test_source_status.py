"""Tests for the source page's model builder."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.config import Config
from app.contract import load_contract
from app.domain.errors import SourceUnavailableError
from app.domain.models import SourceCapabilities
from app.services.source_status import SourceStatusService, capability_rows
from app.sources.fixture_source import FixtureSource
from app.sources.local_log_source import LocalLogSource

NOW = datetime(2026, 10, 8, 18, 0, tzinfo=UTC)


def make_local_service(tmp_path: Path) -> SourceStatusService:
    """A source page service over an empty log file, fixed clock."""
    log = tmp_path / "api.jsonl"
    log.write_text("", encoding="utf-8")
    settings = Config(source="local", local_log_path=log)
    source = LocalLogSource(log, 1_000_000, load_contract(), lambda: NOW)
    return SourceStatusService(source, settings)


def test_the_capability_rows_name_the_three_queries() -> None:
    """The three flags become three named rows, in a fixed order."""
    rows = capability_rows(
        SourceCapabilities(traces=False, error_reporting=True, platform_events=False)
    )
    assert [(row.name, row.available) for row in rows] == [
        ("Error Reporting groups", True),
        ("Platform events", False),
        ("Traces", False),
    ]


def test_build_names_the_source_and_counts_the_read(tmp_path: Path) -> None:
    """The page gets the source's name, its capabilities and its read counts."""
    model = make_local_service(tmp_path).build()
    assert model.source == "local"
    assert model.stats is not None
    assert model.stats.lines_read == 0
    assert [row.available for row in model.capabilities] == [True, False, False]


def test_a_source_without_a_log_file_has_no_read_stats() -> None:
    """A source that reads no file answers None, not an empty read."""
    source = FixtureSource(Config().fixture_dir, load_contract(), now=NOW)
    service = SourceStatusService(source, Config())
    assert service.read_stats() is None
    assert service.footer_stats() is None


def test_the_footer_swallows_a_log_file_that_cannot_be_read(tmp_path: Path) -> None:
    """The footer is on every page, so a missing file must not break the render."""
    missing = tmp_path / "missing.jsonl"
    settings = Config(source="local", local_log_path=missing)
    source = LocalLogSource(missing, 1_000_000, load_contract(), lambda: NOW)
    service = SourceStatusService(source, settings)
    assert service.footer_stats() is None
    with pytest.raises(SourceUnavailableError):
        service.read_stats()
