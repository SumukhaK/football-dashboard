"""Tests for LocalLogSource: the backend's own JSON log file as a source.

The file is written into a temporary directory for each test, so the reading,
the change detection and the counting are all exercised without the fixtures.
Where a real contract line is wanted, the committed sample file is used: it is
the one set of lines the backend is known to have written.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from app.config import REPO_ROOT
from app.contract import Contract, load_contract
from app.domain.errors import SourceUnavailableError
from app.domain.models import MAX_QUERY_LIMIT, EventQuery, TimeWindow
from app.sources import local_log_source
from app.sources.local_log_source import (
    SAMPLE_ERROR_LIMIT,
    SAMPLE_LINE_LENGTH,
    LocalLogSource,
)

CLOCK_TIME = datetime(2026, 10, 8, 18, 0, tzinfo=UTC)
WINDOW = TimeWindow(
    start=datetime(2026, 1, 1, tzinfo=UTC), end=datetime(2027, 1, 1, tzinfo=UTC)
)
CRASH_ROUTE = "/v2/teams/{team}/outlook"

# Every query a test reads with, unless the test needs another one.
EVERYTHING = EventQuery(window=WINDOW, limit=MAX_QUERY_LIMIT)


@pytest.fixture(scope="module")
def contract() -> Contract:
    """The committed contract, loaded once."""
    return load_contract()


def make_source(
    path: Path, contract: Contract, max_bytes: int = 50_000_000
) -> LocalLogSource:
    """A local log source over the given file, with a fixed clock."""
    return LocalLogSource(path, max_bytes, contract, lambda: CLOCK_TIME)


def write_log(path: Path, lines: Iterable[str]) -> Path:
    """Write the given raw lines to a log file, one per line."""
    path.write_text("".join(line + "\n" for line in lines), encoding="utf-8")
    return path


def request_line(
    request_id: str = "req-00000001",
    timestamp: str = "2026-10-08T17:00:00.000Z",
    severity: str = "INFO",
) -> str:
    """One contract-shaped http.request line, as the backend writes it."""
    return json.dumps(
        {
            "timestamp": timestamp,
            "severity": severity,
            "message": "GET /v2/fixtures 200 in 12ms",
            "logger": "backend.app.main",
            "event": "http.request",
            "request_id": request_id,
            "logging.googleapis.com/trace": None,
            "logging.googleapis.com/spanId": None,
            "trace_id": None,
            "service": "football-api",
            "revision": None,
            "api_version": "2.0.0",
            "contract_version": "1.1.0",
            "attributes": {
                "method": "GET",
                "route": "/v2/fixtures",
                "status": 200,
                "duration_ms": 12.5,
                "error_code": None,
            },
        }
    )


def crash_line(
    exception_type: str = "builtins.ZeroDivisionError",
    timestamp: str = "2026-10-08T17:00:00.000Z",
    route: str = CRASH_ROUTE,
) -> str:
    """One contract-shaped app.crash line; its message is the traceback."""
    message = (
        "Traceback (most recent call last):\n"
        '  File "app/main.py", line 42, in handler\n'
        "    1 / 0\n"
        f"{exception_type}: division by zero"
    )
    return json.dumps(
        {
            "timestamp": timestamp,
            "severity": "ERROR",
            "message": message,
            "logger": "backend.app.main",
            "event": "app.crash",
            "request_id": "req-00000009",
            "logging.googleapis.com/trace": None,
            "logging.googleapis.com/spanId": None,
            "trace_id": None,
            "service": "football-api",
            "revision": None,
            "api_version": "2.0.0",
            "contract_version": "1.1.0",
            "attributes": {"route": route, "exception_type": exception_type},
        }
    )


def fixture_log_lines(count: int = 5) -> list[str]:
    """The first lines of the committed sample events, as raw log lines."""
    text = (REPO_ROOT / "fixtures" / "events.jsonl").read_text(encoding="utf-8")
    lines = [line for line in text.splitlines() if line.strip()]
    return lines[:count]


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


def test_a_grown_file_is_read_again(tmp_path: Path, contract: Contract) -> None:
    """A line appended between reads is visible to the next read."""
    path = write_log(tmp_path / "api.jsonl", [request_line("req-00000001")])
    source = make_source(path, contract)
    assert len(source.events(EVERYTHING)) == 1
    with path.open("a", encoding="utf-8") as handle:
        handle.write(request_line("req-00000002") + "\n")
    assert len(source.events(EVERYTHING)) == 2


def test_an_unchanged_file_is_read_once(
    tmp_path: Path, contract: Contract, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Three calls over an unchanged file read the file once."""
    path = write_log(tmp_path / "api.jsonl", [request_line(), crash_line()])
    source = make_source(path, contract)
    reads: list[Path] = []
    real = local_log_source.read_tail

    def spy(where: Path, max_bytes: int, size: int) -> tuple[str, bool]:
        reads.append(where)
        return real(where, max_bytes, size)

    monkeypatch.setattr(local_log_source, "read_tail", spy)
    source.events(EVERYTHING)
    source.read_stats()
    source.error_groups(WINDOW)
    source.platform_events(WINDOW)
    assert reads == [path]


