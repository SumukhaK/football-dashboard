"""Building blocks for the sample telemetry: the window, ids, values and log lines.

Every attribute value the generator writes comes from the constants below, which
copy the allowed values in the telemetry contract (section 3).
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

SEED = 7
END = datetime(2026, 10, 8, 18, 0, tzinfo=UTC)
START = END - timedelta(hours=24)
REVISIONS = ("football-api-00041-kav", "football-api-00042-wum")
REVISION_CHANGE = datetime(2026, 10, 8, 6, 0, tzinfo=UTC)
GCP_PROJECT = "football-intelligence"
SERVICE = "football-api"
API_VERSION = "2.0.0"
CONTRACT_VERSION = "1.0.0"
CHAT_ROUTE = "/v2/assistant/chat"
CHAT_MODEL = "qwen2.5:7b-instruct"
COMPETITIONS = ("Premier League", "Bundesliga", "La Liga", "Serie A", "Ligue 1")

COMPONENTS = (
    "prediction_model",
    "prediction_model_v1",
    "explanation",
    "assistant",
    "season_history",
    "season_outlook",
    "fixtures",
    "match_history",
    "goals_model",
)
# Components rebuilt from the match history after each daily refresh.
MATCH_DATA_COMPONENTS = (
    "fixtures",
    "match_history",
    "goals_model",
    "season_history",
    "season_outlook",
)
TOOLS = (
    "predict_match",
    "explain_match",
    "upcoming_fixtures",
    "team_matches",
    "league_table",
)

Line = dict[str, Any]

_FIXED_SEVERITY = {
    "app.crash": "ERROR",
    "component.degraded": "WARNING",
    "ratelimit.rejected": "WARNING",
    "retry": "WARNING",
    "fallback": "WARNING",
}
_OK_STATUS_EVENTS = frozenset(
    {"component.load", "refresh.run", "assistant.tool", "dependency.call"}
)
_AUTH_WARNINGS = frozenset({"failed", "locked_out", "blocked"})


def stamp(moment: datetime) -> str:
    """Return ``moment`` as RFC 3339 UTC with milliseconds."""
    return moment.astimezone(UTC).isoformat(timespec="milliseconds")[:-6] + "Z"


def revision_at(moment: datetime) -> str:
    """Return the Cloud Run revision serving at ``moment``."""
    return REVISIONS[0] if moment < REVISION_CHANGE else REVISIONS[1]


def milliseconds(value: float) -> timedelta:
    """Return ``value`` milliseconds as a timedelta."""
    return timedelta(milliseconds=value)


class Ids:
    """Deterministic lowercase hex ids drawn from one random generator."""

    def __init__(self, rng: random.Random) -> None:
        """Draw ids from ``rng``."""
        self._rng = rng

    def hex(self, chars: int) -> str:
        """Return ``chars`` lowercase hex characters."""
        return f"{self._rng.getrandbits(chars * 4):0{chars}x}"


@dataclass(frozen=True)
class Request:
    """One HTTP request: every line it causes shares these ids."""

    request_id: str
    trace_id: str
    span_id: str
    method: str
    route: str
    user_ref: str | None

    @classmethod
    def new(cls, ids: Ids, method: str, route: str, user_ref: str | None) -> Request:
        """Create a request with fresh ids."""
        return cls(ids.hex(32), ids.hex(32), ids.hex(16), method, route, user_ref)


def severity(event: str, attributes: dict[str, Any]) -> str:
    """Return the severity the contract gives ``event`` with these attributes."""
    if event in _FIXED_SEVERITY:
        return _FIXED_SEVERITY[event]
    if event in ("http.request", "app.error"):
        status = int(attributes["status"])
        if status >= 500:
            return "ERROR"
        return "WARNING" if status >= 400 or event == "app.error" else "INFO"
    if event in _OK_STATUS_EVENTS:
        return "INFO" if attributes["status"] == "ok" else "WARNING"
    if event == "auth.event":
        return "WARNING" if attributes["outcome"] in _AUTH_WARNINGS else "INFO"
    return "INFO"


def log_line(
    moment: datetime,
    event: str,
    message: str,
    attributes: dict[str, Any],
    *,
    logger: str,
    request: Request | None = None,
    span_id: str | None = None,
) -> Line:
    """Return one log line in the contract's field order."""
    trace_id = request.trace_id if request else None
    return {
        "timestamp": stamp(moment),
        "severity": severity(event, attributes),
        "message": message,
        "logger": logger,
        "event": event,
        "request_id": request.request_id if request else None,
        "logging.googleapis.com/trace": (
            f"projects/{GCP_PROJECT}/traces/{trace_id}" if trace_id else None
        ),
        "logging.googleapis.com/spanId": (
            (span_id or request.span_id) if request else None
        ),
        "trace_id": trace_id,
        "service": SERVICE,
        "revision": revision_at(moment),
        "api_version": API_VERSION,
        "contract_version": CONTRACT_VERSION,
        "attributes": attributes,
    }


def http_request_line(
    started: datetime,
    ended: datetime,
    request: Request,
    status: int,
    error_code: str | None,
) -> Line:
    """Return the ``http.request`` line written once ``request`` is answered."""
    attributes: dict[str, Any] = {
        "method": request.method,
        "route": request.route,
        "status": status,
        "duration_ms": round((ended - started).total_seconds() * 1000),
        "error_code": error_code,
    }
    if request.user_ref is not None:
        attributes["user_ref"] = request.user_ref
    return log_line(
        ended,
        "http.request",
        f"{request.method} request answered with {status}",
        attributes,
        logger="backend.app.middleware.request_context",
        request=request,
    )


def app_error_line(
    moment: datetime,
    request: Request,
    status: int,
    error_code: str,
    exception_type: str,
) -> Line:
    """Return the ``app.error`` line a typed exception handler writes."""
    line = log_line(
        moment,
        "app.error",
        f"Request failed: {error_code}",
        {
            "route": request.route,
            "status": status,
            "error_code": error_code,
            "exception_type": exception_type,
        },
        logger="backend.app.exceptions",
        request=request,
    )
    line["exception_type"] = exception_type
    return line


def app_crash_line(
    moment: datetime, request: Request, exception_type: str, traceback: str
) -> Line:
    """Return the ``app.crash`` line; its message is the traceback for grouping."""
    line = log_line(
        moment,
        "app.crash",
        traceback,
        {"route": request.route, "exception_type": exception_type},
        logger="backend.app.exceptions",
        request=request,
    )
    line["exception_type"] = exception_type
    line["stack_trace"] = traceback
    return line
