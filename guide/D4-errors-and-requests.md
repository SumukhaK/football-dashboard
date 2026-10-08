# D4: Errors, crashes and the request explorer

Branch: `dash/D4-errors-requests` · PR into `main` · PR title: `feat(ui): add the errors page and the request explorer`

## Goal

Two pages. **Errors** answers "what broke, how often, since when?". **Requests** answers "what happened to this one request?", from a search down to its trace waterfall with its log lines beside it.

Done when: from the Overview, clicking the 5xx count opens Requests filtered to 5xx; clicking a chat request opens its detail with the trace waterfall showing the two `retry` events from the fixtures; the Errors page lists the fixture error groups and the out-of-memory platform event.

## Read first

- `guide/telemetry-contract.md` sections 1 to 4.
- `app/services/overview.py` and `app/services/stats.py` (reuse `stats`, do not duplicate it).

## Errors page (`GET /errors`)

1. Window picker, same as the Overview (move the picker into a shared partial if it is not already).
2. **Crash groups** from `source.error_groups(window)`: exception type, message (first line only), count, first seen, last seen, routes. Sorted by last seen. Each row links to Requests filtered to `app.crash` for that window.
3. **Handled errors** from `app.error` events: grouped by `error_code` and `route`, with count, status, last seen, and a sparkline of counts per interval (small ECharts line).
4. **Platform events** from `source.platform_events(window)`: out-of-memory, container exits, failed starts, instance starts, newest first, with revision. Out-of-memory and failed starts are highlighted.
5. **Degraded components** from `component.degraded`: component, route, count.

## Requests page (`GET /requests`)

- Filters as query parameters: `hours`, `route`, `status` (`2xx`, `4xx`, `5xx` or an exact code), `event` (`app.crash`, `retry`, `fallback`, `ratelimit.rejected`), `request_id`. Filters are in a form that submits with HTMX and updates the URL.
- Results table from `http.request` events: time, method, route, status, duration, error code, request ID. Newest first, 100 per page with "Load more" (HTMX, `limit` and a `before` timestamp cursor).
- When `event` is set, show requests whose `request_id` has that event (two queries: the event, then `http.request` for those IDs).
- A request ID typed into the search box goes straight to the detail page.

## Request detail (`GET /requests/{request_id}`)

- Validate `request_id` with `^[A-Za-z0-9._-]{8,64}$`; otherwise 422 structured error.
- Summary: route, status, duration, revision, error code, user ref if present.
- **Timeline:** every log line for that request ID, oldest first, with severity, event, message and attributes (attributes as a small key-value list).
- **Trace waterfall** when the lines carry a `trace_id`: spans as horizontal bars on a shared time axis, indented by depth, with name and duration; span events (`retry`) as markers on their span. Hover shows attributes. Build the bar geometry in a service, not in the template or JavaScript: the service returns rows with `depth`, `offset_ms`, `duration_ms`, `name`, `markers`.
- "Copy request ID" button and a link to the same trace in the Google Cloud console when `source` is `gcp` (`https://console.cloud.google.com/traces/list?project=<id>&tid=<trace_id>`).

## Where the logic goes

- `app/services/errors.py`: `ErrorsService.build(window) -> ErrorsModel`.
- `app/services/requests.py`: `RequestsService.search(filters) -> RequestPage` and `RequestsService.detail(request_id) -> RequestDetail | None`.
- `app/services/waterfall.py`: pure `build_waterfall(trace) -> list[WaterfallRow]`.
- Domain view models in `app/domain/errors.py` and `app/domain/requests.py`.
- Routers: `app/routers/errors.py`, `app/routers/requests.py`. Add "Errors" and "Requests" to the nav.

## Tests to write first

- `test_waterfall.py`: depth and offsets for a three-level trace; span events become markers at the right offset; a trace with spans out of order; a single-span trace.
- `test_requests.py`: each filter; status class parsing (`5xx`, `503`, invalid → `ValueError`); event-based filter; pagination cursor; detail for a known fixture request with its timeline and trace; unknown ID returns `None`.
- `test_errors.py`: grouping by code and route; platform events sorted; degraded counts.
- Router tests: 200 pages; 404 page (structured body) for an unknown request ID; 422 for an invalid one; the Overview's 5xx link lands on a filtered list.

## Do not

- Do not show raw request bodies or query strings; the contract forbids logging them, so never add fields for them.
- Do not fetch more than 5,000 lines for one page; show "narrow the filter" when the limit is hit.

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
