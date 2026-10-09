#!/usr/bin/env python3
"""
Generate deterministic test fixtures for the football dashboard console.
"""

import json
import random
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

SEED = 7

# Weighted distribution of event types (sums to 100); determines how often each
# event type appears across the 1440 generated lines.
EVENT_WEIGHTS = {
    "http.request": 50,
    "assistant.tool": 7,
    "assistant.answer": 6,
    "dependency.call": 6,
    "app.error": 5,
    "auth.event": 5,
    "component.load": 4,
    "component.degraded": 4,
    "refresh.run": 4,
    "data.freshness": 3,
    "retry": 3,
    "ratelimit.rejected": 2,
    "app.crash": 2,
    "fallback": 2,
    "assistant.abstain": 2,
    "guardrail.event": 1,
}

# Routes exercised across events (placeholder parameters for the console router).
ROUTES = [
    "/v2/teams/{team}/outlook",
    "/v2/matches/{match_id}/summary",
    "/v2/players/{player_id}/stats",
    "/v2/competitions/{comp_id}/standings",
    "/v2/fixtures",
    "/v2/admin/settings",
    "/v2/health",
    "/v2/metrics",
    "/v2/auth/login",
    "/v2/reports",
]

METHODS = ["GET", "POST", "PUT", "DELETE", "PATCH"]

# Component names taken verbatim from contract/telemetry-events.json.
COMPONENTS = [
    "prediction_model",
    "prediction_model_v1",
    "explanation",
    "assistant",
    "season_history",
    "season_outlook",
    "fixtures",
    "match_history",
    "goals_model",
]

SERVICE = "football-api"
API_VERSION = "2.0.0"
CONTRACT_VERSION = "1.0.0"
LOGGER = "backend.app.main"


def _hex_trace_id(rng: random.Random) -> str:
    """Return a 32-hex (128-bit) trace ID."""
    return f"{rng.getrandbits(128):032x}"


def _hex_span_id(rng: random.Random) -> str:
    """Return a 16-hex (64-bit) span ID."""
    return f"{rng.getrandbits(64):016x}"


def _status_severity(status: int) -> str:
    """Severity follows the HTTP status per the telemetry contract."""
    if status >= 500:
        return "ERROR"
    if status >= 400:
        return "WARNING"
    return "INFO"


def _make_http_request(rng: random.Random) -> tuple[dict[str, Any], str, str]:
    status = rng.choices(
        [200, 201, 204, 301, 400, 404, 422, 500, 502, 503],
        weights=[50, 10, 5, 5, 4, 4, 4, 3, 3, 3],
    )[0]
    method = rng.choice(METHODS)
    route = rng.choice(ROUTES)
    duration_ms = rng.randint(5, 3000)
    attributes = {
        "method": method,
        "route": route,
        "status": status,
        "duration_ms": duration_ms,
        "error_code": None if status < 400 else f"HTTP_{status}",
        "user_ref": f"user_{rng.randrange(100)}" if rng.random() < 0.3 else None,
    }
    return (
        attributes,
        _status_severity(status),
        f"{method} {route} completed with {status} in {duration_ms} ms",
    )


def _make_app_error(rng: random.Random) -> tuple[dict[str, Any], str, str]:
    status = rng.choice([400, 404, 422, 500, 502, 503])
    exception_type = rng.choice(
        [
            "ValueError",
            "DatabaseError",
            "TimeoutError",
            "JSONDecodeError",
            "KeyError",
            "PermissionError",
        ],
    )
    error_code = rng.choice(
        [
            "VALIDATION_ERROR",
            "RECORD_NOT_FOUND",
            "RATE_LIMIT_EXCEEDED",
            "INTERNAL_SERVER_ERROR",
            "DATABASE_CONNECTION_FAILED",
            "UPSTREAM_TIMEOUT",
        ],
    )
    route = rng.choice(ROUTES)
    attributes = {
        "route": route,
        "status": status,
        "error_code": error_code,
        "exception_type": exception_type,
    }
    return (
        attributes,
        _status_severity(status),
        f"{exception_type} occurred while handling {route}",
    )


