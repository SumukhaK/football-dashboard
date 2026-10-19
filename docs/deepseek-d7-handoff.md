# Dashboard D7 verification and implementation handoff for DeepSeek

Verified: 19 October 2026. Status: implementation instructions; no cloud changes applied.

The main D7 concerns in the supplied note are true, including the live IAM gap.
Several backlog statements are stale. This document records the checked facts
and gives DeepSeek an ordered implementation plan.

## Scope and repositories

This document belongs to `SumukhaK/football-dashboard`, locally at
`D:/Anthropic/TestProjects/football-dashboard`. Dashboard PRs target `main`.
References to `SumukhaK/football-intelligence-platform` describe the separate
backend repository and use explicit cross-repository links.

Read the dashboard's `guide/D7-deploy.md`, `guide/D8-redesign.md`,
`guide/D9-owner-login.md`, `deploy/README.md` and current repository instructions
before implementing a slice. The D9 guide exists locally but is untracked.
Preserve the owner's existing README and guide edits.

The request that produced this document covers verification and documentation.
It does not authorize IAM writes, a deployment, enabling Crashlytics export,
public access or hosted-model calls. Check existing owner authorization before
requesting any missing approval. Work on one assigned slice at a time.

## 1. Verified facts and corrections

| Claim from the note | Checked result | Evidence |
|---|---|---|
| D7 was delivered | True. Dashboard PR #14 merged on 18 October. Its later fixes are in source. | [PR #14](https://github.com/SumukhaK/football-dashboard/pull/14), commits `9eb5bde` and `3cf49da`. |
| The reader probably still has the broad Trace role | Confirmed live. Its direct project bindings are `roles/cloudtrace.user`, `roles/errorreporting.viewer`, `roles/logging.viewer`. | Read-only project IAM query on 19 October. |
| The narrow custom role may be missing | Confirmed live: describing `footballDashboardTraceReader` returned `NOT_FOUND`. | Read-only IAM role query. |
| A Token Creator binding remains on the reader account | Confirmed: one such binding with one member. The original owner-member attribution is recorded in PR #14. | Service-account IAM query and PR #14. |
| The live image predates the redesigns | Confirmed: latest created/ready revision is `football-dashboard-00001-74k`, serving 100% of traffic. | Cloud Run service readback; digest `sha256:0513baf690c7afecbc35fe7ec180dea2dc72092df9558e4859f6dadb7936ade1`. |
| The console is private | Configuration remains private: no `allUsers` or `allAuthenticatedUsers` service binding; invoker IAM check is not disabled. | Service IAM and service description. A fresh HTTP denial/proxy test was not run. |
| The deployment reads staging | Confirmed: reader runtime identity, `SOURCE=gcp`, `API_SERVICE_NAME=football-api-staging`, cache TTL 60 seconds; max scale 1. | Cloud Run service description. |
| App crashes are disabled live | Confirmed: no Crashlytics project is configured on the current revision; config disables the page in that case. | Service environment and `app/config.py`. Firebase dataset/export/IAM was not audited. |
| PR #19 and PR #20 are open | At the original audit they were open at `18668a4` and `8b630d7`. At relocation, #19 is merged as `a96799a`; #20 remains open. | GitHub metadata and dashboard main history. Historical CI counts were not revalidated. |
| PR #16 is a held draft | Stale: merged on 19 October at 03:35:51 UTC; local dashboard `main` includes merge `ad4506d`. | [PR #16](https://github.com/SumukhaK/football-dashboard/pull/16) and local history. |
| D8.4 and D9 implementation remain | Supported by current main: handled errors still group by `(code, route)`, crash groups lack interval series, and owner-login code is absent. | `app/services/errors.py`, `app/domain/errors.py`, app/dependency inspection. |
| Backend M1–M6 still block real telemetry | Incorrect as an implementation claim. Contract 1.1.0, JSON logs, request IDs, events, tracing, retries and monitoring definitions already exist. | [Observability](https://github.com/SumukhaK/football-intelligence-platform/blob/develop/docs/observability/README.md), [ADR 024](https://github.com/SumukhaK/football-intelligence-platform/blob/develop/docs/adr/024-structured-telemetry-and-opentelemetry.md), and source/tests. Cloud monitoring application remains separate. |
| Real local logs still need backend M2 | Stale: M2 is implemented. Configure the backend's JSON output and dashboard `source=local`/`local_log_path`. | Dashboard README and backend formatter/middleware. |
| Project/region are in `deploy/.env.deploy` | That file is absent from the dashboard checkout inspected here. | File existence check. Read-only cloud checks used historical coordinates recorded in PR #14. |
| `/healthz` is intercepted; Docker could not build locally | Historical observations documented in PR #14; not reproduced in this review. | Keep these as dated evidence, not fresh test results or a general Cloud Run guarantee. |

Google's current role reference confirms that `roles/cloudtrace.user` includes
task and trace-scope mutations, despite its read-access description. Current
permission names include `cloudtrace.tasks.*`, `cloudtrace.traceScopes.*` and
`observability.traceScopes.*`; older comments use a different scope spelling.
See [Cloud Trace roles](https://docs.cloud.google.com/iam/docs/roles-permissions/cloudtrace).

## 2. First slice: close the live Trace IAM gap

This is an operations correction. The required implementation already exists in
`deploy/setup_service_account.sh` and `deploy/trace-reader-role.yaml`; do not
rewrite it or grant another broad role.

### Prepare and capture the starting state

1. Inspect the current dashboard branch, PR heads and local changes. Use a clean
   checkout/worktree based on the reviewed dashboard `main`; do not reset the
   owner's edits or deploy an unfinished authentication branch.
2. Restore the gitignored `deploy/.env.deploy` through the owner's private
   configuration, using `.env.deploy.example` as the shape. Confirm project and
   region; explicitly set `API_SERVICE_NAME=football-api-staging`. The script's
   default `football-api` would point this deployment at the wrong service.
3. Keep actual project/region, account email, credentials and raw policies out
   of committed evidence. Record redacted role names, revision and image digest.
4. Run the following reads from the dashboard root in Bash with that private
   file loaded. A failed policy read is an error; do not interpret it as an empty
   policy. Distinguish the expected missing custom role from access denial.

```bash
source deploy/.env.deploy
READER="football-dashboard-reader@${GCP_PROJECT_ID}.iam.gserviceaccount.com"

gcloud iam roles describe footballDashboardTraceReader \
  --project "$GCP_PROJECT_ID" --format='yaml(includedPermissions,deleted)'
gcloud projects get-iam-policy "$GCP_PROJECT_ID" \
  --flatten='bindings[].members' \
  --filter="bindings.members=serviceAccount:${READER}" \
  --format='table(bindings.role)'
gcloud iam service-accounts get-iam-policy "$READER" \
  --project "$GCP_PROJECT_ID"
gcloud run services get-iam-policy football-dashboard \
  --project "$GCP_PROJECT_ID" --region "$REGION"
gcloud run services describe football-dashboard \
  --project "$GCP_PROJECT_ID" --region "$REGION" \
  --format="yaml(status.latestReadyRevisionName,status.traffic,spec.template.spec.serviceAccountName,spec.template.spec.containers[0].image,metadata.annotations)"
```

### Apply the existing correction when authorized

```bash
bash deploy/setup_service_account.sh
```

The script creates/updates the custom role, binds it, then removes the old
`roles/cloudtrace.user` binding. Its only Trace permission must remain
`cloudtrace.traces.get`. Both the original D7 source (`1a5008f`) and current
`app/sources/gcp/trace_reader.py` call `get_trace`, consistent with that permission.
This source check does not substitute for the live smoke test below.

### Acceptance and evidence

- Re-read the role and project IAM. Expected direct reader roles: logging viewer,
  error-reporting viewer and `projects/<GCP_PROJECT_ID>/roles/footballDashboardTraceReader`.
  The broad Trace role must be absent; custom permission list exactly one entry.
- Open the existing private revision through `gcloud run services proxy`, using
  explicit project/region, and open an actual traced request. Its waterfall must
  load without a new permission error. Inspect existing trace data; no hosted-AI
  request is required for this check.
- Allow for IAM propagation and use bounded read retries. If access remains
  broken, stop and report the failing call/permission. Do not silently restore a
  broad role or grant a writer.
- Reconfirm unauthenticated denial and private configuration. Checking only
  `allUsers` is insufficient: Cloud Run also supports disabling the invoker check.
  See [Cloud Run access controls](https://docs.cloud.google.com/run/docs/authenticating/public).
- Existing denied logging-write evidence covers only that permission. Do not
  claim it proves every possible write is forbidden. A fresh live write test,
  even one expected to fail, requires the owner's authorization.

Save the date, commands, exit results and redacted before/after role lists in
dashboard `docs/`. No image redeploy is needed solely to correct IAM.

## 3. Separate slice: decide whether to retain owner impersonation

`roles/iam.serviceAccountTokenCreator` is a policy binding on the reader account;
it is not a runtime role held by the reader. Retaining it supports future
impersonation checks. Removing it is optional cleanup, not a prerequisite for
the narrow Trace role.

After an owner decision, remove only the confirmed member binding if requested:

```bash
gcloud iam service-accounts remove-iam-policy-binding "$READER" \
  --project "$GCP_PROJECT_ID" \
  --member="user:${OWNER_EMAIL}" \
  --role=roles/iam.serviceAccountTokenCreator
```

Read `OWNER_EMAIL` from confirmed private operator configuration. Re-read the
policy; preserve unrelated members/conditions. Do not remove it before a planned
impersonation check or automatically re-add it for later tests.

## 4. Separate slice: integrate and deploy the dashboard redesigns

1. [PR #19](https://github.com/SumukhaK/football-dashboard/pull/19) is merged.
   Recheck [PR #20](https://github.com/SumukhaK/football-dashboard/pull/20) against
   current `main`. Review the exact head and CI before any authorized merge.
   Historical counts do not establish that the current integration passes.
2. Update #20 against `main`, preserving the merged request implementation. Check
   `app/services/labels.py`, its tests and panel behavior. A rebase may be needed;
   a conflict is not guaranteed. Preserve both helpers and their edge-case tests.
3. Do not reopen merged README PR #16. Carry forward only still-relevant local
   documentation changes, including tracking/reviewing the D9 guide. Recheck
   stale status sentences rather than applying the pasted note verbatim.
4. Run the current dashboard quality commands in section 8. Record the reviewed
   commit and previous revision/digest before deploying. Avoid concurrent deploys.
5. With deployment authorization, run `bash deploy/deploy.sh` from the clean,
   reviewed dashboard checkout. It builds and deploys by digest, enables the IAM
   invoker check and promotes traffic with `--to-latest`. It is not a dry run.
6. Verify actual traffic resolves to the intended digest/revision, then test
   `/`, `/requests`, `/errors`, `/assistant`, `/data` and `/access` through the
   proxy. Check a request detail/waterfall, both themes and narrow/wide layouts.
   An absent crashes page is expected until section 5 is completed.
7. Recheck reader identity, staging target, min/max scaling, cache TTL and privacy.
   In cloud, keep invites disabled; do not broaden runtime permissions for it.

Rollback, if the authorized deployment fails its checks:

```bash
gcloud run services update-traffic football-dashboard \
  --project "$GCP_PROJECT_ID" --region "$REGION" \
  --to-revisions "${PREVIOUS_REVISION}=100"
```

Capture `PREVIOUS_REVISION` from the starting traffic readback. Keep that image
available. Recheck private access after rollback. A rollback pin persists until
changed; the existing deploy script explicitly moves traffic on the next deploy.
Do not use this auto-promoting D7 script unchanged for a D9 candidate launch.

## 5. Separate slice: enable real Android crashes when requested

The existing crashes implementation and D8.5 redesign can run against fixtures
without live BigQuery access. Enabling cloud data needs separate configuration:

- Confirm the Firebase project, Crashlytics batch export, dataset, exact staging
  Android table and dataset location. Do not create a second export by guessing.
- Review dataset-scoped `roles/bigquery.dataViewer` and `roles/bigquery.jobUser`
  on the project where the query jobs run. Current `app/sources/factory.py`
  constructs that client with `crashlytics_project_id`, so its job project is the
  Firebase project. Grant only the needed reader identity, with no data-writer role.
- Configure `CRASHLYTICS_PROJECT_ID`, `CRASHLYTICS_DATASET`,
  `CRASHLYTICS_TABLE`, `CRASHLYTICS_LOCATION` and
  `CRASHLYTICS_MAX_BYTES_BILLED` through reviewed deployment configuration.
  Current `deploy.sh --set-env-vars` does not preserve additional settings;
  update it and its fake-gcloud tests before relying on those settings to survive
  later deploys. Keep the source's query-byte cap and caching.
- Test hidden-when-disabled, readable export, missing first-export table,
  permission denial and wrong project/dataset/location behavior. Permission or
  settings failures must not appear as zero crashes. Use a consented existing
  export for live checks; no deliberate user-app crash is required here.

These are dashboard config/deploy and Firebase permissions tasks. A backend
favourites deployment does not enable this data source.

## 6. Remaining code slices: D8.4, panel reuse and D9

### D8.4 errors redesign

Implement the existing `guide/D8-redesign.md` D8.4 section in its own PR after
the request time-label helper is available. Likely files: `app/domain/errors.py`,
`app/services/errors.py`, `app/templates/partials/errors_body.html`,
`app/static/errors.css` and corresponding tests. Keep route orchestration thin.

- Rename server groups to **Server crashes**; show short exception, message,
  route, first/last seen, count and interval sparkline.
- Group handled errors by code at service level, summing counts and counting
  distinct routes. A single-route group names that route; nested per-route rows
  live in `<details>`. Keep each route's existing request links.
- Move platform events into a right-hand timeline, with degraded components
  below. Reuse tokens, pills, duration/relative-time helpers and injected clocks.
- Derive crash interval counts from matching in-window crash events, not evenly
  spreading Error Reporting totals. Respect source capabilities/truncation; if
  the available aggregate cannot support exact buckets, report that limitation.
- Write tests first for aggregation, distinct routes, single-route text,
  interval boundaries, empty/partial data and fixed-clock time labels. Check
  390 px and 1280 px in both themes, keyboard access and console errors.

After #19/#20 integration, review the duplicated panel shells. If they share the
same behavior, extract one shared shell in a separate refactor with open/close,
unknown-ID, navigation and mobile tests. Do not mix that refactor into IAM work.

### D9 owner login

Track and review the existing `guide/D9-owner-login.md` before implementation;
use its D9.1–D9.6 sequence instead of inventing another auth design:
typed policy/config; Google OIDC transaction; login/session routes/UI;
global default-deny route guard; deployment safety; real owner verification.

Cover full pages, partials, details and direct URLs; verified owner identity,
state/nonce/PKCE, expiry, CSRF, safe redirects, secret handling, logout/back/HTMX
and negative non-owner tests. Keep invites disabled in cloud. Maintain private
IAM/proxy access until the protected candidate and launch checks pass. No
public-transport change or secret provisioning follows merely from this plan.

## 7. Backend telemetry and remaining hosting work

Do not reimplement M1–M6. Existing platform code includes
`ai/shared/telemetry/`, `ai/backend/app/middleware/request_context.py`,
`startup_telemetry.py` and `infrastructure/monitoring/`.

For D2b, follow the dashboard README: run the local backend with `LOG_FORMAT=json`,
capture its output to a JSONL file, and point dashboard `source=local` and
`local_log_path` at that file. Use different backend/dashboard ports. This does
not require a hosted model or a cloud deployment.

[Hosting tracker step 4](https://github.com/SumukhaK/football-intelligence-platform/blob/develop/docs/plans/hosting-execution-tracker.md) still needs operational
evidence for metrics/alerts and an explanatory trace. Inspect existing cloud
resources before applying [monitoring definitions](https://github.com/SumukhaK/football-intelligence-platform/blob/develop/infrastructure/monitoring/README.md).
Do not mark them unapplied solely because an older README says so. Production
hosting step 7 is still recorded as not started. These platform operations are
separate assignments from dashboard UI and D7 IAM.

## 8. Verification and completion report

For each dashboard code slice, use the repository's current CI commands:

```bash
uv sync --frozen --extra dev
uv run ruff check .
uv run black --check .
uv run mypy app tests
uv run pytest --cov=app --cov-report=term-missing
```

For deployment changes also run fake-gcloud behavioral tests, ShellCheck,
`bash -n` on both deploy scripts and the CI/runtime image build. Do not call real
gcloud from tests or weaken tests/coverage. If the local Docker engine is
unavailable, state that and obtain exact-head build evidence from CI/Cloud Build.
Keep files under 400 lines, functions under 40 and app coverage at least 80%.

This review ran dashboard deploy/startup tests with a recording fake gcloud:
**38 passed**. Backend contract, telemetry, request-context, startup and log-privacy
checks: **109 passed**, with existing third-party deprecation warnings.
An initial Windows pytest temp-directory access failure was resolved by using a
new dedicated `--basetemp`; source/tests were unchanged. These focused checks do
not establish the current CI status of dashboard PR #19 or #20.

Report each assigned slice with: changed files and commit/PR; checks and results;
cloud changes actually executed; redacted before/after IAM and digest/revision
where applicable; verified UI/negative access checks; and remaining blockers.
Keep historical PR evidence, this read-only audit and subsequent live execution
distinct. This handoff's creation does not complete any deployment or D9 launch.

Cloud health checks should use an implemented, tested endpoint and a matching
probe path. Treat the recorded `/healthz` behavior as something to reproduce;
do not infer internal probe behavior solely from a front-end URL response.
See [Cloud Run health checks](https://docs.cloud.google.com/run/docs/configuring/healthchecks).
