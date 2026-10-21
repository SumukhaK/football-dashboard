# A2 — Bound Google reader retries and page reads

Status: **A2a (Cloud Logging), A2b (Cloud Trace), A2c (Error Reporting) and A2d
(platform logs) implemented and verified in this branch; A2e (BigQuery and the
final page budget) remains pending.** Do not describe all source reads as
bounded until A2e verifies the combined page budget.

Source task: [testing-gaps.md, A2](testing-gaps.md#a2-bound-the-readers-retry-and-timeout-behavior).
Hosted limit: Cloud Run `--timeout 60` (see [D7](D7-deploy.md)).

## Budget policy

The initial policy is deliberately conservative and is shared by the readers:

- A single `TelemetrySource` read gets **5 seconds** of wall-clock budget.
- A Logging or Error Reporting page/RPC gets at most **2 seconds** for transport
  and its own retry deadline, so a budget that expires during an in-flight page
  can overrun by at most one RPC. A paged Logging or Error Reporting read is
  therefore bounded at roughly **7 seconds**.
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
`PlatformReader`; A2d now passes the same budget, timeout and retry to it.

## A2b — Cloud Trace

`TraceServiceClient.get_trace` supports both `retry` and `timeout`. The reader
passes a finite timeout and a matching retry deadline. `NotFound`, including a
retry-wrapped `NotFound`, still returns `None`; a timeout or exhausted retry
still becomes `SourceUnavailableError` through `guarded()`.

## A2c — Error Reporting (done)

`ErrorStatsServiceClient.list_group_stats` supports `retry` and `timeout`. The
reader starts one 5-second budget per `error_groups()` call, checks it before
creating the pager, passes a 2-second transport timeout with a matching retry
deadline, and checks the whole-read budget while consuming the pager. The pager
is consumed inside `guarded()`, so a failure raised after the pager is created
still becomes the existing source error. The project/service filter, period
mapping and post-read window trimming are unchanged.

Tests cover the timeout/retry arguments, a budget that expires before the call,
budget expiry during pager iteration, an iteration-time service failure, quota
mapping and the unchanged request mapping.

## A2d — platform logs (done)

`PlatformReader` now starts one 5-second budget per `platform_events()` call,
passes the 2-second timeout and matching retry deadline through A2a's Logging
adapter, and checks the whole-read budget while consuming the pager. Its
`PLATFORM_EVENT_LIMIT=1000` row cap, system-log filter, newest-first ordering and
classifier are unchanged. The read remains one bounded adapter call.

Tests cover the timeout/retry arguments and row cap, a budget that expires
before the call, budget expiry during pager iteration, an iteration-time service
failure, and the existing classification and source-error cases.

## A2e — BigQuery and final page budget (pending, separate change)

This remains pending and is not part of the A2c/A2d change. It is larger because
it combines BigQuery job/result waits with measuring the whole page budget across
the six page paths (Overview, requests, request detail, errors, data and
assistant), including the allowed overrun of an in-flight call and rendering
margin.

- Bound BigQuery job/result waits with a supported timeout or a remaining
  budget; preserve `maximum_bytes_billed` and parameterised SQL.
- Measure each page path's serial read count.
- Prove the total page budget fits the 60-second hosted limit.
- Only after this check may the repository claim that Google reads are bounded.

## Verification

A2a–A2d evidence, 21 October 2026:

- Focused GCP suite: **159 passed**.
- Full suite: **1,356 passed**, **98.95% coverage** (above the 80% gate). The
  two warnings are the existing FastAPI/Authlib HTTPX deprecations.
- Ruff and Black pass; strict mypy passes across **202 source files**.
- Logging and Trace tests cover timeout/retry arguments, budget exhaustion
  across chunks, expiry during pager iteration, a failure raised during pager
  iteration, `NotFound` including a retry-wrapped `NotFound`, permission errors
  and transport timeouts.
- Error Reporting tests cover the timeout/retry arguments, expiry before the
  call and during pager iteration, an iteration-time service failure and the
  unchanged request mapping.
- Platform-log tests cover the timeout/retry arguments, the 1,000-row cap,
  expiry before the call and during pager iteration, an iteration-time service
  failure and the unchanged filter/classifier.
- Tests use fakes and an injected monotonic clock; there are no real sleeps or
  live Google calls. No new dependency was added.

A2e still needs BigQuery bounds and the whole-page budget measurement. The full
suite needs a non-existent `GOOGLE_APPLICATION_CREDENTIALS` path locally because
the separate credential-dependent navigation test is not yet offline.
