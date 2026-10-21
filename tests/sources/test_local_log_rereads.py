"""LocalLogSource change detection, the read limit and the file encodings."""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import pytest
from local_log_helpers import (
    EVERYTHING,
    WINDOW,
    crash_line,
    make_source,
    request_line,
    write_log,
)

from app.contract import Contract, load_contract
from app.sources import local_log_source


@pytest.fixture(scope="module")
def contract() -> Contract:
    """The committed contract, loaded once."""
    return load_contract()


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

    def spy(where: Path, max_bytes: int) -> Any:
        reads.append(where)
        return real(where, max_bytes)

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


def test_a_file_over_the_limit_is_cut_on_a_whole_line(
    tmp_path: Path, contract: Contract
) -> None:
    """A tail that opens exactly on a line start keeps that whole line.

    The cut lands on the first byte of the final record, so nothing before it is
    a fragment: dropping it would silently lose a valid request.
    """
    first, second = request_line("req-00000001"), request_line("req-00000002")
    path = tmp_path / "api.jsonl"
    path.write_bytes((first + "\n" + second + "\n").encode("utf-8"))
    last = (second + "\n").encode("utf-8")
    source = make_source(path, contract, max_bytes=len(last))
    found = source.events(EVERYTHING)
    assert [event.request_id for event in found] == ["req-00000002"]
    assert source.read_stats().truncated is True


def test_a_file_over_the_limit_cut_on_the_break_keeps_the_next_line(
    tmp_path: Path, contract: Contract
) -> None:
    """A tail that opens on the break before a line drops only that break."""
    first, second = request_line("req-00000001"), request_line("req-00000002")
    path = tmp_path / "api.jsonl"
    path.write_bytes((first + "\n" + second + "\n").encode("utf-8"))
    source = make_source(path, contract, max_bytes=len(second.encode()) + 1)
    found = source.events(EVERYTHING)
    assert [event.request_id for event in found] == ["req-00000002"]


