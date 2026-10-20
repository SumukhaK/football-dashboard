"""Tests for the telemetry contract."""

import pytest

from app.contract import ContractError, load_contract, validate_event


def test_contract_loads() -> None:
    """Load the telemetry contract and verify basic structure."""
    contract = load_contract()
    assert contract is not None
    assert contract.version == "1.1.0"
    assert "common_fields" in contract.__dict__
    assert "components" in contract.__dict__
    assert "events" in contract.__dict__


def test_validate_valid_event() -> None:
    """Validate a correctly formatted event passes."""
    contract = load_contract()
    # Create a minimal valid event according to the contract schema
    event = {
        "timestamp": "2026-10-08T18:32:27.123Z",
        "severity": "INFO",
        "message": "Sample log line",
        "logger": "backend.app.main",
        "event": "http.request",
        "request_id": "req_12345",
        "logging.googleapis.com/trace": None,
        "logging.googleapis.com/spanId": None,
        "trace_id": "trace_abc123",
        "service": "football-api",
        "revision": "rev_001",
        "api_version": "2.0.0",
        "contract_version": "1.1.0",
        "attributes": {
            "method": "GET",
            "route": "/v2/teams/{team}/outlook",
            "status": "200",
            "duration_ms": 150,
            "error_code": None,
        },
    }
    # Should not raise ContractError
    try:
        validate_event(contract, event)
    except ContractError:
        pytest.fail("Valid event raised ContractError unexpectedly")


def test_validate_invalid_event_missing_field() -> None:
    """Validate an invalid event raises ContractError."""
    contract = load_contract()
    # Missing required field "event"
    event = {
        "timestamp": "2026-10-08T18:32:27.123Z",
        "severity": "INFO",
        "message": "Sample log line",
        "logger": "backend.app.main",
        "request_id": "req_12345",
        "logging.googleapis.com/trace": None,
        "logging.googleapis.com/spanId": None,
        "trace_id": "trace_abc123",
        "service": "football-api",
        "revision": "rev_001",
        "api_version": "2.0.0",
        "contract_version": "1.1.0",
        "attributes": {
            "method": "GET",
            "route": "/v2/teams/{team}/outlook",
            "status": "200",
            "duration_ms": 150,
            "error_code": None,
        },
    }
    # Should raise ContractError
    with pytest.raises(ContractError):
        validate_event(contract, event)


def test_validate_event_with_none_attributes() -> None:
    """Validate an event with empty attributes dictionary."""
    contract = load_contract()
    event = {
        "timestamp": "2026-10-08T18:32:27.123Z",
        "severity": "INFO",
        "message": "Sample log line",
        "logger": "backend.app.main",
        "event": "http.request",
        "request_id": "req_12345",
        "logging.googleapis.com/trace": None,
        "logging.googleapis.com/spanId": None,
        "trace_id": "trace_abc123",
        "service": "football-api",
        "revision": "rev_001",
        "api_version": "2.0.0",
        "contract_version": "1.1.0",
        "attributes": {
            "method": "GET",
            "route": "/v2/teams/{team}/outlook",
            "status": "200",
            "duration_ms": 150,
            "error_code": None,
        },
    }
    # Should not raise
    validate_event(contract, event)


def test_contract_1_1_0_allows_user_ref_on_assistant_turns() -> None:
    """Contract 1.1.0 lets every assistant turn and guardrail event carry user_ref."""
    contract = load_contract()
    assert contract.version == "1.1.0"
    for event in (
        "http.request",
        "assistant.answer",
        "assistant.tool",
        "assistant.abstain",
        "guardrail.event",
    ):
        assert "user_ref" in contract.events[event]["optional"], event


def test_validate_event_rejects_a_mismatched_contract_version() -> None:
    """A line announcing a different contract version is not one we can read."""
    contract = load_contract()
    event = {
        "timestamp": "2026-10-08T18:32:27.123Z",
        "severity": "INFO",
        "message": "Sample log line",
        "logger": "backend.app.main",
        "event": "http.request",
        "request_id": "req_12345",
        "logging.googleapis.com/trace": None,
        "logging.googleapis.com/spanId": None,
        "trace_id": "trace_abc123",
        "service": "football-api",
        "revision": "rev_001",
        "api_version": "2.0.0",
        "contract_version": "1.0.0",
        "attributes": {
            "method": "GET",
            "route": "/v2/teams/{team}/outlook",
            "status": 200,
            "duration_ms": 150,
            "error_code": None,
        },
    }
    with pytest.raises(ContractError, match="contract version"):
        validate_event(contract, event)


