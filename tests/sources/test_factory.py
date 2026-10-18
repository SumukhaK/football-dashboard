"""Tests for build_source."""

from __future__ import annotations

import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.config import Config
from app.contract import load_contract
from app.domain.errors import SourceUnavailableError
from app.domain.models import EventQuery, TimeWindow
from app.sources.cached import CachedCrashSource, CachedSource
from app.sources.factory import build_crash_source, build_source
from app.sources.fixture_crashes import FixtureCrashSource
from app.sources.fixture_source import FixtureSource
from app.sources.gcp.crashlytics_reader import BigQueryCrashSource
from app.sources.gcp.source import GcpSource
from app.sources.local_log_source import LocalLogSource

NOW = datetime(2026, 10, 10, 12, 0, tzinfo=UTC)
WINDOW = TimeWindow(start=NOW - timedelta(hours=1), end=NOW)


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


def test_local_source_is_cached_and_reads_the_configured_file(
    tmp_path: Path,
) -> None:
    """source=local builds a cached LocalLogSource for the configured path."""
    log = tmp_path / "api.jsonl"
    log.write_text("", encoding="utf-8")
    settings = Config(source="local", local_log_path=log)
    source = build_source(settings, load_contract(), lambda: NOW)
    assert isinstance(source, CachedSource)
    inner = source._inner
    assert isinstance(inner, LocalLogSource)
    assert inner._path == log


def test_local_source_reads_nothing_at_startup(tmp_path: Path) -> None:
    """Building the source is lazy; the first read reports a missing file."""
    settings = Config(source="local", local_log_path=tmp_path / "missing.jsonl")
    source = build_source(settings, load_contract(), lambda: NOW)
    with pytest.raises(SourceUnavailableError) as raised:
        source.events(EventQuery(window=WINDOW))
    assert raised.value.kind == "not_found"


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
