"""Metrics from identical bounded request, crash and assistant samples."""

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class ReleaseMetrics:
    """One exact recorded release, or the combined sample when used as total."""

    version: str | None
    requests: int
    server_errors: int
    error_rate: float | None
    p50_ms: float | None
    p95_ms: float | None
    latency_samples: int
    crashes: int
    assistant_answers: int
    tokens_in: float | None
    tokens_out: float | None
    token_in_samples: int
    token_out_samples: int
    cost_usd: float | None
    cost_label: str
    cost_samples: int
    observations: int
    first_seen: datetime | None
    last_seen: datetime | None


@dataclass(frozen=True)
class ReleaseComparison:
    """Release rows and pooled totals, with explicit cap and conversion disclosure."""

    rows: tuple[ReleaseMetrics, ...]
    total: ReleaseMetrics
    truncated: bool
    limit: int
    cost_note: str | None
