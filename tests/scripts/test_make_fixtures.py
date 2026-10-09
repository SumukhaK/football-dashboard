"""Tests for fixture generation."""

import re
from pathlib import Path

from scripts.make_fixtures import main


def test_make_fixtures_creates_all_files(tmp_path: Path) -> None:
    """Running make_fixtures should create all expected fixture files."""
    fixtures_dir = tmp_path / "fixtures"
    main(fixtures_dir)

    assert (fixtures_dir / "events.jsonl").exists()
    assert (fixtures_dir / "traces.json").exists()
    assert (fixtures_dir / "error_groups.json").exists()
    assert (fixtures_dir / "platform_events.json").exists()


def test_fixtures_are_deterministic(tmp_path: Path) -> None:
    """Running make_fixtures twice should produce byte-identical files."""
    fixtures_dir = tmp_path / "fixtures"
    main(fixtures_dir)
    first_run = {
        f.name: (fixtures_dir / f.name).read_bytes() for f in fixtures_dir.glob("*")
    }
    main(fixtures_dir)
    for name, first in first_run.items():
        second = (fixtures_dir / name).read_bytes()
        assert first == second, f"File {name} is not deterministic"


def test_events_jsonl_contains_events() -> None:
    """events.jsonl should contain valid JSON lines."""
    from scripts.make_fixtures import generate_events

    events = generate_events()
    assert len(events) > 0  # Should have events (24 hours * 60 minutes = 1440 lines)

    # Test each line is valid JSON
    for event in events:
        assert "timestamp" in event
        assert "severity" in event
        assert "event" in event
        assert event["severity"] in ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


def test_traces_json_has_10_traces() -> None:
    """traces.json should contain 10 traces."""
    from scripts.make_fixtures import generate_traces

    traces = generate_traces()
    assert len(traces) == 10

    for trace in traces:
        assert "trace_id" in trace
        assert "spans" in trace
        assert len(trace["spans"]) > 0


def test_error_groups_json_has_4_groups() -> None:
    """error_groups.json should contain 4 error groups."""
    from scripts.make_fixtures import generate_error_groups

    groups = generate_error_groups()
    assert len(groups) == 4

    for group in groups:
        assert "group_id" in group
        assert "exception_type" in group
        assert "count" in group


def test_platform_events_json_has_platform_events() -> None:
    """platform_events.json should contain platform events."""
    from scripts.make_fixtures import generate_platform_events

    events = generate_platform_events()
    assert (
        len(events) == 4
    )  # out_of_memory, container_exit, instance_started, platform_event

    for event in events:
        assert "kind" in event
        assert "outcome" in event
        assert "timestamp" in event


def test_events_jsonl_validates_against_contract(tmp_path: Path) -> None:
    """Every generated event line must be valid against contract/telemetry-events.json."""
    import json

    from scripts.make_fixtures import generate_events

    contract_path = (
        Path(__file__).parent.parent.parent / "contract" / "telemetry-events.json"
    )
    contract = json.loads(contract_path.read_text())

    events = generate_events()
    assert len(events) == 1440

    required = contract["events"]
    common = contract["common_fields"]
    forbidden = contract["forbidden_attribute_names"]

    seen_events: set[str] = set()
    hex32 = re.compile(r"^[0-9a-f]{32}$")
    hex16 = re.compile(r"^[0-9a-f]{16}$")

    for ev in events:
        # All common fields must be present
        for field in common:
            assert field in ev, f"missing common field {field!r}"

        # Required fields for the event type must be present
        ev_type = ev["event"]
        seen_events.add(ev_type)
        for field in required[ev_type]["required"]:
            assert (
                field in ev["attributes"]
            ), f"{ev_type}: missing required attribute {field!r}"

        # status must be an int where present
        if "status" in ev["attributes"]:
            assert isinstance(
                ev["attributes"]["status"], int
            ), f"{ev_type}: status must be int, got {type(ev['attributes']['status']).__name__}"

        # http.request: severity follows status, error_code rules
        if ev_type == "http.request":
            status = ev["attributes"]["status"]
            severity = ev["severity"]
            error_code = ev["attributes"]["error_code"]
            expected_severity = (
                "ERROR" if status >= 500 else "WARNING" if status >= 400 else "INFO"
            )
            assert (
                severity == expected_severity
            ), f"http.request {status}: severity {severity!r} != {expected_severity!r}"
            if status >= 400:
                assert (
                    error_code is not None
                ), f"http.request {status}: error_code must be set"
            else:
                assert (
                    error_code is None
                ), f"http.request {status}: error_code must be None"

        # trace_id = 32-hex, spanId = 16-hex
        tid = ev["trace_id"]
        assert hex32.match(tid), f"{ev_type}: trace_id not 32-hex: {tid!r}"
        sid = ev["logging.googleapis.com/spanId"]
        assert hex16.match(sid), f"{ev_type}: spanId not 16-hex: {sid!r}"

        # severity must be a known level
        assert ev["severity"] in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}

        # forbidden attribute names must not appear in attributes
        for fname in forbidden:
            assert (
                fname not in ev["attributes"]
            ), f"{ev_type}: forbidden attribute {fname!r}"

    # Every event type must appear at least once
    for ev_type in required:
        assert ev_type in seen_events, f"event type {ev_type!r} never generated"
