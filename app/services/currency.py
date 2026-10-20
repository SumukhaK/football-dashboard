"""Convert canonical USD provider costs only at the display boundary."""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal

from app.config import Config

UNAVAILABLE = "INR conversion unavailable"
UNREPORTED = "Not reported"


def inr_amount(amount: Decimal | float | None) -> str:
    """Format rupees without turning a small nonzero cost into zero."""
    if amount is None:
        return ""
    value = Decimal(str(amount))
    if not value.is_finite():
        return UNREPORTED
    magnitude = abs(value)
    if 0 < magnitude < Decimal("0.0001"):
        return "INR <0.0001" if value > 0 else "INR >-0.0001"
    precision = 4 if 0 < magnitude < Decimal("0.01") else 2
    return f"INR {value:,.{precision}f}"


def conversion_note(settings: Config | None) -> str | None:
    """Disclose the operator's rate/date; there is no live FX lookup."""
    if (
        settings is None
        or settings.inr_per_usd is None
        or settings.inr_per_usd_as_of is None
    ):
        return None
    return (
        f"Estimated provider cost; 1 USD = INR {settings.inr_per_usd}; "
        f"as of {settings.inr_per_usd_as_of:%d %b %Y}; not a cloud billing invoice."
    )


def cost_label(value: object, settings: Config | None) -> str:
    """Convert a reported dollar amount once, preserving missing/invalid data."""
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return UNREPORTED
    amount = Decimal(str(value))
    if not amount.is_finite():
        return UNREPORTED
    if conversion_note(settings) is None:
        return UNAVAILABLE
    assert settings is not None and settings.inr_per_usd is not None
    return inr_amount(amount * Decimal(str(settings.inr_per_usd)))


def display_attributes(
    attributes: Mapping[str, object], settings: Config | None
) -> tuple[tuple[str, str], ...]:
    """Render cost attributes in rupees without modifying stored telemetry."""
    return tuple(
        (
            ("cost_inr", cost_label(value, settings))
            if key == "cost_usd"
            else (key, "null" if value is None else str(value))
        )
        for key, value in sorted(attributes.items())
    )
