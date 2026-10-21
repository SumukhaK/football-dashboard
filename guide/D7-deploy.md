# D7: Deploy the console to Cloud Run

**Execution: Done — implementation and staging deployment.** [PR #14](https://github.com/SumukhaK/football-dashboard/pull/14) delivered D7, [PR #29](https://github.com/SumukhaK/football-dashboard/pull/29) preserved redeploy settings, and [PR #33](https://github.com/SumukhaK/football-dashboard/pull/33) added D9.5 deployment safety. Status checked 20 October 2026.

Live narrow IAM, named deployment, private-first rollback and subsequent owner-login launch are recorded in [D9.6](D9.6-live-verification.md). An actual trace-data smoke read under the narrow role is not recorded there and remains a separate check. The original proxy/denied-write evidence is historical, not a fresh claim about every write permission.

The stage specification below predates D9 and testing-gaps C1–C3. Use the current [deployment runbook](../deploy/README.md) for execution. Since [PR #63](https://github.com/SumukhaK/football-dashboard/pull/63), `deploy/deploy.sh` only creates a private candidate with no traffic; `deploy/promote.sh <revision> <sha256:digest>` serves it after the operator's recorded checks and a configuration readback; `deploy/rollback.sh <revision> [digest]` restores privately unless the target passes the same checks. The `--to-latest` steps and tests described below are historical and must not be followed; app-auth transport opens only at the end of a verified promotion.

Branch: `dash/D7-deploy` · PR into `main` · PR title: `chore(deploy): run the console privately on cloud run`

## Goal

Package the console as a container and run it on Google Cloud Run in the same project as the API: private, scaling to zero, reading telemetry with a read-only service account. Scaling to zero reduces idle compute; registry, storage and other resources can still incur charges.

Done when: `gcloud run services proxy football-dashboard --region <region>` opens the console with `SOURCE=gcp` and real data from the staging API; an unauthenticated request to the service URL gets 403; the service account cannot write anything (shown by a denied `gcloud logging write` while impersonating it).

## D9 access-control dependency

[D9](D9-owner-login.md) is implemented and its controlled launch is recorded in [D9.6](D9.6-live-verification.md). Private IAM/proxy remains the default for unverified deployments. Explicit app-auth transport opens login/callback while the verified owner guard protects data. Never expose a pre-auth revision. Keep invites disabled in cloud; a hosted invite writer needs separate least-privilege approval.

## Before you start (needs the owner)

This step needs the GCP project from the main repo's hosting tracker step 0, and the API running on Cloud Run from tracker step 1. If either is missing, stop and say so. Ask the owner for the project ID and region; never guess them and never commit them. They go in `deploy/.env.deploy` (gitignored) with a committed `deploy/.env.deploy.example`.

## What to build

- `Dockerfile`: `python:3.12-slim`, install with `uv` from the lock file (`uv sync --frozen --no-dev`), non-root user, copy only `app/`, `contract/`, `pyproject.toml`, `uv.lock`. Do not copy `fixtures/`, `tests/` or `scripts/`. Run `uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080}` with one worker. Add `.dockerignore`.
- `deploy/setup_service_account.sh`: creates service account `football-dashboard-reader`, defines the project custom role `footballDashboardTraceReader` from the committed `deploy/trace-reader-role.yaml`, and grants exactly that role plus `roles/logging.viewer` and `roles/errorreporting.viewer` on the project. Nothing else. No predefined role gives read-only Trace access — `roles/cloudtrace.user` also carries Trace task and scope mutations — so the custom role is defined by permission, and its only permission is `cloudtrace.traces.get`, the single Cloud Trace call the console makes. The script also removes a `roles/cloudtrace.user` binding from the reader if one exists, because binding the narrow role does not take the broad one away; it binds the narrow role first, so the removal cannot interrupt the console. Idempotent (safe to run twice). `set -euo pipefail`. Reads project and region from `deploy/.env.deploy`.
- `deploy/deploy.sh`: builds with Cloud Build into Artifact Registry, deploys by image digest with: `--no-allow-unauthenticated`, `--invoker-iam-check`, `--service-account football-dashboard-reader@...`, `--min-instances 0`, `--max-instances 1`, `--cpu 1`, `--memory 512Mi`, `--concurrency 20`, `--timeout 60`, env `SOURCE=gcp`, `GCP_PROJECT_ID`, `API_SERVICE_NAME=football-api`, `CACHE_TTL_SECONDS=60`. Cloud Run is public two independent ways (an `allUsers` binding and a disabled invoker IAM check), so ask for both and then read the service back to confirm neither is in effect before reporting success. Finish with `gcloud run services update-traffic ... --to-latest`, because Cloud Run keeps a rollback's traffic pin across later deployments. Prints the proxy command at the end.
- `deploy/README.md`: one-time setup, deploy, open with the proxy, roll back to the previous revision, delete everything (service, image repository, service account, custom role), and a note that page views make read API calls. Document current pricing and measure usage; personal use and scale-to-zero do not guarantee a zero bill.
- A budget note: the main repo's $10 budget alert covers this project; this step adds no new paid service.
- `.github/workflows/ci.yml`: add a job that builds the Docker image (no push) so a broken Dockerfile fails CI.

## Startup check

At startup with `source=gcp`, log one line saying which project and service the console reads, and fail fast with a clear message if `gcp_project_id` is missing. Do not call Google APIs at startup (cold starts stay fast).

## Tests to write first

- A test that the app starts with `source=gcp` and a fake project ID without any network call (the source is built lazily or the readers take injected clients).
- A test that `deploy/trace-reader-role.yaml` grants only `cloudtrace.traces.get` and no Trace task, scope or span mutation permission, and that `deploy/setup_service_account.sh` hands out only `roles/logging.viewer`, `roles/errorreporting.viewer` and that custom role — parse the `add-iam-policy-binding` statements, and do not settle for searching role names for "writer".
- Behavioural tests that run both scripts against a fake `gcloud` first on `PATH` and check the commands that would reach Google Cloud: the deploy asks for both `--no-allow-unauthenticated` and `--invoker-iam-check`, promotes the revision it just made with `--to-latest`, and issues no deploy or traffic command after a failed build or deploy.
- Shell scripts pass `shellcheck` (add it to CI with the `ludeeus/action-shellcheck` action, pinned by version).

## Do not

- Do not use `--allow-unauthenticated`. The console shows operational data and must stay private.
- Do not create a service account key file or put credentials in the image or repo.
- Do not grant `roles/viewer`, `roles/editor`, any write role, or the predefined `roles/cloudtrace.user` (it carries Trace task and scope mutations, even though it cannot write spans).
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
