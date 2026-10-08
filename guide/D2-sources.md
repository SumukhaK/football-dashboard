# D2: Telemetry sources (fixture and Google Cloud)

Branch: `dash/D2-sources` · PR into `main` · PR title: `feat(sources): read telemetry from fixtures and google cloud`

## Goal

Implement the one interface every page reads from, with two implementations: `FixtureSource` (sample files, used in tests and offline) and `GcpSource` (Cloud Logging, Cloud Trace and Error Reporting, read-only). Add a time-based cache in front of either.

Done when: all source tests pass with no network; `GcpSource` builds correct Cloud Logging filters (unit tested as pure functions); a manual check against a real project is documented in the README but not required for the PR.

## Read first

- `guide/telemetry-contract.md` (sections 1, 3 and 4).
- `app/domain/models.py`, `app/sources/base.py`, `app/contract.py`, `fixtures/README.md` from D1.

## The interface (`app/sources/base.py`)

```python
class TelemetrySource(Protocol):
    """Read-only access to the backend's telemetry."""

    def events(self, query: EventQuery) -> list[TelemetryEvent]: ...
    def trace(self, trace_id: str) -> Trace | None: ...
    def error_groups(self, window: TimeWindow) -> list[ErrorGroup]: ...
    def platform_events(self, window: TimeWindow) -> list[PlatformEvent]: ...
```

`EventQuery` (in `app/domain/models.py`): `window: TimeWindow`, `events: tuple[str, ...]` (empty means all), `request_id: str | None`, `route: str | None`, `min_status: int | None`, `limit: int` (1 to 5,000, default 1,000). Results are newest first.

## FixtureSource (`app/sources/fixture_source.py`)

- Reads the four fixture files once at construction.
- Filters in memory exactly as the query says.
- Re-bases time: an optional `now` argument shifts every fixture timestamp so the newest fixture line equals `now`. This makes local runs show "the last 24 hours". Default: no shift. Tests pass a fixed `now`.

## GcpSource (`app/sources/gcp/`)

Split into small modules: `filters.py` (pure functions), `logging_reader.py`, `trace_reader.py`, `errors_reader.py`, `platform_reader.py`, `source.py` (composes them).

Dependencies to add (exactly these): `google-cloud-logging`, `google-cloud-trace`, `google-cloud-error-reporting`. Authentication uses Application Default Credentials only (`gcloud auth application-default login` locally, the service account on Cloud Run). Never accept a key file path in settings.

**Cloud Logging filters** (`filters.py`, pure, fully unit tested):

- Base: `resource.type="cloud_run_revision" AND resource.labels.service_name="<api_service_name>"`.
- Time: `timestamp>="<start RFC 3339>" AND timestamp<"<end RFC 3339>"`.
- Events: `jsonPayload.event=("http.request" OR "app.error")`.
- Request ID: `jsonPayload.request_id="<id>"`. Route: `jsonPayload.attributes.route="<template>"`. Status: `jsonPayload.attributes.status>=<n>`.
- Escape double quotes and backslashes in every value. Reject a `request_id` that does not match `^[A-Za-z0-9._-]{8,64}$` and a route that does not start with `/`, with `ValueError`.
- Order newest first; page through results until `limit`.

**Cloud Trace** (`trace_reader.py`): use the v1 `TraceServiceClient.get_trace(project_id, trace_id)`; map spans to the domain `Span` (parent IDs, labels to attributes). Span events are not in the v1 API; map labels whose names start with `retry.` into `SpanEvent`s if present, otherwise leave events empty. Return `None` on NotFound.

**Error Reporting** (`errors_reader.py`): `ErrorStatsServiceClient.list_group_stats` for the project, filtered by service `football-api` and the window's time range (pick the smallest `TimeRangePeriod` that covers the window). Map to `ErrorGroup`. Routes come from the group's representative event context when available, otherwise empty.