def test_a_rewritten_file_is_read_again(tmp_path: Path, contract: Contract) -> None:
    """A file that shrinks is a change like any other, and is read again."""
    path = write_log(
        tmp_path / "api.jsonl",
        [request_line("req-00000001"), request_line("req-00000002")],
    )
    source = make_source(path, contract)
    assert len(source.events(EVERYTHING)) == 2
    write_log(path, [request_line("req-00000003")])
    found = source.events(EVERYTHING)
    assert [event.request_id for event in found] == ["req-00000003"]


def test_a_long_file_is_read_from_the_end(tmp_path: Path, contract: Contract) -> None:
    """Only the tail is read, the half line at the cut is dropped, and it says so."""
    first, second, third = (request_line(f"req-0000000{n}") for n in (1, 2, 3))
    path = write_log(tmp_path / "api.jsonl", [first, second, third])
    # Enough of the end for the last line and ten bytes of the one before it.
    max_bytes = len((third + "\n").encode("utf-8")) + 10
    source = make_source(path, contract, max_bytes=max_bytes)
    found = source.events(EVERYTHING)
    assert [event.request_id for event in found] == ["req-00000003"]
    stats = source.read_stats()
    assert stats.truncated is True
    assert stats.lines_read == 1
    assert stats.file_size_bytes == path.stat().st_size


def test_a_file_under_the_limit_is_read_whole(
    tmp_path: Path, contract: Contract
) -> None:
    """A file smaller than the limit is read whole, and the page says so."""
    path = write_log(tmp_path / "api.jsonl", [request_line()])
    stats = make_source(path, contract, max_bytes=1_000_000).read_stats()
    assert stats.truncated is False
    assert stats.lines_read == 1


def test_a_missing_file_is_reported_when_read_not_when_built(
    tmp_path: Path, contract: Contract
) -> None:
    """The source is lazy: building it is fine, reading a missing file is not."""
    source = make_source(tmp_path / "missing.jsonl", contract)
    with pytest.raises(SourceUnavailableError) as raised:
        source.events(EVERYTHING)
    assert raised.value.kind == "not_found"
    assert raised.value.detail == f"{tmp_path / 'missing.jsonl'} not found"


def test_a_file_deleted_between_reads_is_reported(
    tmp_path: Path, contract: Contract
) -> None:
    """A file deleted after one good read is a missing file on the next."""
    path = write_log(tmp_path / "api.jsonl", [request_line()])
    source = make_source(path, contract)
    assert len(source.events(EVERYTHING)) == 1
    path.unlink()
    with pytest.raises(SourceUnavailableError) as raised:
        source.events(EVERYTHING)
    assert raised.value.kind == "not_found"


