"""Tests for build_source."""

from __future__ import annotations

import subprocess
import sys
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


def test_fixture_runs_do_not_load_google_sdks() -> None:
    """Building the app with the fixture source never imports google.cloud."""
    code = (
        "import sys; from app.main import create_app; create_app(); "
        "assert not any(m.startswith('google.cloud') for m in sys.modules)"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr
