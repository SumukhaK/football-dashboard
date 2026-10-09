"""Sample lines outside requests: startups, daily refreshes, data freshness.

Also builds the platform events and error groups that sit beside the log lines.
"""

from __future__ import annotations

import hashlib
import random
from datetime import UTC, date, datetime, timedelta
from typing import Any

from scripts.fixture_core import (
    COMPETITIONS,
    COMPONENTS,
    MATCH_DATA_COMPONENTS,
    REVISION_CHANGE,
    REVISIONS,
    START,
    Line,
    log_line,
    milliseconds,
    revision_at,
    stamp,
)

# The last match day each league had played before the window.
MATCHES_THROUGH = {
    "Premier League": date(2026, 10, 5),
    "Bundesliga": date(2026, 10, 4),
    "La Liga": date(2026, 10, 5),
    "Serie A": date(2026, 10, 5),
    "Ligue 1": date(2026, 10, 4),
}
_LOAD_MEDIAN_MS = {
    "prediction_model": 900,
    "prediction_model_v1": 850,
    "explanation": 1400,
    "assistant": 2600,
    "season_history": 300,
    "season_outlook": 320,
    "fixtures": 60,
    "match_history": 700,
    "goals_model": 4200,
}
FIRST_STARTUP = START + timedelta(minutes=1)
FAILED_REFRESH = datetime(2026, 10, 8, 4, 0, tzinfo=UTC)
GOOD_REFRESH = datetime(2026, 10, 8, 5, 0, tzinfo=UTC)
OUT_OF_MEMORY = datetime(2026, 10, 8, 17, 42, tzinfo=UTC)


def component_load(
    moment: datetime, component: str, status: str, took_ms: int, reason: str | None
) -> Line:
    """Return one ``component.load`` line."""
    return log_line(
        moment,
        "component.load",
        f"Component {component} loaded: {status}",
        {
            "component": component,
            "status": status,
            "duration_ms": took_ms,
            "reason": reason,
        },
        logger="backend.app.main",
    )


def startup(rng: random.Random, moment: datetime, assistant_fails: bool) -> list[Line]:
    """Return one startup sequence: every component loads once, then freshness."""
    lines: list[Line] = []
    for component in COMPONENTS:
        took = round(_LOAD_MEDIAN_MS[component] * rng.lognormvariate(0, 0.2))
        moment += milliseconds(took)
        if component == "assistant" and assistant_fails:
            reason = "Ollama did not answer at startup"
            lines.append(component_load(moment, component, "failed", took, reason))
        else:
            lines.append(component_load(moment, component, "ok", took, None))
    return lines + freshness(moment + milliseconds(5))


def freshness(moment: datetime) -> list[Line]:
    """Return one ``data.freshness`` line per league."""
    lines: list[Line] = []
    for competition in COMPETITIONS:
        through = MATCHES_THROUGH[competition]
        midnight = datetime(through.year, through.month, through.day, tzinfo=UTC)
        age = round((moment - midnight).total_seconds() / 3600, 1)
        lines.append(
            log_line(
                moment,
                "data.freshness",
                f"{competition} match data checked",
                {
                    "competition": competition,
                    "matches_through": through.isoformat(),
                    "age_hours": age,
                },
                logger="backend.app.main",
            )
        )
    return lines


def _download(
    moment: datetime, dependency: str, status: str, http_status: int, attempt: int
) -> Line:
    return log_line(
        moment,
        "dependency.call",
        f"Download from {dependency} finished: {status}",
        {
            "dependency": dependency,
            "operation": "download",
            "status": status,
            "http_status": http_status,
            "attempt": attempt,
            "duration_ms": 1800 if status == "ok" else 30000,
        },
        logger="ingestion.live_refresh",
    )


def _refresh_run(
    moment: datetime, status: str, took_ms: int, dataset: str | None, error: str | None
) -> Line:
    return log_line(
        moment,
        "refresh.run",
        f"Daily refresh finished: {status}",
        {"status": status, "duration_ms": took_ms, "dataset": dataset, "error": error},
        logger="backend.app.services.live_refresh_service",
    )


