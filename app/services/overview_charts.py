"""Chart and sparkline series for the overview page.

Pure functions: they take the window's request events and return the frozen
chart models, so the overview service keeps to reading and headline arithmetic.
"""

from __future__ import annotations

from app.domain.models import TelemetryEvent, TimeWindow
from app.domain.overview import Chart, Series, Sparkline
from app.services.events import durations, in_status_class
from app.services.links import chart_label
from app.services.stats import bucket_by_interval, percentile, rate
from app.services.windows import interval_for

# http.request status classes used by the traffic chart.
STATUS_CLASSES: tuple[tuple[str, int, int], ...] = (
    ("2xx", 200, 300),
    ("4xx", 400, 500),
    ("5xx", 500, 600),
)


def traffic_series(requests: list[TelemetryEvent], window: TimeWindow) -> Chart:
    """Requests per interval, stacked by status class."""
    buckets = bucket_by_interval(
        requests, window, interval_for(window.end - window.start)
    )
    labels = tuple(chart_label(bucket.start, window) for bucket in buckets)
    series = tuple(
        Series(
            name,
            tuple(
                float(
                    sum(
                        1
                        for event in bucket.events
                        if in_status_class(event, low, high)
                    )
                )
                for bucket in buckets
            ),
        )
        for name, low, high in STATUS_CLASSES
    )
    return Chart(labels=labels, series=series)


def latency_series(requests: list[TelemetryEvent], window: TimeWindow) -> Chart:
    """p50 and p95 latency per interval."""
    buckets = bucket_by_interval(
        requests, window, interval_for(window.end - window.start)
    )
    labels = tuple(chart_label(bucket.start, window) for bucket in buckets)
    series = tuple(
        Series(
            name,
            tuple(percentile(durations(bucket.events), q) for bucket in buckets),
        )
        for name, q in (("p50", 0.5), ("p95", 0.95))
    )
    return Chart(labels=labels, series=series)


def sparkline_series(traffic: Chart, latency: Chart) -> tuple[Sparkline, ...]:
    """The per-interval series behind the three headline cards' sparklines."""
    return (
        Sparkline("requests", traffic.labels, _totals(traffic)),
        Sparkline("error_rate", traffic.labels, _error_rate_series(traffic)),
        Sparkline("p95_latency", latency.labels, _line(latency, "p95")),
    )


def _line(chart: Chart, name: str) -> tuple[float | None, ...]:
    """One named series of a chart, or an empty tuple when it is absent."""
    return next((line.values for line in chart.series if line.name == name), ())


def _totals(chart: Chart) -> tuple[float, ...]:
    """The sum of every series in each interval: the requests per interval."""
    return tuple(
        sum(float(line.values[index] or 0.0) for line in chart.series)
        for index in range(len(chart.labels))
    )


def _error_rate_series(chart: Chart) -> tuple[float | None, ...]:
    """Failures (5xx) over all requests, per interval."""
    totals = _totals(chart)
    failures = _line(chart, "5xx")
    return tuple(
        rate(int(failure or 0), int(total)) for failure, total in zip(failures, totals)
    )