**Platform events** (`platform_reader.py`): read Cloud Run system and request logs for the service and classify text with a configurable list of `(pattern, kind)` pairs in Settings (`platform_patterns`). Defaults: `"Memory limit of"` → `out_of_memory`; `"Container called exit"` → `container_exit`; `"failed to start and listen"` → `startup_failed`; `"Starting new instance"` → `instance_started`. Note in the README that these strings must be checked against real logs after the first deploy.

**Errors from Google APIs:** permission denied, quota and unavailable errors become one domain error `SourceUnavailableError(kind, detail)`. Pages show a clear message; they never show a stack trace.

## Cache (`app/sources/cached.py`)

`CachedSource(inner, ttl_seconds, clock)` implements the same protocol. Cache key is the full query (frozen dataclasses are hashable). Expired entries are replaced on next read. `ttl_seconds=0` disables caching. Bounded to 256 entries (least recently used out). No background threads.

## Wiring

`app/sources/factory.py`: `build_source(settings, clock) -> TelemetrySource` returns `CachedSource(FixtureSource(...))` or `CachedSource(GcpSource(...))`. `create_app` stores it in `app.state`; a dependency function `get_source(request)` returns it for routers.

## Tests to write first

- `tests/sources/test_fixture_source.py`: each filter alone and combined; limit; newest first; time re-basing.
- `tests/sources/gcp/test_filters.py`: each filter piece; combination; escaping; rejected inputs.
- `tests/sources/gcp/test_*_reader.py`: each reader with the Google client replaced by a small fake object passed into the constructor (no `unittest.mock.patch` on module paths); mapping of fields; NotFound and PermissionDenied handling.
- `tests/sources/test_cached.py`: hit, expiry with an injected clock, zero TTL, eviction at 257 entries.
- `tests/sources/test_factory.py`: picks the right source from settings.

## Do not

- Do not call Cloud Monitoring or Billing APIs; metrics are computed from events in later steps.
- Do not write to any Google API.
- Do not add a database or any other cache store.

## Repo rules (apply to every file you write)

- Python 3.12, managed with `uv`. Formatting with Black (line length 88), linting with Ruff, types with mypy in strict mode.
- Type annotations on every function signature. No `Any` unless a third-party API forces it, with a comment saying why.
- Every public module, class and function has a one-line docstring.
- No file over 400 lines. No function over 40 lines. Split before you reach either.
- One concern per function. If a function name needs "and", split it.
- No wildcard imports, no mutable default arguments, no global mutable state. Configuration comes only from `app/config.py` (pydantic-settings), never from `os.environ` directly.
- Layering: `app/domain` imports nothing from the app; `app/sources` imports `app/domain`; `app/services` imports `app/domain` and the `TelemetrySource` protocol; `app/routers` import services only. Routers stay thin: no calculations in routes or templates.
- Comments explain why, not what. No commented-out code. No `TODO` without a linked GitHub issue.
- No placeholder code, no fake data paths in production code, no "coming soon" pages. Build the real thing or leave it out.
- The console is read-only. It never writes, deletes or changes anything in Google Cloud.
- Never print or store secrets. `.env` is gitignored; `.env.example` is committed.
- Tests live in `tests/`, mirroring `app/` (`app/services/overview.py` is tested in `tests/services/test_overview.py`). Tests are deterministic: no real clock (inject one), no network, no random without a fixed seed.
- Coverage of at least 80% (`fail_under = 80`).
- Commits use Conventional Commits: `type(scope): description`, lowercase, imperative, no full stop. Types: feat, fix, chore, docs, test, refactor. Scopes: app, sources, ui, ci, deploy, docs, contract.
- Do not add a dependency that this step does not list. If you think one is needed, stop and say why.

## Commands that must pass before you finish

```bash
uv sync --extra dev
uv run ruff check .
uv run black --check .
uv run mypy app tests
uv run pytest --cov=app --cov-report=term-missing
```

If any command fails, fix the code. Never delete, skip or weaken a test to make it pass.