def failed_refresh(moment: datetime) -> list[Line]:
    """Return a refresh whose download fails twice, and the fallback to old data."""
    first = moment + milliseconds(30000)
    retry = log_line(
        first + milliseconds(1),
        "retry",
        "Download failed; retrying",
        {
            "dependency": "football_data",
            "operation": "download",
            "attempt": 1,
            "max_attempts": 2,
            "wait_ms": 5000,
            "cause": "http_error",
        },
        logger="ingestion.live_refresh",
    )
    second = first + milliseconds(35000)
    error = "football-data.co.uk answered 503 twice"
    fallback = log_line(
        second + milliseconds(3),
        "fallback",
        "Keeping the previous match data",
        {
            "from_path": "fresh_match_data",
            "to_path": "previous_match_data",
            "cause": "refresh_failed",
        },
        logger="backend.app.services.live_refresh_service",
    )
    return [
        _download(first, "football_data", "http_error", 503, 1),
        retry,
        _download(second, "football_data", "http_error", 503, 2),
        _refresh_run(second + milliseconds(2), "failed", 65002, None, error),
        fallback,
    ]


def good_refresh(rng: random.Random, moment: datetime) -> list[Line]:
    """Return a refresh that succeeds, the reloads it causes and new freshness."""
    results = moment + milliseconds(1800)
    fixtures = results + milliseconds(1800)
    lines = [
        _download(results, "football_data", "ok", 200, 1),
        _download(fixtures, "openfootball", "ok", 200, 1),
        _refresh_run(fixtures, "ok", 3600, "football_data_2026-10-08.csv", None),
    ]
    reloaded = fixtures
    for component in MATCH_DATA_COMPONENTS:
        took = round(_LOAD_MEDIAN_MS[component] * rng.lognormvariate(0, 0.2))
        reloaded += milliseconds(took)
        lines.append(component_load(reloaded, component, "ok", took, None))
    return lines + freshness(reloaded + milliseconds(5))


def platform_lines(rng: random.Random) -> list[Line]:
    """Return both startups and both refresh attempts."""
    return [
        *startup(rng, FIRST_STARTUP, assistant_fails=True),
        *failed_refresh(FAILED_REFRESH),
        *good_refresh(rng, GOOD_REFRESH),
        *startup(rng, REVISION_CHANGE, assistant_fails=False),
    ]


def platform_events() -> list[dict[str, Any]]:
    """Return Cloud Run events: an instance start per revision, then an OOM."""
    return [
        {
            "timestamp": stamp(FIRST_STARTUP),
            "kind": "instance_started",
            "revision": REVISIONS[0],
            "message": "Started a new instance of the revision",
        },
        {
            "timestamp": stamp(REVISION_CHANGE),
            "kind": "instance_started",
            "revision": REVISIONS[1],
            "message": "Started a new instance of the revision",
        },
        {
            "timestamp": stamp(OUT_OF_MEMORY),
            "kind": "out_of_memory",
            "revision": revision_at(OUT_OF_MEMORY),
            "message": "Memory limit of 2 GiB exceeded",
        },
        {
            "timestamp": stamp(OUT_OF_MEMORY + timedelta(seconds=1)),
            "kind": "container_exit",
            "revision": revision_at(OUT_OF_MEMORY),
            "message": "Container exited with code 137",
        },
    ]


def _is_server_error(line: Line) -> bool:
    if line["event"] == "app.crash":
        return True
    return line["event"] == "app.error" and int(line["attributes"]["status"]) >= 500


def error_groups(lines: list[Line]) -> list[dict[str, Any]]:
    """Group the crashes and 5xx errors in ``lines`` by exception type."""
    groups: dict[str, dict[str, Any]] = {}
    for line in filter(_is_server_error, lines):
        kind = line["exception_type"]
        message = line["message"].splitlines()[-1]
        group = groups.setdefault(
            kind,
            {
                "group_id": hashlib.sha256(kind.encode()).hexdigest()[:12],
                "exception_type": kind,
                "message": message,
                "count": 0,
                "first_seen": line["timestamp"],
                "last_seen": line["timestamp"],
                "affected_routes": [],
            },
        )
        group["count"] += 1
        group["last_seen"] = max(group["last_seen"], line["timestamp"])
        group["first_seen"] = min(group["first_seen"], line["timestamp"])
        if line["attributes"]["route"] not in group["affected_routes"]:
            group["affected_routes"].append(line["attributes"]["route"])
    for group in groups.values():
        group["affected_routes"].sort()
    return sorted(groups.values(), key=lambda g: g["exception_type"])
