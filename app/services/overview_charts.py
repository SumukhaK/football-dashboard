"""Chart and sparkline series for the overview page.

Pure functions: they take the window's request events and return the frozen
chart models, so the overview service keeps to reading and headline arithmetic.
"""

from __future__ import annotations

from app.domain.models import TelemetryEvent, TimeWindow
from app.domain.overview import Chart, Series, Sparkline
from app.services.events import durations, in_status_class, is_failure
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


def sparkline_series(
    requests: list[TelemetryEvent], latency: Chart, window: TimeWindow
) -> tuple[Sparkline, ...]:
    """The per-interval series behind the three headline cards' sparklines.

    Requests and failures are counted from every http.request event, the way the
    headline counts them. The traffic chart's status classes cover 2xx, 4xx and
    5xx only, so reading these two figures off that chart would drop redirects
    from the requests and charge them nothing against the error rate.
    """
    buckets = bucket_by_interval(
        requests, window, interval_for(window.end - window.start)
    )
    labels = tuple(chart_label(bucket.start, window) for bucket in buckets)
    counts = tuple(len(bucket.events) for bucket in buckets)
    failures = tuple(
        sum(1 for event in bucket.events if is_failure(event)) for bucket in buckets
    )
    return (
        Sparkline("requests", labels, tuple(float(count) for count in counts)),
        Sparkline(
            "error_rate",
            labels,
            tuple(rate(failure, count) for failure, count in zip(failures, counts)),
        ),
        Sparkline("p95_latency", latency.labels, _line(latency, "p95")),
    )


def _line(chart: Chart, name: str) -> tuple[float | None, ...]:
    """One named series of a chart, or an empty tuple when it is absent."""
    return next((line.values for line in chart.series if line.name == name), ())