def _make_app_crash(rng: random.Random) -> tuple[dict[str, Any], str, str]:
    exception_type = rng.choice(
        ["OutOfMemoryError", "SegmentationFault", "KilledError", "PanicError"],
    )
    route = rng.choice(ROUTES)
    attributes = {"route": route, "exception_type": exception_type}
    return attributes, "ERROR", f"Application crash on {route}: {exception_type}"


def _make_component_load(rng: random.Random) -> tuple[dict[str, Any], str, str]:
    component = rng.choice(COMPONENTS)
    status = rng.choices([200, 500, 503], weights=[80, 12, 8])[0]
    duration_ms = rng.randint(50, 8000)
    reason = (
        "loaded"
        if status == 200
        else rng.choice(["fail", "cache_miss", "resource_unavailable"])
    )
    attributes = {
        "component": component,
        "status": status,
        "duration_ms": duration_ms,
        "reason": reason,
    }
    return (
        attributes,
        _status_severity(status),
        f"Component {component} load {'success' if status == 200 else 'failed'} ({reason}) in {duration_ms} ms",
    )


def _make_component_degraded(rng: random.Random) -> tuple[dict[str, Any], str, str]:
    component = rng.choice(COMPONENTS)
    attributes = {"component": component, "route": rng.choice(ROUTES)}
    return (
        attributes,
        "WARNING",
        f"Component {component} degraded on {attributes['route']}",
    )


def _make_ratelimit_rejected(rng: random.Random) -> tuple[dict[str, Any], str, str]:
    route = rng.choice(ROUTES)
    attributes = {
        "route": route,
        "client_ref": f"client_{rng.randrange(50)}",
        "retry_after_s": rng.randint(1, 300),
    }
    return (
        attributes,
        "WARNING",
        f"Rate limit rejected for {route} - retry after {attributes['retry_after_s']} s",
    )


def _make_auth_event(rng: random.Random) -> tuple[dict[str, Any], str, str]:
    action = rng.choice(
        ["login", "logout", "token_refresh", "permission_grant", "api_key_rotate"]
    )
    outcome = rng.choices(["success", "denied", "failed"], weights=[70, 20, 10])[0]
    attributes = {
        "action": action,
        "outcome": outcome,
        "user_ref": f"user_{rng.randrange(100)}" if outcome == "success" else None,
    }
    severity = "ERROR" if outcome in ("denied", "failed") else "INFO"
    return attributes, severity, f"Auth {action} {outcome}"


def _make_refresh_run(rng: random.Random) -> tuple[dict[str, Any], str, str]:
    dataset = rng.choice(["fixtures", "standings", "player_stats", "season_outlook"])
    status = rng.choices([200, 500], weights=[85, 15])[0]
    error = None if status == 200 else rng.choice(["timeout", "upstream_error"])
    duration_ms = rng.randint(100, 10000)
    attributes = {
        "status": status,
        "duration_ms": duration_ms,
        "dataset": dataset,
        "error": error,
    }
    return (
        attributes,
        "ERROR" if error else "INFO",
        f"Refresh of {dataset} {'failed: ' + error if error else 'completed'} in {duration_ms} ms",
    )


def generate_events() -> list[dict[str, Any]]:
    """Generate a realistic, contract-valid mix of telemetry events over 24 hours.

    Every event type in contract/telemetry-events.json is exercised; HTTP
    statuses are integers and severity follows the status (INFO/2xx-3xx,
    WARNING/4xx, ERROR/5xx); error_code is set on 4xx/5xx lines; trace IDs
    are 32-hex and span IDs are 16-hex. Output is deterministic under seed 7.
    """
    rng = random.Random(SEED)
    types = []
    for t, w in EVENT_WEIGHTS.items():
        types += [t] * w

    events = []
    start_time = datetime(2026, 10, 8, 0, 0, 0, tzinfo=UTC)

    for i in range(1440):
        event_time = start_time + timedelta(minutes=i)
        timestamp = event_time.strftime("%Y-%m-%dT%H:%M:%S.000Z")
        event_type = rng.choice(types)
        attributes, severity, message = _EVENT_FACTORIES[event_type](rng)
        events.append(
            {
                "timestamp": timestamp,
                "severity": severity,
                "message": message,
                "logger": LOGGER,
                "event": event_type,
                "request_id": f"req_{i:04d}",
                "logging.googleapis.com/trace": (
                    _hex_trace_id(rng) if rng.random() > 0.1 else None
                ),
                "logging.googleapis.com/spanId": _hex_span_id(rng),
                "trace_id": _hex_trace_id(rng),
                "service": SERVICE,
                "revision": f"rev_{rng.randrange(1, 5)}",
                "api_version": API_VERSION,
                "contract_version": CONTRACT_VERSION,
                "attributes": attributes,
            }
        )

    return events


