# Remaining audit gaps: small tasks for Cline / Nemotron

Prepared: **20 October 2026**. Status: **planning only; fixes pending**. Repository: `SumukhaK/football-dashboard`;
integration branch: `main`. Audit source: `221d6b09a7eeed4ec6b74e1d2bda0ff6c1fdbfbf` (PR #37). Rechecked for this
handoff at `b47f4784ba17d4ae077090129a901ba6a9bf5a22` (PR #38).

## 1. Scope and how to use this file

These are implementation defects and unmet requirements, with tests to add. They are not merely requests to increase
coverage. D1–D9 functionality exists; do not rebuild completed pages, Google login or the backend telemetry system.

The credential-dependent navigation test belongs to Claude's separate [offline-test handoff](offline-test-handoff.md).
Do not edit that test/helper in these tasks without coordinating with its implementer. Fixing production retry handling
does not make that test offline.

| Group | Work | Relationship to the original guide |
|---|---|---|
| A | Google retry/error handling | D2 already requires graceful API failure; this missed retry case was found in the audit. |
| B | Malformed Cloud Logging entries | Newly reproduced input-validation defect in an implemented source. |
| C | Candidate verification before promotion | D9.5 explicitly says candidates must not auto-promote. |
| D | Fixture-only loopback boundary and indicator | Explicit D9 requirements not fully implemented. |
| E | Reconcile stale guides | Documentation follow-up after merged code and live execution. |
| F | IST times and INR currency throughout the dashboard | New owner requirements added on 20 October; not defects in the original UTC/USD plan. |

**One task per Cline session.** Paste this whole file, then request one ID, such as A1. Read its files, add its failing
check, implement the smallest fix, run its focused checks, then stop and report. Review each completed task before
starting the next. Keep a group in a focused PR; split further if needed.

Dependency order: A1 → A2; B1 → B2; C1 → C2 → C3; D1 → D2; E1 last. F1 and F2 are independent display tasks; finish them
before E1 reconciles the guides. A, B and D have no code dependency on each other. Work sequentially unless the owner
explicitly arranges separate worktrees and file ownership.

## 2. Rules for every task

1. Inspect current main, instructions, open PRs and `git status` first. Preserve unrelated edits and branches; do not
   reset or clean another agent's work.
2. Reproduce the named case without Google credentials/network. Use existing fake Google clients, fake HTTP and
   recording fake-gcloud harnesses.
3. Add a failing test before the fix. Test visible behavior, not source strings when the existing behavioral seam can
   prove the requirement.
4. Preserve Python 3.12, strict types, current layers, no-secret diagnostics, auth, query limits, numeric secret
   references and existing assertions.
5. No new dependency, framework, database, auth bypass or broad exception swallowing. Keep functions focused; split code
   before the guide's limits.
6. Never skip/xfail/weaken a test to finish. If the known offline-test failure blocks a full run, report it and
   coordinate; do not claim all tests passed.
7. Record fresh commands, results and limits. Historical audit counts below are not evidence that a future change
   passes.
8. Implementation, commit, push and review follow the owner's authorization. This plan alone does not authorize merging
   or live cloud execution.

The user authorized publication of this Markdown file. It does not authorize Cline to deploy, change IAM/public access,
rotate secrets, activate BigQuery, run paid model calls or resume the video walkthrough. Operator tasks are in §8.

## 3. Group A — graceful, bounded Google reads

### A1. Translate an exhausted SDK retry into the existing source error

**Read:** `app/sources/gcp/errors.py`, `app/domain/errors.py`, `tests/sources/gcp/test_gcp_errors.py`, and the page's
source-error tests.

**Observed:** `guarded()` maps `ServiceUnavailable` and `DeadlineExceeded`, but the SDK's final `RetryError` wrapper
escapes. A real blocked Cloud Logging read hit this case in the audit. The browser gets a generic server error rather
than the existing telemetry-unavailable banner.

Small steps:

1. Add a fake callable raising `RetryError("deadline exhausted", ServiceUnavailable("offline"))`.
2. Assert `guarded("Cloud Logging", callable)` raises `SourceUnavailableError` with kind `unavailable`; confirm it
   currently fails without any SDK call.
3. Handle retry exhaustion once in the shared adapter. Preserve mapped permission/quota classifications when a wrapped
   cause supports them; use a bounded unavailable result for exhausted transport retries.
4. Keep unrelated programming errors visible and preserve reader-specific `NotFound` behavior. Do not replace the
   mapping with `except Exception`.
5. Add one router check over a failing fake reader: response is the normal page/banner, not 500, and exposes no raw
   payload, credential or traceback.

**Done when:** direct failures and exhausted retries reach the existing banner; unrelated errors still propagate; no
network or real sleeping occurs in tests.

**Focused checks:** `uv run pytest tests/sources/gcp/test_gcp_errors.py tests/routers/test_overview.py --no-cov -q`. Run
other reader tests affected by the shared adapter as well.

### A2. Bound the reader's retry and timeout behavior

**Read:** `logging_reader.py`, `trace_reader.py`, `errors_reader.py`, `platform_reader.py`, `crashlytics_reader.py`
under `app/sources/gcp/`, their protocols/fakes, `app/services/overview.py` and the pinned SDK signatures.

**Problem:** source calls use SDK defaults. A page performs several reads; mapping the eventual exception does not
prevent a request outlasting the hosted 60-second timeout. A per-call timeout is not a whole-page deadline.

Execute this as five small sessions using the steps below: **A2a** Logging, **A2b** Trace, **A2c** Error Reporting,
**A2d** platform logs, **A2e** BigQuery and the final page-budget check. Each session changes only that reader, its
callers/protocol and fakes/tests. Reuse any policy introduced in A2a. Do not claim all source reads are bounded until
A2e verifies the combined budget.

Small steps:

1. Inventory RPCs, pager iteration, request-ID chunks and BigQuery result waits. List how many serial operations the
   busiest page can make.
2. Use supported arguments in the installed SDK to bound transport calls and total retry/result waits. Choose/document
   limits fitting the page's 60-second hosted budget, including all serial calls and rendering margin.
3. If many chunks/pages can exceed that budget, pass a remaining read budget through the narrow source path or stop with
   the existing source error; do not add an HTTP-wide retry loop or silently call partial results complete.
4. Update the affected Protocol signatures and recording fakes alongside callers. Preserve query caps, parameterized SQL
   and maximum bytes billed.
5. Verify arguments/budget exhaustion using fakes and an injected clock. A paged read failing during iteration must also
   become a source error.

**Done when:** retry and result waits are finite; the documented page budget accounts for chunk/page multiplication;
tests do not wait for real timeouts. Do not blindly assume every Google method accepts the same keyword arguments.

**Focused checks:** `uv run pytest tests/sources/gcp --no-cov -q` plus the page service/router tests whose deadline
behavior changed. Depends on A1.

## 4. Group B — reject one bad record without losing good telemetry

### B1. Make malformed contract shapes fail as contract errors

**Read:** `app/contract.py`, `app/domain/models.py`, `tests/test_contract.py`, `tests/test_models.py`, and the contract
JSON.

**Observed:** replace a valid `http.request` record's `attributes` with JSON `null`. `validate_event()` raises
`TypeError` during required-field membership, rather than `ContractError`. This is a newly found defect, not a new
schema.

Small steps:

1. Copy a valid fixture line; parameterize bad `attributes` values: null, a string, number and list. Assert clear
   `ContractError`, not Python crashes.
2. Test malformed/unhashable `event`, unusable timestamp, and fields needed by `TelemetryEvent.from_log_line`. Preserve
   valid nulls allowed by contract.
3. Add the smallest shape/type checks before indexing or membership tests. Keep one canonical validation rule; do not
   duplicate it in each page.
4. Preserve contract version 1.1.0, allowed/required names and forbidden fields. Do not change the backend contract or
   coerce bad records into good ones.
5. Diagnostic errors name the invalid field without quoting its private value.

**Done when:** malformed shapes are rejected deliberately and valid committed fixtures still validate. No broad parser
rewrite or new dependency.

**Focused checks:** `uv run pytest tests/test_contract.py tests/test_models.py tests/scripts --no-cov -q`.

### B2. Make the Cloud Logging batch conversion resilient per record

**Read:** `app/sources/gcp/entries.py`, `logging_reader.py`, `tests/sources/gcp/test_entries.py`, `gcp_fakes.py`, and
`app/sources/local_log_source.py` for its existing rejection behavior.

Small steps:

1. Build two fake Cloud Logging entries from valid fixtures; make the first malformed as in B1. Assert conversion keeps
   the second and counts one skip.
2. Keep per-record validation and domain conversion inside a deliberate invalid-input boundary. Cover conversion errors
   as well as name checks.
3. Add mixed valid/invalid batches, an all-invalid batch and an empty batch. Preserve input order and accurate skip
   counts; continue after each bad row.
4. Assert warnings contain counts/field categories, not raw log lines, token values or exception text carrying a
   payload.
5. Check that local logs still reject/count bad lines and that valid lifted Cloud Logging trace/span/timestamp/severity
   keys are reconstructed correctly.

**Done when:** one bad record cannot discard later good events or make a page
500. Programming bugs are not hidden behind a blanket exception handler.

**Focused checks:**
`uv run pytest tests/sources/gcp/test_entries.py tests/sources/gcp/test_logging_reader.py tests/sources/test_local_log_source.py --no-cov -q`.
Depends on B1.

## 5. Group C — separate deployment from verified promotion

**Shared context:** D9.5 requires no candidate auto-promotion. Today `deploy/deploy.sh` checks Ready, Google mode and
nonempty secret names, then moves 100% traffic and optionally opens app-auth transport in the same run. The audit's
recording fake reproduced that sequence. The real D9.6 launch used extra manual verification; this finding does not
invalidate that live record.

Read `deploy/deploy.sh`, `lib.sh`, `rollback.sh`, `.env.deploy.example`, `deploy/README.md`, D9 §8/§10 and
`tests/test_deploy_behaviour.py` first. Use its existing `Scripts` harness, which proves the fake shadows real gcloud.

### C1. Stop candidate creation before serving it

1. Add a fake-gcloud test requiring successful candidate creation to issue no traffic promotion and no public-invoker
   addition. Confirm it fails today.
2. Keep build ID/digest capture, named revision, `--no-traffic`, runtime account, numeric secret bindings, scaling
   limits and preservation of unmanaged env.
3. Require verified private transport before creating a candidate/tag. If the service is public, refuse with operator
   instructions; do not quietly cause an outage or assume `--no-allow-unauthenticated` proves the whole boundary.
4. End by printing candidate revision/digest, how to run private checks and the separate promotion command. Do not print
   secrets or tokens.

**Done when:** running candidate deployment alone cannot promote/open access; failed build/deploy/policy reads stop
subsequent actions. No real gcloud runs.

### C2. Promote only an explicitly verified revision

1. Add a small `deploy/promote.sh` reusing the existing helper. Require an explicit revision and expected immutable
   digest; reject missing/latest.
2. Compare candidate identity, readiness, owner/origin/callback/source/target settings and exact secret names plus
   numeric versions against operator configuration. Nonempty secret names and `AUTH_MODE=google` alone are not proof
   that the reviewed image and correct keys are running.
3. Require an explicit operator verification checkpoint tied to that revision and digest: signed-out/partial denials,
   real owner/non-owner results and the D9 privacy checks. Document the evidence required; a `verified=true` flag alone
   is not those checks. Prepare this offline; do not fabricate them.
4. Promote by revision name while private; retire/read back all traffic tags; open service-only app-auth transport only
   if explicitly requested afterward.
5. Record fakes for missing/mismatched settings, secret versions, digest, failed policy reads and tag removal failure.
   All must stop public opening.

**Done when:** verified named promotion is separate from candidate creation; private stays the default; `--to-latest` is
never used. Depends on C1.

### C3. Keep rollback behind the same boundary

1. Add cases for a pre-auth target, a target only carrying Google-mode config, and an auth image referencing retired
   signing-key versions.
2. Close and verify transport before restoring an unverified/pre-auth target. Keep it private; do not reopen because an
   env variable says Google.
3. For a public restore, require the reviewed image and current enabled numeric keys through the C2 verification path.
   Redeploy good code with current keys if an old revision pins retired ones; never re-enable old keys automatically.
4. Preserve named rollback, read-failure aborts and tag retirement; update the runbook, examples and CI ShellCheck
   coverage for any new script.

**Done when:** failed/unknown restore verification cannot leave old code public. Run
`uv run pytest tests/test_deploy.py tests/test_deploy_behaviour.py tests/test_deploy_safety.py --no-cov -q`, `bash -n`
on changed scripts, and ShellCheck. Depends on C2.

## 6. Group D — enforce the local fixture exception

### D1. Refuse fixture serving outside loopback

**Read:** `app/config.py`, `app/main.py`, `app/middleware/auth.py`, `tests/test_auth_startup.py`,
`tests/routers/test_guard.py`, and D9 §4.

**Observed:** an app with `Config(auth_mode="fixture")` returns Overview 200 with non-loopback ASGI server/client
addresses. Config rejects real sources, invites and a hosted revision, but no actual bind/connection check exists. This
demonstrated fixture exposure, not a bypass of deployed Google auth.

Small steps:

1. Add a no-network ASGI test with server `192.0.2.50` and client `192.0.2.20`: assert refusal before page/source work.
   Confirm it currently serves 200.
2. Enforce the D9 requirement using actual server/launcher binding plus ASGI connection facts. Never infer loopback from
   `Host`, Origin or forwarded headers. Refuse wildcard/LAN binds, unknown binding and spoofed headers.
3. If ASGI cannot distinguish a wildcard bind reached through loopback, add a minimal fixture launcher that pins
   loopback and a testable enforcement seam; do not claim a request-host check proves a bind. No environment-only
   bypass.
4. Cover IPv4/IPv6 loopback, LAN, wildcard and missing metadata. Retain the real-source, invites-on and K_REVISION
   startup refusals; Google mode unchanged.
5. Adapt fixture tests to inject actual safe ASGI metadata or the launcher; do not weaken the boundary just to accept
   TestClient's default hostname.

**Done when:** loopback demo works and non-loopback serving is rejected without client-controlled opt-in or production
auth changes.

**Focused checks:**
`uv run pytest tests/test_auth_startup.py tests/test_config.py tests/routers/test_guard.py tests/test_app_wiring.py --no-cov -q`.

### D2. Identify sample mode in the UI and startup instructions

1. Add a visible “Sample data — local demonstration” notice in the shared shell only for fixture auth mode; reuse
   existing tokens and accessible text.
2. Add router assertions that the notice exists in fixture mode and is absent with Google auth. Keep source=fixture with
   real Google auth distinct.
3. Update README/`.env.example` fixture launch commands for D1's safe path. Real local logs still require Google auth;
   do not change those requirements.

**Done when:** sample mode is identifiable, both themes work and the documented command enforces loopback. Use router
tests and an actual local browser check; record if browser access is unavailable. Depends on D1.

## 7. Group E — refresh the existing guides, not another master plan

### E1. Remove obsolete work instructions after verifying their replacements

**Files:** `guide/deepseek-d7-handoff.md`, `D7-deploy.md`, `README.md`, `D9-owner-login.md`,
`D9.6-live-verification.md`, `deploy/README.md` and root README. Paths without a prefix in this row are under `guide/`.

1. Separate dated audit observations from the current work queue. The D7 handoff still says narrow Trace IAM is
   outstanding and D9 untracked/missing.
2. Cite merged PR #27, #28, #29, #31–#35, #37 and D9.6 where relevant. D8 Errors, contract 1.1.0 and Google login are
   implemented; do not redo them.
3. Dated read-only evidence on 20 October found the narrow get-trace-only role bound and the broad Trace role removed.
   The Google-auth revision served 100%, targeting staging, with cloud invites off and no Crashlytics project. Cite
   D9.6; label any fresh readback separately. Do not claim total effective IAM or future live state from these
   historical observations.
4. Remove `--to-latest` as a current D7 instruction. Document the completed C1–C3 candidate/promotion/rollback workflow
   without claiming cloud execution.
5. Preserve original dated evidence and stateless-session limits. Main's D9.6 record supersedes the older preparatory
   D9.7 record; inspect current branches before acting and never delete another agent's commit/history.
6. Link this task list and the separate offline handoff from the existing guide index. Keep all docs in `guide/`; do not
   recreate `docs/` or `tasks/`.

**Done when:** one consistent current queue; no claim that the live login/IAM work is unimplemented; future fixes
reference fresh results. Depends on C/D docs.

## 8. Group F — display times in IST and currency in INR

These are new owner instructions. Record them as the current display requirements; do not rewrite dated UTC evidence as
though it was originally observed in IST.

### F1. Convert every displayed dashboard time to IST

**Read:** `app/templating.py` (`utc_time`, `utc_clock`), `app/services/links.py` (`chart_label`),
`app/services/labels.py`, templates and their router/static tests.

1. Add failing tests for an explicit IST formatter: `2026-10-20T18:45:00Z` must display `21 Oct 00:15 IST`, including
   the date rollover. Cover None, non-UTC aware input, month/year rollover and deterministic chart labels.
2. Use one explicit India display timezone, UTC+05:30, independent of the host's timezone. Reuse shared helpers; rename
   UTC-named display filters/callers so their names and behavior agree. No browser timezone setting is needed.
3. Update pages, panels, full details, hover titles, source read times, invite expiry, “Updated” labels, chart axes and
   tooltips. Search all first-party UI for UTC/time formatting; full-page and HTMX renders must agree.
4. Keep clocks, timestamps in stored telemetry, query/filter/cursor values, trace IDs and bucket math canonical/UTC.
   Relative ages and durations retain their meaning; convert only their absolute-time labels for display.
5. Run formatter/chart-label and affected router tests; check both themes and a chart spanning IST midnight. No
   displayed dashboard time should be labelled UTC. Canonical machine values in requests remain accurate.

**Done when:** all human-facing dashboard times use IST with correct dates; time windows, sorting, pagination and trace
correlation still pass their tests.

### F2. Convert every displayed monetary amount to INR

**Read:** `app/services/assistant_answers.py` (`cost_summary`), `app/domain/assistant.py`,
`app/templates/partials/assistant_body.html`, request timeline/attribute rendering, `app/config.py` and corresponding
tests.

1. Add failing tests using an explicit test rate, for example **80 INR per USD for tests only**: USD 0.25 becomes INR
   20.00. This is not a current FX quote.
2. Add one validated operator-configured positive, finite INR-per-USD rate and its as-of date. Require them when showing
   converted costs; if unavailable, show “INR conversion unavailable”, not a dollar value labelled as rupees. Do not
   fetch live rates, assume a permanent market rate or add an FX service.
3. Keep telemetry contract field `cost_usd`, stored values and canonical USD aggregation unchanged. Convert once in
   presentation/service view models, round only for display, and use a shared INR/₹ formatter with enough precision to
   avoid hiding small per-answer costs as zero.
4. Cover totals, per-answer amounts, labels and any human-facing timeline cost attribute. Search all first-party UI for
   `USD`, dollar signs and cost fields. Never relabel an unchanged number or convert the same value twice.
5. Test known-rate totals/averages, zero, None/unreported cost, invalid/missing rates, precision and full-page/HTMX
   consistency. Null costs remain unreported.
6. Show the conversion rate/as-of date near the cost summary; label converted provider cost as an estimate, distinct
   from an actual cloud billing invoice. Update operator docs/example settings using placeholders, not a live quote.

**Done when:** every displayed monetary amount is genuinely converted to INR; USD remains an internal contract unit.
Unavailable conversion is explicit.

## 9. Operator follow-up: pending evidence/configuration, not missing pages

These are separate from A–F. Prepare a checklist, then wait for relevant owner authorization before external writes,
paid queries, publication or deployment.

- **Android crashes:** inspect the Firebase export/table/location and current runtime settings. Reader/UI already exist.
  If activation is requested, arrange narrowly scoped dataset-read/job permissions, configure existing settings, then
  verify one real issue/detail and the BigQuery cost cap.
- **Live trace:** verify one staging chat request's correlation and waterfall; save an annotated, redacted trace
  explaining its latency. Fixed Trace IAM does not by itself prove the exported spans and UI match end to end.
- **Metrics/alerts:** the separate football-intelligence-platform repository already has monitoring definitions. Inspect
  deployed resources and evidence before deciding what to apply; do not reimplement M1–M6 in the dashboard.
- **Optional Token Creator cleanup:** a reader-account impersonation binding remained in the audit. Confirm its present
  need before proposing removal; never remove the runtime identity or read roles as a shortcut.
- **D9 browser evidence:** hosted storage/bfcache instrumentation and an actual full one-hour hosted expiry were not
  directly observed. Keep the existing real owner/non-owner, local shorter expiry, logout and key-rotation evidence;
  record additional checks truthfully without extracting live cookies/tokens.
- **Screenshots:** PR #22 was open/non-draft at this handoff; #23 closed. Recheck current state and the owner's hold
  instructions. Do not merge/promote it as part of these fixes; keep screenshot assets outside `docs/`.
- **Walkthrough video stays on hold.** No billing/spend panel, cloud migration, account/password system or session
  database is added by this handoff.

## 10. Quality gates and completion report

```bash
uv sync --frozen --extra dev
uv run ruff check .
uv run black --check .
uv run mypy app tests
uv run pytest
```

Also run deploy behavioral tests, `bash -n`, ShellCheck and the runtime image build for group C; source tests for A/B;
browser checks for D2. No real Google calls in tests. Use a workspace-local `--basetemp` on Windows if necessary. For F
run formatter/currency unit tests, affected page/HTMX tests and visual checks.

For each task report: ID; files; failing-before/passing-after evidence; full gate results and coverage; PR/commit if
authorized; actual external actions (normally none); remaining limits. Do not replace missing browser/live evidence with
a green unit test. Update task status with the reviewed commit/evidence.

Historical baseline only: [main CI after PR
#38](https://github.com/SumukhaK/football-dashboard/actions/runs/39441582801) passed 1,105 tests, 98.98%
coverage. The earlier independent local audit had 1,104 passes/one credential-dependent failure. Neither proves future
fixes.

## 11. Starter prompt for Cline / Nemotron

> Read guide/testing-gaps.md completely. Implement task <ID> only, using current
> main and preserving other agents' files. Show the named failing regression
> with existing fakes, then make the smallest change and run the focused checks.
> Keep the offline navigation-test fix assigned to Claude out of this task.
> Do not skip tests, weaken auth/validation, add dependencies or call live cloud
> APIs. Stop after this task with evidence and remaining limits; do not claim
> the whole plan complete or deploy/merge without the owner's authorization.
