# A1 — Google retry exhaustion verification

Implemented: **21 October 2026**, commit `38ebcb5eea8665067a05b15099cc6a94741fea2d`.
Base: `main` at `5ca80ea1b4bd793262418260bc044a594aebe0ae`.
Scope: [testing-gaps.md, A1](testing-gaps.md#a1-translate-an-exhausted-sdk-retry-into-the-existing-source-error).

## Result

The shared Google adapter now translates an exhausted `RetryError` into the
existing `SourceUnavailableError`. Permission and quota causes retain their
existing classifications; other exhausted transport failures are unavailable.
The banner uses a fixed service-specific retry message, without SDK wrapper
text, credential details or payloads. The original exception remains chained.

Direct unmapped errors still propagate. A retry-wrapped `NotFound` is returned
to the reader's existing missing-resource policy; Cloud Trace still returns
None for a missing trace. No route/domain contract or dependency changed.

The adapter calls the supplied operation once. It does not retry, sleep, set
timeouts or bound the full page duration. **A2a–A2d now add finite Logging,
Trace, Error Reporting and platform-log budgets; A2e's BigQuery and whole-page
budget check remains pending.**

## Tests and review evidence

- Before the implementation: the new adapter/banner tests produced **11
  expected failures**, and the wrapped-NotFound Trace test produced one more.
  These used local fake failures, with no SDK network call or real sleep.
- All fake-backed GCP reader tests plus Overview tests: **110 passed**.
- After correcting the new router fake's module-path collision with mypy:
  **28 directly affected tests passed**; repository Ruff and Black passed;
  strict mypy passed across **183 source files**.
- Local full suite: **1,186 passed, 98.95% coverage**, above the existing 80%
  gate. The shared error adapter had **100% coverage**. The run emitted two
  existing FastAPI/Authlib HTTPX deprecation warnings.
- An in-memory mutation that changed every classification to unavailable was
  rejected, including four new wrapped permission/quota cases. No mutation
  was written to the checkout.
- Authenticated full Overview and its HTMX partial both return HTTP 200 with
  the normal alert banner. Private wrapper/cause markers and traceback text
  are absent. Each fake Logging client records exactly one call.
- Self-review checked every `guarded()` caller and preserved direct mappings,
  query limits, auth and reader-specific missing-resource handling. No
  blocking issue remained in the final adapter/test diff.

## Commands

```powershell
uv sync --frozen --extra dev
.venv/Scripts/python.exe -m pytest tests/sources/gcp tests/routers/test_overview.py tests/routers/test_overview_retry.py --no-cov -q
.venv/Scripts/python.exe -m ruff check .
.venv/Scripts/python.exe -m black --check .
.venv/Scripts/python.exe -m mypy app tests
```

For the local full run, `GOOGLE_APPLICATION_CREDENTIALS` was temporarily set
to a verified nonexistent workspace file, restored afterward, and pytest ran
with `--basetemp .pytest_cache/a1-tmp -q --tb=short` and the configured coverage
gate. This prevents existing local ADC from letting the known navigation test
contact Google. It does **not** repair that test's dependency on credentials.
The final router-fake isolation correction was verified with the 28-test subset;
the final PR's full CI is the check for the complete published tree.

## Remaining limits

The separate [offline navigation-test fix](offline-test-handoff.md) remains
pending; its test/helper was not edited. Read retry/time budgets are A2, not
an outcome of this fix. Direct SDK-error diagnostics keep their pre-existing
behavior; this change sanitizes retry-exhaustion details only.

No deployment, IAM/secret changes, live Google failure injection or visual
browser acceptance was performed. HTTP behavior was verified with TestClient
and the production Logging reader over a local fake client.
