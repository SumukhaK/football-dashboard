# D3: Overview page

Branch: `dash/D3-overview` · PR into `main` · PR title: `feat(ui): add the overview page`

## Goal

One page that answers "is anything wrong right now?" in under five seconds of looking. It is the console's home page (`GET /`).

Done when: with the fixture source, the page shows the failed assistant load from the fixtures as a red tile, the refresh fallback as an amber tile, and the traffic and error charts for the last 24 hours; every number links to the filtered request list (the link target is added in D4, so link to `/requests?...` now and D4 makes it work).

## Read first

- `guide/telemetry-contract.md` sections 3 and 5.
- `app/sources/base.py`, `app/domain/models.py`, `app/templates/base.html`.

## What the page shows (top to bottom)

1. **Window picker:** 1 hour, 6 hours, 24 hours (default), 7 days. Changing it reloads the page body with HTMX (`hx-get`, `hx-target`, `hx-push-url="true"`), so the URL holds the choice (`?hours=24`).
2. **Component tiles:** one tile per component from the contract (`prediction_model`, `prediction_model_v1`, `explanation`, `assistant`, `season_history`, `season_outlook`, `fixtures`, `match_history`, `goals_model`), plus `daily_refresh` and `data_freshness`.
   - Component status = the latest `component.load` for it: ok is green, degraded is amber, failed is red, none seen in the window is grey "no data".
   - Any `component.degraded` for it in the window makes a green tile amber, with the count.
   - `daily_refresh`: latest `refresh.run`; red if the last two runs failed, amber if the last one failed, green otherwise.
   - `data_freshness`: worst `age_hours` over leagues; green under 36, amber 36 to 72, red over 72. Thresholds live in Settings.
   - Each tile shows its reason or error text and "since <time>".
3. **Headline numbers:** requests, error rate (status >= 500 divided by all), p95 latency, crashes (`app.crash`), 429s, retries, fallbacks. Each with the change against the previous window of the same length.
4. **Charts (ECharts):** requests per interval stacked by status class (2xx, 4xx, 5xx); p50 and p95 latency per interval as lines. Interval: 1 minute for 1 hour, 5 minutes for 6 hours, 15 minutes for 24 hours, 2 hours for 7 days.
5. **Slowest routes:** table of route, requests, p95, error rate, sorted by p95, top 10.
6. **Last refreshed** time and a "Refresh" button (HTMX reload of the body).

## Where the logic goes

- `app/services/overview.py`: `OverviewService(source, clock, settings)` with one public method `build(window) -> OverviewModel`. Small private helpers, each under 40 lines: `component_tiles`, `headline_numbers`, `traffic_series`, `latency_series`, `slowest_routes`.
- `app/services/stats.py`: pure functions `percentile(values, q)` (nearest-rank, documented), `bucket_by_interval(events, window, interval)`, `rate(numerator, denominator)` (returns `None` when the denominator is 0, never divides by zero).
- `app/domain/overview.py`: the frozen view models (`ComponentTile`, `TileState` enum, `HeadlineNumber`, `Series`, `RouteRow`, `OverviewModel`).
- `app/routers/overview.py`: `GET /` (full page) and `GET /partials/overview` (body only, for HTMX). The route calls the service and renders; nothing else.
- Templates: `templates/overview.html`, `templates/partials/overview_body.html`, `templates/partials/tile.html`. Charts get their data through a `<script type="application/json">` block rendered with Jinja's `tojson`, read by `static/charts.js` (keep under 120 lines). No inline event handlers.
- Add "Overview" to the nav list.

## Accessibility and look

- Tile colour is never the only signal: each tile also shows the word ok, degraded, failed or no data.
- Works at 360 px wide (tiles wrap; tables scroll horizontally inside their own box).
- Light and dark themes through CSS variables.

## Tests to write first

- `tests/services/test_stats.py`: percentile on known lists (including one value and empty list returning `None`); bucketing at window edges; rate with zero denominator.
- `tests/services/test_overview.py`: using `FixtureSource` with a fixed `now`, the assistant tile is failed with its reason; the refresh tile is amber; the error rate equals a hand-computed value from a small hand-written event list (write a tiny in-test source for this, not the big fixture); comparison with the previous window; empty window gives "no data" tiles and `None` rates without errors.
- `tests/routers/test_overview.py`: `GET /` returns 200 and contains each component name and the words "failed" and "degraded"; `GET /partials/overview?hours=1` returns only the body; an invalid `hours` returns 422 with the structured error body `{"error": ..., "detail": ...}`.
- `SourceUnavailableError` from the source renders the page with a clear banner and status 200, not a 500.

## Do not

- No spend or budget panel in this step (it needs a billing export that does not exist yet).
- No auto-refresh timer; the button is enough and keeps Google API reads low.

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
