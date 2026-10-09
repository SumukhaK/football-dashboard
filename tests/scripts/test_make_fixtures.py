"""Tests that the generated sample data follows the telemetry contract.

The allowed values below are copied from guide/telemetry-contract.md section 3
on purpose, rather than imported from the generator, so a wrong value in the
generator cannot also make its test pass.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

from app.contract import Contract, validate_event
from scripts.make_fixtures import build, main

REPO = Path(__file__).resolve().parents[2]
FILES = ("events.jsonl", "traces.json", "error_groups.json", "platform_events.json")
ALLOWED: dict[str, dict[str, set[Any]]] = {
    "component.load": {
        "status": {"ok", "degraded", "failed"},
        "component": {
            "prediction_model",
            "prediction_model_v1",
            "explanation",
            "assistant",
            "season_history",
            "season_outlook",
            "fixtures",
            "match_history",
            "goals_model",
        },
    },
    "refresh.run": {"status": {"ok", "failed"}},
    "assistant.tool": {"status": {"ok", "error"}},
    "auth.event": {
        "action": {"sign_in", "sign_out", "redeem_invite", "consent"},
        "outcome": {
            "ok",
            "failed",
            "locked_out",
            "blocked",
            "consent_required",
            "invalid_invite",
            "weak_password",
            "not_signed_in",
        },
    },
    "dependency.call": {
        "dependency": {
            "ollama_chat",
            "ollama_embed",
            "football_data",
            "openfootball",
            "workers_ai",
        },
        "status": {"ok", "timeout", "http_error", "connection_error", "error"},
    },
    "retry": {
        "dependency": {
            "ollama_chat",
            "ollama_embed",
            "football_data",
            "openfootball",
            "workers_ai",
        }
    },
    "assistant.answer": {"path": {"router", "model", "model_with_tools"}},
    "assistant.abstain": {"reason": {"no_retrieval", "low_score", "model_declined"}},
}
KNOWN_FALLBACKS = {
    ("fresh_match_data", "previous_match_data"),
    ("fresh_fixtures", "previous_fixtures"),
    ("server_features", "supplied_features_only"),
    ("tool_calling", "answer_without_tools"),
}
FIXED_SEVERITY = {
    "app.crash": "ERROR",
    "component.degraded": "WARNING",
    "ratelimit.rejected": "WARNING",
    "retry": "WARNING",
    "fallback": "WARNING",
    "data.freshness": "INFO",
    "assistant.answer": "INFO",
    "assistant.abstain": "INFO",
}


@pytest.fixture(scope="module")
def files() -> dict[str, Any]:
    """One fresh generation, shared by the tests in this module."""
    return build()


@pytest.fixture(scope="module")
def lines(files: dict[str, Any]) -> list[dict[str, Any]]:
    """The generated log lines."""
    events: list[dict[str, Any]] = files["events.jsonl"]
    return events


def _contract() -> Contract:
    data = json.loads((REPO / "contract" / "telemetry-events.json").read_text())
    return Contract(
        version=data["contract_version"],
        common_fields=data["common_fields"],
        components=data["components"],
        events=data["events"],
        forbidden_attribute_names=data["forbidden_attribute_names"],
    )


def _expected_severity(event: str, attributes: dict[str, Any]) -> str:
    if event in FIXED_SEVERITY:
        return FIXED_SEVERITY[event]
    if event in ("http.request", "app.error"):
        status = attributes["status"]
        if status >= 500:
            return "ERROR"
        return "WARNING" if status >= 400 or event == "app.error" else "INFO"
    if event == "auth.event":
        warn = attributes["outcome"] in {"failed", "locked_out", "blocked"}
        return "WARNING" if warn else "INFO"
    return "INFO" if attributes["status"] == "ok" else "WARNING"


def test_main_writes_every_file(tmp_path: Path) -> None:
    main(tmp_path)
    assert sorted(p.name for p in tmp_path.iterdir()) == sorted(FILES)


def test_runs_are_byte_identical(tmp_path: Path) -> None:
    main(tmp_path / "a")
    main(tmp_path / "b")
    for name in FILES:
        assert (tmp_path / "a" / name).read_bytes() == (
            tmp_path / "b" / name
        ).read_bytes()


def test_committed_fixtures_are_the_generated_ones(tmp_path: Path) -> None:
    main(tmp_path)
    for name in FILES:
        committed = (REPO / "fixtures" / name).read_bytes()
        assert committed == (tmp_path / name).read_bytes(), f"regenerate {name}"


def test_every_line_validates(lines: list[dict[str, Any]]) -> None:
    contract = _contract()
    for line in lines:
        validate_event(contract, line)
        assert list(line)[:14] == contract.common_fields


def test_about_a_day_of_lines(lines: list[dict[str, Any]]) -> None:
    assert 2500 <= len(lines) <= 3500
    assert lines[0]["timestamp"] >= "2026-10-07T18:00:00.000Z"
    assert lines[-1]["timestamp"] <= "2026-10-08T18:00:00.000Z"
    assert [line["timestamp"] for line in lines] == sorted(
        line["timestamp"] for line in lines
    )


def test_every_event_but_guardrail_appears(lines: list[dict[str, Any]]) -> None:
    seen = {line["event"] for line in lines}
    assert seen == set(_contract().events) - {"guardrail.event"}


@pytest.mark.parametrize("event", sorted(ALLOWED))
def test_enum_fields_use_contract_values(
    lines: list[dict[str, Any]], event: str
) -> None:
    for line in (line for line in lines if line["event"] == event):
        for name, allowed in ALLOWED[event].items():
            assert line["attributes"][name] in allowed, (event, name, line)


def test_fallbacks_are_known_pairs(lines: list[dict[str, Any]]) -> None:
    for line in (line for line in lines if line["event"] == "fallback"):
        pair = (line["attributes"]["from_path"], line["attributes"]["to_path"])
        assert pair in KNOWN_FALLBACKS


def test_severity_follows_the_contract(lines: list[dict[str, Any]]) -> None:
    for line in lines:
        expected = _expected_severity(line["event"], line["attributes"])
        assert line["severity"] == expected, line


def test_http_statuses_cover_the_console(lines: list[dict[str, Any]]) -> None:
    statuses = {
        line["attributes"]["status"]
        for line in lines
        if line["event"] == "http.request"
    }
    assert {200, 401, 404, 422, 429, 500, 503} <= statuses
    assert all(isinstance(status, int) for status in statuses)


def test_error_codes_match_status(lines: list[dict[str, Any]]) -> None:
    for line in (line for line in lines if line["event"] == "http.request"):
        attributes = line["attributes"]
        if attributes["status"] < 400:
            assert attributes["error_code"] is None
        elif attributes["route"] != "<unmatched>":
            assert attributes["error_code"], line


def test_at_least_ten_real_routes(lines: list[dict[str, Any]]) -> None:
    routes = {
        line["attributes"]["route"] for line in lines if line["event"] == "http.request"
    }
    assert len(routes - {"<unmatched>"}) >= 10
    assert all(route.startswith("/v2/") for route in routes - {"<unmatched>"})


def test_ids_have_the_contract_format(lines: list[dict[str, Any]]) -> None:
    for line in lines:
        if line["request_id"] is None:
            assert line["trace_id"] is None
            continue
        assert re.fullmatch(r"[0-9a-f]{32}", line["request_id"])
        assert re.fullmatch(r"[0-9a-f]{32}", line["trace_id"])
        assert re.fullmatch(r"[0-9a-f]{16}", line["logging.googleapis.com/spanId"])
        assert line["logging.googleapis.com/trace"].endswith(line["trace_id"])
