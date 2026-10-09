"""Sample HTTP traffic: everyday requests, sign-ins, a lockout and a 429 burst."""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from scripts.fixture_core import (
    START,
    Ids,
    Line,
    Request,
    app_crash_line,
    app_error_line,
    http_request_line,
    log_line,
    milliseconds,
)

_ACCOUNTS = "backend.app.services.account_service."
_EXCEPTIONS = "backend.app.exceptions."
NOT_SIGNED_IN = (401, "Not signed in", _ACCOUNTS + "NotSignedInError")


@dataclass(frozen=True)
class Route:
    """A backend route, how often it is called and how slow it is."""

    method: str
    template: str
    weight: int
    median_ms: float
    signed_in: bool = True


ROUTES = (
    Route("GET", "/v2/health", 10, 3, signed_in=False),
    Route("GET", "/v2/fixtures", 14, 40),
    Route("POST", "/v2/predict", 14, 60),
    Route("POST", "/v2/explain", 8, 220),
    Route("POST", "/v2/insights", 8, 120),
    Route("GET", "/v2/teams/{team}/outlook", 10, 350),
    Route("GET", "/v2/teams", 6, 15),
    Route("GET", "/v2/competitions", 4, 8),
    Route("GET", "/v2/teams/{team}/crest", 10, 12, signed_in=False),
    Route("GET", "/v2/competitions/{competition}/emblem", 3, 10, signed_in=False),
    Route("GET", "/v2/model", 2, 5),
    Route("GET", "/v2/me", 4, 6),
)
# Typed failures per route: (chance, status, error_code, exception_type).
_FAILURES: dict[str, tuple[tuple[float, int, str, str], ...]] = {
    "/v2/predict": ((0.04, 422, "Missing feature columns", "FeatureMissingError"),),
    "/v2/insights": ((0.02, 422, "Unknown competition", "UnknownCompetitionError"),),
    "/v2/teams/{team}/outlook": ((0.03, 422, "Unknown team", "UnknownTeamError"),),
}
# Unhandled errors per route: (chance, exception_type, last traceback lines).
_CRASHES: dict[str, tuple[float, str, str]] = {
    "/v2/explain": (
        0.015,
        "builtins.KeyError",
        (
            '  File "/app/backend/app/services/explanation_service.py", line 48, '
            "in explain\n    contribution = values[feature]\nKeyError: 'elo_diff'"
        ),
    ),
    "/v2/predict": (
        0.004,
        "builtins.ValueError",
        (
            '  File "/app/inference/predictor.py", line 71, in predict\n'
            "    probabilities = self._model.predict_proba(frame)\n"
            "ValueError: Input contains NaN"
        ),
    ),
    "/v2/teams/{team}/outlook": (
        0.015,
        "builtins.ZeroDivisionError",
        (
            '  File "/app/backend/app/services/outlook_service.py", line 112, '
            "in _chances\n    share = finished / simulations\n"
            "ZeroDivisionError: division by zero"
        ),
    ),
}


