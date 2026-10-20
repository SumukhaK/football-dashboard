"""INR display must convert once, preserve missing costs and disclose its rate."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from html import unescape
from typing import Any

import pytest
from pydantic import ValidationError

from app.config import Config
from app.domain.models import TelemetryEvent
from app.services.assistant import AssistantService
from app.services.currency import inr_amount
from app.services.requests import RequestsService
from app.templating import templates
from tests.auth.console import console
from tests.services.assistant_helpers import ListSource, answer_line

NOW = datetime(2026, 10, 21, 12, tzinfo=UTC)
RATE_DATE = date(2026, 10, 20)


def settings(**overrides: Any) -> Config:
    """80 is a deterministic test rate, never a market quote."""
    return Config(**{"inr_per_usd": 80, "inr_per_usd_as_of": RATE_DATE, **overrides})


@pytest.mark.parametrize(
    "rate", [0, -1, float("inf"), float("-inf"), float("nan"), True, "bad"]
)
def test_invalid_rate_is_rejected(rate: Any) -> None:
    """Invalid operator input must not silently price the dashboard."""
    with pytest.raises(ValidationError):
        settings(inr_per_usd=rate)


def test_rate_and_as_of_load_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Operators can supply both settings without changing code."""
    monkeypatch.setenv("inr_per_usd", "80.25")
    monkeypatch.setenv("inr_per_usd_as_of", "2026-10-20")
    config = Config()
    assert config.inr_per_usd == 80.25
    assert config.inr_per_usd_as_of == RATE_DATE


def test_invalid_as_of_is_rejected() -> None:
    """A malformed provenance date cannot be displayed as trusted metadata."""
    with pytest.raises(ValidationError):
        settings(inr_per_usd_as_of="yesterday")


@pytest.mark.parametrize(
    ("amount", "expected"),
    [
        (None, ""),
        (0, "INR 0.00"),
        (2100.5, "INR 2,100.50"),
        (0.008, "INR 0.0080"),
        (0.00008, "INR <0.0001"),
        (-0.00008, "INR >-0.0001"),
    ],
)
def test_formatter_keeps_small_nonzero_amounts_visible(
    amount: float | None, expected: str
) -> None:
    """A real small cost must not become a displayed zero."""
    assert inr_amount(amount) == expected
    assert (
        unescape(
            templates.env.from_string("{{ value | inr_amount }}").render(value=amount)
        )
        == expected
    )


def service(events: list[TelemetryEvent], config: Config) -> AssistantService:
    return AssistantService(ListSource(events), lambda: NOW, config)


def test_view_model_converts_once_and_keeps_usd_aggregation() -> None:
    """USD 0.25 is INR 20; a null answer must not dilute the average."""
    events = [
        answer_line(NOW - timedelta(minutes=1), cost_usd=value)
        for value in (0.1, 0.15, None)
    ]
    model = service(events, settings()).build_for_hours(24)
    assert model.cost_total == 0.25
    assert model.cost_per_answer == 0.125
    assert model.cost_total_label == "INR 20.00"
    assert model.cost_per_answer_label == "INR 10.00"
    assert [event.attributes["cost_usd"] for event in events] == [0.1, 0.15, None]


@pytest.mark.parametrize(
    "config",
    [
        settings(inr_per_usd=None, inr_per_usd_as_of=None),
        settings(inr_per_usd=None),
        settings(inr_per_usd_as_of=None),
    ],
)
def test_missing_rate_or_date_is_explicit(config: Config) -> None:
    model = service(
        [answer_line(NOW - timedelta(minutes=1), cost_usd=0.25)], config
    ).build_for_hours(24)
    assert model.cost_total_label == "INR conversion unavailable"
    assert model.cost_per_answer_label == "INR conversion unavailable"


@pytest.mark.parametrize(
    ("value", "expected"),
    [(0.0, "INR 0.00"), (0.000001, "INR <0.0001"), (None, "Not reported")],
)
def test_zero_small_and_unreported_costs_are_distinct(
    value: float | None, expected: str
) -> None:
    model = service(
        [answer_line(NOW - timedelta(minutes=1), cost_usd=value)], settings()
    ).build_for_hours(24)
    assert model.cost_total_label == expected
    assert model.reported_cost is (value is not None)


