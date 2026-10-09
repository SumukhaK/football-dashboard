"""Tests that the sample data tells the stories the console's pages need."""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

import pytest

from scripts.make_fixtures import build

OUTSIDE_REQUESTS = {"component.load", "refresh.run", "data.freshness"}
SPAN_NAME = re.compile(
    r"POST /v2/assistant/chat|assistant\.(route|retrieve|embed|generate)"
    r"|assistant\.tool\.[a-z_]+|dependency\.[a-z_]+"
)


@pytest.fixture(scope="module")
def files() -> dict[str, Any]:
    """One fresh generation, shared by the tests in this module."""
    return build()


@pytest.fixture(scope="module")
def lines(files: dict[str, Any]) -> list[dict[str, Any]]:
    """The generated log lines."""
    events: list[dict[str, Any]] = files["events.jsonl"]
    return events


@pytest.fixture(scope="module")
def requests(lines: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Lines grouped by request ID."""
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for line in lines:
        if line["request_id"] is not None:
            grouped[line["request_id"]].append(line)
    return grouped


def _events(group: list[dict[str, Any]], name: str) -> list[dict[str, Any]]:
    return [line for line in group if line["event"] == name]


def test_background_lines_have_no_request(lines: list[dict[str, Any]]) -> None:
    for line in lines:
        if line["event"] in OUTSIDE_REQUESTS:
            assert line["request_id"] is None


def test_each_request_has_one_closing_line_and_one_trace(
    requests: dict[str, list[dict[str, Any]]],
) -> None:
    for group in requests.values():
        (closing,) = _events(group, "http.request")
        assert closing is group[-1] or closing["timestamp"] == group[-1]["timestamp"]
        assert {line["trace_id"] for line in group} == {closing["trace_id"]}


def test_every_chat_has_its_trace(
    files: dict[str, Any], lines: list[dict[str, Any]]
) -> None:
    chats = [
        line
        for line in lines
        if line["event"] == "http.request"
        and line["attributes"]["route"] == "/v2/assistant/chat"
    ]
    traces = {trace["trace_id"]: trace for trace in files["traces.json"]}
    assert len(chats) == len(traces) == 10
    assert {chat["trace_id"] for chat in chats} == set(traces)


def test_trace_spans_follow_the_contract(files: dict[str, Any]) -> None:
    for trace in files["traces.json"]:
        ids = {span["span_id"] for span in trace["spans"]}
        roots = [span for span in trace["spans"] if span["parent_id"] is None]
        assert len(roots) == 1 and roots[0]["name"] == "POST /v2/assistant/chat"
        for span in trace["spans"]:
            assert SPAN_NAME.fullmatch(span["name"]), span["name"]
            assert re.fullmatch(r"[0-9a-f]{16}", span["span_id"])
            assert span["parent_id"] is None or span["parent_id"] in ids
            assert span["start"] <= span["end"]
            if span["name"] == "assistant.generate":
                assert isinstance(span["attributes"]["round"], int)


def test_chat_lines_point_at_spans_in_their_trace(
    files: dict[str, Any], requests: dict[str, list[dict[str, Any]]]
) -> None:
    spans = {
        trace["trace_id"]: {span["span_id"] for span in trace["spans"]}
        for trace in files["traces.json"]
    }
    for group in requests.values():
        trace_id = group[0]["trace_id"]
        if trace_id in spans:
            for line in group:
                assert line["logging.googleapis.com/spanId"] in spans[trace_id]


def test_retry_then_success(requests: dict[str, list[dict[str, Any]]]) -> None:
    matches = [
        group
        for group in requests.values()
        if len(_events(group, "retry")) == 2 and _events(group, "assistant.answer")
    ]
    assert len(matches) == 1
    calls = _events(matches[0], "dependency.call")
    chat_calls = [c for c in calls if c["attributes"]["dependency"] == "ollama_chat"]
    assert [c["attributes"]["attempt"] for c in chat_calls] == [1, 2, 3]
    assert chat_calls[-1]["attributes"]["status"] == "ok"


def test_retry_is_a_span_event(files: dict[str, Any]) -> None:
    events = [
        event
        for trace in files["traces.json"]
        for span in trace["spans"]
        for event in span["events"]
    ]
    assert events and all(event["name"] == "retry" for event in events)


def test_a_chat_gives_up(requests: dict[str, list[dict[str, Any]]]) -> None:
    gave_up = [
        group
        for group in requests.values()
        if _events(group, "retry")
        and _events(group, "http.request")[0]["attributes"]["status"] == 503
    ]
    assert len(gave_up) == 1
    calls = _events(gave_up[0], "dependency.call")
    assert all(call["attributes"]["status"] != "ok" for call in calls[1:])


def test_failed_refresh_then_fallback(lines: list[dict[str, Any]]) -> None:
    runs = [line for line in lines if line["event"] == "refresh.run"]
    assert [run["attributes"]["status"] for run in runs] == ["failed", "ok"]
    after = [line for line in lines if line["timestamp"] >= runs[0]["timestamp"]]
    fallback = next(line for line in after if line["event"] == "fallback")
    assert fallback["attributes"]["from_path"] == "fresh_match_data"
    assert fallback["attributes"]["to_path"] == "previous_match_data"


def test_rate_limit_burst_from_one_client(
    requests: dict[str, list[dict[str, Any]]],
) -> None:
    rejected = [
        group for group in requests.values() if _events(group, "ratelimit.rejected")
    ]
    assert len(rejected) >= 20
    clients = {
        _events(g, "ratelimit.rejected")[0]["attributes"]["client_ref"]
        for g in rejected
    }
    assert len(clients) == 1
    for group in rejected:
        assert _events(group, "http.request")[0]["attributes"]["status"] == 429


def test_failed_sign_ins_end_in_lockout(lines: list[dict[str, Any]]) -> None:
    sign_ins = [
        line["attributes"]
        for line in lines
        if line["event"] == "auth.event" and line["attributes"]["action"] == "sign_in"
    ]
    locked = next(i for i, a in enumerate(sign_ins) if a["outcome"] == "locked_out")
    user = sign_ins[locked]["user_ref"]
    before = [a["outcome"] for a in sign_ins[:locked] if a.get("user_ref") == user]
    assert before[-5:] == ["failed"] * 5


def test_two_startups_with_the_assistant_failing_once(
    lines: list[dict[str, Any]],
) -> None:
    loads = [line for line in lines if line["event"] == "component.load"]
    by_revision: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for line in loads:
        by_revision[line["revision"]].append(line["attributes"])
    assert len(by_revision) == 2
    failed = [
        revision
        for revision, attributes in by_revision.items()
        if {"component": "assistant", "status": "failed"}.items()
        <= next(a for a in attributes if a["component"] == "assistant").items()
    ]
    assert len(failed) == 1
    for attributes in by_revision.values():
        assert len({a["component"] for a in attributes}) == 9


def test_error_groups_match_the_lines(
    files: dict[str, Any], lines: list[dict[str, Any]]
) -> None:
    server_errors = [
        line
        for line in lines
        if line["event"] == "app.crash"
        or (line["event"] == "app.error" and line["attributes"]["status"] >= 500)
    ]
    groups = files["error_groups.json"]
    assert len(groups) == 4
    assert sum(group["count"] for group in groups) == len(server_errors)
    assert {g["exception_type"] for g in groups} == {
        line["exception_type"] for line in server_errors
    }


def test_platform_events(files: dict[str, Any]) -> None:
    kinds = [event["kind"] for event in files["platform_events.json"]]
    assert kinds.count("instance_started") == 2
    assert "out_of_memory" in kinds and "container_exit" in kinds
    assert set(kinds) <= {
        "out_of_memory",
        "startup_failed",
        "container_exit",
        "instance_started",
    }