def _make_data_freshness(rng: random.Random) -> tuple[dict[str, Any], str, str]:
    competition = rng.choice(
        ["premier_league", "la_liga", "serie_a", "bundesliga", "champions_league"]
    )
    matches_through = rng.randint(10, 380)
    age_hours = rng.randint(0, 72)
    attributes = {
        "competition": competition,
        "matches_through": matches_through,
        "age_hours": age_hours,
    }
    return (
        attributes,
        "WARNING" if age_hours > 24 else "INFO",
        f"Data freshness {competition}: {age_hours} h old ({matches_through} matches)",
    )


def _make_assistant_answer(rng: random.Random) -> tuple[dict[str, Any], str, str]:
    path = rng.choice(
        ["/v2/chat/answer", "/v2/conversation/complete", "/v2/insight/generate"]
    )
    model = rng.choice(["football-v1", "football-v1-pro", "football-v1.5"])
    attributes = {
        "path": path,
        "question_chars": rng.randint(10, 2000),
        "retrieved_count": rng.randint(0, 20),
        "top_score": round(rng.random(), 4),
        "confidence": round(rng.random(), 4),
        "tool_rounds": rng.randint(0, 8),
        "model": model,
        "prompt_tokens": rng.randint(100, 20000),
        "completion_tokens": rng.randint(20, 2000),
        "cost_usd": round(rng.random() * 0.05, 4),
        "duration_ms": rng.randint(50, 5000),
    }
    return (
        attributes,
        "INFO",
        f"Assistant answer on {path} (confidence {attributes['confidence']:.2f})",
    )


def _make_assistant_tool(rng: random.Random) -> tuple[dict[str, Any], str, str]:
    tool = rng.choice(["vector_search", "retrieve", "call_model", "parse_json"])
    status = rng.choices([200, 500], weights=[85, 15])[0]
    error = (
        None
        if status == 200
        else rng.choice(["TOOL_TIMEOUT", "PARSER_ERROR", "MODEL_UNAVAILABLE"])
    )
    duration_ms = rng.randint(10, 3000)
    attributes = {
        "tool": tool,
        "status": status,
        "duration_ms": duration_ms,
        "error": error,
    }
    return (
        attributes,
        "ERROR" if status >= 500 else "INFO",
        f"Tool {tool} {status}{' ' + error if error else ''}",
    )


def _make_assistant_abstain(rng: random.Random) -> tuple[dict[str, Any], str, str]:
    reason = rng.choice(["uncertain", "ambiguous", "out_of_scope", "low_confidence"])
    attributes = {"reason": reason}
    return attributes, "INFO", f"Assistant abstained from answering: {reason}"


def _make_dependency_call(rng: random.Random) -> tuple[dict[str, Any], str, str]:
    dependency = rng.choice(["transfermarkt", "opta", "weather_api", "odds_provider"])
    operation = rng.choice(["get_stats", "get_lineups", "get_freshness", "push_cache"])
    http_status = rng.choices([200, 404, 500, 503], weights=[75, 10, 10, 5])[0]
    attempt = rng.randint(1, 4)
    attributes = {
        "dependency": dependency,
        "operation": operation,
        "status": 1 if http_status == 200 else 0,
        "http_status": http_status,
        "attempt": attempt,
        "duration_ms": rng.randint(10, 2000),
    }
    return (
        attributes,
        _status_severity(http_status),
        f"{dependency}.{operation} attempt {attempt} http={http_status}",
    )


