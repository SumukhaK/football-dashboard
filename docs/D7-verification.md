# D7 verification (19 October 2026)

This is a read-only audit, written on 19 October 2026, of the dashboard's D7
deployment (the private Cloud Run deploy) and of the backlog claims that had grown
up around it. It checks what was actually delivered against `main`, what the live
service looks like, which earlier statements have gone stale, and what is genuinely
left. It is a record of what was observed; it is not a plan approval.

**This record authorises nothing.** Nothing here is permission to make an IAM write,
run a deploy, export Crashlytics data, open public access to the service, or make a
call to a hosted model. Every item under "Left to do" needs its own separate
authorisation before anyone runs it. No cloud read was performed while writing this
file beyond the read-only observations it cites, and no commit, deploy or IAM change
was made.

Real identifiers are not written here. The project is `<GCP_PROJECT_ID>`, the region
is `<REGION>`, and the reader account is
`football-dashboard-reader@<GCP_PROJECT_ID>.iam.gserviceaccount.com`. The one owner
email attributed in PR #14 is redacted as `<owner email>`.

---

## Verified facts

- **D7 was delivered.** PR #14 (`dash/D7-deploy`) merged on 18 October 2026. Its
  two later fixes, `9eb5bde` (make the reader read-only, keep redeploys private) and
  `3cf49da` (abort when an IAM policy read fails), are present in the source.
- **Pull request timeline on `main`.** PR #16 (README refresh) merged 19 October
  2026 as merge commit `ad4506d`. PR #19 (D8.3 requests) merged 19 October 2026 as
  merge commit `a96799a`. PR #20 (`dash/D8-5-crashes`) is still open. `origin/main`
  is at `a96799a`.
- **The live Cloud Run revision.** The serving revision is
  `football-dashboard-00001-74k`, serving 100% of traffic, by image digest
  `sha256:0513baf690c7afecbc35fe7ec180dea2dc72092df9558e4859f6dadb7936ade1`. This
  revision predates the console redesigns (D8.2, D8.3, D8.6 and the rest): it was
  built from the D7 branch.
- **The service is private.** There is no `allUsers` or `allAuthenticatedUsers`
  binding on the service, and the invoker IAM check is not disabled. Both of Cloud
  Run's independent ways of being public are therefore off. A fresh unauthenticated
  HTTP probe was **not** re-run during this audit; the finding is from configuration,
  not from a new request.
- **The deployment reads staging.** The live revision has `SOURCE=gcp`,
  `API_SERVICE_NAME=football-api-staging`, `CACHE_TTL_SECONDS=60` and a maximum of
  one instance. It reads the staging API service, not a production one.
- **App crashes are disabled in the live revision.** No Crashlytics project is
  configured on the revision, and the config hides the crashes page when that
  setting is unset, so `/crashes` does not exist in the live console.

---

## Corrections to earlier claims

| Claim | Checked result |
| --- | --- |
| "The reader probably still has the broad Trace role" | **Confirmed live.** The reader's direct project bindings still include `roles/cloudtrace.user` (see the gap below). |
| "The narrow custom role may be missing" | **Confirmed missing.** A `gcloud iam roles describe footballDashboardTraceReader` returned NOT_FOUND. |
| "A Token Creator binding remains on the reader account" | **Confirmed.** One `roles/iam.serviceAccountTokenCreator` binding with one member. It is optional cleanup; it is not a prerequisite for the narrow role. |
| "The live image predates the redesigns" | **Confirmed.** Revision `football-dashboard-00001-74k`, digest `sha256:0513baf6…` above. |
| "The console is private" | **Confirmed in configuration.** No public binding and the invoker IAM check is enabled. A fresh HTTP denial probe was not re-run. |
| "App crashes are disabled live" | **Confirmed.** No Crashlytics project on the revision, so the page is hidden by design. |
| "PR #16 is a held draft" | **Stale.** It merged 19 October 2026 at 03:35:51 UTC as `ad4506d`. |
| "PR #19 and PR #20 are open" | **Partly stale.** #19 has merged (`a96799a`); #20 is still open. |
| "D8.4 and D9 implementation remain" | **Supported by `main`.** Handled errors still group by (code, route), crash groups carry no interval series, and there is no owner-login code. |
| "Backend M1–M6 still block real telemetry" | **Incorrect as an implementation claim.** The telemetry contract (1.1.0), JSON logs, request ids, events, tracing, retries and the monitoring definitions already exist. Applying the cloud monitoring definitions is a separate piece of work, not an implementation gap. |
| "Real local logs still need backend M2" | **Stale.** M2 is implemented. Run the backend with `LOG_FORMAT=json`, capture its output to a JSONL file, and point the dashboard at it with `source=local` and `local_log_path`, on a port different from the backend's. |
| "Project and region live in `deploy/.env.deploy`" | That file is gitignored and **was absent from the checkout this audit used**. Restore it from private operator configuration using `.env.deploy.example` as the shape, and set `API_SERVICE_NAME=football-api-staging` explicitly, because the script default points at a different service. |
| "`/healthz` is intercepted and Docker could not build locally" | **Historical observations recorded in PR #14, not re-tested here.** Keep them as dated evidence, not as a general Cloud Run or probe guarantee. |

