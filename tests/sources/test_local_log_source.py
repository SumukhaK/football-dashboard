"""Tests for LocalLogSource: the backend's own JSON log file as a source.

The file is written into a temporary directory for each test, so the reading,
the change detection and the counting are all exercised without the fixtures.
Where a real contract line is wanted, the committed sample file is used: it is
the one set of lines the backend is known to have written.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.contract import Contract, load_contract
from app.sources.local_log_source import (
    SAMPLE_ERROR_LIMIT,
    SAMPLE_LINE_LENGTH,
)
from tests.sources.local_log_helpers import (
    CLOCK_TIME,
    EVERYTHING,
    fixture_log_lines,
    make_source,
    request_line,
    write_log,
)


@pytest.fixture(scope="module")
def contract() -> Contract:
    """The committed contract, loaded once."""
    return load_contract()


def test_contract_lines_become_events_newest_first(
    tmp_path: Path, contract: Contract
) -> None:
    """Every contract line in the file becomes an event, newest read first."""
    path = write_log(tmp_path / "api.jsonl", fixture_log_lines())
    found = make_source(path, contract).events(EVERYTHING)
    assert len(found) == 5
    stamps = [event.timestamp for event in found]
    assert stamps == sorted(stamps, reverse=True)


def test_the_file_is_read_with_the_contracts_own_reading(
    tmp_path: Path, contract: Contract
) -> None:
    """A line's fields reach the event, including the trace id after /traces/."""
    line = json.loads(fixture_log_lines(1)[0])
    line["logging.googleapis.com/trace"] = (
        "projects/demo-project/traces/923a736994e3bf911a61dbe22e44158b"
    )
    path = write_log(tmp_path / "api.jsonl", [json.dumps(line)])
    found = make_source(path, contract).events(EVERYTHING)
    assert len(found) == 1
    assert found[0].event == line["event"]
    assert found[0].trace_id == "923a736994e3bf911a61dbe22e44158b"


def test_a_line_that_is_not_json_is_counted_not_raised(
    tmp_path: Path, contract: Contract
) -> None:
    """A start-up banner line is counted, and the lines around it still read."""
    path = write_log(
        tmp_path / "api.jsonl",
        [
            "INFO:     Uvicorn running on http://127.0.0.1:8000",
            request_line(),
            "INFO:     Application startup complete.",
        ],
    )
    source = make_source(path, contract)
    assert len(source.events(EVERYTHING)) == 1
    stats = source.read_stats()
    assert stats.lines_read == 3
    assert stats.events_kept == 1
    assert stats.skipped_non_json == 2
    assert stats.skipped_invalid == 0
    assert stats.skipped_lines == 2
    assert stats.sample_errors[0].startswith("not JSON: INFO:")


def test_a_line_that_breaks_the_contract_is_counted_with_its_reason(
    tmp_path: Path, contract: Contract
) -> None:
    """An off-contract line is skipped, and the contract's message is kept."""
    path = write_log(
        tmp_path / "api.jsonl",
        [json.dumps({"event": "http.request"}), request_line()],
    )
    source = make_source(path, contract)
    assert len(source.events(EVERYTHING)) == 1
    stats = source.read_stats()
    assert stats.skipped_invalid == 1
    assert stats.skipped_non_json == 0
    assert stats.sample_errors == ("missing common field: timestamp",)


def test_a_line_that_is_json_but_not_an_object_is_counted(
    tmp_path: Path, contract: Contract
) -> None:
    """A bare JSON array is not an event, and does not stop the read."""
    path = write_log(tmp_path / "api.jsonl", ["[1, 2, 3]", request_line()])
    source = make_source(path, contract)
    assert len(source.events(EVERYTHING)) == 1
    stats = source.read_stats()
    assert stats.skipped_invalid == 1
    assert stats.sample_errors == ("not a JSON object: [1, 2, 3]",)


def test_a_line_with_a_timestamp_without_a_timezone_is_counted(
    tmp_path: Path, contract: Contract
) -> None:
    """A timezone-less timestamp is skipped, and the valid line beside it lives.

    Kept, that naive time makes the window's filter compare it with an aware
    time and raise, losing every other line in the same read.
    """
    naive = json.loads(request_line("req-00000001"))
    naive["timestamp"] = "2026-10-08T16:00:00"
    path = write_log(
        tmp_path / "api.jsonl", [json.dumps(naive), request_line("req-00000002")]
    )
    source = make_source(path, contract)
    found = source.events(EVERYTHING)
    assert [event.request_id for event in found] == ["req-00000002"]
    stats = source.read_stats()
    assert stats.events_kept == 1
    assert stats.skipped_invalid == 1
    assert "timezone" in stats.sample_errors[0]


def test_only_the_first_few_rejected_lines_are_kept_as_samples(
    tmp_path: Path, contract: Contract
) -> None:
    """However many lines are rejected, the samples stop at the limit."""
    path = write_log(tmp_path / "api.jsonl", ["{oops" for _ in range(9)])
    source = make_source(path, contract)
    assert source.events(EVERYTHING) == []
    stats = source.read_stats()
    assert stats.skipped_non_json == 9
    assert len(stats.sample_errors) == SAMPLE_ERROR_LIMIT


def test_a_very_long_rejected_line_is_cut_to_fit(
    tmp_path: Path, contract: Contract
) -> None:
    """A sample message stays one line, however long the rejected line was."""
    path = write_log(tmp_path / "api.jsonl", ["INFO: " + "x" * 500])
    stats = make_source(path, contract).read_stats()
    sample = stats.sample_errors[0]
    assert sample.startswith("not JSON: INFO: ")
    assert sample.endswith("...")
    assert len(sample) == len("not JSON: ") + SAMPLE_LINE_LENGTH


def test_blank_lines_are_not_counted_at_all(tmp_path: Path, contract: Contract) -> None:
    """A trailing newline is not a line the read has to excuse."""
    path = write_log(tmp_path / "api.jsonl", [request_line(), ""])
    source = make_source(path, contract)
    assert len(source.events(EVERYTHING)) == 1
    stats = source.read_stats()
    assert stats.lines_read == 1
    assert stats.skipped_lines == 0


def test_the_read_stats_name_the_file_and_the_moment(
    tmp_path: Path, contract: Contract
) -> None:
    """The stats carry the file's size and modification time, and the clock."""
    path = write_log(tmp_path / "api.jsonl", [request_line()])
    stats = make_source(path, contract).read_stats()
    assert stats.file_size_bytes == path.stat().st_size
    assert stats.last_modified is not None
    assert stats.last_modified == datetime.fromtimestamp(
        path.stat().st_mtime_ns / 1_000_000_000, tz=UTC
    )
    assert stats.read_at == CLOCK_TIME
