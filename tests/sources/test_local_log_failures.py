"""LocalLogSource file errors, error groups and what a log file can answer."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from local_log_helpers import (
    CRASH_ROUTE,
    EVERYTHING,
    WINDOW,
    crash_line,
    make_source,
    request_line,
    write_log,
)

from app.contract import Contract, load_contract
from app.domain.errors import SourceUnavailableError
from app.domain.models import TimeWindow
from app.sources import local_log_source
from app.sources.local_log_source import (
    read_error,
)


@pytest.fixture(scope="module")
def contract() -> Contract:
    """The committed contract, loaded once."""
    return load_contract()


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


@pytest.mark.parametrize(
    ("failure", "kind"),
    [
        (PermissionError(13, "Permission denied"), "permission_denied"),
        (OSError(5, "Input/output error"), "unavailable"),
    ],
)
def test_read_error_names_what_went_wrong(
    tmp_path: Path, failure: OSError, kind: str
) -> None:
    """A refusal is permission_denied; any other I/O failure is unavailable."""
    path = tmp_path / "api.jsonl"
    error = read_error(path, failure)
    assert error.kind == kind
    assert str(path) in error.detail


def test_a_directory_in_place_of_the_file_is_a_source_error(
    tmp_path: Path, contract: Contract
) -> None:
    """A directory where the log file should be is a banner, not a crash."""
    directory = tmp_path / "logs"
    directory.mkdir()
    with pytest.raises(SourceUnavailableError) as raised:
        make_source(directory, contract).events(EVERYTHING)
    assert raised.value.kind in {"permission_denied", "unavailable"}
    assert str(directory) in raised.value.detail


def test_a_refused_stat_becomes_a_permission_error(
    tmp_path: Path, contract: Contract, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A file the process may not stat is a source error, not a traceback."""
    path = write_log(tmp_path / "api.jsonl", [request_line()])
    source = make_source(path, contract)

    def refused(self: Path, *, follow_symlinks: bool = True) -> os.stat_result:
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(Path, "stat", refused)
    with pytest.raises(SourceUnavailableError) as raised:
        source.read_stats()
    assert raised.value.kind == "permission_denied"
    assert str(path) in raised.value.detail


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
