# A2 — Bound Google reader retries and page reads

Status: **A2a (Cloud Logging) and A2b (Cloud Trace) implemented and verified in
this branch; A2c–A2e remain pending.** Do not describe all source reads as
bounded until A2e verifies the combined page budget.

Source task: [testing-gaps.md, A2](testing-gaps.md#a2-bound-the-readers-retry-and-timeout-behavior).
Hosted limit: Cloud Run `--timeout 60` (see [D7](D7-deploy.md)).

## Budget policy

The initial policy is deliberately conservative and is shared by the readers:

- A single `TelemetrySource` read gets **5 seconds** of wall-clock budget.
- A Logging page/RPC gets at most **2 seconds** for transport and its own
  retry deadline, so a budget that expires during an in-flight page can overrun
  by at most one RPC. A Logging read is therefore bounded at roughly **7
  seconds**.
- A Trace call gets the full **5 seconds** for transport and retry; it is one
  serial operation.
- Time is measured with an injected monotonic clock, not a real sleep, so tests
  can advance it deterministically.
- Budget exhaustion raises the existing `SourceUnavailableError` with kind
  `unavailable` and a fixed, safe detail. It never returns partial data as if
  the read were complete.
- A failure raised while consuming a pager, not only when the pager is created,
  goes through the existing `guarded()` adapter.

The busiest current page is Overview: six serial Logging reads (current window,
previous window and the tile lookback). At the policy above its worst read cost
is about 42 seconds, leaving about 18 seconds for rendering and transport
margin. The request-detail page is Logging plus Trace; A2e must measure the
combined page and adjust these numbers if the real read distribution requires
it.

## A2a — Cloud Logging

Use `LoggingServiceV2Client.list_log_entries`, whose supported `retry` and
`timeout` arguments bound each page call. The high-level `logging.Client` does
not expose those arguments, so a small adapter keeps the existing
`LoggingClient` protocol and converts returned entries back to the entry shape
the readers already use. The adapter passes the policy's timeout and retry
deadline to the SDK and preserves the existing filter, order, page size and
row cap.

The reader starts one budget per `events()` call, checks it before each
request-ID chunk and while consuming entries, and therefore accounts for
chunk/page multiplication. `max_results`, `page_size`, tie handling and
parameterised filters are unchanged. The adapter is also wired into
`PlatformReader`, but that reader does not pass a budget yet, so platform-log
reads remain unbounded until A2d.

## A2b — Cloud Trace

`TraceServiceClient.get_trace` supports both `retry` and `timeout`. The reader
passes a finite timeout and a matching retry deadline. `NotFound`, including a
retry-wrapped `NotFound`, still returns `None`; a timeout or exhausted retry
still becomes `SourceUnavailableError` through `guarded()`.

## A2c — Error Reporting (pending)

- Inventory `list_group_stats` and its pager/retry defaults.
- Pass supported `retry` and `timeout` arguments, with the same finite budget
  policy.
- Convert failures during pager iteration to the existing source error.
- Add a fake that raises during iteration, and a budget-expiry test. Do not
  change the service/window mapping.

## A2d — platform logs (pending)

- Reuse A2a's bounded Logging adapter and budget rather than adding another
  retry wrapper.
- Preserve `PLATFORM_EVENT_LIMIT`, the system-log filter and the classifier.
- Verify the platform read accounts for its 1,000-row cap as one bounded read.

## A2e — BigQuery and final page budget (pending)

- Bound BigQuery job/result waits with a supported timeout or a remaining
  budget; preserve `maximum_bytes_billed` and parameterised SQL.
- Measure the busiest page paths (Overview, requests, request detail, errors,
  data and assistant) with their serial read counts.
- Prove the total page budget, including the allowed overrun of an in-flight
  call and rendering margin, fits the 60-second hosted limit.
- Only after this check may the repository claim that Google reads are bounded.

## Verification

A2a/A2b evidence, 21 October 2026:

- Focused GCP suite: **151 passed**; the budget/reader subset alone is **33
  passed** (`test_budget.py`, `test_logging_client.py`,
  `test_logging_reader.py` and `test_trace_reader.py`).
- Full suite: **1,348 passed**, **98.95% coverage** (above the 80% gate). The
  two warnings are the existing FastAPI/Authlib HTTPX deprecations.
- Ruff and Black pass; strict mypy passes across **202 source files**.
- Logging tests cover timeout/retry arguments, budget exhaustion across chunks,
  expiry during pager iteration, a failure raised during pager iteration,
  structured and text payload conversion, row caps and unchanged filters.
- Trace tests cover timeout/retry arguments, budget expiry before the call,
  `NotFound` including a retry-wrapped `NotFound`, permission errors and a
  transport timeout.
- Tests use fakes and an injected monotonic clock; there are no real sleeps or
  live Google calls. No new dependency was added.

A2c–A2e still need their own tests and page-budget measurement. The full suite
needs a non-existent `GOOGLE_APPLICATION_CREDENTIALS` path locally because the
separate credential-dependent navigation test is not yet offline.
