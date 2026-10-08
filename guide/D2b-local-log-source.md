# D2b: Local log file source

Branch: `dash/D2b-local-logs` · PR into `main` · PR title: `feat(sources): read telemetry from the backend's local json log file`

## Goal

Let the console show real telemetry from the backend running on your own PC, with no Google Cloud project. A third `TelemetrySource`, `LocalLogSource`, reads the JSON log lines that the backend writes when `LOG_FORMAT=json` (main repo step M2) and that you save to a file.

This source is for local development. It is not a replacement for `GcpSource`: it has no traces (they go to Cloud Trace or the local Grafana stack), no Error Reporting groups and no Cloud Run platform logs. Pages must say so clearly instead of showing empty sections as if nothing happened.

Done when: with the backend writing to a file and `SOURCE=local`, a request made to the backend appears on the Requests page within the cache lifetime; malformed and non-contract lines are counted and shown, not silently dropped; all tests pass with no network.

## Before you start

- D1 and D2 must be merged. Read `app/sources/base.py`, `app/sources/fixture_source.py`, `app/sources/cached.py`, `app/sources/factory.py`, `app/contract.py` and `app/config.py`.
- Read `guide/telemetry-contract.md` section 1 (the line format).
- Real data needs the main repo's step M2 (JSON logs). Until then, test only with files you write in tests.

## How the owner produces the file (put this in the README)

From the main repo's `ai/` folder:

```bash
# macOS or Linux
LOG_FORMAT=json uv run uvicorn backend.app.main:app 2>&1 | tee ../logs/api.jsonl
```

```powershell
# Windows PowerShell
$env:LOG_FORMAT="json"; uv run uvicorn backend.app.main:app 2>&1 | Tee-Object -FilePath ..\logs\api.jsonl -Append
```

Then in this repo: `SOURCE=local LOCAL_LOG_PATH=<full path to api.jsonl> uv run uvicorn app.main:app --port 8090`.

## Settings (`app/config.py`)

- `source` becomes `Literal["fixture", "local", "gcp"]`.
- `local_log_path: Path | None = None`. Required when `source` is `local`; validate this, like `gcp_project_id` for `gcp`.
- `local_log_max_bytes: int = 50_000_000` (1 MB to 1 GB). Only the last this-many bytes of the file are read, so a long-running log never makes a page slow. When the read starts mid-file, drop the first partial line.
- Add all three to `.env.example` with comments.

## LocalLogSource (`app/sources/local_log_source.py`)

- Constructor takes the path, the max bytes, the loaded contract and a clock.
- Reads the file lazily and re-reads only when its size or modification time changed since the last read (check with `Path.stat()` on each call; this is cheap). Keep the parsed events in memory between reads.
- Parsing, line by line:
  - Not valid JSON (for example a uvicorn start-up line written before logging is configured): count it as `skipped_non_json`.
  - Valid JSON but fails `validate_event`: count it as `skipped_invalid` and keep the first 5 error messages for display.
  - Otherwise convert with `TelemetryEvent.from_log_line`.
- `events(query)`: same filtering, ordering and limit as `FixtureSource`. Move the shared in-memory filter into one function in `app/sources/filtering.py` and use it from both sources; do not copy it. `FixtureSource` tests must still pass unchanged.
- `trace(trace_id)`: always `None`.
- `error_groups(window)`: built from `app.crash` events in the window, grouped by `exception_type`: count, first seen, last seen, routes, and the first line of the message. Group ID is the exception type.
- `platform_events(window)`: always an empty list.
- `capabilities() -> SourceCapabilities`: a new frozen dataclass in `app/domain/models.py` with `traces: bool`, `error_reporting: bool`, `platform_events: bool`. `LocalLogSource` returns all three False; `FixtureSource` and `GcpSource` return all True. Add `capabilities()` to the `TelemetrySource` protocol and to `CachedSource` (passes through, not cached).
- `read_stats() -> LocalReadStats`: lines read, events kept, `skipped_non_json`, `skipped_invalid`, the sample errors, file size, last modified, and whether the read was truncated by `local_log_max_bytes`.
- A missing file raises `SourceUnavailableError("local_log", "<path> not found")`, so pages show the existing banner.

## Page changes (small)

- Where a page would show traces, Error Reporting groups or platform events, check `capabilities()` and, if unsupported, show one line: "Not available from a local log file. Shown when the console reads Google Cloud." Never show an empty table in that case.
- The request detail page: no waterfall when `traces` is False; the log timeline still shows.
- A small status line in the page footer when `source` is `local`: file path, events kept, skipped lines (as a link to `GET /source`).
- `GET /source` (new router `app/routers/source.py`): source name, capabilities, and for `local` the full `read_stats()` including the sample validation errors. Add it to the footer, not the main nav.

## Tests to write first

- `tests/sources/test_local_log_source.py`, using files written to `tmp_path`:
  - valid lines become events; non-JSON and invalid lines are counted, not raised; sample errors capped at 5;
  - the file is re-read after it grows (append a line, change mtime) and not re-read when unchanged (count reads with a small wrapper or a spy on the reading function);
  - truncation: with a small `local_log_max_bytes` only the tail is read and the partial first line is dropped;
  - `error_groups` from `app.crash` lines; `trace` is None; `platform_events` is empty;
  - missing file raises `SourceUnavailableError`.
- `tests/sources/test_filtering.py`: the shared filter, moved from the fixture source tests where it fits.
- `tests/sources/test_factory.py`: `source="local"` builds a cached `LocalLogSource`; missing path fails settings validation.
- `tests/routers/test_source.py`: `/source` for `fixture` and for `local`.
- Router tests for the "not available from a local log file" line on the request detail page and the Errors page.

## Do not

- Do not watch the file with threads or file-system events; the stat check on each read is enough.
- Do not write to the log file or move it.
- Do not add dependencies.

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