def _make_retry(rng: random.Random) -> tuple[dict[str, Any], str, str]:
    dependency = rng.choice(["transfermarkt", "opta", "weather_api"])
    operation = rng.choice(["get_stats", "get_lineups", "get_freshness"])
    cause = rng.choice(["timeout", "connection_refused", "http_5xx", "rate_limit"])
    attributes = {
        "dependency": dependency,
        "operation": operation,
        "attempt": rng.randint(2, 4),
        "max_attempts": rng.randint(3, 5),
        "wait_ms": rng.choice([1000, 2000, 5000, 10000]),
        "cause": cause,
    }
    return (
        attributes,
        "WARNING",
        f"Retrying {dependency}.{operation} attempt {attributes['attempt']}/{attributes['max_attempts']} ({cause})",
    )


def _make_fallback(rng: random.Random) -> tuple[dict[str, Any], str, str]:
    from_paths = ["/v2/matches/{match_id}/summary", "/v2/players/{player_id}/stats"]
    to_paths = ["/v2/teams/{team}/outlook", "/v2/competitions/{comp_id}/standings"]
    cause = rng.choice(["upstream_timeout", "upstream_5xx", "cache_miss"])
    from_path = rng.choice(from_paths)
    to_path = rng.choice(to_paths)
    attributes = {"from_path": from_path, "to_path": to_path, "cause": cause}
    return attributes, "WARNING", f"Fallback {from_path} -> {to_path} ({cause})"


def _make_guardrail_event(rng: random.Random) -> tuple[dict[str, Any], str, str]:
    kind = rng.choice(["pii_detected", "policy_violation", "rate_limit"])
    outcome = rng.choices(["blocked", "logged"], weights=[30, 70])[0]
    attributes = {"kind": kind, "outcome": outcome}
    return (
        attributes,
        "ERROR" if outcome == "blocked" else "INFO",
        f"Guardrail {kind} {outcome}",
    )


_EVENT_FACTORIES = {
    "http.request": _make_http_request,
    "app.error": _make_app_error,
    "app.crash": _make_app_crash,
    "component.load": _make_component_load,
    "component.degraded": _make_component_degraded,
    "ratelimit.rejected": _make_ratelimit_rejected,
    "auth.event": _make_auth_event,
    "refresh.run": _make_refresh_run,
    "data.freshness": _make_data_freshness,
    "assistant.answer": _make_assistant_answer,
    "assistant.tool": _make_assistant_tool,
    "assistant.abstain": _make_assistant_abstain,
    "dependency.call": _make_dependency_call,
    "retry": _make_retry,
    "fallback": _make_fallback,
    "guardrail.event": _make_guardrail_event,
}


def generate_traces() -> list[dict[str, Any]]:
    """Generate 10 trace records."""
    random.seed(SEED)
    traces = []

    for i in range(10):
        spans = [
            {
                "span_id": f"span_{i * 4:04d}",
                "parent_id": None,
                "name": "http.request",
                "start": "2026-10-08T00:00:00Z",
                "end": "2026-10-08T00:00:50Z",
                "duration_ms": random.randint(50, 3000),
                "status": "200",
                "attributes": {
                    "method": "GET",
                    "route": "/v2/teams/{team}/outlook",
                    "status": "200",
                },
            },
            {
                "span_id": f"span_{i * 4 + 1:04d}",
                "parent_id": f"span_{i * 4:04d}",
                "name": "assistant.retrieve",
                "start": "2026-10-08T00:00:50Z",
                "end": "2026-10-08T00:01:00Z",
                "duration_ms": random.randint(100, 500),
                "operation": "embedding + vector search",
            },
            {
                "span_id": f"span_{i * 4 + 2:04d}",
                "parent_id": f"span_{i * 4:04d}",
                "name": "assistant.generate",
                "start": "2026-10-08T00:01:00Z",
                "end": "2026-10-08T00:01:20Z",
                "duration_ms": random.randint(200, 1500),
                "operation": "model inference",
                "attributes": {"round": i + 1},
            },
            {
                "span_id": f"span_{i * 4 + 3:04d}",
                "parent_id": f"span_{i * 4:04d}",
                "name": "assistant.tool",
                "start": "2026-10-08T00:01:20Z",
                "end": "2026-10-08T00:01:35Z",
                "duration_ms": random.randint(50, 200),
                "operation": "call to ollama_chat",
            },
        ]
        traces.append({"trace_id": f"trace_{i+1:04d}", "spans": spans})
    return traces


