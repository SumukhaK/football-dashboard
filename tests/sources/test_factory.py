"""Tests for build_source."""

from __future__ import annotations

import subprocess
import sys
from datetime import UTC, datetime

from app.config import Config
from app.contract import load_contract
from app.sources.cached import CachedCrashSource, CachedSource
from app.sources.factory import build_crash_source, build_source
from app.sources.fixture_crashes import FixtureCrashSource
from app.sources.fixture_source import FixtureSource
from app.sources.gcp.crashlytics_reader import BigQueryCrashSource
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


def test_crash_source_is_cached_fixture_by_default() -> None:
    """source=fixture builds a cached FixtureCrashSource."""
    source = build_crash_source(Config(), lambda: NOW)
    assert isinstance(source, CachedCrashSource)
    assert isinstance(source._inner, FixtureCrashSource)


def test_crash_source_is_none_on_gcp_without_firebase_project() -> None:
    """source=gcp with no crashlytics_project_id turns the crashes page off."""
    settings = Config(source="gcp", gcp_project_id="demo-project")
    assert build_crash_source(settings, lambda: NOW) is None


def test_gcp_crash_source_names_the_export_table() -> None:
    """With a Firebase project the BigQuery reader targets the export table."""
    settings = Config(
        source="gcp",
        gcp_project_id="demo-project",
        crashlytics_project_id="football-intelligent-platform",
    )
    source = build_crash_source(settings, lambda: NOW)
    assert isinstance(source, CachedCrashSource)
    inner = source._inner
    assert isinstance(inner, BigQueryCrashSource)
    assert inner._table == (
        "football-intelligent-platform.firebase_crashlytics."
        "com_footballintelligence_app_stg_ANDROID"
    )
    assert inner._client is None
