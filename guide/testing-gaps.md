# Dashboard gaps and owner requirements: small tasks for Cline / Nemotron

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
| G | API release filtering, history and comparison | New owner requirement added on 20 October; backend metadata exists, dashboard support is pending. |

**One task per Cline session.** Paste this whole file, then request one ID, such as A1. Read its files, add its failing
check, implement the smallest fix, run its focused checks, then stop and report. Review each completed task before
starting the next. Keep a group in a focused PR; split further if needed.

Dependency order: A1 → A2; B1 → B2; C1 → C2 → C3; D1 → D2; G1 → G2 → G3 → G4 → G5 → G6 → G7; E1 last.
F1 and F2 are independent display tasks; finish F/G before E1 reconciles the guides. A, B and D have no code dependency
on each other. Work sequentially unless the owner
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
rotate secrets, activate BigQuery, run paid model calls or resume the video walkthrough. Operator tasks are in §10.

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

## 9. Group G — API release views, combined data and historical comparisons

**Current evidence:** the platform's `ai/shared/telemetry/json_formatter.py` emits `api_version` on log lines;
`ai/backend/app/config.py` defaults to `2.6.0`; tracing records `service.version`. However,
`app/domain/models.py` drops `api_version` in `TelemetryEvent.from_log_line()`, `EventQuery` has no version predicate,
and local/GCP filters and page services do not filter by API release. Request detail shows a Cloud Run revision,
not an API release. The sidebar's console version and Crashlytics' Android `app_version` are different identities.
**Today the dashboard is combined, not a reliable release-by-release view.** These tasks add a requested feature;
they do not claim an original D1–D9 requirement was missed.

### G1. Preserve release identity and define selection semantics

**Read:** `app/domain/models.py`, `app/domain/requests.py`, `app/contract.py`, `contract/telemetry-events.json`,
`tests/test_models.py`, fixture builders and the platform formatter/config/tracing files named above.

1. Add mixed-release test events for `2.5.0`, `2.5.1`, `2.6.0` and unknown version. Assert parsing retains the recorded
   API release separately from revision, telemetry contract version, console version and Android app version.
2. Add one validated release-selection type: all, exact recorded release, or unknown. Omitted URL selection means all;
   all includes unknown. Known-release selection excludes unknown. Bound input length and escape rendered labels.
3. Preserve exact recorded identity. Do not silently turn the owner's example `2.50` into `2.5.0`, merge `v2.6.0`
   with `2.6.0`, or derive a release from a revision name. Define empty/null/unusable values as unknown; retain the
   existing contract's required-field rules instead of accepting invalid records to manufacture historical coverage.
4. Check the platform release workflow supplies the actual API release rather than a stale default; document any
   mismatch as a narrowly scoped platform prerequisite. Existing historical metadata cannot be rewritten as fact.

**Done when:** identity and all/exact/unknown semantics have offline tests; contract 1.1.0 remains compatible.

### G2. Filter at each source and keep caches independent

**Read:** `app/sources/base.py`, `filtering.py`, `fixture_source.py`, `local_log_source.py`, `cached.py`,
`app/sources/gcp/filters.py`, `logging_reader.py`, `entries.py`, source protocols/fakes and source tests.

1. Implement in small sessions: **G2a** query/shared filtering plus fixture source; **G2b** local logs; **G2c** GCP and
   cache parity. Add release to `EventQuery` and apply it before limit, pagination and aggregation, not after a
   combined capped result. Preserve time, route, status, event and request-ID predicates.
2. Build an escaped exact `jsonPayload.api_version` Cloud Logging predicate and explicit unknown handling matching
   local/fixture semantics. Test malformed/hostile input with recording fakes; never interpolate unchecked clauses.
3. Include release selection in every affected cache key, including later error/platform calls. Test all → 2.5.1 →
   2.6.0 → unknown with identical windows: no cached rows/counts can cross selections. Preserve TTL, caps and A2 budgets.
4. Discover available releases through a bounded, cached source operation within the configured project/service and
   retained period. Do not hardcode the three examples or infer a complete catalog from the first capped events page.
   Surface incomplete discovery and failures; retain a selected URL release even when it has no rows in this window.

**Done when:** fake GCP, local and fixtures return the same selected rows; discovery adds no unbounded scan or per-row
RPC. Run model/filter/source/cache tests, including mixed versions at the page boundary and identical timestamps.

### G3. Add the shared release picker and historical time range

**Read:** `app/templates/base.html`, `partials/window_picker.html`, `partials/sidebar.html`, `app/services/links.py`,
`windows.py`, `labels.py`, routers, navigation/HTMX tests and the existing CSS tokens.

