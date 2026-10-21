"""Release identity is pushed into Cloud Logging before provider row caps."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from gcp_fakes import FakeEntry, as_cloud_entry
from release_helpers import fixture_releases, release_lines

from app.config import REPO_ROOT
from app.contract import load_contract
from app.domain.models import EventQuery, TimeWindow
from app.domain.releases import ReleaseSelection
from app.sources.gcp import filters
from app.sources.gcp.logging_reader import LoggingReader
from app.sources.gcp.release_reader import LogPage, ReleaseReader
from app.sources.local_log_source import LocalLogSource

BASE = datetime(2026, 10, 8, 12, tzinfo=UTC)
WINDOW = TimeWindow(start=BASE, end=BASE + timedelta(hours=1))


def entries() -> list[FakeEntry]:
    """Mixed records with newer case variants that must not consume a cap."""
    original = next(
        json.loads(line)
        for line in (REPO_ROOT / "fixtures/events.jsonl").read_text().splitlines()
    )
    found = []
    for index, version in enumerate(("v2.6.0", "V2.6.0", "2.5.0")):
        line = dict(
            original,
            api_version=version,
            request_id=f"request-{index:08d}",
            timestamp=(BASE + timedelta(minutes=3 - index)).isoformat(),
        )
        found.append(as_cloud_entry(line))
    return found


class FilteringClient:
    """A recording fake applying the supplied exact regex before its row cap."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.data = entries()

    def list_entries(self, **kwargs: Any) -> Iterable[FakeEntry]:
        """Only the provider predicate can prevent unrelated rows using the cap."""
        self.calls.append(kwargs)
        match = re.search(
            r'jsonPayload.api_version\s*=~\s*("(?:\\.|[^"\\])*")', kwargs["filter_"]
        )
        selected = self.data
        if match:
            pattern = json.loads(match.group(1))
            selected = [
                e
                for e in selected
                if isinstance(e.payload["api_version"], str)
                and re.fullmatch(pattern, e.payload["api_version"])
            ]
        return iter(selected[: kwargs["max_results"]])

    def read_page(
        self, log_filter: str, token: str, size: int, timeout: float
    ) -> LogPage:
        """Apply the predicate before explicit provider pagination."""
        selected = list(
            self.list_entries(filter_=log_filter, max_results=len(self.data))
        )
        start = int(token or "0")
        end = start + size
        return LogPage(
            tuple(selected[start:end]), str(end) if end < len(selected) else ""
        )


def test_exact_predicate_precedes_provider_limit() -> None:
    """Case variants cannot exhaust the raw scan cap before the exact match."""
    client = FilteringClient()
    client.data = [entries()[0]] * 6000 + [entries()[1]]

    reader = LoggingReader(
        client,
        load_contract(),
        "football-api",
        100,
        release_reader=ReleaseReader(client, load_contract(), "football-api"),
    )
    found = reader.events(
        EventQuery(
            window=WINDOW, release=ReleaseSelection.from_query("V2.6.0"), limit=1
        )
    )
    assert [e.api_version for e in found] == ["V2.6.0"]
    assert len(client.calls) == 1
    assert 'resource.labels.service_name="football-api"' in client.calls[0]["filter_"]


@pytest.mark.parametrize("label", ['a" OR severity>0 OR "b', "a\\b", "v2.6.0", " β "])
def test_exact_regex_is_literal_case_sensitive_and_quoted(label: str) -> None:
    """Escaping at both regex and query boundaries preserves exact identity."""
    clause = filters.release_clause(ReleaseSelection.from_query(label))
    assert clause is not None and clause.startswith("jsonPayload.api_version=~")
    pattern = json.loads(clause.split("=~", 1)[1])
    assert re.fullmatch(pattern, label)
    assert not re.fullmatch(pattern, label + "other")
    if label.swapcase() != label:
        assert not re.fullmatch(pattern, label.swapcase())


def test_unknown_clause_is_explicit_and_all_has_no_predicate() -> None:
    """Unknown is scoped to present unusable metadata, not a missing-field bypass."""
    assert filters.release_clause(ReleaseSelection()) is None
    clause = filters.release_clause(ReleaseSelection.from_query("unknown"))
    assert clause is not None
    assert clause == "jsonPayload:*"


def test_chunked_id_queries_retain_release_and_cursor() -> None:
    """Every ID chunk retains the release predicate and inclusive tie cursor."""
    client = FilteringClient()

    reader = LoggingReader(
        client,
        load_contract(),
        "football-api",
        100,
        release_reader=ReleaseReader(client, load_contract(), "football-api"),
    )
    query = EventQuery(
        window=WINDOW,
        release=ReleaseSelection.from_query("2.5.0"),
        request_ids=tuple(f"request-{i:08d}" for i in range(101)),
        before=WINDOW.end,
        before_id="request-00000999",
    )
    reader.events(query)
    assert len(client.calls) == 2
    for call in client.calls:
        assert "jsonPayload.api_version=~" in call["filter_"]
        assert "timestamp<=" in call["filter_"]


@pytest.mark.parametrize(
    "value", [None, "2.5.0", "2.6.0", "v2.6.0", "V2.6.0", "unknown", "all"]
)
def test_google_fixture_and_local_return_identical_selected_rows(
    value: str | None, tmp_path: Path
) -> None:
    """All three adapters preserve the same exact/unknown identities and order."""
    lines = release_lines()
    fixture = fixture_releases(tmp_path / "sample", lines)
    path = tmp_path / "api.jsonl"
    path.write_text(
        "".join(json.dumps(line) + "\n" for line in lines), encoding="utf-8"
    )
    local = LocalLogSource(path, 100_000, load_contract(), lambda: BASE)
    client = FilteringClient()
    client.data = [as_cloud_entry(line) for line in reversed(lines)]
    google = LoggingReader(
        client,
        load_contract(),
        "football-api",
        100,
        release_reader=ReleaseReader(client, load_contract(), "football-api"),
    )
    query = EventQuery(
        window=WINDOW, release=ReleaseSelection.from_query(value), limit=2
    )
    expected = fixture.events(query)
    assert google.events(query) == local.events(query) == expected
