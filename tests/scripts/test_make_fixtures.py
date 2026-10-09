"""Tests for fixture generation."""

import tempfile
from pathlib import Path

from scripts.make_fixtures import main


def test_make_fixtures_creates_all_files() -> None:
    """Running make_fixtures should create all expected fixture files."""
    # Clean up any existing fixtures
    fixtures_dir = Path("fixtures")
    if fixtures_dir.exists():
        for f in fixtures_dir.glob("*.json"):
            f.unlink()
        for f in fixtures_dir.glob("*.jsonl"):
            f.unlink()

    # Run the fixture generator
    with tempfile.TemporaryDirectory():
        Path("fixtures").mkdir(exist_ok=True)

        try:
            main()

            # Check all files were created
            assert Path("fixtures/events.jsonl").exists()
            assert Path("fixtures/traces.json").exists()
            assert Path("fixtures/error_groups.json").exists()
            assert Path("fixtures/platform_events.json").exists()
        finally:
            # Cleanup
            for f in fixtures_dir.glob("*.json"):
                f.unlink()
            for f in fixtures_dir.glob("*.jsonl"):
                f.unlink()


def test_fixtures_are_deterministic() -> None:
    """Running make_fixtures twice should produce byte-identical files."""
    fixtures_dir = Path("fixtures")

    if fixtures_dir.exists():
        for f in fixtures_dir.glob("*.json"):
            f.unlink()
        for f in fixtures_dir.glob("*.jsonl"):
            f.unlink()

    try:
        main()

        # Save first run checksums
        first_run = {}
        for f in fixtures_dir.glob("*"):
            first_run[f.name] = f.read_bytes()

        # Run again
        main()

        # Compare with second run
        for f in fixtures_dir.glob("*"):
            second_run = f.read_bytes()
            assert (
                first_run[f.name] == second_run
            ), f"File {f.name} is not deterministic"

    finally:
        # Cleanup
        for f in fixtures_dir.glob("*.json"):
            f.unlink()
        for f in fixtures_dir.glob("*.jsonl"):
            f.unlink()


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
