"""Contract loading and validation.

Loads the contract from contract/telemetry-events.json once at startup,
stores it in app.state, and provides validation for telemetry events.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypedDict


class ContractError(ValueError):
    """Raised when a telemetry event fails contract validation."""


class _EventsDict(TypedDict):
    required: list[str]
    optional: list[str]


@dataclass(frozen=True)
class Contract:
    """Machine-readable telemetry contract."""

    version: str
    common_fields: list[str]
    components: list[str]
    events: dict[str, _EventsDict]
    forbidden_attribute_names: list[str]


_contract: Contract | None = None


def load() -> Contract:
    """Load the contract from disk and store it globally."""
    global _contract
    if _contract is not None:
        return _contract

    path = Path("contract/telemetry-events.json")
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    _contract = Contract(
        version=data["contract_version"],
        common_fields=data["common_fields"],
        components=data["components"],
        events=data["events"],
        forbidden_attribute_names=data["forbidden_attribute_names"],
    )
    return _contract


def get_contract() -> Contract:
    """Return the loaded contract (must be called after load)."""
    if _contract is None:
        raise RuntimeError("Contract not loaded - call load() first")
    return _contract


def validate_event(contract: Contract, line: dict[str, Any]) -> None:
    """Validate a telemetry event against the contract.

    Raises ContractError with the field name in the message on failure.
    """
    # Check all common fields present
    for field_name in contract.common_fields:
        if field_name not in line:
            raise ContractError(f"missing common field: {field_name}")

    # If event is present, it must be in the catalogue
    event_name = line.get("event")
    if event_name is not None and event_name not in contract.events:
        raise ContractError(f"unknown event: {event_name}")

    # Check required and optional attributes
    if event_name is not None:
        event_spec = contract.events[event_name]
        required = event_spec["required"]
        optional = event_spec["optional"]
        allowed = set(required) | set(optional)

        for req in required:
            if req not in line.get("attributes", {}):
                raise ContractError(f"missing required attribute: {req}")

        attrs = line.get("attributes", {})
        for attr_name in attrs:
            if attr_name not in allowed:
                raise ContractError(
                    f"attribute not allowed for {event_name}: {attr_name}"
                )

    # Forbidden attributes check (top-level and in attributes)
    for forbidden in contract.forbidden_attribute_names:
        if forbidden in line:
            raise ContractError(f"forbidden field present: {forbidden}")
        if forbidden in line.get("attributes", {}):
            raise ContractError(f"forbidden attribute present: {forbidden}")
