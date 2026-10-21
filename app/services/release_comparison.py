"""Pure release comparison over the overview's existing bounded samples."""

import math
from collections.abc import Callable, Sequence

from app.config import Config
from app.domain.models import MAX_QUERY_LIMIT, TelemetryEvent
from app.domain.release_comparison import ReleaseComparison, ReleaseMetrics
from app.services.assistant_answers import cost_summary, token_summary
from app.services.currency import conversion_note, cost_label
from app.services.events import by_event, durations, is_failure
from app.services.stats import percentile, rate
from app.services.view_scope import sort_releases

SORT_KEYS = ("version", "requests", "error_rate", "p95")


def compare_releases(
    requests: list[TelemetryEvent],
    counted: list[TelemetryEvent],
    answers: list[TelemetryEvent],
    labels: tuple[str, ...],
    settings: Config,
) -> ReleaseComparison:
    """Compute rows and combined metrics from the same request/crash/answer samples."""
    crashes = by_event(counted, "app.crash")
    events = requests + crashes + answers
    versions = sort_releases(
        tuple({e.api_version for e in events if e.api_version} | set(labels))
    )
    grouped: dict[str | None, list[TelemetryEvent]] = {v: [] for v in (*versions, None)}
    for event in events:
        grouped[event.api_version].append(event)
    return ReleaseComparison(
        tuple(_metrics(v, grouped[v], settings) for v in (*versions, None)),
        _metrics(None, events, settings),
        any(len(page) >= MAX_QUERY_LIMIT for page in (requests, counted, answers)),
        MAX_QUERY_LIMIT,
        conversion_note(settings),
    )


def _metrics(
    version: str | None, events: Sequence[TelemetryEvent], settings: Config
) -> ReleaseMetrics:
    """Pool latency samples and reported cost/token values without averaging rows."""
    requests = by_event(events, "http.request")
    answers = by_event(events, "assistant.answer")
    measured = durations(requests)
    costs = _reported(answers, "cost_usd")
    incoming = _reported(answers, "prompt_tokens")
    outgoing = _reported(answers, "completion_tokens")
    usd, _ = cost_summary(costs)
    failures = sum(is_failure(e) for e in requests)
    return ReleaseMetrics(
        version=version,
        requests=len(requests),
        server_errors=failures,
        error_rate=rate(failures, len(requests)),
        p50_ms=percentile(measured, 0.5),
        p95_ms=percentile(measured, 0.95),
        latency_samples=len(measured),
        crashes=len(by_event(events, "app.crash")),
        assistant_answers=len(answers),
        tokens_in=token_summary(incoming, "prompt_tokens").total,
        tokens_out=token_summary(outgoing, "completion_tokens").total,
        token_in_samples=len(incoming),
        token_out_samples=len(outgoing),
        cost_usd=usd,
        cost_label=cost_label(usd, settings),
        cost_samples=len(costs),
        observations=len(events),
        first_seen=min((e.timestamp for e in events), default=None),
        last_seen=max((e.timestamp for e in events), default=None),
    )


def _reported(answers: Sequence[TelemetryEvent], key: str) -> list[TelemetryEvent]:
    """Exclude missing or unusable measurements rather than manufacture zero values."""
    kept = []
    for answer in answers:
        value = answer.attributes.get(key)
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            continue
        try:
            valid = math.isfinite(value) and value >= 0
        except OverflowError:
            valid = False
        if valid:
            kept.append(answer)
    return kept


def sorted_rows(
    rows: tuple[ReleaseMetrics, ...], key: str, descending: bool
) -> tuple[ReleaseMetrics, ...]:
    """Keep stable semantic ties, missing metrics and unknown release last."""
    if key not in SORT_KEYS:
        raise ValueError("invalid release comparison sort")
    known = [row for row in rows if row.version is not None]
    unknown = [row for row in rows if row.version is None]
    if key == "version":
        return tuple((known if descending else list(reversed(known))) + unknown)
    values: dict[str, Callable[[ReleaseMetrics], float | None]] = {
        "requests": lambda r: r.requests,
        "error_rate": lambda r: r.error_rate,
        "p95": lambda r: r.p95_ms,
    }
    metric = values[key]
    present = [row for row in known if metric(row) is not None]
    missing = [row for row in known if metric(row) is None]
    present.sort(key=lambda row: metric(row) or 0, reverse=descending)
    return tuple(present + missing + unknown)
