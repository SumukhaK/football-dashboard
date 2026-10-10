"""Fixtures shared by the source tests, including the GCP reader tests."""

from __future__ import annotations

import json
from typing import Any

import pytest
from source_helpers import EventFactory, make_event

from app.config import REPO_ROOT


@pytest.fixture
def event_factory() -> EventFactory:
    """Return the event builder."""
    return make_event


@pytest.fixture(scope="session")
def fixture_lines() -> list[dict[str, Any]]:
    """The committed fixture events as raw contract lines."""
    text = (REPO_ROOT / "fixtures" / "events.jsonl").read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines() if line.strip()]
