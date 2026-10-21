# G7 retained-history verification and handoff

Implemented in [PR #66](https://github.com/SumukhaK/football-dashboard/pull/66),
merged as `1ea8cd9`. Status, 21 October 2026: **offline implementation, regression checks and
responsive/browser acceptance complete** (browser acceptance in [PR #76](https://github.com/SumukhaK/football-dashboard/pull/76)). G1-G6 reviewed implementation is recorded
in [the task tracker](testing-gaps.md), [foundation](G-release-foundation.md),
[controls](G3-release-controls.md), [backend views](G4-backend-release-views.md),
[attribution](G5-release-attribution.md) and [comparison](G6-release-comparison.md).
This record does not claim a hosted rollout or newly verified provider retention.

## What was verified offline

The committed [synthetic history fixture](../tests/fixtures/release_history/README.md)
passes through real FixtureSource and LocalLogSource parsers, the shared TTL cache,
release-scoped services and signed-owner full/HTMX page requests. The fixed clock
is 21 October 2026 12:00 UTC. Events span September and two October IST midnights;
two revisions map to API 2.6.0 and one platform revision remains unattributed.
Android display versions are independent, including 2.6.2 alongside API 2.5.0.

| Case | Observed offline result |
|---|---|
| All, 2.5.0, 2.5.1, 2.6.0, unknown, absent | Source rows, service counts and full/partial Requests agree. Selected absent labels remain selected. |
| Pooled comparison | Five requests, one server failure, p50 30 ms, p95 1000 ms; unknown rows reconcile with combined totals. |
| Tokens/cost | Ten prompt/five completion tokens and one reported cost among two answers; configured synthetic 80 INR/USD converts USD 0.25 to INR 20 once. |
| IST/history | 01 Oct 23:59 IST and 02 Oct 00:01 IST remain different local dates. Native IST forms emit exact UTC range URLs. September data is available in its custom range, absent from quick 7d. |
| Navigation/details | Real comparison drill-down selects exact rows. Request and Android full/panel return links keep custom UTC scope; Android links also keep independent Android version, including unknown issue returns. |
| Cache/discovery | Release predicates and periods remain independent. Repeated release navigation shares one catalogue scan. Missing-file failures retry after the file appears. |
| Failed/tail/capped history | Missing log displays unavailable; a byte tail reports incomplete discovery, not complete absence. Actual 5000-row source caps reach service/table/Logs warnings; bounded totals reconcile. |
| Range boundaries | Accepted 31-day span/365-day lookback does not imply retained data. Beyond-bound/future queries reject before events or catalogue reads. |
| Provider attribution | Two revisions map to one recorded API release; an unmapped revision remains visible and unattributed. |

These are real in-process HTTP/adapter checks, not browser-rendering tests.
Existing G2/G5 tests cover Google predicates, read budgets, source failures,
conflicting mappings and Android BigQuery/cache isolation without paid calls.
The separate credential-dependent offline-test defect remains its own handoff.
Local full-suite verification uses an intentionally nonexistent ADC path, as in
prior G tasks; this is not a fix to that separate defect.

The fixture regression caught a G6 defect: aggregation used test-only tokens_in /
tokens_out attribute names. Actual contract 1.1.0 emits prompt_tokens /
completion_tokens. The comparison now uses those existing contract keys; neither
stored telemetry nor the contract changed. Both real-file regressions failed
before the fix. Deliberately restoring the wrong names also fails both tests;
restoration passes the focused suite. G6 unit inputs now use contract field names.

Focused validation: **52 checks passed**, including 31 new history cases and the
21 existing comparison checks. Ruff, Black and strict mypy are required alongside
full coverage, image build and ShellCheck before merge; final CI evidence belongs
to the reviewed PR and the completion record in testing-gaps.md.

## Reviewed completion evidence

Reviewed head `f61164d` passed
[CI 39626673576](https://github.com/SumukhaK/football-dashboard/actions/runs/39626673576):
**1,590 tests, 98.63% coverage**, Ruff, Black, strict mypy (234 files), image
build and ShellCheck. No pending code-review findings remain. Review checked
contract keys, real parsers, scopes/cache, null/cap/failure semantics, return links,
fixture privacy and documentation. Both real-reader tests caught a deliberate
wrong-token-name mutation; the original bytes were restored before verification.
PR #66 merged with the owner's authorized administrator override. Main includes
C1-C3 PR #63; duplicate #65 is closed without merging and was not incorporated.

On Windows, use a short dedicated pytest temporary directory when the checkout
is deeply nested: deployment tests create verification-record filenames that
can exceed legacy path-length limits under a checkout-local --basetemp. The
observed FileNotFoundError passed when rerun under a short temporary directory;
no deployment-code workaround or test suppression was added.

## Supported sources and the meaning of history

- Fixture: deterministic demonstration records, shifted together to the current
  clock in normal local runs. They are synthetic, not production release evidence.
- Local: only valid records in the configured file's retained byte tail (default
  50,000,000 bytes). File rotation/deletion, skipped invalid lines and tail limits
  can remove older evidence; the Source page exposes local read diagnostics.
- Google: only entries actually retained by the selected project/log scope and
  allowed by reader permissions/predicates/budgets. Discovery and event reads are
  bounded; partial/unavailable must not be interpreted as complete history.
- Error Reporting groups in current/all GCP views are provider rolling groups,
  explicitly source-wide. Exact/custom groups use matching retained crash logs.
  Platform attribution needs complete, unambiguous in-window revision evidence.
- Android Crashlytics requires separately configured exports and permissions;
  API release never silently filters Android display_version. API/mobile
  correlation remains a separately coordinated instrumentation/export task.

Omitted api_version means all releases, including unknown. An exact value such as
2.6.0 matches its recorded label; v2.6.0 is a different label. Unknown is explicit.
Console version, Cloud Run revision, API release and Android version are separate.
Quick windows are 1h/6h/24h/7d. Custom start/end are entered in IST, carried as UTC,
start inclusive/end exclusive. Defaults permit 31 days per query and 365 days
back; **these safety settings are not verified cloud retention**. Sorting, filters,
navigation and detail return preserve the selected scope; counts describe the
bounded retained sample, not release lifetime or deployment dates. INR requires
a configured rate/date, preserves canonical USD and remains an estimate.

Actual deployed Logging bucket retention, exclusions, coverage of historical
releases and Android export retention: **not verified in G7**. No provider read,
resource creation, deployment, IAM, secret, retention or paid export was performed.
A release tag cannot prove its telemetry was emitted or still exists. Deleted or
never-emitted telemetry cannot be reconstructed by this dashboard.

## Browser acceptance

Run on 21 October 2026 with Playwright driving Chromium 141.0.7390.37 (headless) against main `59705f3`
plus the PR #76 fix. The earlier controller attempt had reported `Local browser use is disabled in Work
settings`; this run used the cloud session's own Chromium instead. Hosted verification is still separately
pending until an approved candidate is deployed and accepted using the merged C1–C3 workflow.

The offline loopback preview uses the same fixed clock, without Google login. Fixture mode only serves
on a loopback socket the launcher bound itself (D1), so the preview binds through `app.demo`:

```bash
uv run python -c "from app.demo import bind_loopback, _serve; from app.factory import create_app; from tests.history.helpers import NOW, settings; sock, listen = bind_loopback('127.0.0.1', 8082); _serve(create_app(settings().model_copy(update={'auth_mode': 'fixture'}), clock=lambda: NOW, listen=listen), sock)"
```

This deliberately enables fixture demonstration auth on loopback with synthetic
records. It is not the hosted owner-login configuration and must not be deployed.
Open http://127.0.0.1:8082 and select IST 01 Oct 2026 23:58 through 03 Oct 2026 00:05.

| Check | Result |
|---|---|
| Desktop 1280px and mobile 390px/320px, both themes | **Pass.** Overview, Errors, Requests, Logs, Assistant, Crashes, Data and Access: no horizontal page overflow at any width, the theme applied from storage, and no console errors. The comparison table scrolls inside its labelled region (`overflow-x: auto`). |
| Keyboard | **Pass.** Tab reaches the release selector, the Custom period summary, the comparison scroll region and all four sort links; every focused control showed a visible focus style. |
| Release/sort/quick/custom | **Pass.** All, 2.6.0, 2.5.1, 2.5.0 and Unknown each applied, kept the period and showed as selected. Requests and p95 sorts toggled descending/ascending with `aria-sort` and the URL in step, and refresh kept the sort. |
| Requests Logs | **Pass.** Entries are labelled on both sides of IST midnight (01, 02 and 03 Oct), and the severity and event filters are present. No continuation link appears, because the sample period fits on one page. |
| Request and Android details | **Pass.** At 390px the request panel opens as a fixed overlay and closes. The full detail's return link keeps the period. An absent request and an absent issue each answer 404 with a not-found message and a return link, and the crash detail's return link keeps the period. |
| Back/Forward and privacy | **Pass after the fix below.** Back and Forward through period, sort, release and page changes land on the exact URLs. The theme toggle works. Pages and partials are `no-store`, and `hx-history="false"` stays on the body. |

**Defect found and fixed in PR #76.** After Back, Chromium restored the previously chosen release
(2.6.0) in the selector while the page showed all releases, so Apply would silently re-apply the
old scope. Every GET form (release, period, Android version, Logs filters and request search) now
sets `autocomplete="off"`. A rerun shows the selector matching the page after each Back, and
`tests/routers/test_form_state.py` fails if a GET form loses the attribute.

## Conditional retention/archive proposal

No longer-history requirement or provider coverage has been verified here, so
there is no approved storage change. If the owner needs missing release history:

1. Record the project, Logging bucket/location, configured retention days,
   exclusions and actual oldest/newest available metadata using an authorized
   operator. Do not infer this from the dashboard's 365-day query safety bound.
2. Specify the required horizon and daily valid bytes/events. Prefer evaluating
   the existing Logging retention before adding storage or a second query system.
3. Quote current regional pricing before approval: retained GiB by month times
   storage rate, retained volume beyond free allowances, export/ingestion/egress
   costs and expected query bytes times query rate. Include lifecycle/deletion,
   encryption and a maximum query spend; no dollar estimate is invented here.
4. List exact resources and least-privilege writer/reader permissions, data
   minimization/contract validation, access logging and restore/query procedure.
5. Obtain separate owner approval for the concrete cost/IAM/retention proposal.
   Only then implement/export and verify with representative non-sensitive data.

This proposal creates no bucket, sink, database, broad IAM grant or paid scan.