1. **G3a:** put a labelled native API release selector beside the time picker on every telemetry page. Choices:
   “All API releases” (default), discovered releases and “Unknown API release”. Show the active scope above results.
   Sort valid semantic versions numerically newest first (`2.10.0` before `2.9.0`); define prerelease order,
   then stable ordering for other recorded labels, with unknown last. Reuse existing dependencies or small helpers.
2. Store selection in `api_version=2.6.0`; reserve/document `api_version=unknown`, and omit the parameter for all.
   Keep this context in navigation, filter chips, window changes, refresh, HTMX URLs, pagination, details, panel
   open/Close, back/forward and shared links. Reset pagination on selection changes; preserve unrelated filters.
3. **G3b:** retain quick 1h/6h/24h/7d choices and add a bounded custom start/end range for older releases. Input and
   labels use IST (F1); canonical URL/source timestamps use UTC. Resolve one immutable window for every panel and
   comparison; validate reversed/future/excessive ranges and provider limitations without silently widening them.
4. Show “No data for this release and period” separately from source/discovery failure, with retry and change-period
   controls. Never silently revert to all releases. Loading state must not display previous-selection data as current.
5. Verify narrow mobile layout, keyboard/visible focus, both themes, full and partial renders. A long release label
   must not hide controls; use the current shell rather than introducing a frontend framework.

**Done when:** URLs restore both release and period; UI controls work on mobile; no selector silently loses scope.

### G4. Carry selection through every backend view and expose logs

**Read:** services/routers/templates for Overview, Requests/detail/panel, Errors, Assistant, Data and Access;
`app/services/tiles.py`, `freshness.py`, `request_detail.py`, `events.py` and links. Grep all source calls first.

1. Implement and review separately: **G4a** Overview; **G4b** Requests/logs/details; **G4c** Assistant; **G4d** Data;
   **G4e** Access. Each session adds red service/router tests before changing its page and shared callers.
2. Scope tiles, current/previous-window deltas, charts, slow routes, tables, drill-downs, tokens/cost, refresh jobs,
   sign-ins and lockouts to the same release. Apply selection to lookback/latest-state reads too: no fallback to
   another release's component or freshness state when the selected release has none. Label missing state explicitly.
3. Add API release to request rows, summary panels, full details and log timelines. Resolve a detail against its own
   recorded request/release; a mismatched selected release gets a clear not-in-selection result and return control.
   Load only that request's correlated trace; missing trace/version attribution must not become an unrelated waterfall.
4. Provide a “Logs” tab within Requests using existing event/rendering helpers: IST time, API release, severity, event,
   request link when present, and the existing sanitized message/attribute presentation. Include non-request events;
   support severity/event filters, bounded pagination and the same release/time context. No new raw-log export.
5. Source diagnostics, dashboard owner login and invite administration describe the console/source, not backend API
   behavior. Label these “Source-wide”/“Console-wide”; preserve navigation context without claiming release filtering.

**Done when:** every displayed backend metric and event is scoped, with release badges in combined lists; independent
console diagnostics are identified. Test every page/HTMX variant and the mobile Close/error/unknown-ID paths.

### G5. Attribute errors, platform events and Android crashes honestly

**Read:** `app/services/errors.py`, `app/sources/gcp/errors_reader.py`, `platform_reader.py`, local/fixture grouping,
`app/domain/models.py`, crash sources/services and their fakes. Update Protocols, cache keys and all callers together.

1. **G5a, errors:** filter local/fixture `app.crash` events before grouping. The installed Error Reporting SDK has
   `ServiceContextFilter.version`; only use it when evidence shows that provider version equals the API release.
   Cloud Run revision labels are not that evidence. Test one identical exception occurring in two API releases.
2. If Error Reporting cannot answer the exact release or historical end time, derive explicitly labelled groups from
   the matching retained `app.crash` logs; otherwise show “Unavailable for this release/period”. Do not display
   service-wide group counts under a release badge, or provider rolling-period counts as an exact custom window.
3. **G5b, platform:** use an explicit, unambiguous revision → API release mapping from retained telemetry or verified
   operator metadata. A release may span multiple revisions; conflicting/missing mappings stay unattributed.
   Preserve platform events in all mode and expose unknown attribution; never guess from deployment time/name.
4. **G5c, Android:** keep an independent “Android app version” picker for Crashlytics issue lists and details, filtering
   events before grouping and respecting query/bytes caps. A client release does not identify its API release.
   Without a recorded API correlation field show Android data as independently scoped, not filtered by the API picker.
