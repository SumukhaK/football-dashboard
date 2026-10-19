# Dashboard D7 verification and implementation handoff for DeepSeek

Updated: 19 October 2026. Repository snapshot before publication:
`7cd7e732b139006931de76198b6cc10ce6f4aa70` (PRs #20, #21 and #25 merged).
Status: implementation instructions; no cloud changes applied.

Use this as the single DeepSeek implementation handoff. It consolidates the
other chat's audit and this chat's PR reviews and independent cloud readback.
Its canonical path is `guide/deepseek-d7-handoff.md`, moved from `docs/` at the
owner's request after PR #24; keep future updates in this guide file.
The older local remaining-work note and PR #21's dated verification record are
consolidated here; the owner requested removal of the entire `docs/` folder.
Keep dashboard documentation in `guide/` and do not recreate `docs/`.
The [original PR #21 audit](https://github.com/SumukhaK/football-dashboard/blob/c3b5e1a7ed0dcb4b9636aafe29e513d740afb477/docs/D7-verification.md)
remains available in Git history as dated evidence, not another work queue.

**D7's confirmed required follow-up is the live Trace IAM correction in section
2.** The source fix is already merged; applying it and verifying real trace
access remain outstanding. Owner impersonation cleanup is optional. Deploying
newer UI code is a separate release decision; D8.4, Crashlytics activation and D9
are separate stages, not prerequisites for that IAM correction.

## Scope and repositories

This document belongs to `SumukhaK/football-dashboard`, locally at
`D:/Anthropic/TestProjects/football-dashboard`. Dashboard PRs target `main`.
References to `SumukhaK/football-intelligence-platform` describe the separate
backend repository and use explicit cross-repository links.

For D7, read `guide/D7-deploy.md`, `deploy/README.md` and current repository
instructions. For separately assigned UI/auth work, also read
`guide/D8-redesign.md` and `guide/D9-owner-login.md`. The D9 guide exists locally
but is untracked: a fresh clone does not contain it. Preserve the owner's
existing README, guides and untracked documents.

The original handoff request covered verification and documentation. The owner
subsequently authorized merging PRs #20 and #21, publishing this guide and
removing `docs/`, including an administrator override for the documentation merge.
The #20/#21 merges are complete; publication concerns documentation only.
This does not authorize IAM writes, a deployment, enabling Crashlytics export,
public access or hosted-model calls. Check existing owner authorization before
requesting any missing approval. Earlier authorization to merge a particular PR
does not authorize cloud changes. Do not stage, commit, push or merge merely
because this handoff describes those steps. Work on one assigned slice at a time.

## 1. Verified facts and corrections

| Claim from the note | Checked result | Evidence |
|---|---|---|
| D7 was delivered | True. Dashboard PR #14 merged on 18 October. Its later fixes are in source. | [PR #14](https://github.com/SumukhaK/football-dashboard/pull/14), commits `9eb5bde` and `3cf49da`. |
| The reader probably still has the broad Trace role | Confirmed live. Its direct project bindings are `roles/cloudtrace.user`, `roles/errorreporting.viewer`, `roles/logging.viewer`. | Read-only project IAM query on 19 October. |
| The narrow custom role may be missing | Confirmed live: describing `footballDashboardTraceReader` returned `NOT_FOUND`. | Read-only IAM role query. |
| A Token Creator binding remains on the reader account | Confirmed: one such binding with one member. The original owner-member attribution is recorded in PR #14. | Service-account IAM query and PR #14. |
| The live image predates the later redesigns | Confirmed: serving revision is `football-dashboard-00001-74k`, with 100% of traffic. D8.2/D8.3/D8.5/D8.6 are on main but absent from this initial D7 image. | Cloud Run readback; digest `sha256:0513baf690c7afecbc35fe7ec180dea2dc72092df9558e4859f6dadb7936ade1`. |
| The console is private | Configuration remains private: no `allUsers` or `allAuthenticatedUsers` service binding; invoker IAM check is not disabled. | Service IAM and service description. A fresh HTTP denial/proxy test was not run. |
| The deployment reads staging | Confirmed: reader runtime identity, `SOURCE=gcp`, `API_SERVICE_NAME=football-api-staging`, cache TTL 60 seconds; max scale 1. | Cloud Run service description. |
| App crashes are disabled live | Confirmed: no Crashlytics project is configured on the current revision; config disables the page in that case. | Service environment and `app/config.py`. Firebase dataset/export/IAM was not audited. |
| PR #19 and PR #20 are open | Both merged: #19 at `a96799a`, including its missing-Close fix; #20 at `980534c`, retaining reviewed head `f48fdf3` and the conflict resolution. No merge task remains for either. | GitHub merge metadata and local commit ancestry; exact CI results in section 8. |
| PR #16 is a held draft | Stale: merged on 19 October at 03:35:51 UTC; local dashboard `main` includes merge `ad4506d`. | [PR #16](https://github.com/SumukhaK/football-dashboard/pull/16) and local history. |
| PR #21 still needs a code fix | No actionable findings at head `3b798b2`; merged as `c3b5e1a` on 19 October at 09:34:09 UTC. Its record is consolidated into this guide during the owner-requested folder cleanup. | [PR #21](https://github.com/SumukhaK/football-dashboard/pull/21); original audit linked above; see section 8. |
| This handoff is in the backend repo | Corrected: dashboard [PR #24](https://github.com/SumukhaK/football-dashboard/pull/24) originally added it under `docs/` at `0bed781`; the owner subsequently requested this move to `guide/`. The misplaced backend copy/index entry were removed by platform PR #159. | Both chats' correction record; the current guide file is the canonical handoff. |
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

Independent cloud reads completed **19 October 2026 at 09:08:24 UTC (14:38:24
IST)**: service, serving revision, service/project IAM, custom role and reader
account IAM. The invoker-disabled setting was explicitly `false`; the custom
role result was `NOT_FOUND`, not access denial. These are dated observations:
repeat the reads before acting. No fresh HTTP/proxy check, telemetry payload,
billing query or full organization-level effective-permissions audit was run.

Historical PR #14 acceptance: Cloud Build succeeded in 1m10s; unauthenticated
HTTP returned 403; the private proxy returned 200 with 268 staging requests,
0.0% error rate and p95 786 ms. Startup identified the intended staging target.
The owner's logging control write succeeded and the impersonated reader's
logging write was denied. These are historical results, not a fresh live test
or evidence that every Trace mutation is denied.

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

Record the date, commands, exit results and redacted before/after role lists in
this guide handoff, updating its outcome rather than creating another
competing task list. No image redeploy is needed solely to correct IAM. Mark
this slice complete only after policy readback and an actual trace read pass;
merging the script or this document alone does not close the live gap.

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

1. [PR #19](https://github.com/SumukhaK/football-dashboard/pull/19) and
   [PR #20](https://github.com/SumukhaK/football-dashboard/pull/20) are merged.
   Use current reviewed `main`; no further merge is needed for these slices.
2. #20's former `tests/services/test_labels.py` conflict is **resolved and
   published** in `f48fdf32ebe7eb43e8b2b8584bd8b77b1b4d4572`. Both
   `relative_time` and `split_class_name` imports and all tests are retained.
   Independent comparison matches the tested resolution, and fresh current-main
   CI passed before merge. The merge at `980534c` preserves that commit and its
   tests. Do not redo this fix or reopen the merged PR.
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

PR #19's former error/unknown-ID panel Close defect was fixed in `18668a4` and
merged; do not ask DeepSeek to fix it again. PR #20's equivalent recovery states
already passed browser checks. Its published merge resolution preserves the
reviewed application, so that evidence still applies. Rerun affected browser
checks if application/UI behavior changes later.

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

Panel-shell reuse is optional: duplication alone did not produce a confirmed
review finding. Consider a separate refactor only if shared behavior justifies
it; preserve open/close, unknown-ID, navigation and mobile behavior. It does not
block PR #20 or D7 and must not be mixed into IAM work.

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
There is no dashboard-local password today. The D9 design uses the owner's
Google sign-in and Google account recovery; signing keys/client secrets are
separate operator credentials, not a password to give the browser user.

## 7. Backend telemetry and remaining hosting work

Do not reimplement M1–M6. Existing platform code includes
`ai/shared/telemetry/`, `ai/backend/app/middleware/request_context.py`,
`startup_telemetry.py` and `infrastructure/monitoring/`.

For D2b, follow the dashboard README: run the local backend with `LOG_FORMAT=json`,
capture its output to a JSONL file, and point dashboard `source=local` and
`local_log_path` at that file. Create the log directory first; quote an absolute
log path. Keep the backend on 8000 and dashboard on 8090. Load a dashboard `.env`
explicitly with `uv run --env-file .env uvicorn app.main:app --port 8090`;
`Config()` and bare `uv run` do not load that file automatically. This needs no
hosted model or cloud deployment. The merged PR #16 README has working commands.

[Hosting tracker step 4](https://github.com/SumukhaK/football-intelligence-platform/blob/develop/docs/plans/hosting-execution-tracker.md) still needs operational
evidence for metrics/alerts and an explanatory trace. Inspect existing cloud
resources before applying [monitoring definitions](https://github.com/SumukhaK/football-intelligence-platform/blob/develop/infrastructure/monitoring/README.md).
Do not mark them unapplied solely because an older README says so. Production
hosting step 7 is still recorded as not started. These platform operations are
separate assignments from dashboard UI and D7 IAM.

PRs [#22](https://github.com/SumukhaK/football-dashboard/pull/22) (screenshots)
and [#23](https://github.com/SumukhaK/football-dashboard/pull/23) (README status)
are drafts at the owner's request and were not reviewed here. Keep them in draft
until the owner explicitly resumes that work. Main's D8.3 status wording is stale;
assess #23 before duplicating its work. The owner's video walkthrough remains **on
hold**; these screenshot PRs do not automatically restart it. No billing amount
was verified. Scaling to zero is not a zero-total-bill guarantee: image storage,
builds and other project resources may still cost money.

Both screenshot PRs currently add `docs/screenshots/` paths. Before any later
merge, relocate those assets and their links, for example to `screenshots/`,
to preserve the owner's decision to remove `docs/`. Those branches are outside
this publication change; do not merge them unchanged and recreate the folder.
The older M2 prerequisites in `guide/README.md` and
`guide/D2b-local-log-source.md` need wording updates, not backend reimplementation.

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

The other chat's audit ran deploy/startup tests with a recording fake gcloud:
**38 passed**. Backend contract, telemetry, request-context, startup and log-privacy
checks: **109 passed**, with existing third-party deprecation warnings.
An initial Windows pytest temp-directory access failure was resolved by using a
new dedicated `--basetemp`; source/tests were unchanged. These focused checks do
not establish the current CI status of dashboard PR #19 or #20. They were not
rerun for this documentation update.

### Reviewed versions and exact evidence

| Review/check | Result and limitation |
|---|---|
| PR #19 merged code / PR #21 CI | [Run 39196800860](https://github.com/SumukhaK/football-dashboard/actions/runs/39196800860): **807 passed, 99.26%**, Ruff/Black/mypy/image/ShellCheck/GitGuardian green. Test merge `f78833e` combined #21 head `3b798b2fd01c10c53a8ca0d3fb1db5dd59f4eb4e` with main `a96799a`. The earlier 805 / 99.32% note is historical. |
| PR #20 historical CI | [Run 39157231751](https://github.com/SumukhaK/football-dashboard/actions/runs/39157231751): **792 passed, 99.31%**, all gates green, against old main `0274562`. Superseded by the fresh run below. |
| PR #20 independent resolved snapshot | Old head `8b630d7` plus main `a96799a`, keeping both imports: **830 passed, 99.34%** locally, Ruff/Black/mypy clean. Integration tree `ec496776913fe4d59c6b4539884c7d0e8459d9fb`. The published resolution now matches all files; the labels-test blob differs only in line endings. |
| PR #20 published head / fresh CI | **Ship; no remaining findings** at `f48fdf32ebe7eb43e8b2b8584bd8b77b1b4d4572`. [Run 39229729477](https://github.com/SumukhaK/football-dashboard/actions/runs/39229729477): test merge `a2021be` into main `0bed781`, **830 passed, 99.28%**, Ruff/Black/mypy/image/ShellCheck/GitGuardian green. Merged as `980534c` at 09:33:13 UTC. |
| PR #20 browser checks | Fixtures, 390/1280 px, dark/light: 35 recorded states/interactions, eight unknown-ID/source-failure Close checks, filters/windows/full detail/back, no horizontal overflow, zero captured console warnings/errors. No live Crashlytics tested. |
| PR #21 verdict | **Ship; no actionable findings.** Reviewed tree `e3d7f5a157bab3fcc855c1175b442306646c5d06`; merged as `c3b5e1a` after #20. |
| Final merged main CI | [Run 39231053341](https://github.com/SumukhaK/football-dashboard/actions/runs/39231053341) on exact commit `c3b5e1a7ed0dcb4b9636aafe29e513d740afb477`: **830 passed, 99.28%**, one existing warning; Ruff, Black (161 files), mypy (154 source files), container image and ShellCheck passed. |

Main `c3b5e1a` contains #20/#21 with their original commits preserved. PR #25
then removed the old handoff/index paths at `7cd7e73`; this publication removes
the remaining dated audit from `docs/` and publishes the canonical guide.
Other local README/D7/D9 work is outside this commit. Distinguish the earlier
local **830 / 99.34%** evidence from fresh CI's **830 / 99.28%**. Do not copy old counts
as new results. Local supporting reports are under workspace `.pr-reviews/` in
`pr20-8b630d7/` and `pr21-3b798b2/`; this handoff contains the necessary findings
and public CI links so those archives are not required to understand the work.

Report each assigned slice with: changed files and commit/PR; checks and results;
cloud changes actually executed; redacted before/after IAM and digest/revision
where applicable; verified UI/negative access checks; and remaining blockers.
Keep historical PR evidence, this read-only audit and subsequent live execution
distinct. This handoff's creation does not complete any deployment or D9 launch.

Cloud health checks should use an implemented, tested endpoint and a matching
probe path. Treat the recorded `/healthz` behavior as something to reproduce;
do not infer internal probe behavior solely from a front-end URL response.
See [Cloud Run health checks](https://docs.cloud.google.com/run/docs/configuring/healthchecks).
