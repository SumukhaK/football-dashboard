"""Recorded API release identity and immutable query-selection semantics."""

from __future__ import annotations

import json
from dataclasses import FrozenInstanceError
from typing import Any

import pytest

from app.config import REPO_ROOT
from app.contract import ContractError, load_contract, validate_event
from app.domain.models import TelemetryEvent


def line_with_release(value: object) -> dict[str, Any]:
    """Return a real contract fixture with a chosen release value."""
    raw = (REPO_ROOT / "fixtures/events.jsonl").read_text(encoding="utf-8")
    line: dict[str, Any] = json.loads(raw.splitlines()[0])
    line["api_version"] = value
    return line


@pytest.mark.parametrize(
    "version",
    ["2.5.0", "2.5.1", "2.6.0", "2.50", "v2.6.0", "V2.6.0", " β ", "<release>"],
)
def test_recorded_identity_is_preserved_exactly(version: str) -> None:
    """Release spelling is independent of revision and contract identity."""
    line = line_with_release(version)
    validate_event(load_contract(), line)
    event = TelemetryEvent.from_log_line(line)
    assert getattr(event, "api_version", None) == version
    assert event.revision == line["revision"]
    assert line["contract_version"] == "1.1.0"


@pytest.mark.parametrize(
    "value", [None, "", " ", "unknown", 42, {}, "x" * 65, "x\n", "\x00"]
)
def test_unusable_recorded_identity_is_unknown(value: object) -> None:
    """Unknown values do not weaken required-field contract validation."""
    line = line_with_release(value)
    validate_event(load_contract(), line)
    assert TelemetryEvent.from_log_line(line).api_version is None


def test_missing_required_release_remains_invalid() -> None:
    """An absent common field is rejected instead of manufacturing history."""
    line = line_with_release(None)
    del line["api_version"]
    with pytest.raises(ContractError, match="missing common field: api_version"):
        validate_event(load_contract(), line)


def test_query_selections_are_distinct_frozen_and_hashable() -> None:
    """Typed states cannot collide with exact labels in a cache key."""
    from app.domain.releases import ReleaseSelection

    all_releases = ReleaseSelection.from_query(None)
    unknown = ReleaseSelection.from_query("unknown")
    exact = ReleaseSelection.from_query("all")
    assert (all_releases.kind, all_releases.value) == ("all", None)
    assert (unknown.kind, unknown.value) == ("unknown", None)
    assert (exact.kind, exact.value) == ("exact", "all")
    assert len({all_releases, unknown, exact}) == 3
    dynamic: Any = exact
    with pytest.raises(FrozenInstanceError):
        dynamic.value = "2.6.0"


@pytest.mark.parametrize("version", ["2.50", "v2.6.0", "V2.6.0", 'a"b\\c', "x" * 64])
def test_exact_selection_retains_the_input(version: str) -> None:
    """Boundary escaping must not change stored release identity."""
    from app.domain.releases import ReleaseSelection

    selected = ReleaseSelection.from_query(version)
    assert selected.kind == "exact"
    assert selected.value == version


@pytest.mark.parametrize("value", ["", " ", "x" * 65, "bad\nversion", "\x00"])
def test_invalid_explicit_query_is_rejected(value: str) -> None:
    """Invalid input never silently changes to all or unknown."""
    from app.domain.releases import ReleaseSelection

    with pytest.raises(ValueError):
        ReleaseSelection.from_query(value)


@pytest.mark.parametrize(
    ("kind", "value"),
    [
        ("all", "2.6.0"),
        ("unknown", "x"),
        ("exact", None),
        ("exact", "unknown"),
        ("bad", None),
    ],
)
def test_impossible_selection_states_are_rejected(kind: Any, value: str | None) -> None:
    """Direct construction enforces the same invariants as query parsing."""
    from app.domain.releases import ReleaseSelection

    with pytest.raises(ValueError):
        ReleaseSelection(kind, value)
