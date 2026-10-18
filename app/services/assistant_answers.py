"""The answers, latency, tokens and slowest-answer parts of the assistant page.

Every function here is pure: it takes the answer lines one read returned and
gives back the rows the template shows, so the arithmetic is tested on
hand-written lists instead of through a source.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from app.domain.assistant import (
    PATH_ORDER,
    SLOW_ANSWER_MS,
    AbstentionRow,
    AnsweredPathRow,
    LatencyRow,
    PathAnswerRow,
    SlowestAnswer,
    TokenSummary,
)
from app.domain.models import TelemetryEvent
from app.services.events import duration_ms, text
from app.services.labels import display_name, format_duration_ms
from app.services.links import request_detail_link
from app.services.stats import percentile, rate

# The slowest-answers table shows this many rows, so the page stays scannable.
TOP_ANSWERS = 10

UNKNOWN = "<unknown>"

# The colour a path's slice and legend marker use, in contract order, so the
# stacked bar and the table agree whichever paths the window holds.
PATH_TONES: tuple[str, ...] = ("accent", "4xx", "ok", "p50")


def path_rows(answers: Sequence[TelemetryEvent]) -> tuple[PathAnswerRow, ...]:
    """One row per answer path, in the contract's order then by name."""
    counts: dict[str, int] = {}
    for answer in answers:
        path = text(answer.attributes.get("path")) or UNKNOWN
        counts[path] = counts.get(path, 0) + 1
    return tuple(
        PathAnswerRow(
            path=path, answers=counts[path], share=rate(counts[path], len(answers))
        )
        for path in sorted(counts, key=_path_key)
    )


def abstention_rows(abstains: Sequence[TelemetryEvent]) -> tuple[AbstentionRow, ...]:
    """One row per abstention reason, most common first, then by reason."""
    counts: dict[str, int] = {}
    for abstain in abstains:
        reason = text(abstain.attributes.get("reason")) or UNKNOWN
        counts[reason] = counts.get(reason, 0) + 1
    ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return tuple(
        AbstentionRow(reason=reason, label=display_name(reason), count=count)
        for reason, count in ordered
    )


def latency_rows(answers: Sequence[TelemetryEvent]) -> tuple[LatencyRow, ...]:
    """One p50/p95 row per path, over the answers that reported a duration."""
    by_path: dict[str, list[float]] = {}
    for answer in answers:
        value = duration_ms(answer)
        if value is None:
            continue
        path = text(answer.attributes.get("path")) or UNKNOWN
        by_path.setdefault(path, []).append(value)
    rows = [
        LatencyRow(
            path=path,
            answers=len(values),
            p50_ms=percentile(values, 0.5),
            p95_ms=percentile(values, 0.95),
        )
        for path, values in by_path.items()
    ]
    rows.sort(key=lambda row: _path_key(row.path))
    return tuple(rows)


def answered_path_rows(
    paths: Sequence[PathAnswerRow], latency: Sequence[LatencyRow]
) -> tuple[AnsweredPathRow, ...]:
    """Join the path split and its latency into the one table the page shows.

    A path with no reported duration still gets a row: its latency columns read
    "no data" through ``format_duration_ms`` rather than dropping the answers.
    """
    measured = {row.path: row for row in latency}
    return tuple(
        AnsweredPathRow(
            path=row.path,
            label=display_name(row.path),
            tone=_path_tone(index),
            answers=row.answers,
            share=row.share,
            share_pct=(row.share or 0.0) * 100.0,
            p50_label=format_duration_ms(_p50(measured.get(row.path))),
            p95_label=format_duration_ms(_p95(measured.get(row.path))),
            slow=is_slow_ms(_p95(measured.get(row.path))),
        )
        for index, row in enumerate(paths)
    )


def is_slow_ms(p95_ms: float | None) -> bool:
    """Whether a p95 is over the slow-answer threshold; a missing one is not."""
    return p95_ms is not None and p95_ms > SLOW_ANSWER_MS


def _p50(row: LatencyRow | None) -> float | None:
    """A measured row's p50, or None when the path reported no duration."""
    return row.p50_ms if row is not None else None


def _p95(row: LatencyRow | None) -> float | None:
    """A measured row's p95, or None when the path reported no duration."""
    return row.p95_ms if row is not None else None


def _path_tone(index: int) -> str:
    """The stacked bar's colour for the path at this position."""
    return PATH_TONES[index % len(PATH_TONES)]


def token_summary(answers: Sequence[TelemetryEvent], key: str) -> TokenSummary:
    """The percentiles and total of one token field, ignoring null values."""
    values = _numbers(answers, key)
    return TokenSummary(
        p50=percentile(values, 0.5),
        p95=percentile(values, 0.95),
        total=float(sum(values)) if values else None,
    )


def cost_summary(
    answers: Sequence[TelemetryEvent],
) -> tuple[float | None, float | None]:
    """The reported cost total, and the average of the answers that reported one.

    A null ``cost_usd`` is not a zero: an answer that did not report a cost is
    left out of both numbers, and a window with no cost at all reports nothing.
    """
    values = _numbers(answers, "cost_usd")
    if not values:
        return None, None
    total = float(sum(values))
    return total, total / len(values)


def slowest_answers(answers: Sequence[TelemetryEvent]) -> tuple[SlowestAnswer, ...]:
    """The slowest answers, at most TOP_ANSWERS of them, slowest first."""
    ordered = sorted(answers, key=_slowest_key, reverse=True)[:TOP_ANSWERS]
    longest = max((duration_ms(answer) or 0.0 for answer in ordered), default=0.0)
    return tuple(_slowest_row(answer, longest) for answer in ordered)


def _slowest_row(answer: TelemetryEvent, longest: float) -> SlowestAnswer:
    """One slowest-answer row, with its duration bar and its request link."""
    request_id = answer.request_id
    path = text(answer.attributes.get("path")) or UNKNOWN
    value = duration_ms(answer)
    return SlowestAnswer(
        request_id=request_id,
        path=path,
        label=display_name(path),
        tool_rounds=_rounds(answer),
        duration_ms=value,
        duration_label=format_duration_ms(value),
        bar_pct=(value / longest * 100.0) if value is not None and longest else 0.0,
        link=request_detail_link(request_id) if request_id else "",
    )


def _slowest_key(answer: TelemetryEvent) -> tuple[float, datetime, str]:
    """The order the table ranks answers in: slowest first, ties newest first."""
    value = duration_ms(answer)
    return (
        -1.0 if value is None else value,
        answer.timestamp,
        answer.request_id or "",
    )


def _rounds(answer: TelemetryEvent) -> int:
    """The tool rounds one answer reported, or zero when it reported none."""
    value = answer.attributes.get("tool_rounds")
    return value if isinstance(value, int) else 0


def _numbers(answers: Sequence[TelemetryEvent], key: str) -> list[float]:
    """The numeric values of one attribute, dropping nulls and non-numbers."""
    return [
        float(value)
        for answer in answers
        if isinstance(value := answer.attributes.get(key), (int, float))
        and not isinstance(value, bool)
    ]


def _path_key(path: str) -> tuple[int, str]:
    """Sort the contract's paths first, in order, then any other path by name."""
    rank = PATH_ORDER.index(path) if path in PATH_ORDER else len(PATH_ORDER)
    return (rank, path)
