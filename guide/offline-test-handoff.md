# Make the dashboard tests fully offline

Prepared: **20 October 2026**. **Execution: Pending — test fix not implemented.**
Publication is **Done** in [PR #38](https://github.com/SumukhaK/football-dashboard/pull/38); that PR added this guide only. Checked against main `b47f478` on 20 October 2026. Intended implementation session: Claude, 21 October 2026.

- [x] Audit and implementation handoff published.
- [ ] Fail-fast external-reader sentinel added.
- [ ] Offline Overview dependency injected without changing the tested GCP/auth configuration.
- [ ] Regression control and fresh focused/full validation recorded.

## Goal and scope

Remove the known credential-dependent Google call from the navigation test and
add a regression check that detects accidental real Google access immediately.
Tests must pass without internet or Google credentials, and must behave the same
when a developer already has Application Default Credentials (ADC).

This is a test-isolation fix within the existing plan: D2 requires source tests
to run without network, and the guide's repository rules require deterministic,
network-free tests. It is not a new dashboard feature or a login redesign.

Keep this change separate from the production retry/error-handling defect
described below. Do not deploy, alter IAM, read live telemetry or change secrets
to complete this task.

## Verified failure and evidence

Audited GitHub main: `221d6b09a7eeed4ec6b74e1d2bda0ff6c1fdbfbf`, after PR #37.

Affected test:

```text
tests/routers/test_crashes.py::test_gcp_without_firebase_project_has_no_crashes_page
```

At the audited commit, lines 202–207 construct a GCP-configured app, check that
the optional crash routes are absent, then fetch Overview to inspect its nav:

```python
client = _client(Config(source="gcp", gcp_project_id="demo-project"))
for path in ("/crashes", "/partials/crashes", f"/crashes/{FATAL_ISSUE}"):
    assert client.get(path).status_code == 404
assert 'href="/crashes"' not in client.get("/").text
```

The dummy project name does not make the Google client a fake. The final
`GET /` renders Overview, which reads the real GCP telemetry source.

Observed on 20 October:

- Exact-main GitHub CI passed **1,105 tests, 98.98% coverage**:
  [run 39432801751](https://github.com/SumukhaK/football-dashboard/actions/runs/39432801751).
- The independent Windows run passed **1,104 tests and failed this one**,
  with **99.03% coverage**, in 196.32 seconds for the full suite.
- The trace reached Cloud Logging `list_entries` for `projects/demo-project`,
  retried a blocked connection, then raised
  `google.api_core.exceptions.RetryError` caused by `ServiceUnavailable`.
- No cloud write occurred. These are historical audit results, not results
  Claude should copy as verification of its future change.

Optional local evidence, outside the repository:
`D:/Anthropic/TestProjects/.pr-reviews/implementation-audit-2026-10-20/local-tests.log`.
The description above is sufficient if that file is unavailable.

## Why CI can pass while a developer machine fails

With no ADC, client construction can fail early with `DefaultCredentialsError`.
The source-error adapter maps that to the page's unavailable banner, and the nav
assertion can still pass. With usable local ADC, construction proceeds and the
test can actually contact Google, consume read quota or wait for retries.

The audit also exposed a production defect: `app/sources/gcp/errors.py` does not
map exhausted SDK `RetryError` failures into `SourceUnavailableError`. Fixing
that alone would let this test render a banner after a real network attempt; it
would not make the test offline. Keep the test fix independent of that work.

## Read these paths first

| Path | Why it matters |
|---|---|
| `tests/routers/test_crashes.py` | Affected test and nearby optional-page tests. |
| `tests/auth/console.py` | `console()` exposes the app and a client with a real signed test-owner session. |
| `tests/routers/test_overview.py` | Existing `get_overview` dependency-override patterns. |
| `tests/routers/pages_helpers.py` | Existing test sources/helpers, including `BrokenSource`. |
| `app/dependencies.py` | The `get_overview` dependency seam. |
| `app/main.py` | Builds page services around the selected source. |
| `app/services/overview.py` | The page service captures its source at construction. |
| `app/sources/factory.py` | Selects GCP and captures its lazy reader factory. |
| `app/sources/gcp/source.py` | `google_readers()` constructs actual Google clients on first use. |

Re-read applicable repository instructions and current source before editing.
The audit used the older `dash/D9-7-live-verification` branch, which the owner
subsequently discarded as a duplicate. Start implementation from current `main`
in a suitable clean checkout; preserve unrelated files and this handoff. Do not
recreate that discarded proposal or reset another agent's work.

## Implementation steps

1. **Add a failing, fast regression check first.** In the affected test, arrange
   for the real GCP reader/client factory to raise a clear `AssertionError` if
   reached. Install this sentinel before constructing the app: the source
   factory captures a callable during construction. The current test should
   fail at that sentinel without touching ADC, retrying or opening a socket.
2. **Keep the GCP settings and owner guard.** Use `console(settings,
   clock=lambda: NOW)` so the app remains `source=gcp` with no Crashlytics
   project, and the test still uses the signed owner session. Those settings
   are what decide whether the crash routes and nav item exist.
3. **Inject an offline Overview service at the existing seam.** Override
   `get_overview` on this app using `app.dependency_overrides`, following the
   Overview route tests. Use an existing fake or a real `OverviewService` over
   fixture/in-memory telemetry with the fixed clock. Choose the smallest
   existing pattern that preserves the original navigation assertions.
4. **Retain the network sentinel after the fix.** The route checks and Overview
   nav assertion must now pass while any accidental production Google-client
   construction/read would fail immediately.
5. **Inspect related tests for the same leak.** Search for GCP-configured test
   apps followed by real page reads. Any such read must use explicit fake
   readers/services; lazy app construction alone is not proof of offline use.
   Keep any additional corrections limited to confirmed instances.
6. Run the checks below and report fresh results. Keep the focused change in
   tests/helpers unless evidence shows a small test-injection seam is missing.

Important: overriding only `get_source` is insufficient here. Overview already
holds its source in the service created by `create_app()`. Override the service
dependency or explicitly construct that service with the offline source.

## What to preserve and avoid

- Preserve all three missing-route 404 assertions and the missing-nav assertion.
- Preserve Google-mode authorization and the existing signed test-owner helper.
- Do not switch the tested app to `source=fixture`: that enables the optional
  crashes page and changes what this test is proving.
- Do not enable `auth_mode=fixture` or weaken production authentication to
  simplify a route test.
- Do not skip/xfail the test, swallow its exception, reduce retries to hide the
  call, allow real Google network access, or supply real project credentials.
- Do not revoke/delete a developer's ADC or modify their global gcloud config.
- Do not add a new mocking framework, test-only production flag or network
  dependency for this small fix. Existing pytest monkeypatch/fakes suffice.
- Scope interception to the real external boundary. Blanket socket replacement
  can break TestClient's own async plumbing and obscure what is being tested.
- Do not fold the other audit findings, dependency upgrades or guide cleanup
  into this test fix.

## Acceptance criteria

- The original route/nav assertions pass with the real auth guard enabled.
- The affected test makes zero Google client/ADC/network calls, independent of
  whether the developer already has credentials.
- Removing only the offline dependency injection makes the sentinel fail
  promptly. Check this in an isolated copy and restore it afterward.
- Existing fake-HTTP Google login tests and source-reader tests continue to
  exercise their real adapters over fakes; they are not broadly bypassed.
- The full test suite stays offline and retains its existing assertions and
  coverage gate. If any other real call is found, identify and isolate it.
- No application, deployment, IAM or secret behavior changes are needed.

## Verification commands

Run from the dashboard repository root. Dependency installation may require
network; the installed test suite must not require it. On Windows, use a fresh
workspace-local `--basetemp` if the system pytest temp directory is inaccessible.

```bash
uv sync --frozen --extra dev
uv run pytest tests/routers/test_crashes.py::test_gcp_without_firebase_project_has_no_crashes_page --no-cov -q
uv run pytest tests/routers/test_crashes.py tests/routers/test_overview.py --no-cov -q
uv run pytest
uv run ruff check .
uv run black --check .
uv run mypy app tests
```

The fail-fast sentinel is the deterministic offline proof; a quick passing run
on a machine without ADC is insufficient. Preserve unrelated local credentials
and record any verification limits explicitly.

## Prompt to give Claude

> Implement this handoff's offline-test fix against current main. First add a
> fail-fast regression proving that the named GCP navigation test reaches a real
> external reader factory. Then inject an offline Overview service through the
> existing dependency seam while preserving GCP configuration, the signed owner
> session, all route 404s and the absent-nav assertion. Keep the sentinel so the
> test cannot regress into ADC/network use. Check related tests for confirmed
> leaks, use existing helpers, and run the focused and full quality checks. Keep
> production retry handling and the other audit findings outside this change.
> Report changed files, fresh test/coverage results, the regression control and
> any remaining limitations. Preserve other agents' changes.
