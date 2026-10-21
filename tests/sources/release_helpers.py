"""Mixed-release contract records shared by source integration tests."""

from __future__ import annotations

import json
import shutil
from collections.abc import Sequence
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from app.config import REPO_ROOT
from app.contract import load_contract
from app.domain.models import TimeWindow
from app.sources.fixture_source import FixtureSource

BASE = datetime(2026, 10, 8, 12, tzinfo=UTC)
WINDOW = TimeWindow(start=BASE, end=BASE + timedelta(hours=1))
VERSIONS = ("2.5.0", None, "2.6.0", "v2.6.0", "V2.6.0", "2.5.0", "all", "unknown")


def release_lines(versions: Sequence[object] = VERSIONS) -> list[dict[str, Any]]:
    """Clone a real request with distinct IDs, times and chosen release labels."""
    raw = (REPO_ROOT / "fixtures/events.jsonl").read_text(encoding="utf-8")
    originals = [json.loads(line) for line in raw.splitlines() if line]
    template = next(line for line in originals if line["event"] == "http.request")
    lines = []
    for index, version in enumerate(versions):
        line = deepcopy(template)
        line["api_version"] = version
        line["request_id"] = request_id(index)
        line["timestamp"] = (BASE + timedelta(minutes=index)).isoformat()
        line["attributes"]["route"] = "/v2/fixtures"
        line["attributes"]["status"] = 500 if index == 0 else 200
        lines.append(line)
    return lines


def request_id(index: int) -> str:
    """A valid, stably ordered request identity for one generated line."""
    return f"request-{index:08d}"


def fixture_releases(path: Path, lines: list[dict[str, Any]]) -> FixtureSource:
    """Load mixed events through real fixture parsing, preserving support files."""
    shutil.copytree(REPO_ROOT / "fixtures", path)
    (path / "events.jsonl").write_text(
        "".join(json.dumps(line) + "\n" for line in lines), encoding="utf-8"
    )
    return FixtureSource(path, load_contract())