@pytest.mark.parametrize(
    "bad_attributes",
    [None, "invalid-string", 12345, [1, 2, 3]],
)
def test_validate_event_rejects_malformed_attributes(bad_attributes: object) -> None:
    """Validate that non-mapping attributes fail with a ContractError naming attributes."""
    contract = load_contract()
    event = {
        "timestamp": "2026-10-08T18:32:27.123Z",
        "severity": "INFO",
        "message": "Sample log line",
        "logger": "backend.app.main",
        "event": "http.request",
        "request_id": "req_12345",
        "logging.googleapis.com/trace": None,
        "logging.googleapis.com/spanId": None,
        "trace_id": "trace_abc123",
        "service": "football-api",
        "revision": "rev_001",
        "api_version": "2.0.0",
        "contract_version": "1.1.0",
        "attributes": bad_attributes,
    }
    with pytest.raises(ContractError, match="attributes"):
        validate_event(contract, event)


@pytest.mark.parametrize(
    "bad_event",
    [{}, ["http.request"], 12345],
)
def test_validate_event_rejects_malformed_event_type(bad_event: object) -> None:
    """Validate that unhashable or non-string event types fail with ContractError naming event."""
    contract = load_contract()
    event = {
        "timestamp": "2026-10-08T18:32:27.123Z",
        "severity": "INFO",
        "message": "Sample log line",
        "logger": "backend.app.main",
        "event": bad_event,
        "request_id": "req_12345",
        "logging.googleapis.com/trace": None,
        "logging.googleapis.com/spanId": None,
        "trace_id": "trace_abc123",
        "service": "football-api",
        "revision": "rev_001",
        "api_version": "2.0.0",
        "contract_version": "1.1.0",
        "attributes": {
            "method": "GET",
            "route": "/v2/teams/{team}/outlook",
            "status": "200",
            "duration_ms": 150,
            "error_code": None,
        },
    }
    with pytest.raises(ContractError, match="event"):
        validate_event(contract, event)


@pytest.mark.parametrize(
    "bad_ts",
    [
        None,
        "not-a-timestamp",
        123456789,
        "2026-99-99T99:99:99Z",
        "2026-10-08T18:32:27.123",  # Missing offset
        "2026-10-08",  # Date only, missing offset
    ],
)
def test_validate_event_rejects_unusable_timestamp(bad_ts: object) -> None:
    """Validate that unusable, malformed, or missing-offset timestamps fail with ContractError naming timestamp."""
    contract = load_contract()
    event = {
        "timestamp": bad_ts,
        "severity": "INFO",
        "message": "Sample log line",
        "logger": "backend.app.main",
        "event": "http.request",
        "request_id": "req_12345",
        "logging.googleapis.com/trace": None,
        "logging.googleapis.com/spanId": None,
        "trace_id": "trace_abc123",
        "service": "football-api",
        "revision": "rev_001",
        "api_version": "2.0.0",
        "contract_version": "1.1.0",
        "attributes": {
            "method": "GET",
            "route": "/v2/teams/{team}/outlook",
            "status": "200",
            "duration_ms": 150,
            "error_code": None,
        },
    }
    with pytest.raises(ContractError, match="timestamp"):
        validate_event(contract, event)


@pytest.mark.parametrize(
    "valid_ts",
    [
        "2026-10-08T18:32:27.123Z",
        "2026-10-08T18:32:27.123000+00:00",
        "2026-10-08T23:45:00+05:30",
    ],
)
def test_validate_event_accepts_valid_aware_timestamp(valid_ts: str) -> None:
    """Validate that explicit offset-aware ISO timestamps pass validation."""
    contract = load_contract()
    event = {
        "timestamp": valid_ts,
        "severity": "INFO",
        "message": "Sample log line",
        "logger": "backend.app.main",
        "event": "http.request",
        "request_id": "req_12345",
        "logging.googleapis.com/trace": None,
        "logging.googleapis.com/spanId": None,
        "trace_id": "trace_abc123",
        "service": "football-api",
        "revision": "rev_001",
        "api_version": "2.0.0",
        "contract_version": "1.1.0",
        "attributes": {
            "method": "GET",
            "route": "/v2/teams/{team}/outlook",
            "status": "200",
            "duration_ms": 150,
            "error_code": None,
        },
    }
    validate_event(contract, event)


@pytest.mark.parametrize(
    "bad_line",
    [None, "a string", [1, 2, 3], 42],
)
def test_validate_event_rejects_non_mapping_line(bad_line: object) -> None:
    """Validate that non-mapping input raises ContractError."""
    contract = load_contract()
    with pytest.raises(ContractError):
        validate_event(contract, bad_line)