def generate_error_groups() -> list[dict[str, Any]]:
    """Generate 4 error category groups."""
    return [
        {
            "group_id": "out_of_memory",
            "exception_type": "OutOfMemoryError",
            "message": "Out of memory during batch processing",
            "count": 12,
            "first_seen": "2026-10-08T18:00:00Z",
            "last_seen": "2026-10-09T06:00:00Z",
            "affected_routes": ("/v2/teams/{team}/outlook", "/v2/fixtures"),
        },
        {
            "group_id": "container_exit",
            "exception_type": "ContainerExitError",
            "message": "Container exited due to resource limits",
            "count": 8,
            "first_seen": "2026-10-08T19:00:00Z",
            "last_seen": "2026-10-09T07:00:00Z",
            "affected_routes": ("/v2/admin",),
        },
        {
            "group_id": "instance_started",
            "exception_type": "InstanceStartFailed",
            "message": "Instance failed to start on deployment",
            "count": 5,
            "first_seen": "2026-10-08T20:00:00Z",
            "last_seen": "2026-10-09T01:00:00Z",
            "affected_routes": ("/v2/health",),
        },
        {
            "group_id": "platform_event",
            "exception_type": "PlatformEvent",
            "message": "Platform-level infrastructure event",
            "count": 3,
            "first_seen": "2026-10-08T21:00:00Z",
            "last_seen": "2026-10-09T03:00:00Z",
            "affected_routes": ("/v2/metrics",),
        },
    ]


def generate_platform_events() -> list[dict[str, Any]]:
    """Generate platform-level events."""
    return [
        {
            "timestamp": "2026-10-08T18:30:00Z",
            "kind": "out_of_memory",
            "outcome": "warning",
            "revision": "rev_1",
            "message": "Out of memory during batch processing",
        },
        {
            "timestamp": "2026-10-08T19:15:00Z",
            "kind": "container_exit",
            "outcome": "error",
            "revision": "rev_1",
            "message": "Container exited due to resource limits",
        },
        {
            "timestamp": "2026-10-08T20:00:00Z",
            "kind": "instance_started",
            "outcome": "ok",
            "revision": "rev_2",
            "message": "Instance successfully started on new revision",
        },
        {
            "timestamp": "2026-10-08T21:00:00Z",
            "kind": "platform_event",
            "outcome": "info",
            "revision": "rev_2",
            "message": "Platform-level infrastructure event",
        },
    ]


def main(output_dir: Path = Path("fixtures")) -> None:
    """Main entry point: generates all fixture files."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    events = generate_events()
    with open(output_dir / "events.jsonl", "w", newline="") as f:
        f.writelines([json.dumps(ev) + "\n" for ev in events])
    print(f"Generated {len(events)} events in fixtures/events.jsonl")

    traces = generate_traces()
    with open(output_dir / "traces.json", "w", newline="") as f:
        json.dump(traces, f, indent=2)
    print(f"Generated {len(traces)} traces in fixtures/traces.json")

    error_groups = generate_error_groups()
    with open(output_dir / "error_groups.json", "w", newline="") as f:
        json.dump(error_groups, f, indent=2)
    print(f"Generated {len(error_groups)} error groups in fixtures/error_groups.json")

    platform_events = generate_platform_events()
    with open(output_dir / "platform_events.json", "w", newline="") as f:
        json.dump(platform_events, f, indent=2)
    print(
        f"Generated {len(platform_events)} platform events in fixtures/platform_events.json"
    )

    print("All fixtures generated successfully!")


if __name__ == "__main__":
    main()
