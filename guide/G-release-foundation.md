# G1–G2 API release foundation

Updated: 21 October 2026. This record does not enable a release picker or claim
that page metrics already honor a selected release. G3–G7 remain separate.

## G1 identity

Merged in [PR #48](https://github.com/SumukhaK/football-dashboard/pull/48),
merge `645ab69`, reviewed head `1893e2d`; all exact-head CI checks passed.

Implemented from main `0d8ff5a`. [ADR 003](adr/003-api-release-identity.md)
defines exact identity, supported labels and the reserved unknown selection.
TelemetryEvent retains `api_version` independently of revision, contract and
Android identities. ReleaseSelection is frozen/hashable with distinct
all/exact/unknown states. Existing constructors and contract 1.1.0 remain
compatible; required missing fields are still rejected.

Evidence: 33 new failures before implementation, 34 identity checks and 78
identity/model/contract checks passed afterward. Full local suite: **1,260
passed, 98.95% coverage**. Ruff, Black and strict mypy passed. Removing identity
retention in memory failed all eight exact-label cases. The frozen-mutation
test's dynamic assignment was separately rechecked after its typing fix.

Source check in the platform repository: `backend.app.main.create_app()` passes
`settings.api_version` into logging; JsonFormatter emits it unchanged. Config
currently defaults to `2.6.0`. The inspected tracked release/container workflows
do not inject a tag-derived backend API_VERSION. Operator prerequisite: set the
actual backend release explicitly when deploying and verify emitted metadata;
an Android or dashboard release is not that value. No platform files, deployed
configuration or historical records were changed by this task.

## G2a shared query and fixture filtering

Merged in [PR #49](https://github.com/SumukhaK/football-dashboard/pull/49),
merge `752e648`; all exact-head CI checks passed. Full local suite: **1,272
passed, 98.95% coverage**.

EventQuery now carries a frozen ReleaseSelection, defaulting to all for old
callers. The existing shared matcher applies its exact/unknown predicate
before ordering and limiting. FixtureSource reuses that path with no duplicate
filter. Query hashing includes the typed selection, preserving cache identity.

Evidence: 12 regressions failed before implementation; 34 fixture/filter checks
passed afterward; strict mypy passed across 189 files. Cases cover all/exact/
unknown, case-sensitive labels, the literal exact label `all`, sparse matches
at limit=1, mixed predicates and same-timestamp cursor ties. G2a does not claim
GCP push-down, catalogue discovery or per-page metrics scoping.

## G2b local logs

Merged in [PR #50](https://github.com/SumukhaK/football-dashboard/pull/50),
merge `a7a459a`, reviewed head `a896eff`; all exact-head checks passed in
[CI](https://github.com/SumukhaK/football-dashboard/actions/runs/39564521279):
**1,285 passed, 98.95% coverage**.

LocalLogSource already delegates to the shared matcher delivered by G2a. This
slice adds real temporary-file acceptance rather than duplicating that code.
Thirteen local regressions cover fixture parity, limits/cursor ties, switching
release against an unchanged complete snapshot, size-change append detection,
malformed/missing-field counts and the byte-limited tail. Test writers use
explicit LF so byte accounting is identical on Windows and Linux.

All **71 local/shared checks passed**, with repository Ruff/Black and strict
mypy (190 files) passing. An in-memory omitted-filter mutation fails 12 local
checks. The initial byte-tail test caught Windows newline translation in the
test writer, which was corrected; no production bug or new filter was invented.
The published PR's full CI validates this test-only integration slice.

## G2c Google filtering, cache parity and bounded discovery

Implemented from merged main `a7a459a`. [ADR 004](adr/004-bounded-release-discovery.md)
records the source contract and explicit scan policy. Exact selections use
safely quoted, anchored case-sensitive Logging regexes before the raw scan cap.
Google can also match array elements; strict contract conversion and the shared
matcher reject false exacts before the selected-row limit. Unknown selection
uses JSON candidates and strict local identity, with bounded refill. Missing
required fields remain invalid. All-release event reads retain their adapter.

The Google reader scans at most **5,000 raw records / five explicit pages**,
passing **retry=None** and the remaining **five-second RPC scan budget** to each
call. It consumes only the SDK's already-fetched page, without hidden pager
RPCs. A selected page must finish its timestamp tie boundary before sorting by
request ID; if the budget cannot prove a stable page or exhaustion, the source
reports unavailable rather than silently losing rows. Provider failures,
including later-page failures, retain the existing safe error mapping.

Optional ReleaseDiscovery exposes exact observed labels, has_unknown and
truncated for one window independently of active selection. Fixture/local
discovery reuses existing bounded snapshots; local tail limits and rejected
contract records remain explicit. Google discovery marks capped, elapsed-budget
or invalid-record scans incomplete; RPC failures remain source errors.
Unsupported discovery fails explicitly.
The existing TTL/LRU cache keeps full EventQuery identity and window-specific
catalogue keys; failures stay uncached. The extra Google SDK client is lazy.
No dependency was added. Existing local file-error helpers moved unchanged
into a small module, preserving their old imports and the 400-line file limit.

Verification covers all/exact/unknown parity across Google fakes, local files
and fixtures; hostile labels; 6,000 unrelated records before a sparse exact
match; request-ID chunks/cursors; timestamp ties across provider pages; strict
array/scalar identity; row/page/time/repeated-token limits; SDK enum conversion;
later failures; cache contents, TTL, window/source isolation and error retry.
In-memory mutations removing the provider predicate fail seven checks,
removing release from the event-cache key fails one, and ignoring elapsed time
fails two. No production file was mutated by these checks.

Final full local suite: **1,332 passed, 98.93% coverage**. Repository Ruff,
Black and strict mypy (198 source files) passed. Every changed Python file
stays within 400 lines and every changed function within 40 lines. The final
review's timestamp-tie and local-incompleteness regressions failed first and
passed after their fixes. PR CI must pass at the unchanged reviewed head.

Existing A2 client/credential initialization, multiple-ID-chunk and whole-page
read budgets remain pending. This slice bounds its new RPC scans; it does not
claim all dashboard reads have a single deadline. G3–G7 selectors, historical
ranges, URL/page metrics and comparisons remain pending. There was no live
Google query, IAM/secret change or deployment.

## Verification boundaries

All regressions use local fixtures/fakes. Full local pytest uses a nonexistent
GOOGLE_APPLICATION_CREDENTIALS path, restored afterward, to prevent the known
credential-dependent navigation test from using local ADC. That separate
offline-test defect remains pending. Two existing HTTPX deprecation warnings
remain; no tests were skipped or weakened. No live Google query, IAM write,
secret change, deployment or visual browser acceptance is claimed.
