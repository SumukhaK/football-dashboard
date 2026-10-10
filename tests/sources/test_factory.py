"""Tests for build_source."""

from __future__ import annotations

from datetime import UTC, datetime

from app.config import Config
from app.contract import load_contract
from app.sources.cached import CachedSource
from app.sources.factory import build_source
from app.sources.fixture_source import FixtureSource
from app.sources.gcp.source import GcpSource

NOW = datetime(2026, 10, 10, 12, 0, tzinfo=UTC)


def test_fixture_source_is_cached() -> None:
    """source=fixture builds a cached FixtureSource."""
    source = build_source(Config(), load_contract(), lambda: NOW)
    assert isinstance(source, CachedSource)
    assert isinstance(source._inner, FixtureSource)


def test_gcp_source_is_cached_and_lazy() -> None:
    """source=gcp builds a cached GcpSource without contacting Google."""
    settings = Config(source="gcp", gcp_project_id="demo-project")
    source = build_source(settings, load_contract(), lambda: NOW)
    assert isinstance(source, CachedSource)
    assert isinstance(source._inner, GcpSource)