5. If API-attributed Android crashes are required, specify a separate coordinated mobile/export/contract task with
   validated non-secret API-release metadata and mixed-version tests. Mark it pending until that evidence exists;
   do not fabricate a relationship or activate paid exports under this plan.

**Done when:** every Errors/Crashes section says selected, independently scoped or unattributed; source limitations
never masquerade as zero failures. Run error/platform/crash source, service, router and cache tests.

### G6. Compare API releases in Overview, including combined totals

1. In all mode add a “By API release” comparison table below the existing summary: release, request count, 5xx count,
   error rate, p50/p95 latency, backend crash count, assistant tokens/cost in INR, and first/last observed IST time.
   Clicking a release scopes the existing pages. Keep unknown visible and table rows semantically sorted by default;
   allow explicit sorting by request volume, error rate or p95 with stable ties and unknown values last.
2. Use the same bounded window, predicates and samples as the combined summary. Sum compatible counts/tokens/cost;
   calculate combined error rate from total failures / total requests, and latency percentiles from merged request
   samples. Never average per-release percentages or percentiles. Distinguish 4xx/5xx definitions and missing costs.
3. Show sample counts, truncation/sampling warnings and observation range. First/last observed is not a deployment
   timestamp or lifetime coverage. A quiet release is “No observations”, not proof of health or zero lifetime errors.
4. Test uneven release traffic, redirects, one fast/one slow release, missing/unknown versions, null costs and cap
   boundaries. Release totals must reconcile with all mode including unknown. Reuse F2 conversion once for INR.
5. Keep existing charts scoped to the selected release, and the comparison table usable by keyboard and on mobile.
   Do not add multi-select overlays or a second analytics framework to deliver this requirement.

**Done when:** selecting 2.5.0/2.5.1/2.6.0 shows that release's behavior; all mode offers honest comparable totals and
drill-downs without extra per-release scans that defeat A2's page budget.

### G7. Verify history limits and finish the handoff

1. Create deterministic mixed-release fixtures across IST midnight, multiple revisions and older dates. Cover all,
   exact, unknown, empty, failed and truncated results through source → service → page, URL navigation and cache.
2. Test discovery and custom ranges against retained-data limits offline. Document the actual configured retention
   when separately verified; do not assume 2.5.0 logs still exist because the code release/tag exists. Deleted or
   never-emitted telemetry cannot be reconstructed. Keep missing release history explicit rather than inventing data.
3. If longer history is needed, record a separately approved retention/archive proposal with storage/query cost and
   permissions; no new database, sink, bucket retention change, broad IAM or paid historical scan in these tasks.
4. Run full quality gates plus responsive checks for selector/logs/comparison and all detail return controls. Update
   existing guides with supported sources, API-versus-Android identity, IST/INR, exact scope and history limitations.

**Done when:** G1–G6 have reviewed commits and truthful evidence; unavailable historical/provider attribution remains
clearly marked. This publication itself implements none of G1–G7.

## 10. Operator follow-up: pending evidence/configuration, not missing pages

These are separate from A–G. Prepare a checklist, then wait for relevant owner authorization before external writes,
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

## 11. Quality gates and completion report

```bash
uv sync --frozen --extra dev
uv run ruff check .
uv run black --check .
uv run mypy app tests
uv run pytest
```

Also run deploy behavioral tests, `bash -n`, ShellCheck and the runtime image build for group C; source tests for A/B;
browser checks for D2. No real Google calls in tests. Use a workspace-local `--basetemp` on Windows if necessary. For F
run formatter/currency unit tests, affected page/HTMX tests and visual checks. For G run model/filter/source/cache,
aggregation, release/time URL and every affected router test, plus responsive selector/log/comparison checks.

For each task report: ID; files; failing-before/passing-after evidence; full gate results and coverage; PR/commit if
authorized; actual external actions (normally none); remaining limits. Do not replace missing browser/live evidence with
a green unit test. Update task status with the reviewed commit/evidence.

Historical baseline only: [main CI after PR
#38](https://github.com/SumukhaK/football-dashboard/actions/runs/39441582801) passed 1,105 tests, 98.98%
coverage. The earlier independent local audit had 1,104 passes/one credential-dependent failure. Neither proves future
fixes.

## 12. Starter prompt for Cline / Nemotron

> Read guide/testing-gaps.md completely. Implement task <ID> only, using current
> main and preserving other agents' files. Show the named failing regression
> with existing fakes, then make the smallest change and run the focused checks.
> Keep the offline navigation-test fix assigned to Claude out of this task.
> Do not skip tests, weaken auth/validation, add dependencies or call live cloud
> APIs. Stop after this task with evidence and remaining limits; do not claim
> the whole plan complete or deploy/merge without the owner's authorization.
