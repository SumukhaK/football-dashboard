# D5: Assistant page

Branch: `dash/D5-assistant` · PR into `main` · PR title: `feat(ui): add the assistant page`

## Goal

One page that answers "is the assistant healthy and affordable?": how questions are answered, how often tools fail, how often calls to the model are retried or fall back, how many tokens and how much money each answer costs, and where the time goes.

Done when: with the fixture source the page shows the split between router and model answers, the tool error rate per tool, the `ollama_chat` retries and the given-up request, and the slowest answers link to their request detail page.

## Read first

- `guide/telemetry-contract.md`: `assistant.answer`, `assistant.tool`, `assistant.abstain`, `dependency.call`, `retry`, `fallback`, and section 4 (span names).
- `app/services/stats.py`, `app/services/requests.py`.

## What the page shows (`GET /assistant`)

1. Window picker (shared partial).
2. **Answers:** total, split by `path` (`router`, `model`, `model_with_tools`) as a donut chart, abstentions by `reason`, and the abstention rate.
3. **Latency:** p50 and p95 of `assistant.answer.duration_ms` per path. Time split from traces is optional here; use the events only.
4. **Tools:** table per tool: calls, error rate, p95 duration, last error message. Sorted by error rate.
5. **Model calls:** from `dependency.call` where `dependency` is `ollama_chat`, `ollama_embed` or `workers_ai`: attempts, failure rate by `status` (timeout, http_error, connection_error), retries (from `retry`), requests that gave up (a request whose last attempt for that dependency failed).
6. **Fallbacks:** count by `from_path` → `to_path` with cause, including `tool_calling` → `answer_without_tools`.
7. **Tokens and cost:** prompt and completion tokens per answer (p50, p95, total) and `cost_usd` total and per answer. When every value is null (local Ollama), show "Not reported by the current model provider" instead of zeros.
8. **Slowest answers:** top 10 by duration with path, tool rounds and a link to `/requests/{request_id}`.

## Where the logic goes

- `app/services/assistant.py`: `AssistantService.build(window) -> AssistantModel`, with private helpers per section, each under 40 lines. Split into `assistant_answers.py` and `assistant_calls.py` if the file nears 300 lines.
- "Gave up" detection is a pure function `gave_up_requests(calls: list[TelemetryEvent]) -> set[str]`, unit tested on its own.
- `app/domain/assistant.py` for view models. `app/routers/assistant.py`. Add "Assistant" to the nav.

## Tests to write first

- `gave_up_requests`: a request with two failures then success (not gave up); three failures (gave up); calls from two requests interleaved.
- Path split, abstention rate, tool error rate and the null-tokens case, each on small hand-written event lists.
- Router: 200 page containing each section heading; fixture shows the given-up request linked.

## Do not

- Do not show question or answer text. The contract forbids it; the page shows only `question_chars`.
- Do not estimate cost when `cost_usd` is null.

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