def test_a_read_uses_the_files_size_not_the_stat(
    tmp_path: Path, contract: Contract, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A file that grew after the stat is still read, and under the limit.

    The stat is frozen at the smaller size, as if the append landed between the
    stat and the open. The read must take its size from the open file: trusting
    the stat reads every appended byte unbounded and calls the read complete.
    """
    path = write_log(tmp_path / "api.jsonl", [request_line("req-00000001")])
    source = make_source(path, contract, max_bytes=path.stat().st_size + 10)
    stale = source._stat()
    with path.open("a", encoding="utf-8") as handle:
        handle.write(request_line("req-00000002") + "\n")
    monkeypatch.setattr(source, "_stat", lambda: stale)
    stats = source.read_stats()
    assert stats.truncated is True
    assert stats.file_size_bytes == path.stat().st_size
    assert stats.file_size_bytes > stale.size


def test_a_file_saved_as_utf16_with_a_bom_is_read(
    tmp_path: Path, contract: Contract
) -> None:
    """PowerShell 5.1's Tee-Object writes UTF-16; its lines are still read."""
    path = tmp_path / "api.jsonl"
    lines = [request_line("req-00000001"), request_line("req-00000002")]
    path.write_bytes("".join(line + "\r\n" for line in lines).encode("utf-16"))
    source = make_source(path, contract)
    assert len(source.events(EVERYTHING)) == 2
    stats = source.read_stats()
    assert stats.events_kept == 2
    assert stats.skipped_lines == 0


def test_a_file_saved_as_utf8_with_a_bom_is_read(
    tmp_path: Path, contract: Contract
) -> None:
    """An editor's UTF-8 byte-order mark is not a line the read has to excuse."""
    path = tmp_path / "api.jsonl"
    with path.open("w", encoding="utf-8-sig") as handle:
        handle.write(request_line() + "\n")
    source = make_source(path, contract)
    assert len(source.events(EVERYTHING)) == 1
    assert source.read_stats().skipped_non_json == 0


def test_a_utf16_file_over_the_limit_is_read_from_the_end(
    tmp_path: Path, contract: Contract
) -> None:
    """A UTF-16 tail is cut on its own line break, not in the middle of one."""
    first, second = request_line("req-00000001"), request_line("req-00000002")
    path = tmp_path / "api.jsonl"
    path.write_bytes((first + "\r\n" + second + "\r\n").encode("utf-16"))
    max_bytes = len(second.encode("utf-16-le")) + len("\r\n".encode("utf-16-le"))
    source = make_source(path, contract, max_bytes=max_bytes)
    found = source.events(EVERYTHING)
    assert [event.request_id for event in found] == ["req-00000002"]
    assert source.read_stats().truncated is True


def test_a_file_saved_as_utf16_big_endian_is_read(
    tmp_path: Path, contract: Contract
) -> None:
    """A big-endian UTF-16 file is read too, by the mark at its front."""
    path = tmp_path / "api.jsonl"
    text = request_line("req-00000001") + "\r\n"
    path.write_bytes(b"\xfe\xff" + text.encode("utf-16-be"))
    found = make_source(path, contract).events(EVERYTHING)
    assert [event.request_id for event in found] == ["req-00000001"]


def write_encoded_log(path: Path, lines: Iterable[str], encoding: str) -> bytes:
    """Write CRLF lines in one encoding, with a mark for the UTF-16 forms."""
    body = "".join(line + "\r\n" for line in lines)
    if encoding.startswith("utf-16"):
        mark = b"\xff\xfe" if encoding == "utf-16-le" else b"\xfe\xff"
        data = mark + body.encode(encoding)
    else:
        data = body.encode(encoding)
    path.write_bytes(data)
    return data


def record_offsets(
    data: bytes, lines: list[str], encoding: str
) -> list[tuple[int, str]]:
    """The byte offset and request id of each record in a written file."""
    body = "utf-8" if encoding == "utf-8-sig" else encoding
    offsets: list[tuple[int, str]] = []
    for line in lines:
        offsets.append(
            (data.index((line + "\r\n").encode(body)), json.loads(line)["request_id"])
        )
    return offsets


@pytest.mark.parametrize("encoding", ["utf-16-le", "utf-16-be"])
def test_a_utf16_cut_inside_a_break_keeps_the_whole_next_line(
    tmp_path: Path, contract: Contract, encoding: str
) -> None:
    """A cut on the second byte of a UTF-16 break keeps the whole next line.

    The limit is in bytes and may be odd; the window must align to a character
    before deciding whether its first line is a fragment.
    """
    first, second = request_line("req-00000001"), request_line("req-00000002")
    path = tmp_path / "api.jsonl"
    write_encoded_log(path, [first, second], encoding)
    max_bytes = len((second + "\r\n").encode(encoding)) + 1
    source = make_source(path, contract, max_bytes=max_bytes)
    found = source.events(EVERYTHING)
    assert [event.request_id for event in found] == ["req-00000002"]
    assert source.read_stats().truncated is True


@pytest.mark.parametrize("encoding", ["utf-16-le", "utf-16-be"])
def test_a_utf16_cut_inside_the_mark_keeps_the_first_line(
    tmp_path: Path, contract: Contract, encoding: str
) -> None:
    """A window that can only reach into the mark opens at the first line."""
    first = request_line("req-00000001", "2026-10-08T17:00:01.000Z")
    second = request_line("req-00000002", "2026-10-08T17:00:02.000Z")
    path = tmp_path / "api.jsonl"
    data = write_encoded_log(path, [first, second], encoding)
    source = make_source(path, contract, max_bytes=len(data) - 1)
    found = source.events(EVERYTHING)
    assert [event.request_id for event in found] == ["req-00000002", "req-00000001"]
    assert source.read_stats().truncated is True


@pytest.mark.parametrize("encoding", ["utf-8", "utf-8-sig", "utf-16-le", "utf-16-be"])
def test_every_record_inside_the_window_survives_any_cut(
    tmp_path: Path, contract: Contract, encoding: str
) -> None:
    """Sweep every byte cut: no record fully inside the window may be lost."""
    lines = [
        request_line(f"req-{number:08d}", f"2026-10-08T17:00:0{number}.000Z")
        for number in range(1, 5)
    ]
    path = tmp_path / "api.jsonl"
    data = write_encoded_log(path, lines, encoding)
    records = record_offsets(data, lines, encoding)
    for max_bytes in range(1, len(data) + 1):
        cut = len(data) - max_bytes
        expected = [
            request_id for offset, request_id in reversed(records) if offset >= cut
        ]
        found = make_source(path, contract, max_bytes=max_bytes).events(EVERYTHING)
        kept = [event.request_id for event in found]
        assert kept == expected, (encoding, max_bytes)