def test_a_file_deleted_after_the_stat_is_still_reported(
    tmp_path: Path, contract: Contract, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The read notices a file that vanishes between the stat and the open.

    The stat is frozen so the read is reached with a file that is already gone,
    which is the race the second FileNotFoundError catch is there for.
    """
    path = write_log(tmp_path / "api.jsonl", [request_line()])
    source = make_source(path, contract)
    stamp = source._stat()
    monkeypatch.setattr(source, "_stat", lambda: stamp)
    path.unlink()
    with pytest.raises(SourceUnavailableError) as raised:
        source.events(EVERYTHING)
    assert raised.value.kind == "not_found"


def test_error_groups_come_from_the_crash_lines(
    tmp_path: Path, contract: Contract
) -> None:
    """app.crash lines group by exception type, the newest group first."""
    path = write_log(
        tmp_path / "api.jsonl",
        [
            crash_line("builtins.ZeroDivisionError", "2026-10-08T10:00:00.000Z"),
            crash_line("builtins.KeyError", "2026-10-08T11:00:00.000Z", "/v2/x"),
            crash_line("builtins.ZeroDivisionError", "2026-10-08T12:00:00.000Z"),
        ],
    )
    groups = make_source(path, contract).error_groups(WINDOW)
    assert [group.group_id for group in groups] == [
        "builtins.ZeroDivisionError",
        "builtins.KeyError",
    ]
    first = groups[0]
    assert first.exception_type == "builtins.ZeroDivisionError"
    assert first.count == 2
    assert first.first_seen == datetime(2026, 10, 8, 10, 0, tzinfo=UTC)
    assert first.last_seen == datetime(2026, 10, 8, 12, 0, tzinfo=UTC)
    assert first.affected_routes == (CRASH_ROUTE,)
    assert first.message.startswith("Traceback (most recent call last):")


def test_the_same_exception_on_two_routes_names_both(
    tmp_path: Path, contract: Contract
) -> None:
    """Two routes for one exception are listed in path order."""
    path = write_log(
        tmp_path / "api.jsonl",
        [
            crash_line(route=CRASH_ROUTE),
            crash_line(route="/v2/predict"),
        ],
    )
    groups = make_source(path, contract).error_groups(WINDOW)
    assert len(groups) == 1
    assert groups[0].affected_routes == ("/v2/predict", CRASH_ROUTE)


def test_crash_lines_outside_the_window_are_left_out(
    tmp_path: Path, contract: Contract
) -> None:
    """The window is the one the callback asked for."""
    path = write_log(
        tmp_path / "api.jsonl",
        [crash_line(timestamp="2026-10-08T17:00:00.000Z")],
    )
    source = make_source(path, contract)
    narrow = TimeWindow(
        start=datetime(2026, 10, 8, 18, 0, tzinfo=UTC),
        end=datetime(2026, 10, 8, 19, 0, tzinfo=UTC),
    )
    assert source.error_groups(narrow) == []
    assert len(source.error_groups(WINDOW)) == 1


def test_other_events_do_not_become_groups(tmp_path: Path, contract: Contract) -> None:
    """Only app.crash lines are grouped."""
    path = write_log(tmp_path / "api.jsonl", [request_line(), crash_line()])
    groups = make_source(path, contract).error_groups(WINDOW)
    assert len(groups) == 1
    assert groups[0].exception_type == "builtins.ZeroDivisionError"


def test_a_crash_without_an_exception_type_still_groups(
    tmp_path: Path, contract: Contract
) -> None:
    """A null exception type passes the contract, and still lands in a group."""
    line = json.loads(crash_line())
    line["attributes"]["exception_type"] = None
    path = write_log(tmp_path / "api.jsonl", [json.dumps(line)])
    groups = make_source(path, contract).error_groups(WINDOW)
    assert [group.group_id for group in groups] == ["unknown"]


def test_there_are_no_traces_in_a_log_file(tmp_path: Path, contract: Contract) -> None:
    """A trace id from the file still has no trace behind it."""
    path = write_log(tmp_path / "api.jsonl", [request_line()])
    assert make_source(path, contract).trace("a" * 32) is None


def test_there_are_no_platform_events_in_a_log_file(
    tmp_path: Path, contract: Contract
) -> None:
    """Cloud Run's platform log does not arrive in the backend's own file."""
    path = write_log(tmp_path / "api.jsonl", [request_line()])
    assert make_source(path, contract).platform_events(WINDOW) == []


def test_capabilities_name_what_a_log_file_can_answer(
    tmp_path: Path, contract: Contract
) -> None:
    """No traces, no platform events, and its own crash groups."""
    capabilities = make_source(tmp_path / "api.jsonl", contract).capabilities()
    assert capabilities.traces is False
    assert capabilities.error_reporting is True
    assert capabilities.platform_events is False


def test_capabilities_do_not_read_the_file(
    tmp_path: Path, contract: Contract, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Asking what the source can do never touches the log file."""

    def refuse(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("the log file was read for capabilities")

    path = write_log(tmp_path / "api.jsonl", [request_line()])
    monkeypatch.setattr(local_log_source, "read_tail", refuse)
    assert make_source(path, contract).capabilities().error_reporting is True
