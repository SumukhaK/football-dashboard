#!/usr/bin/env python3
"""
Generate deterministic test fixtures for the football dashboard console.
"""

import json
import random

SEED = 7


def generate_events() -> list[dict]:
    """Generate 24-hour of synthetic telemetry events."""
    random.seed(SEED)
    events = []
    for hour in range(24):
        for minute in range(60):
            events.append(
                {
                    "timestamp": f"{hour}:{minute:02d}:00Z",
                    "severity": (
                        "INFO" if hour < 12 else "WARNING" if hour < 18 else "ERROR"
                    ),
                    "message": f"Sample event at {hour}:{minute:02d}",
                    "logger": "backend.app.main",
                    "event": "http.request",
                    "request_id": f"req_{hour * 60 + minute}",
                    "trace_id": f"trace_{hour * 60 + minute}",
                    "service": "football-api",
                    "revision": f"rev_{hour}",
                    "api_version": "2.0.0",
                    "contract_version": "1.0.0",
                    "attributes": {
                        "method": "GET",
                        "route": "/v2/teams/{team}/outlook",
                        "status": "200",
                        "duration_ms": random.randint(50, 800),
                        "error_code": None,
                        "user_ref": None,
                    },
                }
            )
    return events


def generate_traces() -> list[dict]:
    """Generate 10 trace records."""
    random.seed(SEED)
    traces = []
    for i in range(10):
        spans = [
            {
                "name": "http.request",
                "duration_ms": random.randint(50, 3000),
                "status": "200",
            },
            {
                "name": "assistant.retrieve",
                "duration_ms": random.randint(100, 500),
                "operation": "embedding + vector search",
            },
            {
                "name": "assistant.generate",
                "duration_ms": random.randint(200, 1500),
                "operation": "model inference",
                "attributes": {"round": i + 1},
            },
            {
                "name": "assistant.tool",
                "duration_ms": random.randint(50, 200),
                "operation": "call to ollama_chat",
            },
        ]
        traces.append({"trace_id": f"trace_{i+1:04d}", "spans": spans})
    return traces


def generate_error_groups() -> list[dict]:
    """Generate 4 error category groups."""
    return [
        {
            "group_id": "out_of_memory",
            "exception_type": "OutOfMemoryError",
            "message": "Out of memory during batch processing",
            "count": 12,
            "first_seen": "2026-10-08T18:00:00Z",
            "last_seen": "2026-10-09T06:00:00Z",
        },
        {
            "group_id": "container_exit",
            "exception_type": "ContainerExitError",
            "message": "Container exited due to resource limits",
            "count": 8,
            "first_seen": "2026-10-08T19:00:00Z",
            "last_seen": "2026-10-09T07:00:00Z",
        },
        {
            "group_id": "instance_started",
            "exception_type": "InstanceStartFailed",
            "message": "Instance failed to start on deployment",
            "count": 5,
            "first_seen": "2026-10-08T20:00:00Z",
            "last_seen": "2026-10-09T01:00:00Z",
        },
        {
            "group_id": "platform_event",
            "exception_type": "PlatformEvent",
            "message": "Platform-level infrastructure event",
            "count": 3,
            "first_seen": "2026-10-08T21:00:00Z",
            "last_seen": "2026-10-09T03:00:00Z",
        },
    ]


def generate_platform_events() -> list[dict]:
    """Generate platform-level events."""
    return [
        {
            "kind": "out_of_memory",
            "outcome": "warning",
            "timestamp": "2026-10-08T18:30:00Z",
        },
        {
            "kind": "container_exit",
            "outcome": "error",
            "timestamp": "2026-10-08T19:15:00Z",
        },
        {
            "kind": "instance_started",
            "outcome": "ok",
            "timestamp": "2026-10-08T20:00:00Z",
        },
        {
            "kind": "platform_event",
            "outcome": "info",
            "timestamp": "2026-10-08T21:00:00Z",
        },
    ]


def main() -> None:
    """Main entry point: generates all fixture files."""
    events = generate_events()
    with open("fixtures/events.jsonl", "w") as f:
        f.writelines([json.dumps(ev) + "\n" for ev in events])
    print(f"Generated {len(events)} events in fixtures/events.jsonl")

    traces = generate_traces()
    with open("fixtures/traces.json", "w") as f:
        json.dump(traces, f, indent=2)
    print(f"Generated {len(traces)} traces in fixtures/traces.json")

    error_groups = generate_error_groups()
    with open("fixtures/error_groups.json", "w") as f:
        json.dump(error_groups, f, indent=2)
    print(f"Generated {len(error_groups)} error groups in fixtures/error_groups.json")

    platform_events = generate_platform_events()
    with open("fixtures/platform_events.json", "w") as f:
        json.dump(platform_events, f, indent=2)
    print(
        f"Generated {len(platform_events)} platform events in fixtures/platform_events.json"
    )

    print("All fixtures generated successfully!")


if __name__ == "__main__":
    main()
