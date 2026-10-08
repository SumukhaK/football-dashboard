# D7: Deploy the console to Cloud Run

Branch: `dash/D7-deploy` · PR into `main` · PR title: `chore(deploy): run the console privately on cloud run`

## Goal

Package the console as a container and run it on Google Cloud Run in the same project as the API: private, scaling to zero, reading telemetry with a read-only service account. Total cost while unused: nothing.

Done when: `gcloud run services proxy football-dashboard --region <region>` opens the console with `SOURCE=gcp` and real data from the staging API; an unauthenticated request to the service URL gets 403; the service account cannot write anything (shown by a denied `gcloud logging write` while impersonating it).

## Before you start (needs the owner)

This step needs the GCP project from the main repo's hosting tracker step 0, and the API running on Cloud Run from tracker step 1. If either is missing, stop and say so. Ask the owner for the project ID and region; never guess them and never commit them. They go in `deploy/.env.deploy` (gitignored) with a committed `deploy/.env.deploy.example`.

## What to build

- `Dockerfile`: `python:3.12-slim`, install with `uv` from the lock file (`uv sync --frozen --no-dev`), non-root user, copy only `app/`, `contract/`, `pyproject.toml`, `uv.lock`. Do not copy `fixtures/`, `tests/` or `scripts/`. Run `uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080}` with one worker. Add `.dockerignore`.
- `deploy/setup_service_account.sh`: creates service account `football-dashboard-reader` and grants exactly `roles/logging.viewer`, `roles/cloudtrace.user`, `roles/errorreporting.viewer` on the project. Nothing else. Idempotent (safe to run twice). `set -euo pipefail`. Reads project and region from `deploy/.env.deploy`.
- `deploy/deploy.sh`: builds with Cloud Build into Artifact Registry, deploys by image digest with: `--no-allow-unauthenticated`, `--service-account football-dashboard-reader@...`, `--min-instances 0`, `--max-instances 1`, `--cpu 1`, `--memory 512Mi`, `--concurrency 20`, `--timeout 60`, env `SOURCE=gcp`, `GCP_PROJECT_ID`, `API_SERVICE_NAME=football-api`, `CACHE_TTL_SECONDS=60`. Prints the proxy command at the end.
- `deploy/README.md`: one-time setup, deploy, open with the proxy, roll back to the previous revision, delete everything (service, image repository, service account), and a note that every page view makes a few read API calls, which stay inside the free allowances at personal use. Tell the owner to confirm free allowances on the current Google Cloud pricing pages.
- A budget note: the main repo's $10 budget alert covers this project; this step adds no new paid service.
- `.github/workflows/ci.yml`: add a job that builds the Docker image (no push) so a broken Dockerfile fails CI.

## Startup check

At startup with `source=gcp`, log one line saying which project and service the console reads, and fail fast with a clear message if `gcp_project_id` is missing. Do not call Google APIs at startup (cold starts stay fast).

## Tests to write first

- A test that the app starts with `source=gcp` and a fake project ID without any network call (the source is built lazily or the readers take injected clients).
- A test that `deploy/setup_service_account.sh` grants only the three roles: parse the script for `--role=` values and compare with the exact set.
- Shell scripts pass `shellcheck` (add it to CI with the `ludeeus/action-shellcheck` action, pinned by version).

## Do not

- Do not use `--allow-unauthenticated`. The console shows operational data and must stay private.
- Do not create a service account key file or put credentials in the image or repo.
- Do not grant `roles/viewer`, `roles/editor` or any write role.
- Do not set min instances above 0.

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
