# D6: Data and jobs page, and the access page

Branch: `dash/D6-data-access` · PR into `main` · PR title: `feat(ui): add the data and access pages`

## Goal

Two pages. **Data and jobs** answers "is the data fresh, and did the daily refresh and downloads work?". **Access** answers "is anyone abusing the API?".

Done when: with the fixture source, Data shows the failed and the successful refresh, the fallback to previous data, freshness per league and download retries; Access shows the failed sign-in run ending in a lockout and the 429 burst from one client.

## Read first

- `guide/telemetry-contract.md`: `refresh.run`, `data.freshness`, `fallback`, `dependency.call` (`football_data`, `openfootball`), `retry`, `auth.event`, `ratelimit.rejected`.
- The shared window picker and `app/services/stats.py`.

## Data and jobs page (`GET /data`)

1. Window picker; default 7 days on this page.
2. **Freshness:** one row per league (`competition`): matches through, age in hours, the same green, amber, red thresholds as the Overview (reuse the Settings values and the helper; do not copy the thresholds).
3. **Refresh runs:** newest first: time, status, duration, dataset, error. A failed run shows the matching `fallback` lines next to it (same time, within 5 minutes after).
4. **Downloads:** per dependency (`football_data`, `openfootball`): attempts, failures by status, retries, and the last error.
5. **Component reloads:** `component.load` events that happened after a refresh (not at startup), with status.

## Access page (`GET /access`)

1. Window picker; default 24 hours.
2. **Sign-ins:** counts by `outcome` for `action=sign_in`; a chart of failed sign-ins per interval.
3. **Lockouts and blocks:** list of `locked_out` and `blocked` outcomes with time and `user_ref`.
4. **Rate limiting:** 429 count per interval and the top 10 `client_ref` values with counts and routes.
5. **Invites and consent:** counts of `redeem_invite` and `consent` outcomes.
6. **Guardrails:** when any `guardrail.event` exists in the window, counts by `kind` and `outcome`; otherwise the section is not rendered at all.

## Where the logic goes

- `app/services/data_jobs.py` and `app/services/access.py`, each with one public `build(window)` method.
- Move the freshness colour rule into `app/services/freshness.py` and use it from both Overview and Data (update the Overview to import it; its tests must still pass).
- View models in `app/domain/`, routers in `app/routers/`. Add "Data" and "Access" to the nav (the nav now has all six pages).

## Tests to write first

- Freshness rule at each threshold boundary.
- Matching a failed refresh with its fallback (inside and outside the 5-minute window).
- Top clients ordering and ties (ties sorted by `client_ref` for determinism).
- Guardrail section absent with no events, present with one.
- Router tests for both pages.

## Do not

- Do not show emails, IP addresses or account IDs. Only `user_ref` and `client_ref`, which are already hashed.

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
