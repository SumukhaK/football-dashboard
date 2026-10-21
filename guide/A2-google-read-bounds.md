# A2 — Bound Google reader retries and page reads

Status: **A2a (Cloud Logging), A2b (Cloud Trace), A2c (Error Reporting), A2d
(platform logs) and A2e (BigQuery and the final page budget) done.** A2a/A2b
merged in PR #52, A2c/A2d in PR #55 and A2e in PR #57. The page
budget below accounts for every Google source read used by the current pages.

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
- A BigQuery read starts one budget per crash/issue read. Starting the query
  and looking up a missing dataset are single requests and each get the
  **2-second** cap. Waiting for the job result covers the whole query run, so it
  gets whatever is left of the 5-second budget rather than the 2-second cap.
  Every call keeps BigQuery's own retry rules (`DEFAULT_RETRY` and
  `DEFAULT_JOB_RETRY`) with their timeout cut to match. Result rows are consumed
  through the same budget, but a later row page can still be in flight when it
  expires, with up to the job wait's own timeout, so a BigQuery read is bounded
  at roughly **10 seconds**.
- Time is measured with an injected monotonic clock, not a real sleep, so tests
  can advance it deterministically.
- Budget exhaustion raises the existing `SourceUnavailableError` with kind
  `unavailable` and a fixed, safe detail. It never returns partial data as if
  the read were complete.
- A failure raised while consuming a pager, not only when the pager is created,
  goes through the existing `guarded()` adapter.

## Page budget

The table lists the serial reads a full page request can make. The worst case
for a paged Logging, Error Reporting or platform read is 5 seconds plus one
in-flight 2-second RPC (7 seconds). Trace is one 5-second call. A BigQuery read
is 5 seconds plus one in-flight row page (10 seconds). The requests and crashes rows include the
open-panel shape because that is the busiest form of those paths.

G3-G5 add a bounded 5-second API catalogue scan, platform mapping evidence and an
independent capped Android discovery read. The conservative table below assumes
cache misses, including TTL zero; normal TTL caching reuses repeated crash,
catalogue and Android queries. A failed read stops that page path earlier.

| Page path | Serial reads including metadata | Worst case |
| --- | --- | ---: |
| Overview, all releases / G6 comparison | 7 Logging + one API catalogue | 54 s |
| Overview, selected release | 6 Logging + API catalogue | 47 s |
| Errors, current/all GCP provider groups | 3 Logging + Error Reporting + platform + mapping Logging + 2 catalogue scans | 52 s |
| Errors, retained selected/custom groups | 4 Logging (including repeat crash read) + platform + mapping Logging + 3 catalogue scans | 57 s |
| Requests list (event filter, panel open) | 2 Logging + request detail + catalogue | 31 s |
| Requests list (no event filter, panel open) | Logging + request detail + catalogue | 24 s |
| Requests Logs tab | Logging + catalogue | 12 s |
| Request detail | Logging + Trace + catalogue | 17 s |
| Data / Assistant | 3 Logging + catalogue | 26 s |
| Access | Logging + catalogue | 12 s |
| Crashes list + Android discovery | 2 BigQuery + API catalogue | 25 s |
| Crashes detail/panel + discovery | 3 BigQuery + API catalogue | 35 s |
| Crashes list + panel + discovery | 4 BigQuery + API catalogue | 45 s |

This is a serial-read budget calculation, not a hosted latency measurement.
The largest uncached Errors path leaves 3 seconds of the configured 60-second
hosted limit for rendering/transport; keep catalogue and event TTL caching enabled
for hosted use. G5 does not add retries around whole pages or weaken read/bytes caps.
Browser/live deployment verification remains separate G7/operator work.

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

## A2e — BigQuery and final page budget (done)

`BigQueryCrashSource` now starts one 5-second `ReadBudget("BigQuery", monotonic)`
per crash or issue read. `Client.query` and the missing-table `get_dataset`
lookup get the 2-second request cap. `QueryJob.result` waits for the whole query
to run, so it gets the remaining budget after the job starts; a budget already
spent by then raises the source error without waiting. Each call passes
BigQuery's own `DEFAULT_RETRY` and `DEFAULT_JOB_RETRY` cut to the same timeout,
which keeps its retries for `rateLimitExceeded`, backend errors and request
timeouts; a generic `Retry` would drop those and switch job retries off. Result
rows are consumed through `budgeted()`, so a budget that expires during
iteration raises the existing source error instead of returning partial data. A
`concurrent.futures.TimeoutError` or a `requests` timeout (a finite HTTP timeout
raises requests' own error, not a `GoogleAPIError`) from starting the query, the
job wait or the dataset lookup maps to `SourceUnavailableError` with the fixed
`unavailable` detail rather than the generic error page. Parameterised SQL,
query caps, `maximum_bytes_billed`, lazy client construction and the
missing-table behaviour are unchanged.

Tests (`test_crashlytics_budget.py`) cover the 2-second start cap, the job
wait getting the remaining budget, BigQuery's retry rules still covering rate
limits and request timeouts, the dataset-lookup arguments, a budget spent before
the query or while starting it, budget expiry during result iteration, and
job-wait, HTTP and dataset-lookup timeouts. The page budget table above
accounts for all serial page reads, including the open-panel request and crash
pages. No additional page-level retry loop was needed.

## Verification

A2a–A2e evidence, 21 October 2026:

- Focused GCP suite: **171 passed**.
- Full suite: **1,368 passed**, **98.95% coverage** (above the 80% gate). The
  two warnings are the existing FastAPI/Authlib HTTPX deprecations.
- Ruff and Black pass; strict mypy passes across **204 source files**.
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
- BigQuery tests cover the start cap, the remaining-budget job wait, BigQuery's
  own retry rules, the dataset lookup, expiry before the query, while starting
  it and during result iteration, and job-wait, HTTP and dataset-lookup
  timeouts. The existing parameter, byte-cap and
  missing-table tests still pass.
- Tests use fakes and an injected monotonic clock; there are no real sleeps or
  live Google calls. No new dependency was added.

The full suite needs a non-existent `GOOGLE_APPLICATION_CREDENTIALS` path locally
because the separate credential-dependent navigation test is not yet offline.