@pytest.mark.parametrize("path", ["/assistant", "/partials/assistant"])
def test_assistant_renders_converted_totals_and_rate_provenance(path: str) -> None:
    signed = console(settings(), clock=lambda: NOW)
    events = [
        answer_line(NOW - timedelta(minutes=1), cost_usd=value) for value in (0.1, 0.15)
    ]
    signed.app.state.assistant = service(events, signed.settings)
    body = signed.client.get(path).text
    assert "Cost (INR, estimate)" in body
    assert "INR 20.00" in body
    assert "INR 10.00 per answer" in body
    assert "1 USD = INR 80" in body and "20 Oct 2026" in body
    assert "not a cloud billing invoice" in body
    assert "Cost (USD)" not in body and "0.2500" not in body


@pytest.mark.parametrize("path", ["/assistant", "/partials/assistant"])
def test_assistant_missing_rate_never_relabels_dollars(path: str) -> None:
    signed = console(settings(inr_per_usd=None), clock=lambda: NOW)
    signed.app.state.assistant = service(
        [answer_line(NOW - timedelta(minutes=1), cost_usd=0.25)], signed.settings
    )
    body = signed.client.get(path).text
    assert "INR conversion unavailable" in body
    assert "INR 0.25" not in body and "Cost (USD)" not in body


@pytest.mark.parametrize(
    ("value", "config", "expected"),
    [
        (0.25, settings(), "INR 20.00"),
        (0.25, settings(inr_per_usd=None), "INR conversion unavailable"),
        (None, settings(), "Not reported"),
        (0.000001, settings(), "INR &lt;0.0001"),
    ],
)
def test_request_timeline_uses_inr_without_mutating_events(
    value: float | None, config: Config, expected: str
) -> None:
    request_id = "req-currency-001"
    event = answer_line(
        NOW - timedelta(minutes=1), request_id=request_id, cost_usd=value
    )
    signed = console(config, clock=lambda: NOW)
    signed.app.state.requests = RequestsService(
        ListSource([event]), lambda: NOW, signed.settings
    )
    body = signed.client.get(f"/requests/{request_id}").text
    assert expected in body
    assert "cost_inr" in body and "cost_usd" not in body
    assert event.attributes["cost_usd"] == value


@pytest.mark.parametrize("value", [None, 0.0, 0.25])
def test_trace_hover_costs_are_converted_with_the_timeline(value: float | None) -> None:
    """Span and marker hover titles must not bypass the currency display boundary."""
    from app.domain.models import Span, SpanEvent, Trace
    from app.services.request_detail import request_detail
    from tests.services.requests_helpers import FakeSource

    request_id = "req-currency-002"
    event = answer_line(
        NOW - timedelta(minutes=1), request_id=request_id, cost_usd=value
    )
    event = replace(event, trace_id="currency-trace")
    attributes = {"cost_usd": value, "attempt": 1}
    span = Span(
        "span-1",
        None,
        "model call",
        event.timestamp,
        NOW,
        attributes,
        (SpanEvent("model", event.timestamp, attributes),),
    )
    detail = request_detail(
        FakeSource([event], [Trace("currency-trace", (span,))]),
        lambda: NOW,
        settings(),
        request_id,
    )
    assert detail is not None
    expected = (
        "Not reported" if value is None else "INR 0.00" if value == 0 else "INR 20.00"
    )
    assert f"cost_inr={expected}" in detail.waterfall[0].title
    assert f"cost_inr={expected}" in detail.waterfall[0].markers[0].detail
    assert "cost_usd" not in detail.waterfall[0].title
    assert attributes["cost_usd"] == value


def test_large_integer_cost_does_not_crash_request_display() -> None:
    """JSON integer costs need not fit in a machine float to render safely."""
    from app.services.currency import cost_label

    value = 10**400
    assert cost_label(value, settings()).startswith("INR 800,")


@pytest.mark.parametrize(
    "value", [float("nan"), float("inf"), float("-inf"), True, "0.25"]
)
def test_unusable_cost_is_not_fabricated(value: object) -> None:
    """Non-numeric or non-finite cost metadata must not invent an INR amount."""
    from app.services.currency import cost_label

    assert cost_label(value, settings()) == "Not reported"


def test_rate_note_preserves_the_configured_precision() -> None:
    """A rounded six-digit rate note must not contradict the conversion used."""
    from app.services.currency import conversion_note

    note = conversion_note(settings(inr_per_usd=80.123456789))
    assert note is not None and "1 USD = INR 80.123456789;" in note
