"""Contract loading and validation.

Loads the contract from contract/telemetry-events.json once at startup,
stores it in app.state, and provides validation for telemetry events.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
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


DEFAULT_CONTRACT_PATH = (
    Path(__file__).resolve().parent.parent / "contract" / "telemetry-events.json"
)


def load_contract(path: Path = DEFAULT_CONTRACT_PATH) -> Contract:
    """Load the contract from a JSON file."""
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    return Contract(
        version=data["contract_version"],
        common_fields=data["common_fields"],
        components=data["components"],
        events=data["events"],
        forbidden_attribute_names=data["forbidden_attribute_names"],
    )


def validate_event(contract: Contract, line: Any) -> None:
    """Validate a telemetry event against the contract.

    Raises ContractError with the field name in the message on failure.
    """
    if not isinstance(line, Mapping):
        raise ContractError("event line must be a mapping")

    # Check all common fields present
    for field_name in contract.common_fields:
        if field_name not in line:
            raise ContractError(f"missing common field: {field_name}")

    # Check timestamp format
    raw_ts = line.get("timestamp")
    if not isinstance(raw_ts, str):
        raise ContractError("invalid timestamp: timestamp must be an ISO format string")
    try:
        ts = datetime.fromisoformat(raw_ts)
    except (ValueError, TypeError):
        raise ContractError("invalid timestamp: unusable ISO format")
    if ts.tzinfo is None or ts.utcoffset() is None:
        raise ContractError("invalid timestamp: missing timezone offset")

    # The line must announce the version this contract describes; a line from
    # another version is not one this console can read.
    version = line.get("contract_version")
    if version != contract.version:
        raise ContractError(
            f"contract version mismatch: {version} is not {contract.version}"
        )

    # If event is present, it must be a string and in the catalogue
    event_name = line.get("event")
    if event_name is not None:
        if not isinstance(event_name, str):
            raise ContractError("invalid field: event must be a string")
        if event_name not in contract.events:
            raise ContractError(f"unknown event: {event_name}")

    # Attributes check: attributes must be a mapping
    attrs = line.get("attributes")
    if not isinstance(attrs, Mapping):
        raise ContractError("invalid field: attributes must be a mapping")

    # Check required and optional attributes
    if isinstance(event_name, str):
        event_spec = contract.events[event_name]
        required = event_spec["required"]
        optional = event_spec["optional"]
        allowed = set(required) | set(optional)

        for req in required:
            if req not in attrs:
                raise ContractError(f"missing required attribute: {req}")

        for attr_name in attrs:
            if not isinstance(attr_name, str) or attr_name not in allowed:
                raise ContractError(
                    f"attribute not allowed for {event_name}: {attr_name}"
                )

    # Forbidden attributes check (top-level and in attributes)
    for forbidden in contract.forbidden_attribute_names:
        if forbidden in line:
            raise ContractError(f"forbidden field present: {forbidden}")
        if forbidden in attrs:
            raise ContractError(f"forbidden attribute present: {forbidden}")