class Traffic:
    """Generates request lines from one seeded random generator."""

    def __init__(self, rng: random.Random, ids: Ids) -> None:
        """Draw randomness from ``rng`` and ids from ``ids``."""
        self._rng = rng
        self._ids = ids
        self.users = tuple(ids.hex(16) for _ in range(12))

    def duration(self, median_ms: float, spread: float = 0.5) -> timedelta:
        """Return a lognormal duration around ``median_ms``."""
        return milliseconds(
            max(1, round(median_ms * self._rng.lognormvariate(0, spread)))
        )

    def everyday(self, moment: datetime) -> list[Line]:
        """Return the lines of one ordinary request starting at ``moment``."""
        if self._rng.random() < 0.01:
            return self._unmatched(moment)
        route = self._rng.choices(ROUTES, weights=[r.weight for r in ROUTES])[0]
        user = self._rng.choice(self.users) if route.signed_in else None
        request = Request.new(self._ids, route.method, route.template, user)
        ended = moment + self.duration(route.median_ms)
        if route.signed_in and self._rng.random() < 0.02:
            return self.typed_failure(moment, ended, request, NOT_SIGNED_IN)
        crash = _CRASHES.get(route.template)
        if crash and self._rng.random() < crash[0]:
            return self._crash(moment, ended, request, crash[1], crash[2])
        for chance, status, error, kind in _FAILURES.get(route.template, ()):
            if self._rng.random() < chance:
                failure = (status, error, _EXCEPTIONS + kind)
                return self.typed_failure(moment, ended, request, failure)
        return [http_request_line(moment, ended, request, 200, None)]

    def typed_failure(
        self,
        started: datetime,
        ended: datetime,
        request: Request,
        failure: tuple[int, str, str],
    ) -> list[Line]:
        """Return a request answered by a typed exception handler."""
        status, error, kind = failure
        return [
            app_error_line(ended, request, status, error, kind),
            http_request_line(started, ended, request, status, error),
        ]

    def _crash(
        self,
        started: datetime,
        ended: datetime,
        request: Request,
        kind: str,
        tail: str,
    ) -> list[Line]:
        traceback = "Traceback (most recent call last):\n" + tail
        error = "Internal server error"
        return [
            app_crash_line(ended, request, kind, traceback),
            http_request_line(started, ended, request, 500, error),
        ]

    def _unmatched(self, moment: datetime) -> list[Line]:
        # FastAPI's own 404 body has no `error` field, so error_code stays null.
        request = Request.new(self._ids, "GET", "<unmatched>", None)
        ended = moment + self.duration(2)
        return [http_request_line(moment, ended, request, 404, None)]

    def auth_action(
        self,
        moment: datetime,
        action: str,
        outcome: str,
        failure: tuple[int, str, str] | None = None,
        user: str | None = None,
    ) -> list[Line]:
        """Return an account request and its ``auth.event``."""
        routes = {
            "sign_in": ("POST", "/v2/auth/login"),
            "sign_out": ("POST", "/v2/auth/logout"),
            "redeem_invite": ("POST", "/v2/auth/redeem-invite"),
            "consent": ("POST", "/v2/me/consent"),
        }
        method, template = routes[action]
        request = Request.new(self._ids, method, template, user)
        ended = moment + self.duration(180 if action != "consent" else 8)
        attributes: dict[str, Any] = {"action": action, "outcome": outcome}
        if user is not None:
            attributes["user_ref"] = user
        event = log_line(
            ended,
            "auth.event",
            f"Account action {action} finished: {outcome}",
            attributes,
            logger="backend.app.services.account_service",
            request=request,
        )
        if failure is None:
            return [event, http_request_line(moment, ended, request, 200, None)]
        return [event, *self.typed_failure(moment, ended, request, failure)]

    def everyday_auth(self, moment: datetime) -> list[Line]:
        """Return one routine sign-in, sign-out or consent."""
        action = self._rng.choice(("sign_in", "sign_in", "sign_out", "consent"))
        return self.auth_action(moment, action, "ok", user=self._rng.choice(self.users))

    def rate_limit_burst(self, moment: datetime, count: int) -> list[Line]:
        """Return ``count`` requests from one client rejected with 429."""
        client_ref = self._ids.hex(16)
        lines: list[Line] = []
        for index in range(count):
            started = moment + milliseconds(index * 700)
            request = Request.new(self._ids, "POST", "/v2/predict", None)
            wait = max(1, 60 - round((started - moment).total_seconds()))
            lines.append(
                log_line(
                    started + milliseconds(1),
                    "ratelimit.rejected",
                    "Client is over the rate limit",
                    {
                        "route": request.route,
                        "client_ref": client_ref,
                        "retry_after_s": wait,
                    },
                    logger="backend.app.middleware.rate_limit",
                    request=request,
                )
            )
            ended = started + milliseconds(2)
            lines.append(
                http_request_line(started, ended, request, 429, "Too many requests")
            )
        return lines


def everyday_starts(rng: random.Random, until: datetime) -> list[datetime]:
    """Return request start times: busier by day than by night, UTC."""
    starts: list[datetime] = []
    minute = START + timedelta(minutes=3)
    while minute < until:
        busy = 0.6 if 7 <= minute.hour < 23 else 0.25
        for _ in range(4):
            if rng.random() < busy:
                starts.append(minute + timedelta(seconds=rng.uniform(0, 59.9)))
        minute += timedelta(minutes=1)
    return sorted(starts)


_LOCKED = (429, "Too many attempts", _ACCOUNTS + "TooManyAttemptsError")
_ONE_OFF_ACCOUNT_ACTIONS: tuple[tuple[str, str, tuple[int, str, str] | None], ...] = (
    ("redeem_invite", "ok", None),
    (
        "redeem_invite",
        "invalid_invite",
        (400, "Invalid invite", _ACCOUNTS + "InvalidInviteError"),
    ),
    (
        "redeem_invite",
        "weak_password",
        (422, "Password too short", _ACCOUNTS + "WeakPasswordError"),
    ),
    (
        "consent",
        "consent_required",
        (403, "Consent required", _ACCOUNTS + "ConsentRequiredError"),
    ),
    ("sign_in", "blocked", (403, "Account blocked", _ACCOUNTS + "AccountBlockedError")),
    ("sign_out", "not_signed_in", NOT_SIGNED_IN),
)


def account_scenarios(traffic: Traffic, moment: datetime) -> list[Line]:
    """Return one of each rarer account outcome, ten minutes apart."""
    lines: list[Line] = []
    for index, (action, outcome, failure) in enumerate(_ONE_OFF_ACCOUNT_ACTIONS):
        known = outcome in ("ok", "blocked", "consent_required")
        user = traffic.users[index] if known else None
        at = moment + timedelta(minutes=10 * index)
        lines += traffic.auth_action(at, action, outcome, failure, user)
    return lines


def lockout(traffic: Traffic, moment: datetime, user: str) -> list[Line]:
    """Return five failed sign-ins for one account, then the lockout."""
    failed = (401, "Invalid credentials", _ACCOUNTS + "InvalidCredentialsError")
    lines: list[Line] = []
    for attempt in range(5):
        at = moment + timedelta(seconds=9 * attempt)
        lines += traffic.auth_action(at, "sign_in", "failed", failed, user)
    at = moment + timedelta(seconds=50)
    return lines + traffic.auth_action(at, "sign_in", "locked_out", _LOCKED, user)
