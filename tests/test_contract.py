"""Tests for the telemetry contract."""

import pytest

from app.contract import ContractError, load_contract, validate_event


def test_contract_loads() -> None:
    """Load the telemetry contract and verify basic structure."""
    contract = load_contract()
    assert contract is not None
    assert contract.version == "1.0.0"
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
        "contract_version": "1.0.0",
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
        "contract_version": "1.0.0",
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
        "contract_version": "1.0.0",
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