---

## The live Trace IAM gap

This is the one item worth attention, and it is the same read-only audit as above.

- **What the reader holds directly on the project:** `roles/cloudtrace.user`,
  `roles/errorreporting.viewer` and `roles/logging.viewer`.
- **What the merged script intends.** `deploy/setup_service_account.sh` defines the
  narrow custom role `footballDashboardTraceReader` from
  `deploy/trace-reader-role.yaml`, grants exactly that role plus
  `roles/logging.viewer` and `roles/errorreporting.viewer`, and removes an existing
  `roles/cloudtrace.user` binding from the reader.
- **What is actually installed.** The custom role `footballDashboardTraceReader`
  does not exist in the project: a `describe` returned NOT_FOUND. The correction
  already written into the script and the role file has not been applied live.
- **Why the broad role is wrong.** `roles/cloudtrace.user` is broader than its
  description suggests: it carries Trace **task** and **trace-scope** mutations, not
  only reads. A read-only console must never hold them.
- **Why the narrow role is enough.** The dashboard's trace reader calls `get_trace`,
  which needs only `cloudtrace.traces.get` — the single permission the custom role
  grants. The deployed revision's only Cloud Trace call is that same read.
- **The impersonation binding.** A `roles/iam.serviceAccountTokenCreator` binding
  still exists on the reader service account, with one member (`<owner email>`,
  attributed in PR #14). It is a policy binding **on** the account — it lets a person
  act as the reader — not a role the reader holds, and it is never used at runtime.

So the guardrail the project promised (a reader that can read traces and nothing
else) is not the guardrail that is installed live.

---

## Left to do, in order

Each item below needs its own authorisation. Nothing here has been run.

1. **Close the live Trace IAM gap.**
   - *What:* bind the narrow custom role to the reader, then remove the broad
     `roles/cloudtrace.user` binding.
   - *Why:* the reader currently holds Trace mutation permissions a read-only console
     must not have, and the promised narrow role does not exist.
   - *Before it can run:* capture the starting state read-only (describe the custom
     role and list the reader's project bindings).
   - *Implementation already exists:* `deploy/setup_service_account.sh` and
     `deploy/trace-reader-role.yaml`. Do **not** rewrite them, and do **not** grant
     another broad role.
   - *Acceptance:* the reader's direct roles are logging viewer, error-reporting
     viewer and the custom role; the broad Trace role is gone; the custom role names
     exactly `cloudtrace.traces.get`; and a real traced request's waterfall loads
     through `gcloud run services proxy` with no new permission error. Allow for IAM
     propagation; if access stays broken, stop and report the failing call — never
     silently restore a broad role.
2. **Decide whether to keep owner impersonation.**
   - *What:* decide whether the `roles/iam.serviceAccountTokenCreator` binding on the
     reader stays.
   - *Why:* it is broader than the console needs, but it is what makes the
     "denied write while impersonating the reader" evidence producible.
   - *Before it can run:* a decision. If removed, remove it for that one member only,
     after the decision, as optional cleanup — it is not a prerequisite for item 1.
3. **Integrate and deploy the redesigns.**
   - *What:* PR #20 (`dash/D8-5-crashes`) is still open. Recheck its head and CI,
     merge it second, then deploy the reviewed commit.
   - *Why:* the live revision predates the redesigns, so none of the new pages are
     live.
   - *Before it can run:* a reviewed, merged commit and an authorised deploy.
   - *Verify:* `/`, `/requests`, `/errors`, `/assistant`, `/data` and `/access`; a
     request-detail waterfall; both themes; narrow and wide layouts; and recheck the
     reader identity, the staging target, scaling, cache TTL and privacy. Keep a
     rollback pin ready.
4. **Enable real Android crashes when asked.**
   - *What:* point the console at the Firebase Crashlytics export.
   - *Why:* the crashes page is hidden live because no Crashlytics project is set.
   - *Before it can run:* the Firebase/Crashlytics export, the right BigQuery viewer
     and job roles, and settings that survive a redeploy. A permission or settings
     failure must not read as zero crashes.
5. **D8.4 errors redesign.**
   - *What:* the errors-page redesign (rename "Crash groups" to "Server crashes";
     group handled errors by code with per-route rows; move platform events and
     degraded components to a right-hand timeline; add per-interval counts).
   - *Why:* it is the last D8 slice, and it was waiting on the requests work in #19.
   - *Before it can run:* its own branch and PR (in progress separately).
6. **Shared panel shell refactor.**
   - *What:* replace the two panel shapes with one shared shell.
   - *Why:* the requests panel and the crashes panel duplicate structure.
   - *Before it can run:* only after the requests and crashes panels are both on
     `main`. Extract one shell only if they behave the same; no behaviour change, in
     a separate PR.
7. **D9 owner login.**
   - *What:* owner-only Google sign-in.
   - *Why:* the console currently relies entirely on the Cloud Run boundary because
     it has no login.
   - *Before it can run:* review the existing `guide/D9-owner-login.md` (untracked in
     the owner's checkout) and follow its D9.1–D9.6 sequence.

---

## Stale statements found in this repository

Found by searching the tracked Markdown in the worktree on 19 October 2026. None of
these were edited; they are listed here only.

**Status line listing which D-steps are merged or in review**

- `README.md:250-255` — "Steps D1 to D8.2, the optional local-log source (D2b) and
  the redesigned assistant page (D8.6) are merged. The requests page (D8.3) and the
  app crashes page (D8.5) are in review, the errors page (D8.4) is the last redesign
  slice still to build…" — the verification says **D8.3 (PR #19) has merged** as
  `a96799a` on 19 October 2026; only D8.5 (PR #20) is still in review.

**Claims that backend M1–M6 or M2 still block real telemetry**

- `guide/README.md:22` — "It needs the main repo's step M2 for real logs." — the
  verification says **M2 is implemented**; run the backend with `LOG_FORMAT=json`,
  capture the output to a JSONL file, and point the console at it with `source=local`
  and `local_log_path`.
- `guide/README.md:23` — "Real data needs the backend to emit the contract. That work
  is the main repo's hosting tracker step 4 (steps M1 to M6 there)." — the verification
  says the **telemetry contract (1.1.0), JSON logs, request ids, events, tracing,
  retries and monitoring definitions already exist**; applying cloud monitoring is a
  separate remaining piece.
- `guide/D2b-local-log-source.md:7` — "…the JSON log lines that the backend writes
  when `LOG_FORMAT=json` (main repo step M2)…" — same as above: **M2 is implemented**.
- `guide/D2b-local-log-source.md:17` — "Real data needs the main repo's step M2 (JSON
  logs). Until then, test only with files you write in tests." — **stale**; local real
  logs work today with `LOG_FORMAT=json`, a captured JSONL file, `source=local` and
  `local_log_path`.

**A sentence saying "D6 and D8.1 are separate open PRs"**

- **No hits.** No tracked Markdown file on `origin/main` contains that sentence. The
  tracked `README.md` and `guide/README.md` do not mention D6 or D8.1 as open PRs.

**A claim that `deploy/.env.deploy` exists**

- **No tracked statement asserts the file is present.** The closest references are
  `deploy/README.md:15` ("`cp deploy/.env.deploy.example deploy/.env.deploy`") and
  `guide/D7-deploy.md:13` ("They go in `deploy/.env.deploy` (gitignored)") together
  with `guide/D7-deploy.md:18` ("Reads project and region from
  `deploy/.env.deploy`"). These are instructions or descriptions of where the values
  go, not assertions that the file is currently there. The verification's point
  stands: the file is gitignored and was **absent from the checkout this audit
  used**, so it must be restored from private operator configuration before any deploy.

---

## Checks to run for each code slice

```bash
uv sync --frozen --extra dev
uv run ruff check .
uv run black --check .
uv run mypy app tests
uv run pytest --cov=app --cov-report=term-missing
```

For deployment changes, also run the fake-`gcloud` tests, ShellCheck and `bash -n` on
both deploy scripts, plus the image build. Repo rules: files under 400 lines,
functions under 40 lines, app coverage at least 80%. Never call real `gcloud` from
tests, and never weaken a test.

For this documentation-only record, the five commands above were run unchanged and
are expected to pass without modification.
